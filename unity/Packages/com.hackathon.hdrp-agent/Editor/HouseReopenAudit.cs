using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
// Read-only, isolated verification of saved candidate lighting resources.
[InitializeOnLoad] internal static class HouseReopenAudit {
 static Scene scene,user;static Camera camera;static RenderTexture target;static JObject request,report,userState;static string directory,scenePath,sceneHash,userHash;static bool userDirty;static int index,warm;static Light sun;
 internal static bool Running{get;private set;}
 static HouseReopenAudit(){EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=()=>{if(Running)Finish("interrupted");};}
 static Vector3 V(JToken t)=>new Vector3((float)t[0],(float)t[1],(float)t[2]);
 [MenuItem("Tools/HDRP Agent/House/Audit reopened candidate lighting")]
 internal static void Begin(){
  if(Running||CommandExecutor.Busy||ReferenceWorkflow.Running||DirectRoomExperiment.Running||Lightmapping.isRunning||EditorApplication.isPlayingOrWillChangePlaymode)throw new InvalidOperationException("Idle edit mode required");
  directory=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reopen-audit");request=JObject.Parse(File.ReadAllText(Path.Combine(directory,"request.json")));
  string id=(string)request["id"];if(id==null||id.Length!=32||id.Any(c=>!Uri.IsHexDigit(c)))throw new InvalidDataException("Audit ID required");directory=Path.Combine(directory,id);if(Directory.Exists(directory))throw new InvalidOperationException("Audit ID already used");Directory.CreateDirectory(directory);
  scenePath=(string)request["scene_path"];
  if(!scenePath.StartsWith("Assets/AgentWorkspace/HouseRuns/",StringComparison.Ordinal)||scenePath.Contains("..")||!scenePath.EndsWith(".unity"))throw new InvalidDataException("Saved candidate scene required");
  sceneHash=BridgeJson.Hash(File.ReadAllBytes(scenePath));if(sceneHash!=(string)request["scene_sha256"])throw new InvalidDataException("Candidate hash changed");
  if(Enumerable.Range(0,SceneManager.sceneCount).Any(i=>SceneManager.GetSceneAt(i).path==scenePath))throw new InvalidOperationException("Candidate already open");
  user=SceneManager.GetActiveScene();userDirty=user.isDirty;userState=HouseBuildJob.UserState(user);userHash=File.Exists(user.path)?BridgeJson.Hash(File.ReadAllBytes(user.path)):null;
  report=new JObject{["scene_path"]=scenePath,["scene_sha256"]=sceneHash,["captures"]=new JArray(),["status"]="running"};Running=true;index=warm=0;
  try{
   scene=EditorSceneManager.OpenScene(scenePath,OpenSceneMode.Additive);SceneManager.SetActiveScene(scene);
   int layer;for(layer=31;layer>=8;layer--)if(!Resources.FindObjectsOfTypeAll<GameObject>().Any(g=>g.scene.IsValid()&&g.scene!=scene&&g.layer==layer))break;
   if(layer<8)throw new InvalidOperationException("No isolated layer");
   ulong mask=EditorSceneManager.CalculateAvailableSceneCullingMask();if(mask==0)throw new InvalidOperationException("No isolated scene mask");EditorSceneManager.SetSceneCullingMask(scene,mask);
   var roots=scene.GetRootGameObjects();foreach(var t in roots.SelectMany(g=>g.GetComponentsInChildren<Transform>(true)))t.gameObject.layer=layer;
   foreach(var light in roots.SelectMany(g=>g.GetComponentsInChildren<Light>(true)))light.cullingMask=1<<layer;
   sun=roots.SelectMany(g=>g.GetComponentsInChildren<Light>(true)).Single(l=>l.type==LightType.Directional);
   if((bool?)request["zero_sun_shadow_bias"]==true){
    var hdSun=sun.GetComponent<HDAdditionalLightData>();
    report["temporary_sun_bias_override"]=new JObject{["normal_before"]=hdSun.normalBias,["slope_before"]=hdSun.slopeBias,["normal_after"]=0,["slope_after"]=0};
    hdSun.normalBias=0;hdSun.slopeBias=0;
   }
   var go=new GameObject("Reopened lighting observation"){hideFlags=HideFlags.HideAndDontSave};SceneManager.MoveGameObjectToScene(go,scene);camera=go.AddComponent<Camera>();camera.enabled=false;camera.nearClipPlane=.05f;camera.farClipPlane=100;camera.fieldOfView=75;camera.aspect=1280f/720;camera.cullingMask=1<<layer;camera.overrideSceneCullingMask=mask;var hd=go.AddComponent<HDAdditionalCameraData>();hd.volumeLayerMask=1<<layer;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;hd.allowDynamicResolution=false;
   target=new RenderTexture(1280,720,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB){hideFlags=HideFlags.HideAndDontSave};target.Create();
   if((bool?)request["two_sided_architecture_shadows"]==true){
    var changed=new JArray();
    foreach(var renderer in roots.SelectMany(g=>g.GetComponentsInChildren<MeshRenderer>())){
     string prefab=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(renderer.gameObject);
     if(!prefab.StartsWith("Assets/AtmosphericHouse/Prefabs/Building/",StringComparison.Ordinal))continue;
     changed.Add(new JObject{["prefab"]=prefab,["before"]=renderer.shadowCastingMode.ToString(),["after"]="TwoSided"});
     renderer.shadowCastingMode=ShadowCastingMode.TwoSided;
    }
    report["temporary_shadow_override"]=changed;
   }
   HouseSeamGeometry.Export(scene,directory);
   report["lightmaps"]=new JArray(LightmapSettings.lightmaps.Select(m=>AssetDatabase.GetAssetPath(m.lightmapColor)));
   ReferenceWorkflow.Atomic(Path.Combine(directory,"report.json"),report);
  }catch(Exception e){report["error"]=e.Message;Finish("failed");}
 }
 static void Tick(){
  if(!Running)return;
  try{
   if(user.isDirty!=userDirty||!HouseBuildJob.SameUserContent(userState,HouseBuildJob.UserState(user)))throw new InvalidOperationException("User scene changed during audit");
   var views=(JArray)request["views"];int count=views.Count;if(index>=count*2){Finish("completed");return;}
   var view=views[index%count];sun.enabled=index<count;
   camera.transform.SetPositionAndRotation(V(view["position_m"]),Quaternion.Euler(V(view["rotation_deg"])));
   RenderPipeline.SubmitRenderRequest(camera,new RenderPipeline.StandardRequest{destination=target});if(++warm<32)return;warm=0;
   CaptureGiTextures();
   string file=(index<count?"saved-":"sun-off-")+(string)view["key"]+".png";
   var previous=RenderTexture.active;var image=new Texture2D(1280,720,TextureFormat.RGB24,false);
   try{RenderTexture.active=target;image.ReadPixels(new Rect(0,0,1280,720),0,0);image.Apply();File.WriteAllBytes(Path.Combine(directory,file),image.EncodeToPNG());}finally{RenderTexture.active=previous;UnityEngine.Object.DestroyImmediate(image);}
   ((JArray)report["captures"]).Add(new JObject{["file"]=file,["sun_enabled"]=sun.enabled,["ev100"]=HouseExposure.ReadEv(camera)});index++;
   ReferenceWorkflow.Atomic(Path.Combine(directory,"report.json"),report);
  }catch(Exception e){report["error"]=e.Message;Finish("failed");}
 }
 static void CaptureGiTextures(){
  try{
   var type=AppDomain.CurrentDomain.GetAssemblies().Select(a=>a.GetType("UnityEditor.LightmapVisualizationUtility")).FirstOrDefault(t=>t!=null);
   var method=type?.GetMethods(System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic).SingleOrDefault(m=>m.Name=="GetBakedGITexture"&&m.GetParameters().Length==4);
   if(method==null)throw new InvalidOperationException("GI visualization API unavailable");
   var parameters=method.GetParameters();var kind=parameters[2].ParameterType;
   var rows=new JArray();
   foreach(string name in Enum.GetNames(kind).Where(n=>n.IndexOf("Valid",StringComparison.OrdinalIgnoreCase)>=0||n.IndexOf("Overlap",StringComparison.OrdinalIgnoreCase)>=0||n.IndexOf("Chart",StringComparison.OrdinalIgnoreCase)>=0)){
    object value=method.Invoke(null,new object[]{0,Activator.CreateInstance(parameters[1].ParameterType),Enum.Parse(kind,name),false});
    var fields=value.GetType().GetFields(System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic);
    var row=new JObject{["kind"]=name,["fields"]=new JArray(fields.Select(f=>f.Name+":"+f.FieldType.Name))};
    foreach(var field in fields.Where(f=>f.FieldType.IsEnum))row[field.Name]=field.GetValue(value).ToString();
    var texture=fields.Where(f=>typeof(Texture).IsAssignableFrom(f.FieldType)).Select(f=>f.GetValue(value) as Texture).FirstOrDefault(t=>t);
    if(texture){
     string file="gi-"+name+".png";var previous=RenderTexture.active;var rt=RenderTexture.GetTemporary(texture.width,texture.height,0,RenderTextureFormat.ARGBFloat,RenderTextureReadWrite.Linear);var pixels=new Texture2D(texture.width,texture.height,TextureFormat.RGBA32,false,true);
     try{Graphics.Blit(texture,rt);RenderTexture.active=rt;pixels.ReadPixels(new Rect(0,0,texture.width,texture.height),0,0);pixels.Apply();File.WriteAllBytes(Path.Combine(directory,file),pixels.EncodeToPNG());row["file"]=file;row["width"]=texture.width;row["height"]=texture.height;}finally{RenderTexture.active=previous;RenderTexture.ReleaseTemporary(rt);UnityEngine.Object.DestroyImmediate(pixels);}
    }
    rows.Add(row);
   }
   report["gi_visualization"]=rows;
  }catch(Exception e){report["gi_visualization_error"]=e.Message;}
 }
 static void Finish(string status){
  if(camera)UnityEngine.Object.DestroyImmediate(camera.gameObject);camera=null;if(target){target.Release();UnityEngine.Object.DestroyImmediate(target);}target=null;
  if(scene.IsValid()&&scene.isLoaded)EditorSceneManager.CloseScene(scene,true);if(user.IsValid())SceneManager.SetActiveScene(user);
  report["status"]=status;report["candidate_file_unchanged"]=sceneHash==BridgeJson.Hash(File.ReadAllBytes(scenePath));report["user_scene_unchanged"]=user.isDirty==userDirty&&HouseBuildJob.SameUserContent(userState,HouseBuildJob.UserState(user))&&(userHash==null||userHash==BridgeJson.Hash(File.ReadAllBytes(user.path)));
  ReferenceWorkflow.Atomic(Path.Combine(directory,"report.json"),report);Running=false;
 }
}
}
