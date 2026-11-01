using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;
using UnityEditor;
using UnityEditor.SceneManagement;

namespace HdrpAgent.Editor {
// Reference learning is read-only and separate from generated scene ground truth.
[InitializeOnLoad] public static class HouseReferenceAudit {
 static Scene preview; static Camera camera; static RenderTexture target;
 static string source,sourceHash,directory; static int index,warm; static JObject report;
 static readonly List<Tuple<string,Vector3,Quaternion>> views=new List<Tuple<string,Vector3,Quaternion>>();
 static readonly HashSet<string> rooms=new HashSet<string>{"Kitchen","Office","Bedroom_master","Bathroom_upstairs","Bathroom_downstairs","Laundry_room","Bedroom_girl","Guest_room","TV_room","Hallway_upstairs","Hallway_downstairs","Living_room","Dining_room","Basement_props","Porch"};
 public static bool Running=>camera!=null;
 static HouseReferenceAudit(){EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=()=>Finish("interrupted","Assembly reload");}
 static JArray V(Vector3 v)=>new JArray(v.x,v.y,v.z);
 static string Hierarchy(Transform t){var names=new List<string>();for(;t!=null;t=t.parent)names.Add(t.name);names.Reverse();return string.Join("/",names);}
 static Bounds BoundsOf(GameObject go){var rs=go.GetComponentsInChildren<Renderer>(true).Where(r=>r is MeshRenderer||r is SkinnedMeshRenderer).ToArray();if(rs.Length==0)return new Bounds(go.transform.position,Vector3.zero);var b=rs[0].bounds;foreach(var r in rs.Skip(1))b.Encapsulate(r.bounds);return b;}
 static JObject Box(Bounds b)=>new JObject{["center"]=V(b.center),["size"]=V(b.size),["min"]=V(b.min),["max"]=V(b.max)};
 static void Write(string name,JToken value){var p=Path.Combine(directory,name);File.WriteAllText(p+".writing",value.ToString());if(File.Exists(p))File.Delete(p);File.Move(p+".writing",p);}
 [MenuItem("Tools/HDRP Agent/House/Inspect reference house")]
 public static void BeginDefault()=>Begin("Assets/AtmosphericHouse/Scenes/House_worn_night.unity",Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reports/house-worn-night/native"));
 public static void Begin(string scenePath,string output){
  if(Running||ReferenceWorkflow.Running||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)throw new InvalidOperationException("Native editor must be idle before reference inspection");
  if(!scenePath.StartsWith("Assets/",StringComparison.Ordinal)||!scenePath.EndsWith(".unity",StringComparison.Ordinal)||scenePath.Contains(".."))throw new InvalidDataException("Project scene required");
  source=scenePath;sourceHash=BridgeJson.Hash(File.ReadAllBytes(source));directory=output;Directory.CreateDirectory(directory);views.Clear();index=warm=0;
  report=new JObject{["schema_version"]="house-atlas.v1",["source_scene"]=source,["source_sha256"]=sourceHash,["active_scene_before"]=SceneManager.GetActiveScene().path,["active_scene_dirty_before"]=SceneManager.GetActiveScene().isDirty,["status"]="inspecting",["visual_qualified"]=false,["capture_protocol"]="isolated_preview_hdrp_original_scene_volumes_unqualified",["captures"]=new JArray()};
  try {
   preview=EditorSceneManager.OpenPreviewScene(source);var roots=preview.GetRootGameObjects();var ts=roots.SelectMany(r=>r.GetComponentsInChildren<Transform>(true)).ToArray();var instances=new JArray();var materials=new HashSet<string>();
   foreach(var t in ts.Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject))){var path=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject);var b=BoundsOf(t.gameObject);var room=t.GetComponentsInParent<Transform>(true).FirstOrDefault(p=>rooms.Contains(p.name));
    var mats=t.GetComponentsInChildren<Renderer>(true).SelectMany(r=>r.sharedMaterials).Where(m=>m!=null).Select(AssetDatabase.GetAssetPath).Distinct().ToArray();foreach(var m in mats)materials.Add(m);
    instances.Add(new JObject{["hierarchy"]=Hierarchy(t),["room"]=room==null?null:room.name,["prefab_path"]=path,["prefab_guid"]=AssetDatabase.AssetPathToGUID(path),["dependency_hash"]=AssetDatabase.GetAssetDependencyHash(path).ToString(),["connected"]=PrefabUtility.GetPrefabInstanceStatus(t.gameObject)==PrefabInstanceStatus.Connected,["active"]=t.gameObject.activeInHierarchy,["position_m"]=V(t.position),["rotation_deg"]=V(t.eulerAngles),["scale"]=V(t.lossyScale),["bounds"]=Box(b),["materials"]=new JArray(mats)});
   }
   var roomRows=new JArray();foreach(var t in ts.Where(t=>rooms.Contains(t.name))){var b=BoundsOf(t.gameObject);roomRows.Add(new JObject{["name"]=t.name,["hierarchy"]=Hierarchy(t),["bounds"]=Box(b),["position_m"]=V(t.position)});if(b.size.x<.1f||b.size.z<.1f)continue;
    var position=new Vector3(b.center.x,b.min.y+1.6f,b.center.z);for(int side=0;side<4;side++)views.Add(Tuple.Create(t.name+"-"+side,position,Quaternion.Euler(0,side*90,0)));
   }
   var structural=new JArray();foreach(var t in ts.Where(t=>t.name.StartsWith("Floors_")||t.name.StartsWith("Walls_")||t.name=="Roofs"||t.name=="Ceilings"))structural.Add(new JObject{["name"]=t.name,["bounds"]=Box(BoundsOf(t.gameObject))});
   var floorLevels=ts.Where(t=>t.name.StartsWith("Floors_")).Select(t=>BoundsOf(t.gameObject).max.y).OrderBy(y=>y).ToArray();
   foreach(var t in ts.Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)&&Path.GetFileName(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)).StartsWith("Stairs_"))){
    var b=BoundsOf(t.gameObject);bool alongX=b.size.x>b.size.z;var axis=alongX?Vector3.right:Vector3.forward;
    var horizontal=alongX?b.extents.x:b.extents.z;float lower=floorLevels.OrderBy(y=>Mathf.Abs(y-b.min.y)).First();float upper=floorLevels.Where(y=>y>lower+.2f).DefaultIfEmpty(lower+3).Min();
    foreach(var level in new[]{lower,upper})for(int end=0;end<2;end++){var position=b.center+axis*(end==0?-1:1)*Mathf.Max(.2f,horizontal-.7f);position.y=level+1.6f;var look=b.center;look.y=position.y-.2f;var key="stairs-level-"+BridgeJson.Hash(System.Text.Encoding.UTF8.GetBytes(Hierarchy(t))).Substring(0,8)+"-"+(level==lower?"lower":"upper")+"-"+end;views.Add(Tuple.Create(key,position,Quaternion.LookRotation(look-position)));}
   }
   var previousPath=Path.Combine(directory,"atlas.json");if(File.Exists(previousPath)){var previous=JObject.Parse(File.ReadAllText(previousPath));if((string)previous["source_sha256"]==sourceHash&&(string)previous["status"]=="complete"){
    report["captures"]=previous["captures"].DeepClone();var captured=new HashSet<string>(((JArray)report["captures"]).OfType<JObject>().Select(c=>(string)c["key"]));views.RemoveAll(v=>captured.Contains(v.Item1));
   }}
   report["instances"]=instances;report["rooms"]=roomRows;report["structure"]=structural;report["materials"]=new JArray(materials.OrderBy(x=>x));report["lights"]=JArray.FromObject(ts.SelectMany(t=>t.GetComponents<Light>()).Select(l=>new{hierarchy=Hierarchy(l.transform),active=l.isActiveAndEnabled,type=l.type.ToString(),position_m=new[]{l.transform.position.x,l.transform.position.y,l.transform.position.z},intensity=l.intensity,range=l.range,color=new[]{l.color.r,l.color.g,l.color.b},shadows=l.shadows.ToString(),bake=l.lightmapBakeType.ToString()}));Write("atlas.json",report);
   var go=EditorUtility.CreateGameObjectWithHideFlags("House reference audit camera",HideFlags.HideAndDontSave,typeof(Camera),typeof(HDAdditionalCameraData));SceneManager.MoveGameObjectToScene(go,preview);camera=go.GetComponent<Camera>();camera.enabled=false;camera.nearClipPlane=.05f;camera.farClipPlane=150;camera.fieldOfView=75;camera.aspect=1280f/720;camera.overrideSceneCullingMask=EditorSceneManager.GetSceneCullingMask(preview);
   var hd=go.GetComponent<HDAdditionalCameraData>();hd.allowDynamicResolution=false;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;hd.volumeLayerMask=~0;
   target=new RenderTexture(1280,720,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB){hideFlags=HideFlags.HideAndDontSave};target.Create();
  }catch(Exception e){Finish("failed",e.ToString());throw;}
 }
 static void Tick(){
  if(camera==null||EditorApplication.isCompiling||EditorApplication.isUpdating)return;
  try {
   if(SceneManager.GetActiveScene().path!=(string)report["active_scene_before"]){Finish("interrupted","Active user scene changed during reference inspection");return;}
   if(index>=views.Count){Finish("complete",null);return;}var view=views[index];camera.transform.SetPositionAndRotation(view.Item2,view.Item3);
   RenderPipeline.SubmitRenderRequest(camera,new RenderPipeline.StandardRequest{destination=target});if(++warm<32)return;
   var old=RenderTexture.active;var tex=new Texture2D(target.width,target.height,TextureFormat.RGB24,false);try{RenderTexture.active=target;tex.ReadPixels(new Rect(0,0,target.width,target.height),0,0);tex.Apply();string file=view.Item1+".png";File.WriteAllBytes(Path.Combine(directory,file),tex.EncodeToPNG());
    var pixels=tex.GetPixels32();double mean=pixels.Average(p=>(p.r+p.g+p.b)/765.0);((JArray)report["captures"]).Add(new JObject{["key"]=view.Item1,["file"]=file,["position_m"]=V(view.Item2),["rotation_deg"]=V(view.Item3.eulerAngles),["mean_rgb"]=mean,["coverage_qualified"]=false,["warning"]="Candidate camera derived from room prop bounds; review occlusion, floor height and original lighting before using as evidence"});
   }finally{RenderTexture.active=old;UnityEngine.Object.DestroyImmediate(tex);}index++;warm=0;Write("atlas.json",report);
  }catch(Exception e){Finish("failed",e.ToString());}
 }
 static void Finish(string status,string error){
  if(report==null)return;
  try{if(camera!=null)UnityEngine.Object.DestroyImmediate(camera.gameObject);if(target!=null){target.Release();UnityEngine.Object.DestroyImmediate(target);}if(preview.IsValid())EditorSceneManager.ClosePreviewScene(preview);
   report["status"]=status;report["error"]=error;report["source_unchanged"]=BridgeJson.Hash(File.ReadAllBytes(source))==sourceHash;report["active_scene_after"]=SceneManager.GetActiveScene().path;report["active_scene_dirty_after"]=SceneManager.GetActiveScene().isDirty;Write("atlas.json",report);
  }finally{camera=null;target=null;report=null;views.Clear();}
 }
}
}
