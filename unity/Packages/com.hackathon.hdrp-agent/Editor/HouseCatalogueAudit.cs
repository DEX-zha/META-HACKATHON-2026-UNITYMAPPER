using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEditor;
namespace HdrpAgent.Editor {
 public static class HouseCatalogueAudit {
  static JArray V(Vector3 v)=>new JArray(v.x,v.y,v.z);
  static bool Active(Transform t){for(;t!=null;t=t.parent)if(!t.gameObject.activeSelf)return false;return true;}
  public static JObject Measure(GameObject prefab,string path){
   var bounds=new Bounds();bool first=true;var surfaces=new JArray();
   foreach(var mf in prefab.GetComponentsInChildren<MeshFilter>(true)){
    var renderer=mf.GetComponent<MeshRenderer>();if(renderer==null||!renderer.enabled||!Active(mf.transform)||mf.sharedMesh==null)continue;
    var matrix=prefab.transform.worldToLocalMatrix*mf.transform.localToWorldMatrix;var mesh=mf.sharedMesh;
    var b=mesh.bounds;for(int i=0;i<8;i++){var p=matrix.MultiplyPoint3x4(b.center+Vector3.Scale(b.extents,new Vector3((i&1)==0?-1:1,(i&2)==0?-1:1,(i&4)==0?-1:1)));if(first){bounds=new Bounds(p,Vector3.zero);first=false;}else bounds.Encapsulate(p);}
    try {
     var verts=mesh.vertices;var tri=mesh.triangles;var patches=new Dictionary<int,JArray>();
     for(int i=0;i<tri.Length;i+=3){var a=matrix.MultiplyPoint3x4(verts[tri[i]]);var c=matrix.MultiplyPoint3x4(verts[tri[i+1]]);var d=matrix.MultiplyPoint3x4(verts[tri[i+2]]);var n=Vector3.Cross(c-a,d-a);if(n.magnitude<1e-8f||n.normalized.y<.985f)continue;int level=Mathf.RoundToInt((a.y+c.y+d.y)/3/.005f);if(!patches.TryGetValue(level,out var triangles)){triangles=new JArray();patches[level]=triangles;}triangles.Add(new JArray(V(a),V(c),V(d)));}
     foreach(var patch in patches)surfaces.Add(new JObject{["id"]="surface-"+surfaces.Count,["height_m"]=patch.Key*.005f,["triangles"]=patch.Value,["qualification"]="geometry_candidate",["supports_items"]=false,["reason"]="Upward mesh triangles; semantic support and stability still require qualification"});
    }catch(Exception e){surfaces.Add(new JObject{["id"]="surface-"+surfaces.Count,["qualification"]="unavailable",["reason"]=e.GetType().Name});}
   }
   return new JObject{["prefab_guid"]=AssetDatabase.AssetPathToGUID(path),["dependency_hash"]=AssetDatabase.GetAssetDependencyHash(path).ToString(),["prefab_path"]=path,["bounds_center"]=V(bounds.center),["bounds_size"]=V(bounds.size),["surfaces"]=surfaces,["measurement_evidence"]="unity_mesh_local_coordinates_v1"};
  }
  [MenuItem("Tools/HDRP Agent/House/Render functional prefab views")]
  public static void RenderFunctionalViews(){
   if(HouseReferenceAudit.Running||ReferenceWorkflow.Running||CommandExecutor.Busy)throw new InvalidOperationException("Wait for native inspection or generation");
   var names=new HashSet<string>{"Workdesk","Chair_kitchen","Computer_screen","Computer_keyboard","Computer_mouse","Sofa_3seat","Kitchen_counter_A","Kitchen_counter_sink","Stove","Fridge","Toilet","Bathroom_sink","Bed_king","Side_table_E","Table_coffee","Side_table_D","TV_off","Table_A","Wardrobe","Bookshelf","Lamp_table_work","Lamp_ceiling_round","Dresser_C","Computer_mousepad","Pencil_holder","Notebook","Interior_plant_A","Book_set_bookshelf_A","Book_set_I","Book_set_A","Sofa_1seat"};
   var directory=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/house/functional-views");Directory.CreateDirectory(directory);var rows=new JArray();var oldPath=Path.Combine(directory,"manifest.json");var prior=File.Exists(oldPath)?JArray.Parse(File.ReadAllText(oldPath)):new JArray();
   foreach(JObject asset in ReferenceAssets.Catalogue("Assets/AtmosphericHouse/Prefabs"))if(names.Contains((string)asset["name"])){
    string file=(string)asset["asset_guid"]+".png";if(!File.Exists(Path.Combine(directory,file))||!prior.OfType<JObject>().Any(p=>(string)p["prefab_guid"]==(string)asset["asset_guid"]&&(string)p["dependency_hash"]==(string)asset["dependency_hash"]))ReferenceAssets.SavePreview(asset,Path.Combine(directory,file));rows.Add(new JObject{["prefab_guid"]=asset["asset_guid"],["dependency_hash"]=asset["dependency_hash"],["path"]=asset["path"],["name"]=asset["name"],["file"]=file,["camera_offsets"]=new JArray(new JArray(1,.7,1),new JArray(-1,.7,-1))});
   }
   File.WriteAllText(Path.Combine(directory,"manifest.json"),rows.ToString());
  }
  [MenuItem("Tools/HDRP Agent/House/Measure prefab catalogue")]
  public static void Export(){
   if(HouseReferenceAudit.Running||ReferenceWorkflow.Running||CommandExecutor.Busy)throw new InvalidOperationException("Wait for native inspection or generation");
   var rows=new JArray();foreach(var guid in AssetDatabase.FindAssets("t:Prefab",new[]{"Assets/AtmosphericHouse/Prefabs","Assets/HouseProps"}).OrderBy(x=>x)){
    var path=AssetDatabase.GUIDToAssetPath(guid);var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(path);if(prefab!=null)rows.Add(Measure(prefab,path));
   }
   var directory=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/house");Directory.CreateDirectory(directory);File.WriteAllText(Path.Combine(directory,"catalogue-native.json"),rows.ToString());
  }
 }
}
