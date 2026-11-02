using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
// Explicit, local experiment. A single copied scene persists across observation/move/undo.
[InitializeOnLoad] public static class DirectRoomExperiment {
 static Scene scene,userScene; static string directory,source,sourceHash,candidate; static JObject bootstrap,request;
 static readonly Dictionary<string,GameObject> objects=new Dictionary<string,GameObject>();
 static readonly Stack<JArray> history=new Stack<JArray>(); static Camera camera; static RenderTexture texture;
 static string requestPath; static int warm,layer; static bool enabled; static JArray previews,reference;
 public static bool Running=>enabled;
 static DirectRoomExperiment(){EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=()=>{if(enabled)Close();};}
 static JArray V(Vector3 v)=>new JArray(v.x,v.y,v.z);
 static Vector3 Vec(JToken t){if(!(t is JArray a)||a.Count!=3)throw new InvalidDataException("Three coordinates required");var v=new Vector3((float)a[0],(float)a[1],(float)a[2]);if(float.IsNaN(v.sqrMagnitude)||float.IsInfinity(v.sqrMagnitude)||v.magnitude>200)throw new InvalidDataException("Invalid coordinates");return v;}
 static Bounds BoundsOf(GameObject go){var rs=go.GetComponentsInChildren<Renderer>().Where(r=>r.enabled).ToArray();if(rs.Length==0)throw new InvalidDataException("No visible bounds");var b=rs[0].bounds;foreach(var r in rs.Skip(1))b.Encapsulate(r.bounds);return b;}
 static void Write(string path,JToken data)=>ReferenceWorkflow.Atomic(path,data);
 static JArray Poses()=>new JArray(objects.Select(p=>new JObject{["id"]=p.Key,["position"]=V(p.Value.transform.position),["yaw"] =p.Value.transform.eulerAngles.y,["scale"]=V(p.Value.transform.localScale)}));
 static string Version()=>BridgeJson.Hash(System.Text.Encoding.UTF8.GetBytes(string.Join(";",scene.GetRootGameObjects().Where(g=>g.hideFlags==HideFlags.None).SelectMany(g=>g.GetComponentsInChildren<Transform>(true)).Select(t=>t.GetInstanceID()+":"+t.localPosition.ToString("R")+":"+t.localRotation.ToString("R")+":"+t.localScale.ToString("R")+":"+t.gameObject.activeSelf))));
 static void Restore(JArray poses){foreach(JObject p in poses){var t=objects[(string)p["id"]].transform;t.SetPositionAndRotation(Vec(p["position"]),Quaternion.Euler(0,(float)p["yaw"],0));t.localScale=Vec(p["scale"]);}}
 static JObject State(){var rows=new JArray();foreach(var p in objects){var b=BoundsOf(p.Value);rows.Add(new JObject{["id"]=p.Key,["prefab_path"]=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(p.Value),["position"]=V(p.Value.transform.position),["yaw"]=p.Value.transform.eulerAngles.y,["bounds_center"]=V(b.center),["bounds_size"]=V(b.size)});}return new JObject{["version"]=Version(),["scene_path"]=candidate,["objects"]=rows,["previews"]=previews,["reference"]=reference,["reference_source"]="Assets/AtmosphericHouse/Scenes/House_clean_day.unity",["reference_sha256"]=BridgeJson.Hash(File.ReadAllBytes("Assets/AtmosphericHouse/Scenes/House_clean_day.unity")),["source_unchanged"]=sourceHash==BridgeJson.Hash(File.ReadAllBytes(source)),["active_scene_unchanged"]=SceneManager.GetActiveScene()==userScene};}
 [MenuItem("Tools/HDRP Agent/House/Start direct interaction experiment")]
 public static void Begin(){
  if(enabled||CommandExecutor.Busy||ReferenceWorkflow.Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)throw new InvalidOperationException("Idle editor required");
  string workspace=BridgeClient.ResolveWorkspace();bootstrap=JObject.Parse(File.ReadAllText(Path.Combine(workspace,".hdrp-agent/direct-room/bootstrap.json")));
  string id=(string)bootstrap["id"];if(id.Length!=32||id.Any(c=>!Uri.IsHexDigit(c)))throw new InvalidDataException("Invalid experiment ID");
  directory=Path.Combine(workspace,".hdrp-agent/direct-room",id);Directory.CreateDirectory(directory);
  source=(string)bootstrap["source_scene"];if(!source.StartsWith("Assets/AgentWorkspace/HouseRuns/",StringComparison.Ordinal)||source.Contains("..")||!source.EndsWith(".unity"))throw new InvalidDataException("Generated source scene required");
  sourceHash=BridgeJson.Hash(File.ReadAllBytes(source));if(sourceHash!=(string)bootstrap["source_sha256"])throw new InvalidDataException("Source changed");
  userScene=SceneManager.GetActiveScene();objects.Clear();history.Clear();previews=new JArray();reference=new JArray();
  try{
   string folder="Assets/AgentWorkspace/DirectExperiments/"+id;Directory.CreateDirectory(folder);AssetDatabase.Refresh();candidate=folder+"/Room.unity";
   if(!AssetDatabase.CopyAsset(source,candidate))throw new IOException("Cannot copy generated source");
   scene=EditorSceneManager.OpenScene(candidate,OpenSceneMode.Additive);
   for(layer=29;layer>=8;layer--)if(!Resources.FindObjectsOfTypeAll<GameObject>().Any(g=>g.scene.IsValid()&&g.scene!=scene&&g.layer==layer))break;
   if(layer<8)throw new InvalidOperationException("No isolated rendering layer available");
   var roots=scene.GetRootGameObjects();foreach(var t in roots.SelectMany(g=>g.GetComponentsInChildren<Transform>(true))){t.gameObject.layer=layer;if(((JArray)bootstrap["instances"]).Any(i=>(string)i["id"]==t.name)&&PrefabUtility.IsOutermostPrefabInstanceRoot(t.gameObject))objects.Add(t.name,t.gameObject);}
   foreach(var light in roots.SelectMany(g=>g.GetComponentsInChildren<Light>(true)))light.cullingMask=1<<layer;
   foreach(var volume in roots.SelectMany(g=>g.GetComponentsInChildren<Volume>(true)))volume.gameObject.layer=layer;
   foreach(string key in ((JArray)bootstrap["selection_ids"]).Values<string>()){
    var go=objects[key];string path=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(go),file="prefab-"+previews.Count+".png";
    ReferenceAssets.SavePreview(new JObject{["path"]=path,["asset_guid"]=AssetDatabase.AssetPathToGUID(path),["dependency_hash"]=AssetDatabase.GetAssetDependencyHash(path).ToString()},Path.Combine(directory,file));
    previews.Add(new JObject{["instance_id"]=key,["file"]=file,["prefab_path"]=path,["sha256"]=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,file)))});
   }
   // Read reference prefab relationships; never copy reference transforms into the candidate.
   var refScene=EditorSceneManager.OpenPreviewScene("Assets/AtmosphericHouse/Scenes/House_clean_day.unity");
   try{var refs=refScene.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Transform>(true)).Where(t=>PrefabUtility.IsOutermostPrefabInstanceRoot(t.gameObject)).ToArray();
    foreach(var t in refs){string path=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject);if(!path.Contains("Chair")&&!path.Contains("Workdesk")&&!path.Contains("Table_"))continue;var b=BoundsOf(t.gameObject);reference.Add(new JObject{["prefab_path"]=path,["position"]=V(t.position),["yaw"]=t.eulerAngles.y,["bounds_center"]=V(b.center),["bounds_size"]=V(b.size)});}
   }finally{EditorSceneManager.ClosePreviewScene(refScene);}
   var cameraObject=new GameObject("Direct interaction camera"){hideFlags=HideFlags.HideAndDontSave};SceneManager.MoveGameObjectToScene(cameraObject,scene);camera=cameraObject.AddComponent<Camera>();camera.enabled=false;camera.nearClipPlane=.05f;camera.farClipPlane=100;camera.fieldOfView=65;camera.aspect=1280f/720;camera.cullingMask=1<<layer;camera.overrideSceneCullingMask=EditorSceneManager.GetSceneCullingMask(scene);
   var hd=cameraObject.AddComponent<HDAdditionalCameraData>();hd.volumeLayerMask=1<<layer;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;hd.allowDynamicResolution=false;
   texture=new RenderTexture(1280,720,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB);texture.Create();
   enabled=true;if(!EditorSceneManager.SaveScene(scene))throw new IOException("Candidate scene could not be saved");Write(Path.Combine(directory,"ready.json"),State());
  }catch(Exception e){Write(Path.Combine(directory,"error.json"),new JObject{["error"]=e.Message});Close();throw;}
 }
 static void Apply(JObject value){
  string id=(string)value["target_id"];if(!((JArray)bootstrap["selection_ids"]).Values<string>().Contains(id))throw new InvalidDataException("Target outside selected pair");
  var go=objects[id];var next=Vec(value["position"]);float yaw=(float)value["yaw"];if(float.IsNaN(yaw)||float.IsInfinity(yaw)||Mathf.Abs(yaw)>360)throw new InvalidDataException("Invalid yaw");
  if(Mathf.Abs(next.y-go.transform.position.y)>.001f)throw new InvalidDataException("Keep measured floor contact");
  var before=Poses();var old=go.transform.position;float delta=yaw-go.transform.eulerAngles.y;var q=Quaternion.Euler(0,delta,0);
  var manifest=(JArray)bootstrap["instances"];var selected=new HashSet<string>{id};bool added;
  do{added=false;foreach(JObject item in manifest)if(selected.Contains((string)item["support_id"]??"")&&selected.Add((string)item["id"]))added=true;}while(added);
  foreach(string key in selected){var t=objects[key].transform;Undo.RecordObject(t,"Agent direct pose");t.SetPositionAndRotation(next+q*(t.position-old),q*t.rotation);PrefabUtility.RecordPrefabInstancePropertyModifications(t);}
  try{
   var roomId=(string)manifest.OfType<JObject>().First(i=>(string)i["id"]==id)["room_id"];var room=((JArray)bootstrap["building"]["rooms"]).OfType<JObject>().First(r=>(string)r["id"]==roomId);var poly=(JArray)room["polygon"];
   foreach(string key in selected){var b=BoundsOf(objects[key]);if(b.min.x<poly.Min(p=>(float)p[0])+.08f||b.max.x>poly.Max(p=>(float)p[0])-.08f||b.min.z<poly.Min(p=>(float)p[1])+.08f||b.max.z>poly.Max(p=>(float)p[1])-.08f)throw new InvalidDataException("Pose leaves room boundaries");
    foreach(JObject portal in (JArray)bootstrap["building"]["portals"]){
     if((string)portal["kind"]!="door"||!((JArray)portal["spaces"]).Values<string>().Contains(roomId))continue;
     var wall=((JArray)bootstrap["building"]["boundaries"]).OfType<JObject>().First(w=>(string)w["id"]==(string)portal["boundary_id"]);
     var start=new Vector3((float)wall["start"][0],0,(float)wall["start"][1]);var end=new Vector3((float)wall["end"][0],0,(float)wall["end"][1]);var axis=(end-start).normalized;
     var middle=start+axis*((float)portal["interval_m"][0]+(float)portal["interval_m"][1])*.5f;
     var inward=Mathf.Abs(axis.x)>.5f?new Vector3(0,0,Mathf.Sign(poly.Average(p=>(float)p[1])-middle.z)):new Vector3(Mathf.Sign(poly.Average(p=>(float)p[0])-middle.x),0,0);
     var clearance=new Bounds(middle+inward*.5f+Vector3.up,Mathf.Abs(axis.x)>.5f?new Vector3(1.5f,2,1.2f):new Vector3(1.2f,2,1.5f));
     if(b.Intersects(clearance))throw new InvalidDataException("Pose obstructs door clearance");
    }
    b.Expand(-.02f);foreach(var other in objects.Where(p=>!selected.Contains(p.Key))){var entry=manifest.OfType<JObject>().FirstOrDefault(i=>(string)i["id"]==other.Key);if(entry==null||(string)entry["role"]=="floor_covering")continue;if(b.Intersects(BoundsOf(other.Value)))throw new InvalidDataException("Pose intersects "+other.Key);}}
  }catch{Restore(before);throw;}
  history.Push(before);EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene))throw new IOException("Candidate scene could not be saved");
 }
 static void Tick(){if(!enabled)return;
  try{
   if(CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode)throw new InvalidOperationException("Another operation owns editor");
   if(request!=null){if((string)request["expected_version"]!=Version())throw new InvalidDataException("Concurrent edit during observation");RenderPipeline.SubmitRenderRequest(camera,new RenderPipeline.StandardRequest{destination=texture});if(++warm<24)return;var previous=RenderTexture.active;var image=new Texture2D(1280,720,TextureFormat.RGB24,false);
    try{RenderTexture.active=texture;image.ReadPixels(new Rect(0,0,1280,720),0,0);image.Apply();string file=Path.GetFileNameWithoutExtension(requestPath)+".png";File.WriteAllBytes(Path.Combine(directory,file),image.EncodeToPNG());var result=State();result["file"]=file;result["image_sha256"]=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,file)));result["camera_position"]=V(camera.transform.position);result["camera_rotation"]=V(camera.transform.eulerAngles);Complete(result);}finally{RenderTexture.active=previous;UnityEngine.Object.DestroyImmediate(image);}return;}
   string path=Directory.GetFiles(directory,"command-*.json").OrderBy(p=>p,StringComparer.Ordinal).FirstOrDefault(p=>!p.EndsWith(".result.json",StringComparison.Ordinal)&&!File.Exists(p+".result.json"));if(path==null)return;
   requestPath=path;request=JObject.Parse(File.ReadAllText(path));string action=(string)request["action"];
   if((string)request["expected_version"]!=Version())throw new InvalidDataException("Scene changed; refresh inventory before applying an action");
   if(action=="observe"){var position=Vec(request["position"]);var look=Vec(request["look_at"]);if((position-look).sqrMagnitude<.01f)throw new InvalidDataException("Camera needs a distinct look target");camera.transform.SetPositionAndRotation(position,Quaternion.LookRotation(look-position));camera.fieldOfView=Mathf.Clamp((float)request["fov"],20,90);HDCamera.GetOrCreate(camera).Reset();warm=0;return;}
   if(action=="move")Apply(request);
   else if(action=="undo"){if(history.Count==0)throw new InvalidOperationException("No move to undo");Restore(history.Pop());EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene))throw new IOException("Candidate scene could not be saved");}
   else if(action!="finish"&&action!="inventory")throw new InvalidDataException("Unknown interaction action");
   Complete(State());if(action=="finish")Close();
  }catch(Exception e){if(requestPath!=null)Complete(new JObject{["error"]=e.Message,["version"]=Version()});else{Write(Path.Combine(directory,"error.json"),new JObject{["error"]=e.Message});Close();}}
 }
 static void Complete(JObject value){Write(requestPath+".result.json",value);request=null;requestPath=null;}
 [MenuItem("Tools/HDRP Agent/House/Close direct interaction experiment")]
 public static void Close(){enabled=false;request=null;requestPath=null;if(camera)UnityEngine.Object.DestroyImmediate(camera.gameObject);camera=null;if(texture){texture.Release();UnityEngine.Object.DestroyImmediate(texture);}texture=null;if(scene.IsValid()&&scene.isLoaded)EditorSceneManager.CloseScene(scene,true);objects.Clear();}
}
}
