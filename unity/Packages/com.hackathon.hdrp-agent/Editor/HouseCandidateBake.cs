using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
// Bake only the explicitly supplied generated scene. Never use BakeAsync()
// without a scene argument while an unrelated user scene is loaded.
internal sealed class HouseCandidateBake : IDisposable {
 readonly Scene scene;readonly string directory;readonly double deadline;
 bool completed,cancelled,failed,requestedCancel;string error;
 readonly JArray events=new JArray();
 readonly int[] initialWindows=Resources.FindObjectsOfTypeAll<EditorWindow>().Select(w=>w.GetInstanceID()).ToArray();
 internal bool Finished{get;private set;}
 internal bool Succeeded{get;private set;}
 internal JObject Receipt{get;private set;}
 internal static void Prepare(GameObject root,string scenePath){
  string folder=Path.GetDirectoryName(scenePath).Replace('\\','/');
  var source=AssetDatabase.LoadAssetAtPath<LightingSettings>("Assets/AtmosphericHouse/Scenes/House_clean_daySettings.lighting");
  if(!source)throw new InvalidDataException("Clean-day lighting settings missing");
  var settings=UnityEngine.Object.Instantiate(source);settings.name="Candidate lighting settings";
  settings.lightmapper=LightingSettings.Lightmapper.ProgressiveGPU;
  AssetDatabase.CreateAsset(settings,AssetDatabase.GenerateUniqueAssetPath(folder+"/BakeSettings.lighting"));
  Lightmapping.SetLightingSettingsForScene(root.scene,settings);
  ReferenceWorkflow.Atomic(folder+"/MaterialGI.json",HouseGiMaterials.Apply(root,folder));
  foreach(var renderer in root.GetComponentsInChildren<MeshRenderer>()){
   GameObjectUtility.SetStaticEditorFlags(renderer.gameObject,GameObjectUtility.GetStaticEditorFlags(renderer.gameObject)|StaticEditorFlags.ContributeGI);
   renderer.receiveGI=ReceiveGI.Lightmaps;PrefabUtility.RecordPrefabInstancePropertyModifications(renderer);
  }
  foreach(var light in root.GetComponentsInChildren<Light>(true)){
   if(light.enabled&&light.type==LightType.Rectangle)light.lightmapBakeType=LightmapBakeType.Baked;
   PrefabUtility.RecordPrefabInstancePropertyModifications(light);
  }
  var skyObject=new GameObject("Candidate static lighting sky");skyObject.transform.SetParent(root.transform,false);
  var sky=skyObject.AddComponent<UnityEngine.Rendering.HighDefinition.StaticLightingSky>();sky.profile=root.GetComponentInChildren<Volume>().sharedProfile;sky.staticLightingSkyUniqueID=(int)UnityEngine.Rendering.HighDefinition.SkyType.PhysicallyBased;
  var probes=new GameObject("Candidate adaptive probe volume");probes.transform.SetParent(root.transform,false);
  probes.AddComponent<ProbeVolume>().mode=ProbeVolume.Mode.Scene;
  var set=ScriptableObject.CreateInstance<ProbeVolumeBakingSet>();
  var defaults=typeof(ProbeVolumeBakingSet).GetMethod("SetDefaults",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic);
  if(defaults==null)throw new InvalidOperationException("Probe baking defaults API unavailable");defaults.Invoke(set,null);
  var serialized=new SerializedObject(set);serialized.FindProperty("singleSceneMode").boolValue=false;serialized.ApplyModifiedPropertiesWithoutUndo();
  AssetDatabase.CreateAsset(set,AssetDatabase.GenerateUniqueAssetPath(folder+"/ProbeBakingSet.asset"));
  if(!set.TryAddScene(AssetDatabase.AssetPathToGUID(scenePath)))throw new InvalidOperationException("Candidate scene already belongs to another probe baking set");
  EditorUtility.SetDirty(set);AssetDatabase.SaveAssetIfDirty(set);
 }
 internal HouseCandidateBake(Scene target,string reportDirectory){
  if(Lightmapping.isRunning)throw new InvalidOperationException("Another bake is already running");
  if(!target.path.StartsWith("Assets/AgentWorkspace/HouseRuns/",StringComparison.Ordinal))throw new InvalidOperationException("Candidate-owned scene required");
  scene=target;directory=reportDirectory;deadline=EditorApplication.timeSinceStartup+600;
  Receipt=new JObject{["scene_path"]=scene.path,["status"]="requested",["method"]="scene_scoped_gpu_bake",["events"]=events};
  string materials=Path.Combine(Path.GetDirectoryName(scene.path),"MaterialGI.json");if(File.Exists(materials))Receipt["material_gi"]=JArray.Parse(File.ReadAllText(materials));
  Lightmapping.bakeStarted+=Started;Lightmapping.bakeCompleted+=Completed;Lightmapping.bakeCancelled+=Cancelled;Application.logMessageReceived+=Log;
  Record("requested");
  try{SceneManager.SetActiveScene(scene);if(!UnityEditor.Experimental.Lightmapping.BakeAsync(scene)){failed=true;error="Scene-scoped GPU bake was refused";}}
  catch(Exception e){failed=true;error=e.Message;}
 }
 void Record(string phase){events.Add(new JObject{["phase"]=phase,["utc"]=DateTime.UtcNow.ToString("o")});ReferenceWorkflow.Atomic(Path.Combine(directory,"bake.json"),Receipt);}
 void Started(){Receipt["status"]="running";Record("started");}
 void Completed(){completed=true;Record("completed_event");}
 void Cancelled(){cancelled=true;Record("cancelled_event");}
 void Log(string message,string trace,LogType type){
  if(type==LogType.Error||type==LogType.Exception||message.IndexOf("falling back",StringComparison.OrdinalIgnoreCase)>=0){failed=true;error=message;Record("engine_error_or_fallback");}
 }
 internal void Cancel(){if(requestedCancel||Finished)return;requestedCancel=true;Record("cancel_requested");if(Lightmapping.isRunning)Lightmapping.Cancel();}
 internal void Tick(){
  if(Finished)return;
  if(EditorApplication.timeSinceStartup>=deadline&&!requestedCancel)Cancel();
  if(Lightmapping.isRunning)return;
  if(!completed&&!cancelled&&!failed&&!requestedCancel)return;
  var data=Lightmapping.GetLightingDataAssetForScene(scene);string path=data?AssetDatabase.GetAssetPath(data):null;
  string folder=Path.GetDirectoryName(scene.path).Replace('\\','/')+"/";
  bool owned=path!=null&&path.StartsWith(folder,StringComparison.Ordinal)&&File.Exists(path);
  var maps=new JArray();
  foreach(var texture in LightmapSettings.lightmaps.SelectMany(l=>new[]{l.lightmapColor,l.lightmapDir,l.shadowMask}).Where(t=>t).Distinct()){
   string file=AssetDatabase.GetAssetPath(texture);if(!file.StartsWith(folder,StringComparison.Ordinal))continue;
   maps.Add(new JObject{["path"]=file,["sha256"]=BridgeJson.Hash(File.ReadAllBytes(file))});
  }
  Succeeded=completed&&!cancelled&&!failed&&!requestedCancel&&owned&&maps.Count>0;
  Receipt["status"]=Succeeded?"completed":"failed";Receipt["lighting_data_path"]=path;Receipt["candidate_owned"]=owned;Receipt["lightmaps"]=maps;Receipt["error"]=error;
  Receipt["bake_qualified"]=Succeeded;Finished=true;Record("settled");Dispose();
 }
 internal void CloseCreatedLightingWindows(){foreach(var window in Resources.FindObjectsOfTypeAll<EditorWindow>().Where(w=>w.GetType().Name=="LightingWindow"&&!initialWindows.Contains(w.GetInstanceID())))window.Close();}
 public void Dispose(){Lightmapping.bakeStarted-=Started;Lightmapping.bakeCompleted-=Completed;Lightmapping.bakeCancelled-=Cancelled;Application.logMessageReceived-=Log;}
}
}
