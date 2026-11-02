using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
// Incremental, resumable prefab observations. Never instantiate into the user's scene.
[InitializeOnLoad] internal static class HouseVisualCatalogue {
 static Queue<JObject> pending;static JArray rows;static string directory,activePath;static bool activeDirty;
 internal static bool Running=>pending!=null;
 static HouseVisualCatalogue(){EditorApplication.update+=Tick;}
 [MenuItem("Tools/HDRP Agent/House/Render full visual catalogue")]
 static void Begin(){
  if(Running||CommandExecutor.Busy||DirectRoomExperiment.Running||HouseReferenceAudit.Running||ReferenceWorkflow.Running||Lightmapping.isRunning)throw new InvalidOperationException("Idle editor required for catalogue rendering");
  directory=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/house/visual-catalogue");Directory.CreateDirectory(directory);
  string manifest=Path.Combine(directory,"manifest.json");rows=File.Exists(manifest)?JArray.Parse(File.ReadAllText(manifest)):new JArray();
  var work=new List<JObject>();
  foreach(string guid in AssetDatabase.FindAssets("t:Prefab",new[]{"Assets/AtmosphericHouse/Prefabs","Assets/HouseProps"}).OrderBy(g=>g)){
   string path=AssetDatabase.GUIDToAssetPath(guid),hash=AssetDatabase.GetAssetDependencyHash(path).ToString();
   var old=rows.OfType<JObject>().FirstOrDefault(r=>(string)r["prefab_guid"]==guid);
   if(old!=null&&(string)old["dependency_hash"]==hash&&(string)old["status"]=="ready"&&File.Exists(Path.Combine(directory,(string)old["file"]))&&BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,(string)old["file"])))==(string)old["sha256"])continue;
   if(old!=null)rows.Remove(old);
   work.Add(new JObject{["asset_guid"]=guid,["dependency_hash"]=hash,["path"]=path});
  }
  activePath=SceneManager.GetActiveScene().path;activeDirty=SceneManager.GetActiveScene().isDirty;pending=new Queue<JObject>(work);Save();
 }
 static void Save(){ReferenceWorkflow.Atomic(Path.Combine(directory,"manifest.json"),rows);ReferenceWorkflow.Atomic(Path.Combine(directory,"progress.json"),new JObject{["pending"]=pending?.Count??0,["ready"]=rows.OfType<JObject>().Count(r=>(string)r["status"]=="ready"),["failed"]=rows.OfType<JObject>().Count(r=>(string)r["status"]=="failed"),["active_scene_unchanged"]=SceneManager.GetActiveScene().path==activePath,["active_scene_dirty_unchanged"]=SceneManager.GetActiveScene().isDirty==activeDirty,["status"]=pending==null?"complete":"rendering"});}
 static void Tick(){
  if(pending==null||EditorApplication.isCompiling||EditorApplication.isUpdating||CommandExecutor.Busy||DirectRoomExperiment.Running||HouseReferenceAudit.Running||ReferenceWorkflow.Running||Lightmapping.isRunning||EditorApplication.isPlayingOrWillChangePlaymode)return;
  if(pending.Count==0){pending=null;Save();return;}
  var asset=pending.Dequeue();string file=(string)asset["asset_guid"]+".png";
  var row=new JObject{["prefab_guid"]=asset["asset_guid"],["dependency_hash"]=asset["dependency_hash"],["path"]=asset["path"],["name"]=Path.GetFileNameWithoutExtension((string)asset["path"]),["file"]=file,["camera_offsets"]=new JArray(new JArray(1,.7,1),new JArray(-1,.7,-1)),["semantic_qualified"]=false};
  try{ReferenceAssets.SavePreview(asset,Path.Combine(directory,file));row["sha256"]=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,file)));row["status"]="ready";}
  catch(Exception e){row["status"]="failed";row["error"]=e.Message;}
  rows.Add(row);Save();
 }
}
}
