using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace HdrpAgent.Editor
{
    [InitializeOnLoad]
    public static class LocalValidationRunner
    {
        public static string Status{get;private set;}="Not started";
        public static bool Running=>stage!=null;
        static string stage,scope,a,b,c,baselineHash;
        static SnapshotRecord baseline;
        static BakeJob bake;
        static bool stopped;
        static JObject plan;
        static string Workspace=>Directory.GetParent(Application.dataPath).Parent.Parent.FullName;
        static string Report=>Path.Combine(Workspace,".hdrp-agent","reports","j0-local-pipeline.json");
        static LocalValidationRunner(){EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=()=>{if(Running){Status="Interrupted by domain reload";Save(false,"Domain reload interrupted qualification");}};}
        [MenuItem("Tools/HDRP Agent/Validation/Validate Local Pipeline")]
        public static void Start(){
            if(Running||BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)throw new InvalidOperationException("A session or editor operation already owns the scene");
            ValidationRoomBuilder.PrepareWorkingRoom();scope=SceneInspector.Scope;plan=JObject.Parse(File.ReadAllText(Path.Combine(Workspace,"fixtures","inspection-plans","room.json")));
            stopped=false;a=b=c=null;Status="GPU bake in progress";stage="baking";bake=BakeController.Begin(600);Save(false,"Local qualification running; no inference");
        }
        public static void Stop(){stopped=true;bake?.Cancel();if(EditorApplication.isPlaying)EditorApplication.isPlaying=false;Status="Stopping; waiting for native operations";}
        static bool Ready(string directory)=>!string.IsNullOrEmpty(directory)&&File.Exists(Path.Combine(directory,"editor-proof.json"));
        static void Tick(){
            if(stage==null)return;
            try{
                if(EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)return;
                if(stopped){Save(false,"Operator stopped local qualification");stage=null;return;}
                if(stage=="baking"){
                    if(!bake.Finished)return;baseline=SnapshotStore.Take(scope);baselineHash=baseline.manifest_hash;a=CaptureController.Begin(plan,true);stage="capture-a";Status="First graphical capture and six-second clip";return;
                }
                if(stage=="capture-a"&&Ready(a)){b=CaptureController.Begin(plan,false);stage="capture-b";Status="Repeated capture witness";return;}
                if(stage=="capture-b"&&Ready(b)){
                    var target=SceneInspector.Bindings.First(binding=>binding.GetComponent<UnityEngine.Rendering.Volume>()!=null);
                    var patch=new JObject{["id"]="j0-local-patch",["session_id"]="j0-local-session",["expected_version"]=SceneInspector.Version(),["hypothesis_id"]="j0-mutation-test",["expected_effect"]="Local transport and rollback test; not a visual correction",["operations"]=new JArray(new JObject{["op"]="set_fog",["target_id"]=target.logicalKey,["property"]="mean_free_path_m",["value"]=20}),["needs_bake"]=false};
                    PatchExecutor.Apply(patch,(string)patch["expected_version"]);var changed=SnapshotStore.ManifestHash(scope);if(changed==baselineHash)throw new InvalidOperationException("Test mutation did not change owned files");
                    SnapshotStore.Restore(baseline,changed);c=CaptureController.Begin(plan,false);stage="restored-capture";Status="Fresh capture after exact-file restoration";return;
                }
                if(stage=="restored-capture"&&Ready(c)){Save(SnapshotStore.ManifestHash(scope)==baselineHash,"Awaiting independent Python image repeatability and video checks");stage=null;Status="Graphical evidence ready for independent verification";}
            }catch(Exception e){Status=e.GetType().Name+": "+e.Message;stage="failed";Save(false,e.ToString());stage=null;}
        }
        static void Save(bool restored,string note){
            Directory.CreateDirectory(Path.GetDirectoryName(Report));var report=new JObject{["schema_version"]="1.0",["provider_mode"]="offline",["provider_requests_sent"]=0,["status"]=stage??"not_running",["capture_verified"]=false,["gpu_bake_verified"]=bake!=null&&bake.Finished&&bake.Succeeded,["restored_files_verified"]=restored,["scope_id"]=scope,["captures"]=new JArray(a,b,c),["baseline_manifest_hash"]=baselineHash,["bake_job_id"]=bake?.Id,["bake_error"]=bake?.Error,["note"]=note};
            File.WriteAllText(Report,report.ToString());
        }
    }
}
