using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEditor;
using UnityEditor.SceneManagement;

namespace HdrpAgent.Editor {
[InitializeOnLoad] public sealed class HouseBuildJob : ICommandJob {
 static HouseBuildJob(){CommandExecutor.Register("build_house",c=>new HouseBuildJob(c));}
 readonly BridgeCommand command;readonly string before;readonly Scene userScene;readonly bool userDirty;readonly string userSignature;
 Scene scene;GameObject root;Camera camera;RenderTexture target;VolumeProfile profile;
 JObject manifest,proof;string directory,scenePath;bool started,waiting,cancelled,built;int viewIndex,warm;
 readonly List<Tuple<string,Vector3,Quaternion>> views=new List<Tuple<string,Vector3,Quaternion>>();
 readonly List<MeshCollider> colliders=new List<MeshCollider>();readonly List<string> hashes=new List<string>();
 public CommandResult Result{get;private set;}
 public HouseBuildJob(BridgeCommand c){command=c;before=SceneInspector.Version();userScene=SceneManager.GetActiveScene();userDirty=userScene.isDirty;userSignature=UserSignature(userScene);}
 static string UserSignature(Scene s)=>BridgeJson.Hash(System.Text.Encoding.UTF8.GetBytes(string.Join(";",s.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Component>(true)).Where(c=>c!=null).Select(c=>c.GetInstanceID()+":"+EditorUtility.GetDirtyCount(c)))));
 public void Cancel(){cancelled=true;}
 static Vector3 V(JToken t)=>new Vector3((float)t[0],(float)t[1],(float)t[2]);
 static JArray A(Vector3 v)=>new JArray(v.x,v.y,v.z);
 static Bounds BoundsOf(GameObject go){var rs=go.GetComponentsInChildren<Renderer>().Where(r=>r.enabled&&r is MeshRenderer).ToArray();if(rs.Length==0)throw new InvalidDataException("Prefab has no active mesh");var b=rs[0].bounds;foreach(var r in rs.Skip(1))b.Encapsulate(r.bounds);return b;}
 void Publish(string message){if(directory==null)return;ReferenceWorkflow.Atomic(Path.Combine(directory,"progress.json"),new JObject{["run_id"]=command.payload["run_id"],["message"]=message,["captured"]=viewIndex,["total_views"]=views.Count,["captures"]=proof?["captures"]?.DeepClone()??new JArray(),["updated_at"]=DateTime.UtcNow.ToString("o")});}
 public void Tick(){
  if(Result!=null||waiting||BridgeClient.RequestInProgress)return;
  try{
   if(cancelled){Fail("CANCELLED","House operation cancelled","cancelled");return;}
   if(SceneManager.GetActiveScene()!=userScene||SceneInspector.Version()!=before||userScene.isDirty!=userDirty||UserSignature(userScene)!=userSignature){Fail("CONCURRENT_EDIT","User scene changed; generated result retained separately");return;}
   if(!started){started=true;waiting=true;BridgeClient.Request("GET","/v1/artifacts/"+(string)command.payload["manifest_hash"],null,null,(ok,text)=>{waiting=false;if(!ok){Fail("EVIDENCE_MISSING","House manifest unavailable");return;}try{var bytes=System.Text.Encoding.UTF8.GetBytes(text);if(BridgeJson.Hash(bytes)!=(string)command.payload["manifest_hash"])throw new InvalidDataException("Manifest hash differs");manifest=JObject.Parse(text);Build();}catch(Exception e){Fail("HOUSE_BUILD_FAILED",e.Message);}});return;}
   if(!built)return;
   if(viewIndex<views.Count){
    var view=views[viewIndex];camera.transform.SetPositionAndRotation(view.Item2,view.Item3);
    RenderPipeline.SubmitRenderRequest(camera,new RenderPipeline.StandardRequest{destination=target});if(++warm<16)return;
    var previous=RenderTexture.active;var image=new Texture2D(1280,720,TextureFormat.RGB24,false);byte[] bytes;float mean;
    try{RenderTexture.active=target;image.ReadPixels(new Rect(0,0,1280,720),0,0);image.Apply();mean=image.GetPixels32().Average(p=>(p.r+p.g+p.b)/765f);bytes=image.EncodeToPNG();}finally{RenderTexture.active=previous;UnityEngine.Object.DestroyImmediate(image);}
    string file="view-"+viewIndex+".png";File.WriteAllBytes(Path.Combine(directory,file),bytes);waiting=true;
    BridgeClient.PutArtifact(bytes,"image/png",(ok,hash)=>{waiting=false;if(!ok){Fail("ARTIFACT_UPLOAD_FAILED","House image not acknowledged","unknown");return;}hashes.Add(hash);((JArray)proof["captures"]).Add(new JObject{["room_id"]=view.Item1,["key"]=Path.GetFileNameWithoutExtension(file),["artifact_hash"]=hash,["file"]=file,["position_m"]=A(view.Item2),["rotation_deg"]=A(view.Item3.eulerAngles),["usable"]=mean>.008f&&mean<.98f,["mean_rgb"]=mean,["coverage_qualified"]=false});viewIndex++;warm=0;Publish("Vue intérieure "+viewIndex+" / "+views.Count);});return;
   }
   proof["source_scene_unchanged"]=SceneManager.GetActiveScene()==userScene&&SceneInspector.Version()==before&&userScene.isDirty==userDirty;
   Publish("Captures terminées ; enregistrement du reçu");Cleanup();waiting=true;
   BridgeClient.PutArtifact(System.Text.Encoding.UTF8.GetBytes(proof.ToString(Newtonsoft.Json.Formatting.None)),"application/json",(ok,hash)=>{waiting=false;if(!ok){Fail("ARTIFACT_UPLOAD_FAILED","House receipt not acknowledged","unknown");return;}hashes.Add(hash);Result=new CommandResult{command_id=command.id,bridge_epoch=command.bridge_epoch,payload_hash=command.payload_hash,status="succeeded",before_version=before,after_version=SceneInspector.Version(),artifact_hashes=hashes.ToArray(),details_artifact_hash=hash,bake_status="not_required"};});
  }catch(Exception e){Fail("HOUSE_BUILD_FAILED",e.Message);}
 }
 void Build(){
  BridgeJson.Closed(manifest,"schema_version","run_id","building","instances","access","interior_style","lighting","designs");
  if((string)manifest["schema_version"]!="house-manifest.v1"||(string)manifest["run_id"]!=(string)command.payload["run_id"])throw new InvalidDataException("House manifest identity differs");
  string run=(string)manifest["run_id"];if(run.Length!=32||run.Any(c=>!Uri.IsHexDigit(c)))throw new InvalidDataException("Invalid run ID");
  directory=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/house/runs",run);Directory.CreateDirectory(directory);
  scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);SceneManager.SetActiveScene(scene);
  root=new GameObject("House v1 "+run);SceneManager.MoveGameObjectToScene(root,scene);
  var building=(JObject)manifest["building"];var walls=new JArray();var surfaces=new JArray();
  foreach(JObject wall in building["boundaries"]){
   var a=V2(wall["start"]);var b=V2(wall["end"]);var room=((JArray)building["rooms"]).OfType<JObject>().First(r=>(string)r["id"]==(string)wall["room_ids"][0]);var polygon=(JArray)room["polygon"];float cx=polygon.Average(p=>(float)p[0]),cz=polygon.Average(p=>(float)p[1]);
   float yaw=Mathf.Abs(a.z-b.z)<.01f?(a.z>cz?0:180):(a.x<cx?270:90);string key=(string)wall["id"];new GameObject(key).transform.SetParent(root.transform,false);float length=Vector3.Distance(a,b);
   var openings=new JArray(((JArray)building["portals"]).OfType<JObject>().Where(p=>(string)p["boundary_id"]==key).Select(p=>new JObject{["key"]=p["id"],["kind"]=p["kind"],["start"]=(float)p["interval_m"][0]/length,["end"]=(float)p["interval_m"][1]/length}));
   walls.Add(new JObject{["object_key"]=key,["start_m"]=A(a),["end_m"]=A(b),["rotation_deg"]=new JArray(0,yaw,0),["segment_key"]=key,["partition"]=((JArray)wall["room_ids"]).Count==2,["openings"]=openings});
  }
  foreach(JObject room in building["rooms"]){var poly=(JArray)room["polygon"];float x0=poly.Min(p=>(float)p[0]),x1=poly.Max(p=>(float)p[0]),z0=poly.Min(p=>(float)p[1]),z1=poly.Max(p=>(float)p[1]);
   foreach(string kind in new[]{"floor","ceiling"}){string key=(string)room["id"]+"-"+kind;new GameObject(key).transform.SetParent(root.transform,false);surfaces.Add(new JObject{["object_key"]=key,["kind"]=kind,["min_m"]=new JArray(x0,z0),["size_m"]=new JArray(x1-x0,z1-z0)});}
   var centre=new Vector3((x0+x1)/2,1.6f,(z0+z1)/2);for(int angle=0;angle<360;angle+=90)views.Add(Tuple.Create((string)room["id"],centre,Quaternion.Euler(0,angle,0)));
   var lightObject=new GameObject("Ceiling light "+(string)room["id"]);lightObject.transform.SetParent(root.transform,false);lightObject.transform.position=new Vector3(centre.x,2.55f,centre.z);var light=lightObject.AddComponent<Light>();light.type=LightType.Point;lightObject.AddComponent<HDAdditionalLightData>();light.lightUnit=LightUnit.Lumen;light.intensity=1500;light.range=12;light.color=new Color(1,.82f,.63f);light.shadows=LightShadows.Soft;light.cullingMask=1<<30;
  }
  var architecture=ReferenceArchitecture.Build(root,new JObject{["walls"]=walls,["height_m"]=2.8f,["thickness_m"]=.2f,["lighting"]="warm_interior",["surfaces"]=surfaces},(string)manifest["interior_style"]);
  var instances=new JArray();var defects=new JArray();var objects=new Dictionary<string,GameObject>();
  foreach(JObject item in manifest["instances"]){
   string key=(string)item["id"],path=AssetDatabase.GUIDToAssetPath((string)item["prefab_guid"]);
   if(!path.StartsWith("Assets/AtmosphericHouse/Prefabs/",StringComparison.Ordinal)&&!path.StartsWith("Assets/HouseProps/",StringComparison.Ordinal))throw new InvalidDataException("Prefab outside approved roots");
   if(AssetDatabase.GetAssetDependencyHash(path).ToString()!=(string)item["dependency_hash"])throw new InvalidDataException("Prefab dependency changed: "+path);
   if((V(item["scale"])-Vector3.one).magnitude>.0001f)throw new InvalidDataException("Native prefab scale required");
   var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(path);var go=(GameObject)PrefabUtility.InstantiatePrefab(prefab,scene);go.name=key;go.transform.SetParent(root.transform,false);go.transform.position=V(item["position"]);go.transform.rotation=Quaternion.Euler(0,(float)item["yaw"],0);go.transform.localScale=Vector3.one;PrefabUtility.RecordPrefabInstancePropertyModifications(go.transform);objects.Add(key,go);
  }
  foreach(var t in root.GetComponentsInChildren<Transform>(true))t.gameObject.layer=30;
  foreach(var mf in root.GetComponentsInChildren<MeshFilter>()){var renderer=mf.GetComponent<MeshRenderer>();if(renderer==null||!renderer.enabled||mf.sharedMesh==null)continue;var collider=mf.gameObject.AddComponent<MeshCollider>();collider.sharedMesh=mf.sharedMesh;collider.hideFlags=HideFlags.HideAndDontSave;colliders.Add(collider);}
  Physics.SyncTransforms();
  foreach(JObject item in manifest["instances"]){
   string key=(string)item["id"];var go=objects[key];var b=BoundsOf(go);string support=(string)item["support_id"];
   bool contact=Physics.RaycastAll(new Vector3(b.center.x,b.min.y+.03f,b.center.z),Vector3.down,.065f,1<<30,QueryTriggerInteraction.Ignore).Any(h=>h.collider.gameObject.scene==scene&&h.collider.transform.root==root.transform&&!h.collider.transform.IsChildOf(go.transform)&&(support==null?h.collider.GetComponentsInParent<Transform>().Any(t=>t.name.EndsWith("-floor")):h.collider.transform.IsChildOf(objects[support].transform)));
   bool connected=PrefabUtility.GetPrefabInstanceStatus(go)==PrefabInstanceStatus.Connected,scale=(go.transform.lossyScale-Vector3.one).magnitude<.001f;
   instances.Add(new JObject{["id"]=key,["room_id"]=item["room_id"],["connected"]=connected,["native_scale"]=scale,["support_passed"]=contact,["bounds_center"]=A(b.center),["bounds_size"]=A(b.size),["position"]=A(go.transform.position),["yaw"]=go.transform.eulerAngles.y,["prefab_guid"]=item["prefab_guid"]});
   if(!contact)defects.Add(new JObject{["instance_id"]=key,["kind"]="support",["message"]="No measured supporting surface within 3 cm of prefab base"});
  }
  // Detail observations use actual native bounds and reject blocked camera paths.
  foreach(var group in ((JArray)manifest["instances"]).OfType<JObject>().GroupBy(i=>(string)i["room_id"]+"/"+(string)i["group_id"])){
   var first=group.First();var bounds=BoundsOf(objects[(string)first["id"]]);foreach(var item in group.Skip(1))bounds.Encapsulate(BoundsOf(objects[(string)item["id"]]));
   var room=((JArray)building["rooms"]).OfType<JObject>().First(r=>(string)r["id"]==(string)first["room_id"]);var polygon=(JArray)room["polygon"];
   float x0=polygon.Min(p=>(float)p[0])+.3f,x1=polygon.Max(p=>(float)p[0])-.3f,z0=polygon.Min(p=>(float)p[1])+.3f,z1=polygon.Max(p=>(float)p[1])-.3f;
   foreach(float angle in new[]{0f,90f,180f,270f}){
    var look=bounds.center;var offset=Quaternion.Euler(0,angle,0)*Vector3.forward*Mathf.Max(1.1f,bounds.extents.magnitude*1.6f);var point=look+offset;point.y=Mathf.Clamp(bounds.max.y+.45f,1.2f,2.2f);
    if(point.x<x0||point.x>x1||point.z<z0||point.z>z1||Physics.OverlapSphere(point,.15f,1<<30).Any(c=>c.transform.IsChildOf(root.transform)))continue;
    var ray=look-point;var hits=Physics.RaycastAll(point,ray.normalized,ray.magnitude,1<<30).Where(h=>h.collider.transform.IsChildOf(root.transform)).OrderBy(h=>h.distance).ToArray();
    if(hits.Length>0&&!group.Any(i=>hits[0].collider.transform.IsChildOf(objects[(string)i["id"]].transform)))continue;
    views.Add(Tuple.Create((string)first["room_id"],point,Quaternion.LookRotation(ray)));
   }
  }
  var traversal=HouseTraversal.Check(root,manifest);foreach(var defect in (JArray)traversal["defects"])defects.Add(defect.DeepClone());
  foreach(var collider in colliders)if(collider)UnityEngine.Object.DestroyImmediate(collider);colliders.Clear();
  var volumeObject=new GameObject("House lighting profile");volumeObject.transform.SetParent(root.transform,false);volumeObject.layer=30;var volume=volumeObject.AddComponent<Volume>();volume.isGlobal=true;volume.priority=10000;profile=ScriptableObject.CreateInstance<VolumeProfile>();var exposure=profile.Add<Exposure>(true);exposure.mode.Override(ExposureMode.Fixed);exposure.fixedExposure.Override(6);var tone=profile.Add<Tonemapping>(true);tone.mode.Override(TonemappingMode.ACES);volume.sharedProfile=profile;
  string folder="Assets/AgentWorkspace/HouseRuns/"+run;Directory.CreateDirectory(folder);AssetDatabase.Refresh();string profilePath=folder+"/Lighting.asset";AssetDatabase.CreateAsset(profile,AssetDatabase.GenerateUniqueAssetPath(profilePath));scenePath=AssetDatabase.GenerateUniqueAssetPath(folder+"/House.unity");
  if(!EditorSceneManager.SaveScene(scene,scenePath))throw new IOException("Generated scene could not be saved");
  proof=new JObject{["schema_version"]="house-native.v1",["run_id"]=run,["manifest_hash"]=command.payload["manifest_hash"],["scene_path"]=scenePath,["scene_version"]=BridgeJson.Hash(File.ReadAllBytes(scenePath)),["instances"]=instances,["architecture"]=architecture,["defects"]=defects,["captures"]=new JArray(),["traversal"]=traversal,["traversal_qualified"]=(bool)traversal["passed"],["lighting_qualified"]=false};
  var cameraObject=new GameObject("House inspection camera"){hideFlags=HideFlags.HideAndDontSave};SceneManager.MoveGameObjectToScene(cameraObject,scene);camera=cameraObject.AddComponent<Camera>();camera.enabled=false;camera.nearClipPlane=.05f;camera.farClipPlane=100;camera.fieldOfView=75;camera.aspect=1280f/720;camera.cullingMask=1<<30;camera.overrideSceneCullingMask=EditorSceneManager.GetSceneCullingMask(scene);var hd=cameraObject.AddComponent<HDAdditionalCameraData>();hd.volumeLayerMask=1<<30;hd.allowDynamicResolution=false;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;
  target=new RenderTexture(1280,720,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB){hideFlags=HideFlags.HideAndDontSave};target.Create();SceneManager.SetActiveScene(userScene);built=true;Publish("Architecture assemblée ; inspection intérieure");
 }
 static Vector3 V2(JToken t)=>new Vector3((float)t[0],0,(float)t[1]);
 void Cleanup(){foreach(var c in colliders)if(c)UnityEngine.Object.DestroyImmediate(c);colliders.Clear();if(camera)UnityEngine.Object.DestroyImmediate(camera.gameObject);camera=null;if(target){target.Release();UnityEngine.Object.DestroyImmediate(target);}target=null;if(scene.IsValid())EditorSceneManager.CloseScene(scene,true);if(userScene.IsValid())SceneManager.SetActiveScene(userScene);}
 void Fail(string code,string message,string status="failed"){Cleanup();Publish(message);Result=new CommandResult{command_id=command.id,bridge_epoch=command.bridge_epoch,payload_hash=command.payload_hash,status=status,before_version=before,after_version=SceneInspector.Version(),error=new BridgeError{code=code,message=message,command_id=command.id}};}
}
}
