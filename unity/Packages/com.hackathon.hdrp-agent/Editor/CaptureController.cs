using System;
using System.IO;
using System.Linq;
using HdrpAgent.Runtime;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    [InitializeOnLoad]
    public static class CaptureController
    {
        const string Pending="HdrpAgent.PendingCapture";
        static string State=>Path.Combine(Directory.GetParent(Application.dataPath).FullName,".hdrp-agent","captures");
        public static string LastOutput=>SessionState.GetString("HdrpAgent.LastCapture","");
        static double began;
        static CaptureController(){EditorApplication.playModeStateChanged+=Changed;EditorApplication.update+=Tick;}
        // Unity 6000.3 editor-only adapter; actual dimensions are independently checked by readback.
        public static void SetGameViewSize(int width,int height){
            var assembly=typeof(EditorWindow).Assembly;
            var sizes=assembly.GetType("UnityEditor.GameViewSizes");var instance=sizes.BaseType.GetProperty("instance").GetValue(null);
            var group=sizes.GetProperty("currentGroup").GetValue(instance);var groupType=group.GetType();var index=(int)groupType.GetMethod("GetTotalCount").Invoke(group,null);
            var sizeType=assembly.GetType("UnityEditor.GameViewSizeType");var type=assembly.GetType("UnityEditor.GameViewSize");
            var size=Activator.CreateInstance(type,new object[]{Enum.Parse(sizeType,"FixedResolution"),width,height,"HDRP Agent "+width+"x"+height});
            groupType.GetMethod("AddCustomSize").Invoke(group,new[]{size});
            var game=EditorWindow.GetWindow(assembly.GetType("UnityEditor.GameView"));game.Show();game.Focus();
            game.GetType().GetMethod("SizeSelectionCallback").Invoke(game,new object[]{index,null});game.Repaint();
        }
        public static string Begin(JObject plan,bool includeClip=true)=>BeginInternal(plan,includeClip,false);
        public static string BeginReference(JObject plan,bool includeClip=true)=>BeginInternal(plan,includeClip,true);
        public static JObject RuntimePlan(JObject plan)=>JObject.Parse(JsonUtility.ToJson(JsonUtility.FromJson<CapturePlan>(plan.ToString())));
        static string BeginInternal(JObject plan,bool includeClip,bool preserveCamera){
            if(EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning||SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("Saved EditMode with no active bake required");
            if(EditorUtility.scriptCompilationFailed||EditorApplication.isCompiling)throw new InvalidOperationException("Fix all compiler errors before capture");
            var scope=SceneInspector.Scope;var id="capture-"+Guid.NewGuid().ToString("N");var directory=Path.Combine(State,id);Directory.CreateDirectory(directory);
            // Hash the actual float-valued runtime plan, independent of JSON numeric parsing.
            if(preserveCamera)plan=RuntimePlan(plan);
            var request=new CaptureRequest{capture_id=id,output_directory=directory,scope_id=scope,scene_manifest_hash=SnapshotStore.ManifestHash(scope),bake_status=BakeController.Active!=null&&BakeController.Active.Finished&&BakeController.Active.Succeeded&&(string)BakeController.Active.Journal["after_version"]==SceneInspector.Version()?"complete":"not_required",bake_job_id=BakeController.Active?.Id,version_id=SceneInspector.Version(),inspection_hash=BridgeJson.CanonicalHash(plan),conditions_hash=BridgeJson.CanonicalHash(JObject.FromObject(new{plan,unity=Application.unityVersion,hdrp="17.3.0",graphics=SystemInfo.graphicsDeviceType.ToString(),color_space="sRGB_LDR_gameview",anti_aliasing="none",dynamic_resolution=false})),plan=JsonUtility.FromJson<CapturePlan>(plan.ToString()),include_clip=includeClip};
            request.preserve_camera_settings=preserveCamera;
            if(preserveCamera)request.conditions_hash=BridgeJson.CanonicalHash(JObject.FromObject(new{plan,unity=Application.unityVersion,hdrp="17.3.0",graphics=SystemInfo.graphicsDeviceType.ToString(),preserve_camera_settings=true,color_space="sRGB_LDR_gameview",anti_aliasing="none",dynamic_resolution=false}));
            var file=Path.Combine(directory,"request.json");File.WriteAllText(file,JsonUtility.ToJson(request,true));
            SetGameViewSize(request.plan.width,request.plan.height);
            SessionState.SetString(Pending,file);SessionState.SetString("HdrpAgent.LastCapture",directory);SessionState.SetFloat("HdrpAgent.CaptureStarted",(float)EditorApplication.timeSinceStartup);
            SessionState.SetBool("HdrpAgent.CaptureRunning",false);
            SessionState.SetBool("HdrpAgent.PreviousPlayOptionsEnabled",EditorSettings.enterPlayModeOptionsEnabled);
            SessionState.SetInt("HdrpAgent.PreviousPlayOptions",(int)EditorSettings.enterPlayModeOptions);
            EditorSettings.enterPlayModeOptionsEnabled=true;EditorSettings.enterPlayModeOptions=EnterPlayModeOptions.DisableDomainReload;
            EditorApplication.isPlaying=true;return directory;
        }
        static void Changed(PlayModeStateChange state){
            var pending=SessionState.GetString(Pending,"");if(string.IsNullOrEmpty(pending))return;
            if(state==PlayModeStateChange.EnteredPlayMode){
                SessionState.SetBool("HdrpAgent.CaptureRunning",true);
                var game=EditorWindow.GetWindow(typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView"));game.Show();game.Focus();game.Repaint();
                try{var request=JsonUtility.FromJson<CaptureRequest>(File.ReadAllText(pending));var rig=new GameObject("HDRP Agent Capture Job").AddComponent<CaptureRig>();rig.Configure(request);began=EditorApplication.timeSinceStartup;}
                catch(Exception){File.WriteAllText(Path.Combine(Path.GetDirectoryName(pending),"interruption.json"),"{\"status\":\"interrupted\",\"reason\":\"Runtime rig initialization failed\"}");EditorApplication.isPlaying=false;}
            }
            if(state==PlayModeStateChange.EnteredEditMode){
                var directory=Path.GetDirectoryName(pending);var manifest=Path.Combine(directory,"manifest.json");
                if(File.Exists(manifest)){
                    var data=JObject.Parse(File.ReadAllText(manifest));var hashes=new JObject();
                    if(data["frames"] is JArray frames)foreach(var frame in frames){var name=(string)frame["file"];if(Path.GetFileName(name)!=name)throw new InvalidDataException("Frame path outside capture root");hashes[name]=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,name)));}
                    var proof=new JObject{["scene_version_after"]=SceneInspector.Version(),["manifest_hash_after"]=SnapshotStore.ManifestHash(SceneInspector.Scope),["frame_hashes"]=hashes};
                    File.WriteAllText(Path.Combine(directory,"editor-proof.json"),proof.ToString());
                }
                SessionState.EraseString(Pending);SessionState.SetBool("HdrpAgent.CaptureRunning",false);
                EditorSettings.enterPlayModeOptionsEnabled=SessionState.GetBool("HdrpAgent.PreviousPlayOptionsEnabled",false);
                EditorSettings.enterPlayModeOptions=(EnterPlayModeOptions)SessionState.GetInt("HdrpAgent.PreviousPlayOptions",0);
            }
        }
        static void Tick(){
            var pending=SessionState.GetString(Pending,"");if(string.IsNullOrEmpty(pending))return;
            if(!EditorApplication.isPlayingOrWillChangePlaymode&&EditorApplication.timeSinceStartup-SessionState.GetFloat("HdrpAgent.CaptureStarted",0)>10){
                File.WriteAllText(Path.Combine(Path.GetDirectoryName(pending),"interruption.json"),"{\"status\":\"interrupted\",\"reason\":\"PlayMode did not start\"}");
                EditorSettings.enterPlayModeOptionsEnabled=SessionState.GetBool("HdrpAgent.PreviousPlayOptionsEnabled",false);EditorSettings.enterPlayModeOptions=(EnterPlayModeOptions)SessionState.GetInt("HdrpAgent.PreviousPlayOptions",0);SessionState.EraseString(Pending);return;
            }
            if(!EditorApplication.isPlaying||!SessionState.GetBool("HdrpAgent.CaptureRunning",false))return;
            var directory=Path.GetDirectoryName(pending);var manifest=Path.Combine(directory,"manifest.json");
            if(File.Exists(manifest)){
                var result=JObject.Parse(File.ReadAllText(manifest));if((string)result["status"]!="running"){EditorApplication.isPlaying=false;return;}
            }
            if(EditorApplication.timeSinceStartup-began>180){File.WriteAllText(Path.Combine(directory,"interruption.json"),"{\"status\":\"interrupted\",\"reason\":\"GameView timeout\"}");EditorApplication.isPlaying=false;}
        }
    }
}
