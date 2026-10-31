using System;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    [InitializeOnLoad]
    public static class BridgeClient
    {
        public static readonly string Epoch="editor-"+Guid.NewGuid().ToString("N");
        public static string Status {get;private set;}="Disconnected";
        public static bool Registered {get;private set;}
        public static bool RequestInProgress=>requesting;
        static bool sessionActive=true;
        public static bool SessionOwnsEditor=>ReferenceWorkflow.Running||(enabled&&(!Registered||sessionActive));
        public static string ProjectId {get;private set;}
        public static string SceneId {get;private set;}
        public static string Workspace {get;private set;}
        static string token;
        static string registrationNonce=Guid.NewGuid().ToString("N");
        static bool enabled,requesting;
        static double nextPoll,nextHeartbeat;
        static BridgeCommand current;
        static string pendingResult;
        const string BaseUrl="http://127.0.0.1:8765";
        static BridgeClient(){
            EditorApplication.update+=Update;
            EditorSceneManager.activeSceneChangedInEditMode+=(before,after)=>{Registered=false;registrationNonce=Guid.NewGuid().ToString("N");};
            AssemblyReloadEvents.beforeAssemblyReload+=()=>{ enabled=false; };
            EditorApplication.delayCall+=()=>{
                if(EditorPrefs.GetBool("HdrpAgent.BridgeEnabled",false)) Connect();
            };
        }
        [MenuItem("Window/HDRP Agent/Connect Local Service")]
        public static void Connect(){
            try{
                var project=Directory.GetParent(Application.dataPath).FullName;
                var root=new DirectoryInfo(project);
                while(root!=null&&!File.Exists(Path.Combine(root.FullName,"pyproject.toml")))root=root.Parent;
                if(root==null)throw new IOException("No registered workspace found");
                Workspace=root.FullName;
                // Asset import workers share the Unity application name. Bind OS
                // activation to this editor process, never to the ambiguous name.
                File.WriteAllText(Path.Combine(Workspace,".hdrp-agent","unity-editor.pid"),System.Diagnostics.Process.GetCurrentProcess().Id.ToString(System.Globalization.CultureInfo.InvariantCulture));
                var tokenPath=Path.Combine(Workspace,".hdrp-agent","local-token");
                token=File.ReadAllText(tokenPath).Trim();
                if(token.Length<20)throw new IOException("Local service token missing");
                ProjectId="project-"+BridgeJson.Hash(Encoding.UTF8.GetBytes(project)).Substring(0,24);
                CommandExecutor.Receipts=new ReceiptStore(Path.Combine(project,".hdrp-agent","bridge","receipts"));
                enabled=true;Registered=false;registrationNonce=Guid.NewGuid().ToString("N");Status="Connecting";nextPoll=0;
                EditorPrefs.SetBool("HdrpAgent.BridgeEnabled",true);
            }catch(Exception){Status="Start the local service and save a working scene before connecting";}
        }
        [MenuItem("Window/HDRP Agent/Disconnect Local Service")]
        public static void Disconnect(){enabled=false;Registered=false;Status="Disconnected";EditorPrefs.SetBool("HdrpAgent.BridgeEnabled",false);}
        static void Update(){
            if(!enabled||requesting||ReferenceWorkflow.Running||EditorApplication.isCompiling||EditorApplication.timeSinceStartup<nextPoll)return;
            nextPoll=EditorApplication.timeSinceStartup+.5;
            if(!Registered){Register();return;}
            if(pendingResult!=null){SendResult(pendingResult);return;}
            var receipt=CommandExecutor.Receipts.Pending().FirstOrDefault(p=>(string)p["bridge_epoch"]==Epoch&&p["result"].Type!=JTokenType.Null);
            if(receipt!=null){pendingResult=(string)receipt["command_id"];SendResult(pendingResult);return;}
            if(CommandExecutor.Busy){
                if(EditorApplication.timeSinceStartup<nextHeartbeat)return;
                nextHeartbeat=EditorApplication.timeSinceStartup+1;
                var progress=new {bridge_epoch=Epoch,phase="running",progress=0.0,message="Unity job active; native stages may defer callbacks"};
                Request("POST","/v1/bridge/commands/"+current.id+"/progress",BridgeJson.Write(progress),null,(ok,text)=>{
                    if(!ok)return;
                    try{var control=BridgeJson.Read<CommandControl>(text);if(control.command_id!=current.id)throw new InvalidDataException();if(control.directive=="cancel")CommandExecutor.Cancel();else if(control.directive!="continue")throw new InvalidDataException();}
                    catch(Exception){Status="Invalid control response; recovery required";CommandExecutor.Cancel();}
                });return;
            }
            Request("POST","/v1/bridge/poll",BridgeJson.Write(new{project_id=ProjectId,bridge_epoch=Epoch,last_receipt_id=(string)null}),null,(ok,text)=>{
                if(!ok)return;
                try{
                    var batch=BridgeJson.Read<CommandBatch>(text);
                    sessionActive=batch.session_active;
                    if(batch.commands.Length>1)throw new InvalidDataException("More than one command claimed");
                    if(batch.commands.Length==0)return;
                    current=batch.commands[0];
                    CommandExecutor.Start(current,Epoch,result=>{pendingResult=result.command_id;Status="Receipt saved; awaiting acknowledgement";});
                }catch(Exception){Status="Command rejected; durable receipt reconciliation required";}
            });
        }
        static void Register(){
            var scene=SceneManager.GetActiveScene();
            if(!scene.IsValid()||string.IsNullOrEmpty(scene.path)||scene.isDirty){Status="Save the working scene before registering";nextPoll=EditorApplication.timeSinceStartup+2;return;}
            if(UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline==null||SystemInfo.graphicsDeviceType!=UnityEngine.Rendering.GraphicsDeviceType.Metal){Status="HDRP/Metal capability missing";return;}
            SceneId="scene-"+AssetDatabase.AssetPathToGUID(scene.path);
            var data=new {project_id=ProjectId,scene_id=SceneId,project_root=Directory.GetParent(Application.dataPath).FullName,working_scene_path=scene.path,
                editor_version=Application.unityVersion,hdrp_version="17.3.0",graphics_api="Metal",scene_version=CommandExecutor.CurrentVersion(),
                capabilities=CommandExecutor.Capabilities.Concat(new[]{"bridge-v1","durable-receipts"}).ToArray(),bridge_epoch=Epoch};
            Request("POST","/v1/projects/register",BridgeJson.Write(data),Epoch+"-"+registrationNonce+"-"+SceneId+"-"+data.scene_version,(ok,text)=>{Registered=ok;Status=ok?"Connected (offline capabilities only until qualified)":"Registration failed; inspect local service";});
        }
        static void SendResult(string id){
            var receipt=CommandExecutor.Receipts.Get(id);
            Request("POST","/v1/bridge/commands/"+id+"/result",BridgeJson.Write(receipt["result"]),null,(ok,text)=>{
                if(ok){CommandExecutor.Receipts.Acknowledge(id);pendingResult=null;Status="Connected; receipt acknowledged";}
            });
        }
        public static void PutArtifact(byte[] bytes,string mediaType,Action<bool,string> done){
            if(requesting)throw new InvalidOperationException("Bridge request already active");
            requesting=true;var hash=BridgeJson.Hash(bytes);
            var request=new UnityWebRequest(BaseUrl+"/v1/artifacts/"+hash,"PUT"){downloadHandler=new DownloadHandlerBuffer(),uploadHandler=new UploadHandlerRaw(bytes),timeout=20};
            request.SetRequestHeader("Authorization","Bearer "+token);request.SetRequestHeader("Content-Type",mediaType);
            request.SendWebRequest().completed+=op=>{requesting=false;bool ok=request.result==UnityWebRequest.Result.Success;request.Dispose();done(ok,hash);};
        }
        public static void Request(string method,string route,string body,string idempotency,Action<bool,string> done){
            if(requesting)throw new InvalidOperationException("Bridge HTTP request already active");
            if(method!="GET"&&method!="POST")throw new InvalidDataException("Unsupported bridge request method");
            var request=new UnityWebRequest(BaseUrl+route,method){downloadHandler=new DownloadHandlerBuffer(),timeout=5};
            if(body!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));request.SetRequestHeader("Content-Type","application/json");}
            request.SetRequestHeader("Authorization","Bearer "+token);
            if(idempotency!=null)request.SetRequestHeader("Idempotency-Key",idempotency);
            requesting=true;
            try{request.SendWebRequest().completed+=op=>{
                requesting=false;
                bool ok=request.result==UnityWebRequest.Result.Success;
                var response=request.downloadHandler.text;
                if(!ok){Status="Local service unavailable or request rejected; no command replay";nextPoll=EditorApplication.timeSinceStartup+2;}
                request.Dispose();done(ok,response);
            };}catch{requesting=false;request.Dispose();throw;}
        }
    }
}
