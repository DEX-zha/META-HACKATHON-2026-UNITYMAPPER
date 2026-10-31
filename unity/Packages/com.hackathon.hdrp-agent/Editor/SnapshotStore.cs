using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    public sealed class SnapshotRecord {
        public string id, scope_id, scene_path, manifest_hash;
        public Dictionary<string,string> files;
    }
    public static class SnapshotStore
    {
        public const string Runs="Assets/AgentWorkspace/Runs";
        static string Project=>Directory.GetParent(Application.dataPath).FullName;
        static string Archive=>Path.Combine(Project,".hdrp-agent","snapshots");
        public static string Root(string scope){
            if(string.IsNullOrEmpty(scope)||!Regex.IsMatch(scope,@"^[A-Za-z0-9_-]{1,100}$"))throw new InvalidDataException("Invalid owned scope");
            return Runs+"/"+scope;
        }
        static void NoLinks(string path){
            var absolute=Path.GetFullPath(path);
            if(!absolute.StartsWith(Project+Path.DirectorySeparatorChar,StringComparison.Ordinal))throw new InvalidDataException("Path outside project");
            var item=new FileInfo(absolute) as FileSystemInfo;
            while(item!=null&&item.FullName!=Project){if((File.Exists(item.FullName)||Directory.Exists(item.FullName))&&(item.Attributes&FileAttributes.ReparsePoint)!=0)throw new InvalidDataException("Symlink in owned path");item=Directory.GetParent(item.FullName);}
        }
        public static Dictionary<string,string> Manifest(string scope){
            var root=Root(scope);NoLinks(root);
            if(!Directory.Exists(root))throw new DirectoryNotFoundException("Owned scope is missing");
            var files=Directory.GetFiles(root,"*",SearchOption.AllDirectories).OrderBy(p=>p,StringComparer.Ordinal);
            var result=new Dictionary<string,string>();
            foreach(var file in files){NoLinks(file);result[file.Replace('\\','/')]=BridgeJson.Hash(File.ReadAllBytes(file));}
            return result;
        }
        public static string ManifestHash(string scope)=>BridgeJson.CanonicalHash(Newtonsoft.Json.Linq.JObject.FromObject(Manifest(scope)));
        static bool Mutable(string path){
            var type=AssetDatabase.GetMainAssetTypeAtPath(path);
            return type!=null&&(typeof(Material).IsAssignableFrom(type)||typeof(VolumeProfile).IsAssignableFrom(type)||typeof(LightingSettings).IsAssignableFrom(type)||typeof(LightingDataAsset).IsAssignableFrom(type)||typeof(ProbeVolumeBakingSet).IsAssignableFrom(type)||
                (typeof(TextAsset).IsAssignableFrom(type)&&Path.GetFileName(path).Contains(".Cell"))||
                (typeof(Texture).IsAssignableFrom(type)&&Path.GetFileName(path).StartsWith("Lightmap",StringComparison.OrdinalIgnoreCase)));
        }
        public static string CreateWorkingCopy(string source,string scope){
            if(EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)throw new InvalidOperationException("EditMode without active bake is required");
            if(!source.StartsWith("Assets/",StringComparison.Ordinal)||!source.EndsWith(".unity",StringComparison.Ordinal)||!File.Exists(source))throw new InvalidDataException("Saved source scene is required");
            NoLinks(source);
            var active=SceneManager.GetActiveScene();if(active.isDirty)throw new InvalidOperationException("Save source changes first");
            var root=Root(scope);if(Directory.Exists(root))throw new InvalidOperationException("Scope already exists");
            Directory.CreateDirectory(root+"/Resources");AssetDatabase.Refresh();
            var remaps=new Dictionary<string,string>();
            foreach(var dependency in AssetDatabase.GetDependencies(source,true).Where(Mutable)){
                var dest=root+"/Resources/"+AssetDatabase.AssetPathToGUID(dependency)+"-"+Path.GetFileName(dependency);
                if(!AssetDatabase.CopyAsset(dependency,dest))throw new IOException("Cannot clone mutable dependency");
                remaps[AssetDatabase.AssetPathToGUID(dependency)]=AssetDatabase.AssetPathToGUID(dest);
            }
            var working=root+"/Working.unity";
            if(!AssetDatabase.CopyAsset(source,working))throw new IOException("Cannot clone scene");
            remaps[AssetDatabase.AssetPathToGUID(source)]=AssetDatabase.AssetPathToGUID(working);
            var serialized=Directory.GetFiles(root,"*",SearchOption.AllDirectories).Where(p=>p.EndsWith(".unity")||p.EndsWith(".mat")||p.EndsWith(".asset")).ToArray();
            AssetDatabase.ForceReserializeAssets(serialized,ForceReserializeAssetsOptions.ReserializeAssets);
            // Unity-generated text assets: remap GUID references, while retaining each new .meta GUID.
            foreach(var file in serialized){
                var bytes=File.ReadAllBytes(file);var text=Encoding.UTF8.GetString(bytes);
                if(!text.StartsWith("%YAML",StringComparison.Ordinal))throw new InvalidDataException("Dependency cannot be safely remapped as serialized YAML");
                foreach(var pair in remaps)text=Regex.Replace(text,@"(?<![a-fA-F0-9])"+Regex.Escape(pair.Key)+@"(?![a-fA-F0-9])",pair.Value);
                File.WriteAllText(file,text,new UTF8Encoding(false));
            }
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            EditorSceneManager.OpenScene(working,OpenSceneMode.Single);
            // APV-enabled HDRP otherwise opens a modal prompt inside BakeAsync,
            // suspending main-thread heartbeats. Prepare the owned copy explicitly.
            if(!SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(o=>o.GetComponentsInChildren<ProbeVolume>(true)).Any()){
                var probes=new GameObject("Adaptive Probe Volume").AddComponent<ProbeVolume>();probes.mode=ProbeVolume.Mode.Scene;
            }
            SceneInspector.BindWorkingScene(source);
            File.WriteAllText(root+"/provenance.json",JsonConvert.SerializeObject(new{source_scene=source,working_scene=working,source_to_working_guids=remaps},Formatting.Indented));
            AssetDatabase.Refresh();
            return working;
        }
        public static SnapshotRecord Take(string scope){
            if(Lightmapping.isRunning||EditorApplication.isPlayingOrWillChangePlaymode)throw new InvalidOperationException("Snapshot requires a stopped editor operation");
            var scene=SceneManager.GetActiveScene();
            if(!scene.path.StartsWith(Root(scope)+"/",StringComparison.Ordinal))throw new InvalidDataException("Active scene is outside scope");
            if(scene.isDirty)throw new InvalidOperationException("Save owned scene before snapshot");
            AssetDatabase.SaveAssets();
            var record=new SnapshotRecord{id="snapshot-"+Guid.NewGuid().ToString("N"),scope_id=scope,scene_path=scene.path,files=Manifest(scope),manifest_hash=ManifestHash(scope)};
            var folder=Path.Combine(Archive,record.id);Directory.CreateDirectory(folder);
            foreach(var pair in record.files){var dest=Path.Combine(folder,pair.Value);if(!File.Exists(dest))File.Copy(pair.Key,dest);}
            File.WriteAllText(Path.Combine(folder,"record.json"),JsonConvert.SerializeObject(record,Formatting.Indented));
            return record;
        }
        public static SnapshotRecord Load(string id){
            if(!Regex.IsMatch(id??"",@"^snapshot-[a-f0-9]{32}$"))throw new InvalidDataException("Invalid snapshot ID");
            return JsonConvert.DeserializeObject<SnapshotRecord>(File.ReadAllText(Path.Combine(Archive,id,"record.json")));
        }
        public static void Restore(SnapshotRecord record,string expectedManifest){
            if(Lightmapping.isRunning||EditorApplication.isPlayingOrWillChangePlaymode)throw new InvalidOperationException("Wait for actual bake/PlayMode stop before restoring files");
            if(SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("CONCURRENT_EDIT: unsaved editor change");
            if(ManifestHash(record.scope_id)!=expectedManifest)throw new InvalidOperationException("CONCURRENT_EDIT: owned files changed");
            var root=Root(record.scope_id);
            foreach(var pair in record.files){
                if(!pair.Key.StartsWith(root+"/",StringComparison.Ordinal))throw new InvalidDataException("Snapshot contains an unowned file");
                NoLinks(pair.Key);var backup=Path.Combine(Archive,record.id,pair.Value);
                if(!File.Exists(backup)||BridgeJson.Hash(File.ReadAllBytes(backup))!=pair.Value)throw new InvalidDataException("Snapshot is corrupt");
            }
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
            AssetDatabase.StartAssetEditing();
            try{
                foreach(var file in Manifest(record.scope_id).Keys.Where(p=>!record.files.ContainsKey(p)))File.Delete(file);
                foreach(var pair in record.files){Directory.CreateDirectory(Path.GetDirectoryName(pair.Key));File.Copy(Path.Combine(Archive,record.id,pair.Value),pair.Key,true);}
            }finally{AssetDatabase.StopAssetEditing();}
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            EditorSceneManager.OpenScene(record.scene_path,OpenSceneMode.Single);
            if(ManifestHash(record.scope_id)!=record.manifest_hash)throw new IOException("Restored manifest differs after reimport");
            File.WriteAllText(Path.Combine(Archive,record.id,"restore-log.json"),JsonConvert.SerializeObject(new{restored_utc=DateTimeOffset.UtcNow,expected_manifest=expectedManifest,restored_manifest=record.manifest_hash}));
        }
    }
}
