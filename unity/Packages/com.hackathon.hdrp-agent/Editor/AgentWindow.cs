using System;
using System.IO;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace HdrpAgent.Editor
{
    public sealed class AgentWindow:EditorWindow
    {
        string brief="A naturally lit room with a window, a table, and a clearly visible volumetric beam.";
        string diagnostic="Qualify the local pipeline before autonomous correction.";
        string mode="offline";
        Vector2 scroll;
        Texture2D preview;
        string loaded;
        int comparisonView;
        string sessionId,sessionState="Aucune session",sessionVerdict="pending",budgetStatus="",pendingRoute,pendingBody,pendingMethod;
        bool startWhenRegistered;
        double nextSessionPoll;
        string Workspace=>Directory.GetParent(Application.dataPath).Parent.Parent.FullName;
        void StartSession(){
            if(!BridgeClient.Registered){diagnostic="Connect the service, then retry.";return;}
            startWhenRegistered=true;BridgeClient.Connect();
        }
        void QueueSession(){
            var plan=JObject.Parse(File.ReadAllText(Path.Combine(Workspace,"fixtures","inspection-plans","room.json")));
            var frozenBrief=JObject.Parse(File.ReadAllText(Path.Combine(Workspace,"fixtures","briefs","room.json")));
            frozenBrief["text"]=brief;frozenBrief["mutation_scope_id"]=SceneInspector.Scope;
            var criteria=new JArray{
                new JObject{["id"]="visibility",["kind"]="visibility",["target"]="work-front",["method"]="luminance_range",["minimum"]=.01,["maximum"]=.9,["unit"]="normalized",["required"]=true},
                new JObject{["id"]="performance",["kind"]="performance",["target"]="performance",["method"]="frame_time_regression",["minimum"]=null,["maximum"]=.2,["unit"]="ratio",["required"]=true},
                new JObject{["id"]="ambiance",["kind"]="artistic",["target"]="ambiance",["method"]="artistic_review",["minimum"]=null,["maximum"]=null,["unit"]="human",["required"]=true}
            };
            pendingBody=new JObject{["project_id"]=BridgeClient.ProjectId,["scene_id"]=BridgeClient.SceneId,["base_version"]=SceneInspector.Version(),["mode"]="inspect",["brief"]=frozenBrief,["criteria"]=criteria,["inspection"]=plan,["max_attempts"]=3,["session_timeout_seconds"]=1200,["bake_timeout_seconds"]=600,["provider_mode"]=mode}.ToString(Newtonsoft.Json.Formatting.None);
            pendingRoute="/v1/sessions";pendingMethod="POST";
        }
        void PollService(){
            if(!BridgeClient.Registered||BridgeClient.RequestInProgress)return;
            if(startWhenRegistered){startWhenRegistered=false;Try(QueueSession);}
            if(!string.IsNullOrEmpty(pendingRoute)){
                var route=pendingRoute;var body=pendingBody;var method=pendingMethod;pendingRoute=null;pendingBody=null;
                if(string.IsNullOrEmpty(method)){diagnostic="Panel command incomplete after transition; retry explicitly.";return;}
                BridgeClient.Request(method,route,body,"ui-"+Guid.NewGuid().ToString("N"),(ok,text)=>{
                    diagnostic=text;if(ok){var data=JObject.Parse(text);if(data["id"]!=null)sessionId=(string)data["id"];}
                });return;
            }
            if(EditorApplication.timeSinceStartup<nextSessionPoll)return;
            nextSessionPoll=EditorApplication.timeSinceStartup+2;
            if(!string.IsNullOrEmpty(sessionId))BridgeClient.Request("GET","/v1/sessions/"+sessionId,null,null,(ok,text)=>{
                if(!ok)return;var data=JObject.Parse(text);sessionState=(string)data["state"];sessionVerdict=(string)data["verdict"];diagnostic=text;
            });
            else BridgeClient.Request("GET","/v1/budget",null,null,(ok,text)=>{if(ok){var data=JObject.Parse(text);budgetStatus=string.Format("Available: {0:F4} $ · reserved: {1:F4} $",(double)data["available_usd_micro"]/1000000,(double)data["active_reserved_usd_micro"]/1000000);}});
        }
        readonly Dictionary<string,Texture2D> comparisons=new Dictionary<string,Texture2D>();
        void DrawComparison(){
            var workspace=Directory.GetParent(Application.dataPath).Parent.Parent.FullName;
            var report=Path.Combine(workspace,".hdrp-agent","reports","j0-local-pipeline.json");if(!File.Exists(report))return;
            var data=JObject.Parse(File.ReadAllText(report));if((bool?)data["restored_files_verified"]!=true)return;
            var captures=data["captures"] as JArray;if(captures==null||captures.Count<3||captures[0].Type==JTokenType.Null||captures[2].Type==JTokenType.Null)return;
            var keys=new[]{"work-front","work-right","work-left","control-corner","control-low"};comparisonView=EditorGUILayout.Popup("Same view",comparisonView,keys);
            EditorGUILayout.LabelField("Before / after restoration — local evidence, no correction verdict",EditorStyles.wordWrappedLabel);
            EditorGUILayout.BeginHorizontal();
            foreach(var index in new[]{0,2}){
                var path=Path.Combine((string)captures[index],keys[comparisonView]+".png");
                if(!File.Exists(path))continue;
                if(!comparisons.TryGetValue(path,out var texture)){texture=new Texture2D(2,2);texture.LoadImage(File.ReadAllBytes(path));comparisons[path]=texture;}
                GUILayout.Label(texture,GUILayout.Width((position.width-35)/2),GUILayout.Height((position.width-35)*9/32));
            }
            EditorGUILayout.EndHorizontal();
        }
        [MenuItem("Window/HDRP Agent/Agent")]
        public static void Open(){GetWindow<AgentWindow>("HDRP Agent");}
        void OnInspectorUpdate(){PollService();Repaint();}
        void OnGUI(){
            scroll=EditorGUILayout.BeginScrollView(scroll);
            EditorGUILayout.LabelField("HDRP scene agent",EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(BridgeClient.Status,BridgeClient.Registered?MessageType.Info:MessageType.Warning);
            using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor&&BridgeClient.Registered)){
                if(GUILayout.Button("Connect local service"))BridgeClient.Connect();
            }
            EditorGUILayout.LabelField("Brief");brief=EditorGUILayout.TextArea(brief,GUILayout.MinHeight(60));
            int choice=EditorGUILayout.Popup("Requested mode",mode=="offline"?0:1,new[]{"Offline — local validation","Live — after qualification and budget checks"});mode=choice==0?"offline":"live";
            EditorGUILayout.HelpBox("Legacy validation: 3 trials, 20 minutes, 10 minutes per bake. API budget is shared across sessions; check the live balance below.",MessageType.None);
            EditorGUILayout.LabelField("API budget",budgetStatus);
            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Reconstruct a reference",EditorStyles.boldLabel);
            EditorGUILayout.LabelField("Recreate objects, placement, and lighting using project assets.",EditorStyles.wordWrappedLabel);
            using(new EditorGUI.DisabledScope(ReferenceWorkflow.Running||BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||LocalValidationRunner.Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)){
                SessionState.SetBool("HdrpAgent.EvidencedScale",EditorGUILayout.Toggle(new GUIContent("Adjust sizes using multiview evidence","Sizes are locked by default. Corrections require three consistent views and are limited to 15%."),SessionState.GetBool("HdrpAgent.EvidencedScale",false)));
                if(GUILayout.Button("Record and reconstruct this scene"))Try(()=>ReferenceWorkflow.RecordCurrent());
                if(GUILayout.Button("Learn assemblies from an example scene…"))Try(()=>{var file=EditorUtility.OpenFilePanel("Saved example scene",Application.dataPath,"unity");if(!string.IsNullOrEmpty(file)){var path=FileUtil.GetProjectRelativePath(file);if(!path.StartsWith("Assets/",StringComparison.Ordinal))throw new InvalidOperationException("Choose a scene saved in the project Assets folder");ReferenceAssemblyExample.Inspect(path);ReferenceAssemblyExample.ValidatePreview();}});
                if(GUILayout.Button("Reconstruct a floor plan using Building modules…"))Try(()=>{var file=EditorUtility.OpenFilePanel("Floor plan with a door and window","","");if(!string.IsNullOrEmpty(file))ReferenceWorkflow.ImportBuildingPlan(new[]{file});});
                if(GUILayout.Button("Reconstruct an image or video…"))Try(()=>{var file=EditorUtility.OpenFilePanel("Visual reference","","");if(!string.IsNullOrEmpty(file))ReferenceWorkflow.ImportMedia(new[]{file});});
            }
            EditorGUILayout.LabelField(ReferenceWorkflow.Status,EditorStyles.wordWrappedLabel);
            if(GUILayout.Button("View agent vision and gizmos"))ReferenceVisionWindow.ShowWindow();
            if(ReferenceWorkflow.Running&&GUILayout.Button("Stop reconstruction"))ReferenceWorkflow.Stop();
            if(!ReferenceWorkflow.Running&&!string.IsNullOrEmpty(ReferenceWorkflow.LastDirectory)&&File.Exists(Path.Combine(ReferenceWorkflow.LastDirectory,"report.json"))){
                using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode))if(GUILayout.Button("Continue from the saved analysis"))Try(()=>ReferenceWorkflow.ContinueSavedAnalysis());
                using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode))if(GUILayout.Button("Rebuild from this saved reference"))Try(()=>ReferenceWorkflow.RebuildSavedReference());
            }
            var referenceReport=Path.Combine(ReferenceWorkflow.LastDirectory,"comparison.html");
            if(File.Exists(referenceReport)&&GUILayout.Button("View the reference comparison"))Application.OpenURL(new Uri(referenceReport).AbsoluteUri);
            if(!ReferenceWorkflow.Running&&File.Exists(referenceReport)&&GUILayout.Button("Compare with actual demo positions"))Try(()=>EditorUtility.RevealInFinder(ReferenceGroundTruthAudit.AuditSavedReference()));
            EditorGUILayout.LabelField("Session",sessionState+" · "+sessionVerdict);
            using(new EditorGUI.DisabledScope(!BridgeClient.Registered||BridgeClient.SessionOwnsEditor||LocalValidationRunner.Running||startWhenRegistered||pendingRoute!=null||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode)){
                if(GUILayout.Button("Inspect and correct the active copy"))Try(StartSession);
            }
            if(!string.IsNullOrEmpty(sessionId)){
                if(GUILayout.Button("Request session stop")){pendingMethod="POST";pendingRoute="/v1/sessions/"+sessionId+"/stop";pendingBody="{\"reason\":\"Stop requested from Unity\"}";}
                if(GUILayout.Button("Read session report")){pendingMethod="GET";pendingRoute="/v1/sessions/"+sessionId+"/report";pendingBody=null;}
            }
            EditorGUILayout.LabelField("Implemented capabilities",string.Join(", ",CommandExecutor.Capabilities));
            using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||LocalValidationRunner.Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)){
                if(GUILayout.Button("Prepare the validation room"))Try(()=>ValidationRoomBuilder.Prepare());
                if(GUILayout.Button("Create an isolated working copy"))Try(()=>ValidationRoomBuilder.PrepareWorkingRoom());
                if(GUILayout.Button("Inspecter la copie active"))Try(()=>diagnostic=SceneInspector.Inspect().ToString());
                if(GUILayout.Button("Validate local pipeline (J0)"))Try(()=>LocalValidationRunner.Start());
            }
            EditorGUILayout.LabelField("Progression",LocalValidationRunner.Status);
            if(LocalValidationRunner.Running&&GUILayout.Button("Request stop"))LocalValidationRunner.Stop();
            if(BakeController.Active!=null)EditorGUILayout.LabelField("Bake GPU",BakeController.Active.Finished?(BakeController.Active.Succeeded?"Verified":"Failed / interrupted"):"In progress — native cancellation may be delayed");
            EditorGUILayout.LabelField("Diagnostics / state",EditorStyles.boldLabel);EditorGUILayout.SelectableLabel(diagnostic,GUILayout.MinHeight(120));
            var output=CaptureController.LastOutput;var path=Path.Combine(output??"","work-front.png");
            if(path!=loaded&&File.Exists(path)){if(preview!=null)DestroyImmediate(preview);preview=new Texture2D(2,2);preview.LoadImage(File.ReadAllBytes(path));loaded=path;}
            if(preview!=null){EditorGUILayout.LabelField("Latest local capture — no improvement claimed");GUILayout.Label(preview,GUILayout.MaxWidth(position.width-30),GUILayout.Height((position.width-30)*9/16));}
            DrawComparison();
            EditorGUILayout.EndScrollView();
        }
        void Try(Action action){try{action();}catch(Exception e){diagnostic=e.GetType().Name+": "+e.Message;}}
        void OnDisable(){if(preview!=null)DestroyImmediate(preview);foreach(var texture in comparisons.Values)DestroyImmediate(texture);comparisons.Clear();}
    }
}
