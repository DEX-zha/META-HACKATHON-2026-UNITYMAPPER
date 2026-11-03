using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.SceneManagement;
using UnityEngine.Rendering;

namespace HdrpAgent.Editor {
// APV inspects every loaded scene even for a scene-scoped lightmap bake.
// Never unload unsaved work or enroll another scene in the candidate's set.
[InitializeOnLoad] internal sealed class HouseBakeIsolation {
 readonly JArray originals; readonly string journal; bool entered,restored;
 static string JournalPath=>Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/house/bake-isolation.json");
 static HouseBakeIsolation(){EditorApplication.delayCall+=Recover;EditorApplication.delayCall+=AuditScenes;}
 internal HouseBakeIsolation(){
  journal=JournalPath;
  if(File.Exists(journal))throw new InvalidOperationException("Previous bake scene restoration is pending");
  originals=new JArray();
  for(int index=0;index<SceneManager.sceneCount;index++){
   var s=SceneManager.GetSceneAt(index);
   if(string.IsNullOrEmpty(s.path)||!File.Exists(s.path)||(s.isLoaded&&s.isDirty))throw new InvalidOperationException("Save modified or untitled scenes before isolated lighting baking; no scene was unloaded");
   originals.Add(new JObject{["path"]=s.path,["loaded"]=s.isLoaded,["active"]=s==SceneManager.GetActiveScene(),["sha256"]=Hash(s.path)});
  }
 }
 static string Hash(string path)=>File.Exists(path)?BridgeJson.Hash(File.ReadAllBytes(path)):null;
 internal void Enter(Scene candidate){
  if(entered)throw new InvalidOperationException("Bake isolation already entered");
  foreach(JObject row in originals){var s=SceneManager.GetSceneByPath((string)row["path"]);if(Hash(s.path)!=(string)row["sha256"]||((bool)row["loaded"]&&s.isDirty))throw new InvalidOperationException("Scene changed before bake isolation");}
  ReferenceWorkflow.Atomic(journal,new JObject{["candidate"]=candidate.path,["originals"]=originals.DeepClone()});entered=true;
  SceneManager.SetActiveScene(candidate);
  foreach(JObject row in originals){var s=SceneManager.GetSceneByPath((string)row["path"]);if(!EditorSceneManager.CloseScene(s,true))throw new InvalidOperationException("Could not unload clean scene for bake isolation");}
  // Drain old-set deletions before the bake switches the active APV set.
  ProbeReferenceVolume.instance.PerformPendingOperations();
 }
 internal bool Unchanged(Scene candidate)=>entered&&!restored&&originals.Cast<JObject>().All(r=>Hash((string)r["path"])==(string)r["sha256"]&&!SceneManager.GetSceneByPath((string)r["path"]).isLoaded)&&Enumerable.Range(0,SceneManager.sceneCount).All(i=>!SceneManager.GetSceneAt(i).isLoaded||SceneManager.GetSceneAt(i)==candidate);
 internal bool Restore(){
  if(!entered||restored)return true;
  bool ok=RestoreRows(originals);if(ok){restored=true;File.Delete(journal);}return ok;
 }
 static bool RestoreRows(JArray rows){
  // Refuse changed files rather than silently replacing the user's scene state.
  if(rows.Cast<JObject>().Any(r=>Hash((string)r["path"])!=(string)r["sha256"]))return false;
  foreach(JObject row in rows)if((bool)row["loaded"]){
   var s=SceneManager.GetSceneByPath((string)row["path"]);
   if(!s.isLoaded)s=EditorSceneManager.OpenScene((string)row["path"],OpenSceneMode.Additive);
   if(!s.isLoaded||s.isDirty)return false;
  }
  foreach(JObject row in rows)if(!(bool)row["loaded"]){
   var s=SceneManager.GetSceneByPath((string)row["path"]);
   if(!s.IsValid())s=EditorSceneManager.OpenScene((string)row["path"],OpenSceneMode.AdditiveWithoutLoading);
   if(s.isLoaded)return false;
  }
  var active=rows.Cast<JObject>().FirstOrDefault(r=>(bool)r["active"]);
  return active==null||SceneManager.GetActiveScene().path==(string)active["path"]||SceneManager.SetActiveScene(SceneManager.GetSceneByPath((string)active["path"]));
 }
 [MenuItem("Tools/HDRP Agent/House/Test bake isolation guards")]
 static void TestGuards(){
  var active=SceneManager.GetActiveScene();var before=EditorSceneManager.GetSceneManagerSetup();
  var temporary=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);
  bool rejected=false;
  try{try{new HouseBakeIsolation();}catch(InvalidOperationException){rejected=true;}
   var report=new JObject{["untitled_scene_rejected"]=rejected,["untitled_scene_still_loaded"]=temporary.isLoaded,["original_scenes_still_loaded"]=before.All(s=>SceneManager.GetSceneByPath(s.path).isLoaded==s.isLoaded),["no_recovery_journal_created"]=!File.Exists(JournalPath)};
   string folder="Assets/AgentWorkspace/IsolationTests/"+Guid.NewGuid().ToString("N");System.IO.Directory.CreateDirectory(folder);
   EditorSceneManager.SaveScene(temporary,folder+"/DirtySource.unity");EditorSceneManager.MarkSceneDirty(temporary);
   bool dirtyRejected=false;try{new HouseBakeIsolation();}catch(InvalidOperationException){dirtyRejected=true;}
   report["modified_scene_rejected"]=dirtyRejected&&temporary.isLoaded&&temporary.isDirty;
   EditorSceneManager.CloseScene(temporary,true);
   var unloaded=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);string unloadedPath=folder+"/Unloaded.unity";
   EditorSceneManager.SaveScene(unloaded,unloadedPath);SceneManager.SetActiveScene(active);EditorSceneManager.CloseScene(unloaded,false);
   var scope=new HouseBakeIsolation();var candidate=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);EditorSceneManager.SaveScene(candidate,folder+"/Candidate.unity");
   try{scope.Enter(candidate);report["candidate_is_only_registered_scene"]=SceneManager.sceneCount==1&&scope.Unchanged(candidate);report["restore_succeeded"]=scope.Restore();
    var returned=SceneManager.GetSceneByPath(unloadedPath);report["unloaded_scene_restored"]=returned.IsValid()&&!returned.isLoaded;
    report["active_scene_restored"]=SceneManager.GetActiveScene().path==before.First(s=>s.isActive).path;
   }finally{scope.Restore();if(candidate.IsValid())EditorSceneManager.CloseScene(candidate,true);var returned=SceneManager.GetSceneByPath(unloadedPath);if(returned.IsValid())EditorSceneManager.CloseScene(returned,true);}
   report["passed"]=report.Properties().All(p=>(bool)p.Value);
   ReferenceWorkflow.Atomic(Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reports/bake-isolation-guards.json"),report);
  }finally{if(temporary.IsValid())EditorSceneManager.CloseScene(temporary,true);var original=SceneManager.GetSceneByPath(before.First(s=>s.isActive).path);if(original.IsValid())SceneManager.SetActiveScene(original);}
 }
 static void AuditScenes(){
  var rows=new JArray();for(int i=0;i<SceneManager.sceneCount;i++){var s=SceneManager.GetSceneAt(i);rows.Add(new JObject{["path"]=s.path,["loaded"]=s.isLoaded,["dirty"]=s.isDirty,["roots"]=s.isLoaded?new JArray(s.GetRootGameObjects().Select(g=>g.name)):new JArray()});}
  ReferenceWorkflow.Atomic(Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reports/bake-isolation-scenes.json"),new JObject{["scenes"]=rows,["bake_running"]=UnityEditor.Lightmapping.isRunning});
 }
 [MenuItem("Tools/HDRP Agent/House/Recover isolated bake scenes")]
 static void Recover(){
  if(EditorApplication.isCompiling){EditorApplication.delayCall+=Recover;return;}
  if(UnityEditor.Lightmapping.isRunning)return;
  try{string path=JournalPath;if(!File.Exists(path))return;var saved=JObject.Parse(File.ReadAllText(path));bool restored=RestoreRows((JArray)saved["originals"]);ReferenceWorkflow.Atomic(Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reports/bake-isolation-recovery.json"),new JObject{["restored"]=restored,["utc"]=DateTime.UtcNow.ToString("o")});if(restored)File.Delete(path);}
  catch(Exception e){UnityEngine.Debug.LogError("Bake scene restoration remains pending: "+e.Message);}
 }
}
}
