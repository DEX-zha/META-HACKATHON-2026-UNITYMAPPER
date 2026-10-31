using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    public sealed class BakeJob
    {
        public readonly string Id="bake-"+Guid.NewGuid().ToString("N");
        public readonly string BeforeVersion,ScenePath;
        public readonly DateTimeOffset Deadline;
        public bool Finished{get;private set;}
        public bool Succeeded{get;private set;}
        public string Error{get;private set;}
        public JObject Journal{get;private set;}
        bool started,completed,cancelled,cancelRequested,nativeAccepted,hasError;
        readonly JArray events=new JArray();
        readonly string reportPath;
        public BakeJob(int timeoutSeconds){
            if(timeoutSeconds<30||timeoutSeconds>600)throw new InvalidDataException("MVP GPU bake timeout must be 30–600 seconds");
            if(EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)throw new InvalidOperationException("Editor/bake is busy");
            if(SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("Save owned scene before bake");
            var scope=SceneInspector.Scope;var settings=Lightmapping.lightingSettings;
            if(settings==null||!AssetDatabase.GetAssetPath(settings).StartsWith(SnapshotStore.Root(scope)+"/",StringComparison.Ordinal))throw new InvalidDataException("Owned LightingSettings required");
            if(settings.lightmapper!=LightingSettings.Lightmapper.ProgressiveGPU)throw new InvalidDataException("Progressive GPU required; CPU fallback is not qualified");
            if(!SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(o=>o.GetComponentsInChildren<ProbeVolume>(true)).Any())throw new InvalidOperationException("Prepare an owned Adaptive Probe Volume before baking; native modal prompts suspend the bridge");
            BeforeVersion=SceneInspector.Version();ScenePath=SceneManager.GetActiveScene().path;Deadline=DateTimeOffset.UtcNow.AddSeconds(timeoutSeconds);
            var dir=Path.Combine(Directory.GetParent(Application.dataPath).FullName,".hdrp-agent","bakes");Directory.CreateDirectory(dir);reportPath=Path.Combine(dir,Id+".json");
            Journal=JObject.FromObject(new{schema_version="1.0",job_id=Id,scene_path=ScenePath,before_version=BeforeVersion,status="pending",deadline_utc=Deadline.ToString("O"),events});
            Lightmapping.bakeStarted+=Started;Lightmapping.bakeCompleted+=Completed;Lightmapping.bakeCancelled+=Cancelled;Application.logMessageReceived+=Log;
            EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=Reload;
            Record("requested");
            try{nativeAccepted=Lightmapping.BakeAsync();if(!nativeAccepted){hasError=true;Error="GPU bake was refused";}}catch(Exception){hasError=true;Error="GPU bake failed to start";}
        }
        void Record(string phase){events.Add(new JObject{["phase"]=phase,["utc"]=DateTimeOffset.UtcNow.ToString("O")});Journal["events"]=events.DeepClone();Persist();}
        void Persist(){var bytes=System.Text.Encoding.UTF8.GetBytes(Journal.ToString());var tmp=reportPath+".writing";using(var stream=new FileStream(tmp,FileMode.Create,FileAccess.Write,FileShare.None)){stream.Write(bytes,0,bytes.Length);stream.Flush(true);}if(File.Exists(reportPath))File.Replace(tmp,reportPath,null);else File.Move(tmp,reportPath);}
        void Started(){started=true;Journal["status"]="running";Record("bakeStarted");}
        void Completed(){completed=true;Record("bakeCompleted");}
        void Cancelled(){cancelled=true;Record("bakeCancelled");}
        void Log(string text,string trace,LogType type){
            if(type==LogType.Error||type==LogType.Exception||text.IndexOf("falling back",StringComparison.OrdinalIgnoreCase)>=0||text.IndexOf("fallback",StringComparison.OrdinalIgnoreCase)>=0){hasError=true;Error="Unity reported a bake error or backend fallback";Record("engine_error_or_fallback");}
        }
        public void Cancel(){if(Finished)return;cancelRequested=true;Journal["status"]="cancelling";Record("cancel_requested");if(Lightmapping.isRunning)Lightmapping.Cancel();}
        void Tick(){
            if(Finished)return;
            if(DateTimeOffset.UtcNow>=Deadline&&!cancelRequested)Cancel();
            if(Lightmapping.isRunning)return;
            if(!completed&&!cancelled&&nativeAccepted&&!hasError&&DateTimeOffset.UtcNow<Deadline)return;
            bool resources=Lightmapping.lightingDataAsset!=null&&LightmapSettings.lightmaps.Length>0&&LightmapSettings.lightmaps.All(m=>m.lightmapColor!=null);
            bool local=resources&&AssetDatabase.GetAssetPath(Lightmapping.lightingDataAsset).StartsWith(SnapshotStore.Root(SceneInspector.Scope)+"/",StringComparison.Ordinal)&&LightmapSettings.lightmaps.All(m=>AssetDatabase.GetAssetPath(m.lightmapColor).StartsWith(SnapshotStore.Root(SceneInspector.Scope)+"/",StringComparison.Ordinal));
            Succeeded=started&&completed&&!cancelled&&!cancelRequested&&!hasError&&resources&&local;
            if(!Succeeded&&Error==null)Error=cancelRequested?"Bake cancelled or deadline reached":"Current-job completion and owned lightmap resources were not verified";
            AssetDatabase.SaveAssets();EditorSceneManager.SaveScene(SceneManager.GetActiveScene());
            Journal["status"]=Succeeded?"complete":cancelRequested||cancelled?"interrupted":"failed";Journal["error"]=Error;Journal["resources_verified"]=resources&&local;Journal["after_version"]=SceneInspector.Version();Journal["manifest_hash"]=SnapshotStore.ManifestHash(SceneInspector.Scope);
            Finished=true;Record("stopped");Detach();
        }
        void Reload(){if(Finished)return;Journal["status"]="interrupted";Record("domain_reload_without_completion_proof");Detach();}
        void Detach(){Lightmapping.bakeStarted-=Started;Lightmapping.bakeCompleted-=Completed;Lightmapping.bakeCancelled-=Cancelled;Application.logMessageReceived-=Log;EditorApplication.update-=Tick;AssemblyReloadEvents.beforeAssemblyReload-=Reload;}
    }
    public static class BakeController
    {
        public static BakeJob Active{get;private set;}
        public static BakeJob Begin(int timeoutSeconds=600){if(Active!=null&&!Active.Finished)throw new InvalidOperationException("Bake job already active");return Active=new BakeJob(timeoutSeconds);}
    }
}
