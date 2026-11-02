using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    // Editor inspection is intentionally separate from GameView/performance proof.
    [InitializeOnLoad]
    public static class ReferenceVision
    {
        static Camera probe;
        static RenderTexture target;
        static JArray views,records,map;
        static JObject request,architecture;
        static string output,version,scenePath;
        static int index,warm;
        static double began;
        public static bool Running=>probe!=null;
        public static bool Follow=false,Gizmos=true;
        public static string Status {get;private set;}="Aucune inspection en cours.";
        public static Texture2D Image {get;private set;}
        public static JObject Current=>views!=null&&index<views.Count?(JObject)views[index]:null;
        static ReferenceVision(){EditorApplication.update+=Tick;SceneView.duringSceneGui+=Draw;AssemblyReloadEvents.beforeAssemblyReload+=()=>Cancel("Domain reload interrupted inspection");}
        static Transform Root=>SceneManager.GetActiveScene().GetRootGameObjects().FirstOrDefault(o=>o.name=="Reconstruction")?.transform;
        static Transform Find(string key)=>Root==null?null:Root.Cast<Transform>().SingleOrDefault(t=>t.name==key);
        static Bounds? BoundsOf(Transform t){if(t==null)return null;var rs=t.GetComponentsInChildren<Renderer>().Where(r=>r.enabled).ToArray();if(rs.Length==0)return null;var b=rs[0].bounds;foreach(var r in rs.Skip(1))b.Encapsulate(r.bounds);return b;}
        public static void Validate(JObject value){
            BridgeJson.Closed(value,"ordinal","version","scene_path","views","objects");
            var items=value["views"] as JArray;if(items==null||items.Count<1||items.Count>12)throw new InvalidDataException("One to twelve inspection views required");
            var objects=value["objects"] as JArray;if(objects==null||objects.Count>20)throw new InvalidDataException("Bounded candidate mapping required");
            foreach(JObject item in objects){BridgeJson.Closed(item,"key","support_key","residual");if(item["residual"]?.Type!=JTokenType.Null)ReferenceSceneBuilder.Number(item["residual"],0,1);if(Find((string)item["key"])==null)throw new InvalidDataException("Unknown candidate object");}
            if(items.Select(v=>(string)v["key"]).Distinct().Count()!=items.Count)throw new InvalidDataException("Duplicate inspection camera");
            foreach(JObject view in items){
                BridgeJson.Closed(view,"key","object_key","angle","position_m","rotation_deg","fov_deg");
                if(!objects.Any(o=>(string)o["key"]==(string)view["object_key"])||!new[]{"top","front","back","room_sweep","interior_detail"}.Contains((string)view["angle"]))throw new InvalidDataException("Unknown inspection target");
                ReferenceSceneBuilder.Vector(view["position_m"],-100,100);ReferenceSceneBuilder.Vector(view["rotation_deg"],-360,360);ReferenceSceneBuilder.Number(view["fov_deg"],5,120);
            }
        }
        public static void Begin(JObject value,string destination){
            if(Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning||SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("Saved idle candidate required for editor inspection");
            Validate(value);version=(string)value["version"];scenePath=(string)value["scene_path"];
            if(!scenePath.StartsWith(SnapshotStore.Runs+"/",StringComparison.Ordinal)||scenePath!=SceneManager.GetActiveScene().path||version!=SceneInspector.Version())throw new InvalidDataException("Inspection candidate version changed");
            if(Directory.Exists(destination))throw new InvalidDataException("Inspection already started; no replay");
            Directory.CreateDirectory(destination);output=destination;request=(JObject)value.DeepClone();views=(JArray)value["views"].DeepClone();map=(JArray)value["objects"].DeepClone();records=new JArray();architecture=ReferenceRoomAudit.Inspect(Root,ReferenceSceneBuilder.Vector(views[0]["position_m"],-100,100));index=0;began=EditorApplication.timeSinceStartup;
            ReferenceWorkflow.Atomic(Path.Combine(output,"request.json"),request);
            try{
                var go=new GameObject("Agent editor inspection camera"){hideFlags=HideFlags.HideAndDontSave};probe=go.AddComponent<Camera>();probe.enabled=false;
                var original=Camera.main;if(original!=null)probe.CopyFrom(original);probe.enabled=false;probe.targetTexture=null;probe.aspect=1280f/720;probe.nearClipPlane=.01f;
                var hd=go.AddComponent<HDAdditionalCameraData>();var sourceHD=original?.GetComponent<HDAdditionalCameraData>();if(sourceHD!=null)JsonUtility.FromJsonOverwrite(JsonUtility.ToJson(sourceHD),hd);
                hd.allowDynamicResolution=false;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;
                target=new RenderTexture(1280,720,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB){hideFlags=HideFlags.HideAndDontSave};target.Create();
                ReferenceVisionWindow.ShowWindow();Move();
            }catch(Exception e){Cancel(e.Message);throw;}
        }
        static void Move(){
            var view=Current;probe.transform.SetPositionAndRotation(ReferenceSceneBuilder.Vector(view["position_m"],-100,100),Quaternion.Euler(ReferenceSceneBuilder.Vector(view["rotation_deg"],-360,360)));probe.fieldOfView=(float)view["fov_deg"];HDCamera.GetOrCreate(probe).Reset();warm=0;
            Status="Inspection "+(index+1)+"/"+views.Count+" · "+(string)view["object_key"]+" · "+(string)view["angle"]+" · difference to verify";
            Navigate(view);
        }
        static void Navigate(JObject view){
            if(!Follow)return;var scene=SceneView.lastActiveSceneView??EditorWindow.GetWindow<SceneView>();scene.Show();scene.Focus();scene.sceneLighting=true;scene.drawGizmos=false;
            var position=ReferenceSceneBuilder.Vector(view["position_m"],-100,100);var rotation=Quaternion.Euler(ReferenceSceneBuilder.Vector(view["rotation_deg"],-360,360));float fov=(float)view["fov_deg"];scene.cameraSettings.fieldOfView=fov;
            var b=BoundsOf(Find((string)view["object_key"]));float distance=b.HasValue?Vector3.Distance(position,b.Value.center):2;
            scene.LookAt(position+rotation*Vector3.forward*distance,rotation,Mathf.Max(.01f,distance*Mathf.Sin(fov*.5f*Mathf.Deg2Rad)),false,false);
        }
        public static void ShowSaved(string directory){
            if(Running)throw new InvalidOperationException("Inspection is still running");
            var saved=JObject.Parse(File.ReadAllText(Path.Combine(directory,"request.json")));var result=JObject.Parse(File.ReadAllText(Path.Combine(directory,"result.json")));
            if((string)result["status"]!="complete"||(string)result["scene_path"]!=SceneManager.GetActiveScene().path||(string)result["version"]!=SceneInspector.Version()||(string)result["request_sha256"]!=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"request.json"))))throw new InvalidDataException("Saved inspection does not describe the active candidate");
            var frame=result["frames"][0];var file=(string)frame["file"];if(Path.GetFileName(file)!=file)throw new InvalidDataException("Invalid inspection image path");var bytes=File.ReadAllBytes(Path.Combine(directory,file));if(BridgeJson.Hash(bytes)!=(string)frame["sha256"])throw new InvalidDataException("Saved image changed");
            if(Image==null)Image=new Texture2D(2,2){hideFlags=HideFlags.HideAndDontSave};if(!Image.LoadImage(bytes))throw new InvalidDataException("Invalid saved image");
            scenePath=(string)result["scene_path"];version=(string)result["version"];architecture=result["architecture"] as JObject;views=(JArray)saved["views"];map=(JArray)saved["objects"];index=0;
            Status="Candidate retained · inspection retained · "+(string)Current["object_key"]+" · "+(string)Current["angle"];ReferenceVisionWindow.ShowWindow();Navigate(Current);ReferenceVisionWindow.Refresh();
        }
        static void Readback(){
            var old=RenderTexture.active;try{RenderTexture.active=target;if(Image==null)Image=new Texture2D(1280,720,TextureFormat.RGB24,false){hideFlags=HideFlags.HideAndDontSave};Image.ReadPixels(new Rect(0,0,1280,720),0,0);Image.Apply();}finally{RenderTexture.active=old;}
            ReferenceVisionWindow.Refresh();
        }
        static void Tick(){
            if(!Running)return;
            try{
                if(EditorApplication.isPlayingOrWillChangePlaymode||SceneManager.GetActiveScene().isDirty||SceneManager.GetActiveScene().path!=scenePath)throw new InvalidOperationException("Concurrent scene edit during inspection");
                if(EditorApplication.timeSinceStartup-began>300)throw new TimeoutException("Editor inspection time limit");
                RenderPipeline.SubmitRenderRequest(probe,new RenderPipeline.StandardRequest{destination=target});warm++;
                if(warm%8==0)Readback();
                if(warm<32)return;
                if(SceneInspector.Version()!=version)throw new InvalidDataException("Candidate changed during inspection");
                var file="view-"+index.ToString("D2")+".png";var png=Image.EncodeToPNG();File.WriteAllBytes(Path.Combine(output,file),png);
                records.Add(new JObject{["view"]=Current.DeepClone(),["file"]=file,["sha256"]=BridgeJson.Hash(png),["projected_objects"]=ReferenceRoomAudit.Project(Root,probe)});
                index++;if(index<views.Count){Move();return;}
                ReferenceWorkflow.Atomic(Path.Combine(output,"result.json"),new JObject{["status"]="complete",["mode"]="editor_hdrp_probe",["scene_path"]=scenePath,["version"]=version,["request_sha256"]=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(output,"request.json"))),["width"]=1280,["height"]=720,["warmup_frames"]=32,["frames"]=records,["architecture"]=architecture,["render_protocol"]=JObject.FromObject(HdrpAgent.Runtime.ReferenceRenderProtocol.Read(probe,"editor_hdrp_probe")),["performance_qualified"]=false,["gizmos_in_images"]=false});
                Status="Inspection complete · close-ups passed to the next correction";Cleanup();
            }catch(Exception e){Cancel(e.GetType().Name+": "+e.Message);}
        }
        public static void Cancel(string reason){if(!Running)return;ReferenceWorkflow.Atomic(Path.Combine(output,"interruption.json"),new JObject{["reason"]=reason});Status="Inspection stopped: "+reason;Cleanup();}
        static void Cleanup(){if(probe!=null)UnityEngine.Object.DestroyImmediate(probe.gameObject);probe=null;if(target!=null){target.Release();UnityEngine.Object.DestroyImmediate(target);}target=null;ReferenceVisionWindow.Refresh();}
        static void Draw(SceneView scene){
            if(!Gizmos||map==null||SceneManager.GetActiveScene().path!=scenePath||EditorApplication.isPlaying)return;
            var old=Handles.color;try{foreach(JObject item in map){var t=Find((string)item["key"]);var b=BoundsOf(t);if(!b.HasValue)continue;bool active=Current!=null&&(string)Current["object_key"]==(string)item["key"];
                Handles.color=active?Color.cyan:new Color(1,.65f,.1f,.8f);Handles.DrawWireCube(b.Value.center,b.Value.size);if(active)Handles.Label(b.Value.max,(string)item["key"]+(item["residual"]?.Type==JTokenType.Null?" · not measured":" · difference "+((float)item["residual"]).ToString("F3")));
                var support=BoundsOf(Find((string)item["support_key"]));if(support.HasValue)Handles.DrawDottedLine(b.Value.center,support.Value.center,4);
            }
            if(architecture?["walls"] is JArray walls)foreach(JObject wall in walls){
                var t=Find((string)wall["object_key"]);if(t==null)continue;var b=BoundsOf(t);if(!b.HasValue)continue;
                Handles.color=(bool)wall["outward_axis_points_to_observer"]?Color.red:Color.green;
                Handles.ArrowHandleCap(0,b.Value.center,Quaternion.LookRotation(t.forward),.5f,EventType.Repaint);
            }
            }finally{Handles.color=old;}
        }
    }
    public sealed class ReferenceVisionWindow:EditorWindow
    {
        [MenuItem("Window/HDRP Agent/Vision de l’agent")]
        public static void ShowWindow(){var w=Resources.FindObjectsOfTypeAll<ReferenceVisionWindow>().FirstOrDefault();if(w==null){w=CreateInstance<ReferenceVisionWindow>();w.titleContent=new GUIContent("Vision de l’agent");w.position=new Rect(50,80,620,440);}w.minSize=new Vector2(400,280);w.ShowUtility();}
        public static void Refresh(){foreach(var w in Resources.FindObjectsOfTypeAll<ReferenceVisionWindow>())w.Repaint();SceneView.RepaintAll();}
        void OnGUI(){
            EditorGUILayout.LabelField(ReferenceVision.Status,EditorStyles.wordWrappedLabel);
            ReferenceVision.Follow=EditorGUILayout.Toggle("Follow in Scene view",ReferenceVision.Follow);ReferenceVision.Gizmos=EditorGUILayout.Toggle("Show map and supports",ReferenceVision.Gizmos);
            EditorGUILayout.LabelField("Cyan: observed target · orange: placement to verify · dotted: assumed support",EditorStyles.wordWrappedMiniLabel);
            using(new EditorGUI.DisabledScope(ReferenceVision.Running)){
                EditorGUILayout.BeginHorizontal();if(GUILayout.Button("360° interior survey"))ReferenceRoomControls.Survey();if(GUILayout.Button("Inspect the Scene camera"))ReferenceRoomControls.InspectSceneCamera();EditorGUILayout.EndHorizontal();
            }
            var rect=GUILayoutUtility.GetRect(200,Mathf.Max(120,position.height-155));if(ReferenceVision.Image!=null)GUI.DrawTexture(rect,ReferenceVision.Image,ScaleMode.ScaleToFit);
            EditorGUILayout.LabelField("HDRP inspection camera stream · images analyzed without gizmos",EditorStyles.miniLabel);
        }
    }
}
