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
 static GameObject Part(Transform parent,string name,Vector3 center,Quaternion rotation,Vector3 scale){
  var source=Source(name);var go=(GameObject)PrefabUtility.InstantiatePrefab(source,parent.gameObject.scene);
  go.transform.SetParent(parent,false);go.transform.localPosition=Vector3.zero;go.transform.localRotation=Quaternion.identity;go.transform.localScale=Vector3.one;
  foreach(var script in go.GetComponentsInChildren<MonoBehaviour>(true).Where(b=>b!=null&&b.GetType().FullName=="FS_Atmo.SwapPrefab")){
   var so=new SerializedObject(script);var placed=so.FindProperty("placed");if(placed!=null){placed.boolValue=true;so.ApplyModifiedPropertiesWithoutUndo();PrefabUtility.RecordPrefabInstancePropertyModifications(script);}
  }
  var bounds=LocalBounds(go);go.transform.localScale=scale;go.transform.localRotation=rotation;go.transform.localPosition=center-rotation*Vector3.Scale(bounds.center,scale);
  PrefabUtility.RecordPrefabInstancePropertyModifications(go.transform);return go;
 }
 static void Panel(Transform parent,string name,float x0,float x1,float y0,float y1,float z,bool reverse){
  if(x1-x0<.001f||y1-y0<.001f)return;var b=LocalBounds(Source(name));
  Part(parent,name,new Vector3((x0+x1)/2,(y0+y1)/2,z),Quaternion.Euler(0,reverse?180:0,0),new Vector3((x1-x0)/b.size.x,(y1-y0)/b.size.y,1));
 }
 static void Solid(Transform parent,string outside,string inside,float a,float b,float low,float high,float thickness){
  Panel(parent,outside,a,b,low,high,thickness/2,false);Panel(parent,inside,a,b,low,high,-thickness/2,true);
 }
 static void Cap(Transform parent,string inside,float x0,float x1,float y,float thickness){
  if(x1-x0<.001f)return;var b=LocalBounds(Source(inside));
  Part(parent,inside,new Vector3((x0+x1)/2,y,0),Quaternion.Euler(-90,0,0),new Vector3((x1-x0)/b.size.x,thickness/b.size.y,.01f));
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
  int tested=0,missing=0,blocked=0;
  for(int ix=0;ix<40;ix++)for(int iy=0;iy<9;iy++){
   float x=-length/2+(ix+.5f)*length/40,y=(iy+.5f)*height/9;
   bool aperture=holes.OfType<JObject>().Any(h=>x>(float)h["left_m"]+.02f&&x<(float)h["right_m"]-.02f&&y>(float)h["bottom_m"]+.02f&&y<(float)h["top_m"]-.02f);
   bool boundary=holes.OfType<JObject>().Any(h=>x>(float)h["left_m"]-.02f&&x<(float)h["right_m"]+.02f&&y>(float)h["bottom_m"]-.02f&&y<(float)h["top_m"]+.02f);
   if(boundary&&!aperture)continue;
   foreach(float side in new[]{-1f,1f}){
    bool hit=triangles.Any(t=>FrontHit(t[0],t[1],t[2],new Vector3(x,y,side*2),new Vector3(0,0,-side)));tested++;
    if(!aperture&&!hit)missing++;if(aperture&&hit)blocked++;
   }
  }
  return new JObject{["method"]="sampled_front_facing_triangle_rays_both_sides",["samples"]=tested,["missing_solid_samples"]=missing,["blocked_aperture_samples"]=blocked,["passed"]=missing==0&&blocked==0};
 }
 public static JObject Build(GameObject root,JObject description,string style){
  BridgeJson.Closed(description,"walls","height_m","thickness_m","lighting");
  if(!new[]{"A","B","C"}.Contains(style))throw new InvalidDataException("Unknown interior style");
  float height=ReferenceSceneBuilder.Number(description["height_m"],2,4),thickness=ReferenceSceneBuilder.Number(description["thickness_m"],.1f,.5f);
  var rows=description["walls"] as JArray??throw new InvalidDataException("Walls required");var receipts=new JArray();
  foreach(JObject wall in rows){
   BridgeJson.Closed(wall,"object_key","start_m","end_m","partition","openings");
   var old=root.transform.Cast<Transform>().Single(t=>t.name==(string)wall["object_key"]);
   var a=ReferenceSceneBuilder.Vector(wall["start_m"],-100,100);var b=ReferenceSceneBuilder.Vector(wall["end_m"],-100,100);float length=Vector3.Distance(a,b);
   if(length<.1f||Mathf.Abs(a.y-b.y)>.001f)throw new InvalidDataException("Invalid wall segment");
   var wrapper=new GameObject(old.name);wrapper.transform.SetParent(root.transform,false);wrapper.transform.SetPositionAndRotation(old.position,old.rotation);wrapper.transform.localScale=old.localScale;
   try{
    var group=new GameObject("Connected structural modules");group.transform.SetParent(wrapper.transform,false);group.transform.position=(a+b)/2;group.transform.rotation=old.rotation;group.transform.localScale=new Vector3(1/old.lossyScale.x,1/old.lossyScale.y,1/old.lossyScale.z);
    var start=group.transform.InverseTransformPoint(a).x;var end=group.transform.InverseTransformPoint(b).x;
    string inside="WallIn_"+style+"_1x",outside=(bool)wall["partition"]?inside:"WallOut_1x";
    var apertures=((JArray)wall["openings"]).OfType<JObject>().Select(o=>{
     BridgeJson.Closed(o,"key","kind","start","end");float s=ReferenceSceneBuilder.Number(o["start"],0,1),e=ReferenceSceneBuilder.Number(o["end"],0,1);if(s>=e)throw new InvalidDataException("Invalid aperture interval");
     return new {value=o,left=Mathf.Min(Mathf.Lerp(start,end,s),Mathf.Lerp(start,end,e)),right=Mathf.Max(Mathf.Lerp(start,end,s),Mathf.Lerp(start,end,e))};
    }).OrderBy(o=>o.left).ToArray();
    float cursor=-length/2;var holes=new JArray();
    foreach(var opening in apertures){
     if(opening.left<cursor-.001f)throw new InvalidDataException("Overlapping wall apertures");
     Solid(group.transform,outside,inside,cursor,opening.left,0,height,thickness);
     float width=opening.right-opening.left,mid=(opening.right+opening.left)/2;string kind=(string)opening.value["kind"];float bottom,top;
     if(kind=="door"){
      var frame=LocalBounds(Source("Doorframe_in_single"));float uniform=width/frame.size.x;top=frame.size.y*uniform;bottom=0;
      if(top>height-.08f||uniform<.65f)throw new InvalidDataException("Door aperture incompatible with prefab proportions");
      Part(group.transform,"Doorframe_in_single",new Vector3(mid,top/2,0),Quaternion.identity,Vector3.one*uniform);
      var door=LocalBounds(Source("Door_parent_A_L"));Part(group.transform,"Door_parent_A_L",new Vector3(mid,door.size.y*uniform/2,0),Quaternion.identity,Vector3.one*uniform);
     }else if(kind=="window"){
      var win=LocalBounds(Source("Window_single_static"));bottom=.8f;top=Mathf.Min(height-.15f,bottom+win.size.y);
      Part(group.transform,"Window_single_static",new Vector3(mid,(bottom+top)/2,0),Quaternion.identity,new Vector3(width/win.size.x,(top-bottom)/win.size.y,1));
      Solid(group.transform,outside,inside,opening.left,opening.right,0,bottom,thickness);
     }else throw new InvalidDataException("Unknown aperture type");
     Solid(group.transform,outside,inside,opening.left,opening.right,top,height,thickness);
     var jamb=LocalBounds(Source(inside));
     foreach(float side in new[]{-1f,1f})Part(group.transform,inside,new Vector3(side<0?opening.left:opening.right,(bottom+top)/2,0),Quaternion.Euler(0,-side*90,0),new Vector3(thickness/jamb.size.x,(top-bottom)/jamb.size.y,.01f));
     if(bottom>0)Cap(group.transform,inside,opening.left,opening.right,bottom,thickness);

     holes.Add(new JObject{["key"]=opening.value["key"],["kind"]=kind,["left_m"]=opening.left,["right_m"]=opening.right,["bottom_m"]=bottom,["top_m"]=top,["insert_present"]=true});cursor=opening.right;
    }
    Solid(group.transform,outside,inside,cursor,length/2,0,height,thickness);Cap(group.transform,inside,-length/2,length/2,height,thickness);
    // Close exposed wall ends without plugging passages.
    var capBounds=LocalBounds(Source(inside));foreach(float side in new[]{-1f,1f})Part(group.transform,inside,new Vector3(side*length/2,height/2,0),Quaternion.Euler(0,side*90,0),new Vector3(thickness/capBounds.size.x,height/capBounds.size.y,.01f));
    var parts=group.GetComponentsInChildren<Transform>().Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)).ToArray();
    if(parts.Any(t=>PrefabUtility.GetPrefabInstanceStatus(t.gameObject)!=PrefabInstanceStatus.Connected))throw new InvalidDataException("Disconnected architecture prefab");
    var audit=Audit(group.transform,length,height,holes);if(!(bool)audit["passed"])throw new InvalidDataException("Wall surface validation failed: "+old.name+" "+audit.ToString());
    receipts.Add(new JObject{["surface_audit"]=audit,["object_key"]=old.name,["partition"]=(bool)wall["partition"],["length_m"]=length,["two_faces"]=true,["openings"]=holes,["connected_parts"]=parts.Length,["prefabs"]=new JArray(parts.Select(t=>PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)).Distinct())});
   }catch{UnityEngine.Object.DestroyImmediate(wrapper);throw;}
   UnityEngine.Object.DestroyImmediate(old.gameObject);
  }
  return new JObject{["method"]="connected_prefab_panels_and_explicit_apertures",["walls"]=receipts,["lighting"]="neutral_construction_no_directional_shadows",["visual_qualified"]=false};
 }
}
}
