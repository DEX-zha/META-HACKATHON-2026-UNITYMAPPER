using System;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    [InitializeOnLoad]
    public static class ReferenceWorkflow
    {
        static string stage,directory,id,capture,expectedVersion;
        static int iteration;
        static JObject bundle,appliedPlan,contactReport;
        static JArray catalogue;
        static double began,previewBegan;
        static JArray detailViews,detailCaptures,detailLimits;
        static int detailOffset,detailCount;
        public static bool Running=>stage!=null;
        public static string Status=>SessionState.GetString("HdrpAgent.ReferenceStatus","Prêt à enregistrer une référence.");
        public static string LastDirectory=>SessionState.GetString("HdrpAgent.ReferenceDirectory","");
        static string Workspace=>BridgeClient.ResolveWorkspace();
        static string Owner=>Path.Combine(Workspace,".hdrp-agent","reference-owner.json");
        static ReferenceWorkflow(){EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=()=>{if(Running)Fail("Domain reload interrupted the reference workflow; no automatic replay");};}
        public static void Atomic(string path,JToken value){var temp=path+".writing";File.WriteAllText(temp,value.ToString(Newtonsoft.Json.Formatting.None));if(File.Exists(path))File.Replace(temp,path,null);else File.Move(temp,path);}
        static void Say(string text){SessionState.SetString("HdrpAgent.ReferenceStatus",text);}
        static void Begin(string kind,string brief,string[] media,string checkpoint=null,BridgeCommand admission=null){
            if(Running||(admission==null&&(BridgeClient.SessionOwnsEditor||CommandExecutor.Busy))||LocalValidationRunner.Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning||EditorApplication.isCompiling)throw new InvalidOperationException("Another operation owns the editor");
            if(admission!=null&&!CommandExecutor.Owns(admission))throw new InvalidOperationException("Preparation does not own the active command");
            if(File.Exists(Owner))throw new InvalidOperationException("A previous reference workflow requires reconciliation; no replay");
            id=admission==null?Guid.NewGuid().ToString("N"):(string)admission.payload["run_id"];directory=Path.Combine(Workspace,".hdrp-agent","reconstructions",id);Directory.CreateDirectory(directory);iteration=0;capture=null;previewBegan=0;began=EditorApplication.timeSinceStartup;
            using(var stream=new FileStream(Owner,FileMode.CreateNew,FileAccess.Write,FileShare.Read))using(var writer=new StreamWriter(stream))writer.Write(new JObject{["id"]=id,["directory"]=directory}.ToString());
            stage="preparing";SessionState.SetString("HdrpAgent.ReferenceDirectory",directory);
            try{
                var scene=SceneManager.GetActiveScene();var folder="Assets/AgentWorkspace/References/"+id;Directory.CreateDirectory(folder);AssetDatabase.Refresh();var source=folder+"/Source.unity";
                JObject previousBundle=null;
                if(checkpoint==null){if(!EditorSceneManager.SaveScene(scene,source,true))throw new IOException("Could not preserve source scene");}
                else{
                    var checkpointId=Path.GetFileName(checkpoint);Guid.ParseExact(checkpointId,"N");if(Path.GetFullPath(checkpoint)!=Path.Combine(Workspace,".hdrp-agent","reconstructions",checkpointId))throw new InvalidDataException("Unknown reference checkpoint");
                    previousBundle=JObject.Parse(File.ReadAllText(Path.Combine(checkpoint,"bundle.json")));var old=JObject.Parse(File.ReadAllText(Path.Combine(checkpoint,"source-private.json")));var saved=(string)old["source_scene"];
                    if((string)previousBundle["kind"]!=kind||!saved.StartsWith("Assets/AgentWorkspace/References/",StringComparison.Ordinal)||BridgeJson.Hash(File.ReadAllBytes(saved))!=(string)old["source_scene_sha256"])throw new InvalidDataException("Preserved reference source changed");
                    if(!AssetDatabase.CopyAsset(saved,source))throw new IOException("Could not preserve recorded reference");
                }
                Atomic(Path.Combine(directory,"source-private.json"),new JObject{["source_scene"]=source,["previous_scene"]=scene.path,["source_scene_sha256"]=BridgeJson.Hash(File.ReadAllBytes(source))});
                if(admission==null)BridgeClient.Disconnect();EditorSceneManager.OpenScene(source,OpenSceneMode.Single);
                catalogue=ReferenceAssets.Catalogue("Assets/AtmosphericHouse/Prefabs");Atomic(Path.Combine(directory,"catalogue.json"),catalogue);
                // Domain reload may clear the disconnected bridge's cached ID.
                // Use the same deterministic project identity; the worker still
                // requires its existing registration before admitting any call.
                var projectId="project-"+BridgeJson.Hash(Encoding.UTF8.GetBytes(Directory.GetParent(Application.dataPath).FullName)).Substring(0,24);
                bundle=new JObject{["schema_version"]="1.0",["id"]=id,["kind"]=kind,["brief"]=brief,["provider_mode"]="live",["max_iterations"]=6,["session_timeout_seconds"]=2400,["autonomous_refinement"]=true,["scene_inspection"]=true,["fidelity_mode"]="1.0",["scale_mode"]=SessionState.GetBool("HdrpAgent.EvidencedScale",false)?"evidenced":"locked",["priority_view"]="work-top-front",["project_id"]=projectId,["catalogue_file"]="catalogue.json",["asset_visual_matching"]=true,["pose_geometry"]=true,["detail_capture"]=checkpoint==null&&kind=="recorded"};
                if(admission!=null){bundle["operation_id"]=admission.payload["operation_id"];bundle["session_id"]=admission.session_id;foreach(var key in new[]{"building_policy","interior_style","ceiling_prefab"})bundle[key]=admission.payload[key].DeepClone();}
                if(kind=="external"){bundle.Remove("fidelity_mode");bundle["priority_view"]="reference-0";}
                if(previousBundle!=null&&kind=="external"){
                    SnapshotStore.CreateWorkingCopy(source,"reference-"+id);expectedVersion=SceneInspector.Version();
                    var copied=new JArray();foreach(var token in (JArray)previousBundle["media_files"]){var file=(string)token;if(Path.GetFileName(file)!=file)throw new InvalidDataException("Invalid saved media path");File.Copy(Path.Combine(checkpoint,file),Path.Combine(directory,file));copied.Add(file);}
                    bundle["media_files"]=copied;bundle["analysis_checkpoint_job_id"]=Path.GetFileName(checkpoint);bundle["cached_sam_only"]=true;Submit();return;
                }
                if(previousBundle!=null){
                    SnapshotStore.CreateWorkingCopy(source,"reference-"+id);expectedVersion=SceneInspector.Version();bundle["capture_directory"]=previousBundle["capture_directory"].DeepClone();bundle["inspection"]=previousBundle["inspection"].DeepClone();bundle["analysis_checkpoint_job_id"]=Path.GetFileName(checkpoint);bundle["cached_sam_only"]=false;
                    var origin=checkpoint;
                    for(int depth=0;depth<32;depth++){
                        if(File.Exists(Path.Combine(origin,"detail-result.json"))){bundle["detail_checkpoint_job_id"]=Path.GetFileName(origin);break;}
                        var ancestor=(string)JObject.Parse(File.ReadAllText(Path.Combine(origin,"bundle.json")))["analysis_checkpoint_job_id"];if(ancestor==null)break;
                        Guid.ParseExact(ancestor,"N");origin=Path.Combine(Workspace,".hdrp-agent","reconstructions",ancestor);
                    }
                    Submit();return;
                }
                if(kind=="recorded"){
                    SnapshotStore.CreateWorkingCopy(source,"reference-"+id);
                    // Record the current static composition, not a later physics
                    // or animation state. Only this owned recording copy changes.
                    foreach(var body in UnityEngine.Object.FindObjectsByType<Rigidbody>(FindObjectsInactive.Include,FindObjectsSortMode.None))body.isKinematic=true;
                    foreach(var animator in UnityEngine.Object.FindObjectsByType<Animator>(FindObjectsInactive.Include,FindObjectsSortMode.None))animator.enabled=false;
                    foreach(var behaviour in UnityEngine.Object.FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Include,FindObjectsSortMode.None))if(behaviour!=null&&(behaviour.GetType().Namespace=="FS_Atmo"||behaviour.GetType().Assembly.GetName().Name=="Assembly-CSharp"))behaviour.enabled=false;
                    EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());EditorSceneManager.SaveScene(SceneManager.GetActiveScene());bundle["static_snapshot"]=true;
                    var camera=Camera.main??UnityEngine.Object.FindObjectsByType<Camera>(FindObjectsSortMode.None).FirstOrDefault();if(camera==null)throw new InvalidOperationException("Place a camera before recording the scene");
                    var plan=CreateRecordingPlan(camera);bundle["inspection"]=plan;expectedVersion=SceneInspector.Version();capture=CaptureController.BeginReference(plan,true);stage="recording";Say("Enregistrement à 360° : devant, derrière, côtés et dessus…");
                }else{
                    var files=new JArray();for(int i=0;i<media.Length;i++){var ext=Path.GetExtension(media[i]).ToLowerInvariant();if(!new[]{".png",".jpg",".jpeg",".mp4",".mov",".m4v",".webm"}.Contains(ext)||new FileInfo(media[i]).Length>200000000)throw new InvalidDataException("Unsupported or oversized reference media");var name="input-"+i+ext;File.Copy(media[i],Path.Combine(directory,name));files.Add(name);}bundle["media_files"]=files;
                    // The source is preserved, but no source object is copied into the output.
                    SnapshotStore.CreateWorkingCopy(source,"reference-"+id);expectedVersion=SceneInspector.Version();Submit();
                }
            }catch(Exception e){Fail(e.GetType().Name+": "+e.Message);throw;}
        }
        public static JObject PrepareAdmitted(BridgeCommand command,string[] media){
            Begin("external",(string)command.payload["brief"],media,null,command);
            var path=Path.Combine(directory,"bundle.json");
            return new JObject{["operation_id"]=command.payload["operation_id"],["session_id"]=command.session_id,["run_id"]=id,["bundle_sha256"]=BridgeJson.Hash(File.ReadAllBytes(path))};
        }
        public static void RecordCurrent()=>Begin("recorded","Reproduire fidèlement la composition visible, les objets du projet, les matériaux, les lumières et l’atmosphère de la référence.",Array.Empty<string>());
        public static void RebuildSavedReference(){var saved=LastDirectory;var previous=JObject.Parse(File.ReadAllText(Path.Combine(saved,"bundle.json")));var kind=(string)previous["kind"];Begin(kind,((string)previous["brief"]??"")+" Reproduire fidèlement la référence conservée ; corriger la disposition, le cadrage et le rendu depuis les comparaisons visuelles. Les dimensions d’une image non cotée sont estimées.",Array.Empty<string>(),saved);}
        public static void ContinueSavedAnalysis(){
            if(Running||BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||LocalValidationRunner.Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning||File.Exists(Owner))throw new InvalidOperationException("Another operation owns editor");
            var saved=LastDirectory;if(string.IsNullOrEmpty(saved)||!Directory.Exists(saved))throw new InvalidDataException("No saved reference analysis");
            var jobId=Path.GetFileName(saved);Guid.ParseExact(jobId,"N");
            if(Directory.GetFiles(saved,"plan-*.json").Length>0||Directory.GetFiles(saved,"receipt-*.json").Length>0||File.Exists(Path.Combine(saved,"resume-request.json")))throw new InvalidDataException("Only a pre-construction analysis can continue once");
            var input=JObject.Parse(File.ReadAllText(Path.Combine(saved,"bundle.json")));
            var kind=(string)input["kind"];if(kind!="recorded"&&kind!="external")throw new InvalidDataException("Unknown reference kind");
            var version=kind=="recorded"?(string)JObject.Parse(File.ReadAllText(Path.Combine((string)input["capture_directory"],"editor-proof.json")))["scene_version_after"]:(string)input["candidate_base_version"];
            if(SceneManager.GetActiveScene().isDirty||!SceneManager.GetActiveScene().path.StartsWith(SnapshotStore.Root("reference-"+jobId)+"/",StringComparison.Ordinal)||SceneInspector.Version()!=version)throw new InvalidDataException("Recording scene changed; cannot continue from this checkpoint");
            directory=saved;id=jobId;bundle=input;catalogue=JArray.Parse(File.ReadAllText(Path.Combine(directory,"catalogue.json")));iteration=0;capture=null;expectedVersion=version;began=EditorApplication.timeSinceStartup;
            using(var stream=new FileStream(Owner,FileMode.CreateNew,FileAccess.Write,FileShare.Read))using(var writer=new StreamWriter(stream))writer.Write(new JObject{["id"]=id,["directory"]=directory}.ToString());
            try{
                foreach(var name in new[]{"native-stop.json","status.json","report.json"}){var file=Path.Combine(directory,name);if(File.Exists(file))File.Move(file,Path.Combine(directory,"before-continuation-"+name));}
                Atomic(Path.Combine(directory,"status.json"),new JObject{["state"]="resuming",["message"]="Réutilisation de l’analyse et des masques conservés ; aucun appel interrompu renvoyé."});
                stage="awaiting-plan";BridgeClient.Disconnect();Atomic(Path.Combine(directory,"resume-request.json"),new JObject{["cached_sam_only"]=true,["new_layout_only"]=true});Say("Poursuite depuis l’analyse enregistrée…");
            }catch(Exception e){Fail(e.GetType().Name+": "+e.Message);throw;}
        }
        public static void ImportBuildingPlan(string[] paths){if(paths==null||paths.Length<1||paths.Length>3)throw new InvalidDataException("One video or up to three images");Begin("external","[building-prefabs-required] Reproduce this illustrated living room plan using Assets/AtmosphericHouse/Prefabs/Building for floor and all wall modules, including actual door and window openings. Use project furniture and fittings for the remaining visible objects. Match composition, materials and lighting. Dimensions and hidden geometry are estimates. No primitive replacement walls.",paths);}
        public static void ImportMedia(string[] paths){if(paths==null||paths.Length<1||paths.Length>3)throw new InvalidDataException("One video or up to three images");Begin("external","Reproduire les objets et le rendu de la référence avec les assets locaux et les lumières ; signaler les éléments absents ou ambigus.",paths);}
        static JObject Pose(string key,Vector3 position,Quaternion rotation,float fov)=>JObject.FromObject(new{key,position_m=ReferenceAssets.Vec(position),rotation_deg=ReferenceAssets.Vec(rotation.eulerAngles),fov_deg=fov});
        public static JObject CreateRecordingPlan(Camera camera){
            // Bounds choose recording cameras only. Object transforms/bounds from
            // this source scene are never exported to the reconstruction model.
            var renderers=SceneManager.GetActiveScene().GetRootGameObjects().Where(go=>(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(go)??"").StartsWith("Assets/AtmosphericHouse/",StringComparison.Ordinal)).SelectMany(go=>go.GetComponentsInChildren<MeshRenderer>(true)).ToArray();
            if(renderers.Length==0)renderers=UnityEngine.Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None);
            var bounds=renderers.Length>0?renderers[0].bounds:new Bounds(camera.transform.position+camera.transform.forward*4,Vector3.one*3);foreach(var renderer in renderers)bounds.Encapsulate(renderer.bounds);
            var target=bounds.center;float fov=42,distance=Mathf.Max(4,bounds.extents.magnitude/Mathf.Sin(fov*.5f*Mathf.Deg2Rad)*1.05f);
            var delta=camera.transform.position-target;float start=Mathf.Atan2(delta.x,delta.z);
            Func<string,float,float,JObject> orbit=(key,degrees,elevation)=>{
                float azimuth=start+degrees*Mathf.Deg2Rad,pitch=elevation*Mathf.Deg2Rad;
                var position=target+new Vector3(Mathf.Sin(azimuth)*Mathf.Cos(pitch),Mathf.Sin(pitch),Mathf.Cos(azimuth)*Mathf.Cos(pitch))*distance;
                return Pose(key,position,Quaternion.LookRotation(target-position,Vector3.up),fov);
            };
            var names=new[]{"work-front","work-front-right","work-back-right","work-back","work-back-left","work-front-left"};var work=new JArray();for(int i=0;i<6;i++)work.Add(orbit(names[i],i*60,25));work.Add(orbit("work-top-front",0,65));work.Add(orbit("work-top-back",180,65));
            return new JObject{["work_views"]=work,["control_views"]=new JArray(orbit("control-high",90,55),orbit("control-low",270,10)),["path_key"]="reference-orbit",["fps"]=24,["duration_seconds"]=6,["width"]=1280,["height"]=720,["fixed_ev"]=0,["seed"]=1729,["warmup_frames"]=64};
        }
        static void Submit(){bundle["candidate_base_version"]=expectedVersion;Atomic(Path.Combine(directory,"bundle.json"),bundle);stage="awaiting-plan";Say("Référence prête ; analyse Muse et segmentation SAM…");}
        static void BeginDetailBatch(){
            if(SceneManager.GetActiveScene().isDirty||SceneInspector.Version()!=expectedVersion)throw new InvalidDataException("Source changed before detail recording");
            detailCount=Math.Min(8,detailViews.Count-detailOffset);var work=new JArray();
            foreach(JObject view in detailViews.Skip(detailOffset).Take(detailCount)){var pose=(JObject)view.DeepClone();pose.Remove("object_key");pose.Remove("angle");work.Add(pose);}
            while(work.Count<3){var padding=(JObject)work[0].DeepClone();padding["key"]="detail-padding-"+work.Count;work.Add(padding);}
            var plan=(JObject)bundle["inspection"].DeepClone();plan["work_views"]=work;plan["warmup_frames"]=32;plan["path_key"]="detail-static";
            capture=CaptureController.BeginReference(plan,false);stage="recording-details";Say("Gros plans réels : "+(detailOffset+1)+"–"+(detailOffset+detailCount)+" / "+detailViews.Count+"…");
        }
        public static void Stop(){if(!Running)return;Atomic(Path.Combine(directory,"native-stop.json"),new JObject{["reason"]="Operator requested stop"});stage="stopping";if(EditorApplication.isPlaying)EditorApplication.isPlaying=false;}
        static void Fail(string reason){
            if(directory!=null&&Directory.Exists(directory))Atomic(Path.Combine(directory,"native-stop.json"),new JObject{["reason"]=reason,["replay_allowed"]=false});
            if(directory!=null&&Directory.Exists(directory)){
                try{
                    if(EditorApplication.isPlayingOrWillChangePlaymode||EditorApplication.isCompiling||Lightmapping.isRunning||SceneManager.GetActiveScene().isDirty||SceneInspector.Version()!=expectedVersion)throw new InvalidOperationException("Restoration deferred: editor busy or concurrent scene change");
                    var reportPath=Path.Combine(directory,"report.json");if(File.Exists(reportPath)){
                        var job=JObject.Parse(File.ReadAllText(reportPath))["job"];var ordinal=(int?)job["retained_ordinal"];
                        if(ordinal.HasValue){
                            var receipt=JObject.Parse(File.ReadAllText(Path.Combine(directory,"receipt-"+ordinal.Value+".json")));var path=(string)receipt["scene_path"];
                            if(path!=SnapshotStore.Runs+"/repro-"+id+"-"+ordinal.Value+"/Reconstruction.unity")throw new InvalidDataException("Retained scene is outside this run");
                            ReferenceVision.Cancel("Restoring retained candidate after interruption");EditorSceneManager.OpenScene(path,OpenSceneMode.Single);
                            if(SceneInspector.Version()!=(string)receipt["version"])throw new InvalidDataException("Retained scene changed since measurement");
                            var inspection=Path.Combine(directory,"inspection-"+ordinal.Value);if(File.Exists(Path.Combine(inspection,"result.json")))ReferenceVision.ShowSaved(inspection);
                            Atomic(Path.Combine(directory,"interruption-restoration.json"),new JObject{["status"]="restored",["ordinal"]=ordinal.Value,["scene_path"]=path,["version"]=receipt["version"],["native_command_replayed"]=false});
                        }
                    }
                }catch(Exception e){Atomic(Path.Combine(directory,"interruption-restoration.json"),new JObject{["status"]="not_restored",["reason"]=e.Message,["native_command_replayed"]=false});}
            }
            Say("Arrêt : "+reason);Release();
        }
        static void Release(){
            ReferenceVision.Cancel("Reference workflow released");stage=null;
            if(File.Exists(Owner)){try{if((string)JObject.Parse(File.ReadAllText(Owner))["id"]==id)File.Delete(Owner);}catch(Newtonsoft.Json.JsonException){}}
            if(!EditorApplication.isPlayingOrWillChangePlaymode&&!SceneManager.GetActiveScene().isDirty)BridgeClient.Connect();
        }
        static bool CaptureReady()=>capture!=null&&File.Exists(Path.Combine(capture,"editor-proof.json"));
        static void CheckCapture(){
            if(File.Exists(Path.Combine(capture,"interruption.json")))throw new InvalidOperationException("Native capture interrupted");
            var manifest=JObject.Parse(File.ReadAllText(Path.Combine(capture,"manifest.json")));var proof=JObject.Parse(File.ReadAllText(Path.Combine(capture,"editor-proof.json")));
            if((string)manifest["status"]!="complete"||(string)proof["scene_version_after"]!=expectedVersion||SceneInspector.Version()!=expectedVersion)throw new InvalidDataException("Reference capture version changed");
        }
        static void Tick(){
            if(!Running||EditorApplication.isCompiling)return;
            try{
                if(EditorApplication.timeSinceStartup-began>2450)throw new TimeoutException("Reference workflow time limit reached");
                if(EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)return;
                if(capture!=null&&File.Exists(Path.Combine(capture,"interruption.json")))throw new InvalidOperationException("Native capture interrupted; no replay");
                if(stage=="stopping"){Fail("Operator stopped the workflow; partial evidence retained");return;}
                if(stage=="recording"&&CaptureReady()){CheckCapture();bundle["capture_directory"]=capture;Submit();return;}
                if(stage=="recording-details"&&CaptureReady()){
                    CheckCapture();detailCaptures.Add(new JObject{["capture_directory"]=capture,["views"]=new JArray(detailViews.Skip(detailOffset).Take(detailCount).Select(v=>v.DeepClone()))});detailOffset+=detailCount;
                    if(detailOffset<detailViews.Count)BeginDetailBatch();else{Atomic(Path.Combine(directory,"detail-result.json"),new JObject{["captures"]=detailCaptures,["limits"]=detailLimits});stage="awaiting-plan";}return;
                }
                if(stage=="capturing"&&CaptureReady()){
                    CheckCapture();Atomic(Path.Combine(directory,"render-"+iteration+".json"),new JObject{["ordinal"]=iteration,["capture_directory"]=capture,["scene_path"]=SceneManager.GetActiveScene().path,["version"]=expectedVersion,["applied_plan"]=appliedPlan,["contacts"]=contactReport,["room_finish"]=ReferenceSceneBuilder.LastRoomFinish});iteration++;stage="awaiting-plan";Say("Rendu candidat terminé ; comparaison et ajustement…");return;
                }
                if(stage=="inspecting"){
                    var folder=Path.Combine(directory,"inspection-"+(iteration-1));
                    if(File.Exists(Path.Combine(folder,"interruption.json")))throw new InvalidOperationException("Editor inspection interrupted; no replay");
                    if(File.Exists(Path.Combine(folder,"result.json"))){stage="awaiting-plan";Say("Inspection ciblée terminée ; analyse des gros plans…");}return;
                }
                if(stage!="awaiting-plan")return;
                var inspectionRequest=Path.Combine(directory,"inspection-request-"+(iteration-1)+".json");
                if(iteration>0&&File.Exists(inspectionRequest)&&!Directory.Exists(Path.Combine(directory,"inspection-"+(iteration-1)))){
                    if((bool?)bundle["scene_inspection"]!=true||new FileInfo(inspectionRequest).Length>50000)throw new InvalidDataException("Editor inspection not admitted");
                    var inspectionCommand=JObject.Parse(File.ReadAllText(inspectionRequest));
                    if((int)inspectionCommand["ordinal"]!=iteration-1||(string)inspectionCommand["version"]!=expectedVersion)throw new InvalidDataException("Stale inspection command");
                    ReferenceVision.Begin(inspectionCommand,Path.Combine(directory,"inspection-"+(iteration-1)));stage="inspecting";Say("La caméra Scene inspecte les écarts et leurs supports…");return;
                }
                var detailRequest=Path.Combine(directory,"detail-request.json");
                if(File.Exists(detailRequest)&&!File.Exists(Path.Combine(directory,"detail-result.json"))){
                    if((bool?)bundle["detail_capture"]!=true)throw new InvalidDataException("Detail capture not admitted by this source bundle");
                    var request=JObject.Parse(File.ReadAllText(detailRequest));BridgeJson.Closed(request,"input_bundle_sha256","objects");
                    if((string)request["input_bundle_sha256"]!=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"bundle.json")))||SceneManager.GetActiveScene().isDirty||SceneInspector.Version()!=expectedVersion)throw new InvalidDataException("Source changed before detail request");
                    var details=ReferenceDetails.Plan((JArray)request["objects"],(JObject)bundle["inspection"]);detailViews=(JArray)details["views"];detailLimits=(JArray)details["limits"];detailCaptures=new JArray();detailOffset=0;
                    if(detailViews.Count==0)Atomic(Path.Combine(directory,"detail-result.json"),new JObject{["captures"]=detailCaptures,["limits"]=detailLimits});else BeginDetailBatch();return;
                }
                var previewRequest=Path.Combine(directory,"preview-request.json");var previewResult=Path.Combine(directory,"preview-result.json");
                if(File.Exists(previewRequest)&&!File.Exists(previewResult)){
                    var request=JObject.Parse(File.ReadAllText(previewRequest));BridgeJson.Closed(request,"asset_ids","catalogue_sha256");
                    if((string)request["catalogue_sha256"]!=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"catalogue.json"))))throw new InvalidDataException("Preview catalogue changed");
                    var ids=(JArray)request["asset_ids"];if(ids.Count>160)throw new InvalidDataException("Preview request exceeds bound");if(previewBegan==0)previewBegan=EditorApplication.timeSinceStartup;
                    var records=new JArray();bool pending=false;
                    foreach(var token in ids){
                        var asset=catalogue.OfType<JObject>().SingleOrDefault(a=>(string)a["asset_id"]==(string)token)??throw new InvalidDataException("Unknown preview asset");var name="preview-"+(string)asset["asset_guid"]+".png";var path=Path.Combine(directory,name);bool ready=File.Exists(path);
                        var checkpoint=(string)bundle["analysis_checkpoint_job_id"];
                        if(!ready&&checkpoint!=null){
                            Guid.ParseExact(checkpoint,"N");var prior=Path.Combine(Workspace,".hdrp-agent","reconstructions",checkpoint);var old=Path.Combine(prior,name);
                            if(File.Exists(old)&&BridgeJson.Hash(File.ReadAllBytes(Path.Combine(prior,"catalogue.json")))==(string)request["catalogue_sha256"]){File.Copy(old,path);ready=true;}
                        }
                        if(!ready)ready=ReferenceAssets.SavePreview(asset,path);if(!ready)pending=true;records.Add(new JObject{["asset_id"]=token.DeepClone(),["file"]=ready?name:null});
                    }
                    if(!pending||EditorApplication.timeSinceStartup-previewBegan>30)Atomic(previewResult,records);return;
                }
                var statusFile=Path.Combine(directory,"status.json");
                if(File.Exists(statusFile)){
                    var status=JObject.Parse(File.ReadAllText(statusFile));var state=(string)status["state"];
                    if(state=="interrupted"||state=="failed"){Fail((string)status["message"]??"Service interrupted");return;}
                    if(state=="completed"){
                        var path=(string)status["best_scene_path"];var ordinal=(int?)status["best_ordinal"];if(path!=null){
                            var receipt=JObject.Parse(File.ReadAllText(Path.Combine(directory,"receipt-"+ordinal+".json")));
                            if((string)receipt["scene_path"]!=path||!path.StartsWith(SnapshotStore.Runs+"/repro-"+id+"-",StringComparison.Ordinal)||SceneManager.GetActiveScene().isDirty||SceneInspector.Version()!=expectedVersion)throw new InvalidDataException("Cannot activate the best candidate after concurrent edit");
                            EditorSceneManager.OpenScene(path,OpenSceneMode.Single);
                            if(SceneInspector.Version()!=(string)receipt["version"])throw new InvalidDataException("Retained candidate changed since its measurement");
                            var savedInspection=Path.Combine(directory,"inspection-"+ordinal);if(File.Exists(Path.Combine(savedInspection,"result.json")))ReferenceVision.ShowSaved(savedInspection);
                        }
                        Say("Reconstruction terminée — comparer le résultat à la référence. "+(string)status["message"]);Release();return;
                    }
                    Say((string)status["message"]??"Analyse en cours…");
                }
                var geometryRequest=Path.Combine(directory,"geometry-request.json");var geometryResult=Path.Combine(directory,"geometry-result.json");
                if(File.Exists(geometryRequest)&&!File.Exists(geometryResult)){
                    var request=JObject.Parse(File.ReadAllText(geometryRequest));BridgeJson.Closed(request,"catalogue_sha256","asset_ids");
                    if((string)request["catalogue_sha256"]!=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"catalogue.json"))))throw new InvalidDataException("Geometry catalogue changed");
                    Atomic(geometryResult,new JObject{["catalogue_sha256"]=request["catalogue_sha256"],["assets"]=ReferencePoseGeometry.Export((JArray)request["asset_ids"],catalogue)});return;
                }
                var planFile=Path.Combine(directory,"plan-"+iteration+".json");if(!File.Exists(planFile))return;
                if(iteration>=(int)bundle["max_iterations"]||iteration>=6)throw new InvalidDataException("Reference candidate bound reached");
                if(new FileInfo(planFile).Length>1000000)throw new InvalidDataException("Plan exceeds bound");
                var command=BridgeJson.Read<JObject>(File.ReadAllText(planFile));
                if((string)bundle["fidelity_mode"]=="1.0")ReferenceFidelity.ValidateCommand(command,BridgeJson.Read<JObject>(File.ReadAllText(Path.Combine(directory,"fidelity-policy.json"))),expectedVersion);
                else BridgeJson.Closed(command,"ordinal","input_bundle_sha256","catalogue_sha256","plan","inspection","supports");
                if((int)command["ordinal"]!=iteration||(string)command["input_bundle_sha256"]!=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"bundle.json")))||(string)command["catalogue_sha256"]!=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"catalogue.json"))))throw new InvalidDataException("Input evidence changed");
                if(SceneManager.GetActiveScene().isDirty||SceneInspector.Version()!=expectedVersion)throw new InvalidOperationException("CONCURRENT_EDIT: source or candidate changed");
                var receiptFile=Path.Combine(directory,"receipt-"+iteration+".json");if(File.Exists(receiptFile))throw new InvalidDataException("Construction already started; reconcile instead of replaying");
                var plan=(JObject)command["plan"];ReferenceSceneBuilder.Validate(plan,catalogue);ReferenceContacts.Validate((JArray)command["supports"],plan);
                Atomic(receiptFile,new JObject{["status"]="started",["ordinal"]=iteration,["command_sha256"]=BridgeJson.Hash(File.ReadAllBytes(planFile)),["before_version"]=expectedVersion});
                var scene=ReferenceSceneBuilder.Build(plan,catalogue,"repro-"+id+"-"+iteration,(JObject)command["inspection"],(JArray)command["supports"],(JObject)command["capture_protocol"],(string)bundle["interior_style"]??"B");
                appliedPlan=(JObject)plan.DeepClone();contactReport=ReferenceSceneBuilder.LastContacts;
                expectedVersion=SceneInspector.Version();Atomic(receiptFile,new JObject{["status"]="built",["ordinal"]=iteration,["scene_path"]=scene,["version"]=expectedVersion,["applied_plan"]=appliedPlan,["contacts"]=contactReport,["room_finish"]=ReferenceSceneBuilder.LastRoomFinish});
                capture=CaptureController.BeginReference((JObject)command["inspection"],true);stage="capturing";Say("Construction et capture du candidat "+(iteration+1)+"/"+(int)bundle["max_iterations"]+"…");
            }catch(Exception e){Fail(e.GetType().Name+": "+e.Message);}
        }
    }
}
