using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace HdrpAgent.Editor {
// Solid modules surround explicit apertures. Every surface remains a connected prefab.
public static class ReferenceArchitecture {
 const string Building="Assets/AtmosphericHouse/Prefabs/Building/";
 static GameObject Source(string name){
  var paths=AssetDatabase.FindAssets(name+" t:Prefab",new[]{"Assets/AtmosphericHouse/Prefabs"}).Select(AssetDatabase.GUIDToAssetPath).Where(p=>Path.GetFileNameWithoutExtension(p)==name).ToArray();
  if(paths.Length!=1)throw new InvalidDataException("Architecture prefab must resolve uniquely: "+name);
  return AssetDatabase.LoadAssetAtPath<GameObject>(paths[0]);
 }
 static Bounds LocalBounds(GameObject go){
  var filters=go.GetComponentsInChildren<MeshFilter>();bool found=false;Bounds bounds=default;
  foreach(var f in filters){if(f.sharedMesh==null)continue;var b=f.sharedMesh.bounds;
   for(int x=-1;x<=1;x+=2)for(int y=-1;y<=1;y+=2)for(int z=-1;z<=1;z+=2){var p=go.transform.InverseTransformPoint(f.transform.TransformPoint(b.center+Vector3.Scale(b.extents,new Vector3(x,y,z))));if(!found){bounds=new Bounds(p,Vector3.zero);found=true;}else bounds.Encapsulate(p);}
  }
  if(!found)throw new InvalidDataException("Architecture prefab has no geometry");return bounds;
 }
 static bool FrontHit(Vector3 a,Vector3 b,Vector3 c,Vector3 origin,Vector3 direction){
  var e1=b-a;var e2=c-a;var p=Vector3.Cross(direction,e2);float det=Vector3.Dot(e1,p);if(det<1e-8f)return false;
  var t=origin-a;float u=Vector3.Dot(t,p)/det;if(u<0||u>1)return false;var q=Vector3.Cross(t,e1);float v=Vector3.Dot(direction,q)/det;
  return v>=0&&u+v<=1&&Vector3.Dot(e2,q)/det>=0;
 }
 public static JObject Audit(Transform group,float length,float height,JArray holes){
  var triangles=new List<Vector3[]>();
  foreach(var filter in group.GetComponentsInChildren<MeshFilter>()){
   var renderer=filter.GetComponent<MeshRenderer>();if(renderer==null||!renderer.enabled||!renderer.gameObject.activeInHierarchy)continue;
   var path=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(filter.gameObject);var name=Path.GetFileName(path);
   if(!name.StartsWith("WallIn_")&&!name.StartsWith("WallOut_"))continue;
   if(renderer.sharedMaterials.Any(m=>m==null||(m.HasProperty("_SurfaceType")&&m.GetFloat("_SurfaceType")>.5f)))throw new InvalidDataException("Wall surface must use opaque materials");

   var mesh=filter.sharedMesh;if(mesh==null)continue;var vertices=mesh.vertices;var indices=mesh.triangles;
   for(int i=0;i<indices.Length;i+=3)triangles.Add(new[]{group.InverseTransformPoint(filter.transform.TransformPoint(vertices[indices[i]])),group.InverseTransformPoint(filter.transform.TransformPoint(vertices[indices[i+1]])),group.InverseTransformPoint(filter.transform.TransformPoint(vertices[indices[i+2]]))});
  }
  int tested=0,missing=0,blocked=0;var defects=new JArray();
  for(int ix=0;ix<40;ix++)for(int iy=0;iy<9;iy++){
   float x=-length/2+(ix+.5f)*length/40,y=(iy+.5f)*height/9;
   bool aperture=holes.OfType<JObject>().Any(h=>x>(float)h["left_m"]+.02f&&x<(float)h["right_m"]-.02f&&y>(float)h["bottom_m"]+.02f&&y<(float)h["top_m"]-.02f);
   bool boundary=holes.OfType<JObject>().Any(h=>x>(float)h["left_m"]-.02f&&x<(float)h["right_m"]+.02f&&y>(float)h["bottom_m"]-.02f&&y<(float)h["top_m"]+.02f);
   if(boundary&&!aperture)continue;
   foreach(float side in new[]{-1f,1f}){
    bool hit=triangles.Any(t=>FrontHit(t[0],t[1],t[2],new Vector3(x,y,side*2),new Vector3(0,0,-side)));tested++;
    if(!aperture&&!hit)missing++;if(aperture&&hit)blocked++;
    if(aperture==hit&&defects.Count<24)defects.Add(new JObject{["x"]=x,["y"]=y,["side"]=side,["kind"]=aperture?"blocked":"missing"});
   }
  }
  return new JObject{["method"]="sampled_front_facing_triangle_rays_both_sides",["samples"]=tested,["defects"]=defects,["missing_solid_samples"]=missing,["blocked_aperture_samples"]=blocked,["passed"]=missing==0&&blocked==0};
 }
 static GameObject Native(Transform parent,string name,Vector3 pivot,Quaternion rotation,bool companions=true){
  var go=ReferenceAssets.InstantiateAssembly(Source(name),companions?null:new JArray(),parent.gameObject.scene);
  go.transform.SetParent(parent,false);go.transform.localPosition=pivot;go.transform.localRotation=rotation;go.transform.localScale=Vector3.one;
  PrefabUtility.RecordPrefabInstancePropertyModifications(go.transform);return go;
 }
 static void Style(GameObject go,string style){
  foreach(var t in go.GetComponentsInChildren<Transform>().Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)).ToArray()){
   var name=Path.GetFileNameWithoutExtension(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject));
   if(!name.StartsWith("WallIn_")||name.StartsWith("WallIn_"+style+"_"))continue;
   Native(t.parent,"WallIn_"+style+name.Substring(8),t.localPosition,t.localRotation);UnityEngine.Object.DestroyImmediate(t.gameObject);
  }
 }
 static void Module(Transform group,string suffix,float left,float width,bool partition,string style){
  if(partition){
   Native(group,"WallIn_"+style+"_"+suffix,new Vector3(left+width,0,0),Quaternion.identity);
   Native(group,"WallIn_"+style+"_"+suffix,new Vector3(left,0,0),Quaternion.Euler(0,180,0));
   if(suffix.EndsWith("_door")){
    Native(group,"Doorframe_in_single",new Vector3(left+width/2,0,0),Quaternion.identity);
    Native(group,"Door_parent_A_L",new Vector3(left+width/2,0,0),Quaternion.identity);
   }
  }else Style(Native(group,"WallOut_"+suffix,new Vector3(left+width,0,0),Quaternion.identity),style);
 }
 static void Fill(Transform group,int from,int to,float length,bool partition,string style){
  while(from<to){int width=new[]{6,3,2,1}.First(n=>n<=to-from);Module(group,width+"x",from-length/2,width,partition,style);from+=width;}
 }
 public static JObject Build(GameObject root,JObject description,string style){
  BridgeJson.Closed(description,"walls","height_m","thickness_m","lighting","surfaces");
  if(!new[]{"A","B","C"}.Contains(style))throw new InvalidDataException("Unknown interior style");
  float height=ReferenceSceneBuilder.Number(description["height_m"],2,4);
  if(Mathf.Abs(height-2.8f)>.001f)throw new InvalidDataException("Native pack interior height is 2.8 metres");
  var rows=description["walls"] as JArray??throw new InvalidDataException("Walls required");var receipts=new JArray();
  var originals=root.transform.Cast<Transform>().ToDictionary(t=>t.name);var wrappers=new Dictionary<string,GameObject>();
  foreach(JObject wall in rows){
   if(wall["segment_key"]!=null)BridgeJson.Closed(wall,"object_key","segment_key","rotation_deg","start_m","end_m","partition","openings");
   else BridgeJson.Closed(wall,"object_key","start_m","end_m","partition","openings");
   var old=originals[(string)wall["object_key"]];
   var a=ReferenceSceneBuilder.Vector(wall["start_m"],-100,100);var b=ReferenceSceneBuilder.Vector(wall["end_m"],-100,100);float length=Vector3.Distance(a,b);
   int metres=Mathf.RoundToInt(length);bool partition=(bool)wall["partition"];
   if(metres<1||Mathf.Abs(length-metres)>.002f||Mathf.Abs(a.y-b.y)>.001f)throw new InvalidDataException("Wall must fit whole native metre modules");
   if(!wrappers.TryGetValue(old.name,out var wrapper)){
    wrapper=new GameObject(old.name);wrapper.transform.SetParent(root.transform,false);wrappers.Add(old.name,wrapper);
    new GameObject("Connected structural modules").transform.SetParent(wrapper.transform,false);
   }
   try{
    var group=new GameObject((string)wall["segment_key"]??"segment");group.transform.SetParent(wrapper.transform.Find("Connected structural modules"),false);group.transform.position=(a+b)/2;group.transform.rotation=wall["rotation_deg"]==null?old.rotation:Quaternion.Euler(ReferenceSceneBuilder.Vector(wall["rotation_deg"],-360,360));
    float start=group.transform.InverseTransformPoint(a).x,end=group.transform.InverseTransformPoint(b).x;
    var slots=((JArray)wall["openings"]).OfType<JObject>().Select(o=>{
     BridgeJson.Closed(o,"key","kind","start","end");float s=ReferenceSceneBuilder.Number(o["start"],0,1),e=ReferenceSceneBuilder.Number(o["end"],0,1);if(s>=e)throw new InvalidDataException("Invalid aperture interval");
     return new {value=o,slot=Mathf.Clamp(Mathf.RoundToInt(Mathf.Lerp(start,end,(s+e)/2)+length/2-1.5f),0,metres-3)};
    }).OrderBy(o=>o.slot).ToArray();
    int cursor=0;var holes=new JArray();
    foreach(var opening in slots){
     if(metres<3||opening.slot<cursor)throw new InvalidDataException("Opening modules do not fit; adjust room or module selection");
     Fill(group.transform,cursor,opening.slot,length,partition,style);
     string kind=(string)opening.value["kind"];if(kind!="door"&&kind!="window")throw new InvalidDataException("Unknown opening");
     if(partition&&kind=="window")throw new InvalidDataException("Interior window module is not qualified");
     string suffix=kind=="door"?"3x_door":"3x_window_static";
     Module(group.transform,suffix,opening.slot-length/2,3,partition,style);
     float mid=opening.slot-length/2+1.5f;
     holes.Add(new JObject{["key"]=opening.value["key"],["kind"]=kind,["left_m"]=mid-(kind=="door"?.6f:.55f),["right_m"]=mid+(kind=="door"?.6f:.55f),["bottom_m"]=kind=="door"?0:.7f,["top_m"]=kind=="door"?2.2f:2.3f,["insert_present"]=true});cursor=opening.slot+3;
    }
    Fill(group.transform,cursor,metres,length,partition,style);
    var parts=group.GetComponentsInChildren<Transform>().Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)).ToArray();
    if(parts.Any(t=>PrefabUtility.GetPrefabInstanceStatus(t.gameObject)!=PrefabInstanceStatus.Connected||(t.lossyScale-Vector3.one).magnitude>.001f))throw new InvalidDataException("Architecture must retain connected native-size prefabs");
    var audit=Audit(group.transform,length,height,holes);if(!(bool)audit["passed"])throw new InvalidDataException("Wall surface validation failed: "+old.name+" "+audit.ToString());
    receipts.Add(new JObject{["surface_audit"]=audit,["segment_key"]=wall["segment_key"]??old.name,["object_key"]=old.name,["partition"]=partition,["length_m"]=length,["two_faces"]=true,["openings"]=holes,["connected_parts"]=parts.Length,["prefabs"]=new JArray(parts.Select(t=>PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)).Distinct())});
   }catch{UnityEngine.Object.DestroyImmediate(wrapper);throw;}
  }
  foreach(var key in wrappers.Keys)UnityEngine.Object.DestroyImmediate(originals[key].gameObject);
  var tiles=new JArray();
  foreach(var batch in (description["surfaces"] as JArray??new JArray()).OfType<JObject>().GroupBy(s=>(string)s["object_key"])){
   var old=root.transform.Cast<Transform>().Single(t=>t.name==batch.Key);var wrapper=new GameObject(old.name);wrapper.transform.SetParent(root.transform,false);
   try{foreach(var surface in batch){
    BridgeJson.Closed(surface,"object_key","kind","min_m","size_m");bool ceiling=(string)surface["kind"]=="ceiling";
    float width=(float)surface["size_m"][0],depth=(float)surface["size_m"][1];
    bool rotated=Mathf.Abs(depth/3-Mathf.Round(depth/3))>.001f;
    float across=rotated?depth:width,along=rotated?width:depth;
    int nx=Mathf.RoundToInt(across),nz=Mathf.RoundToInt(along/3);
    if(nx<1||nz<1||Mathf.Abs(nx-across)>.002f||Mathf.Abs(nz*3-along)>.002f)throw new InvalidDataException("Floor/ceiling must fit whole tiles");
    for(int z=0;z<nz;z++)for(int x=0;x<nx;){
     int span=new[]{6,4,3,2,1}.First(n=>n<=nx-x);string name=(ceiling?"Ceiling_":"Floor_")+span+"x3";
     var bounds=LocalBounds(Source(name));var centre=new Vector3((float)surface["min_m"][0]+(rotated?z*3+1.5f:x+span/2f),ceiling?2.8f:0,(float)surface["min_m"][1]+(rotated?x+span/2f:z*3+1.5f));
     var rotation=Quaternion.Euler(0,rotated?90:0,0);
     var tile=Native(wrapper.transform,name,centre-rotation*new Vector3(bounds.center.x,ceiling?bounds.min.y:bounds.max.y,bounds.center.z),rotation);
     foreach(var helper in tile.GetComponentsInChildren<MonoBehaviour>(true).Where(c=>c!=null&&c.GetType().FullName=="FS_Atmo.DisableAtStart")){helper.gameObject.SetActive(false);PrefabUtility.RecordPrefabInstancePropertyModifications(helper.gameObject);}
     tiles.Add(new JObject{["object_key"]=batch.Key,["prefab"]=AssetDatabase.GetAssetPath(Source(name)),["scale"]=new JArray(1,1,1)});x+=span;
    }
   }}catch{UnityEngine.Object.DestroyImmediate(wrapper);throw;}
   UnityEngine.Object.DestroyImmediate(old.gameObject);
  }
  return new JObject{["method"]="whole_native_prefab_modules",["walls"]=receipts,["tiles"]=tiles,["lighting"]="neutral_construction_no_directional_shadows",["visual_qualified"]=false};
 }
}
}
