using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;
namespace HdrpAgent.Editor {
 public static class ReferenceRoomFinish {
 const string Building="Assets/AtmosphericHouse/Prefabs/Building/";
 public static JObject Apply(GameObject root,string style="B"){
 if(!new[]{"A","B","C"}.Contains(style))throw new InvalidDataException("Unknown wall style");
 var walls=root.transform.Cast<Transform>().Where(t=>Path.GetFileName(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)).StartsWith("WallOut_")).ToArray();
 var floors=root.transform.Cast<Transform>().Where(t=>Path.GetFileName(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)).StartsWith("Floor_")).ToArray();
 var changes=new JArray();if(walls.Length<4||floors.Length==0)return new JObject{["applied"]=false};
 foreach(var wall in walls)foreach(var old in wall.GetComponentsInChildren<Transform>().Where(t=>t.name.StartsWith("WallIn_")).ToArray()){
 var path=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(old.gameObject);var name=Path.GetFileNameWithoutExtension(path);if(name.Length<10)continue;
 var desired="WallIn_"+style+name.Substring(8);if(name==desired)continue;
 var source=AssetDatabase.LoadAssetAtPath<GameObject>(Building+desired);if(source==null)source=AssetDatabase.LoadAssetAtPath<GameObject>(Building+desired+".prefab");
 if(source==null)throw new InvalidDataException("Missing coherent interior variant: "+desired);
 var replacement=ReferenceAssets.InstantiateAssembly(source,null,root.scene);replacement.transform.SetParent(old.parent,false);replacement.transform.localPosition=old.localPosition;replacement.transform.localRotation=old.localRotation;replacement.transform.localScale=old.localScale;PrefabUtility.RecordPrefabInstancePropertyModifications(replacement.transform);
 changes.Add(new JObject{["wall"]=wall.name,["from"]=name,["to"]=desired});UnityEngine.Object.DestroyImmediate(old.gameObject);
 }
 var rs=floors.SelectMany(t=>t.GetComponentsInChildren<Renderer>()).ToArray();var bounds=rs[0].bounds;foreach(var r in rs.Skip(1))bounds.Encapsulate(r.bounds);
 // Only close a rectangular, axis-aligned footprint. Do not roof guessed voids.
 float area=rs.Sum(r=>r.bounds.size.x*r.bounds.size.z);if(Mathf.Abs(area-bounds.size.x*bounds.size.z)>.01f*area)throw new InvalidDataException("Ceiling needs a rectangular floor footprint");
 var inward=walls.SelectMany(t=>t.GetComponentsInChildren<MeshRenderer>()).Where(r=>Path.GetFileName(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(r.gameObject)).StartsWith("WallIn_")).ToArray();
 float y=inward.Min(r=>r.bounds.max.y);if(inward.Any(r=>Mathf.Abs(r.bounds.max.y-y)>.02f))throw new InvalidDataException("Uneven interior wall tops");
 var ceiling=AssetDatabase.LoadAssetAtPath<GameObject>(Building+"Ceiling_3x3.prefab");var mesh=ceiling.GetComponent<MeshFilter>().sharedMesh;
 var existing=root.scene.GetRootGameObjects().FirstOrDefault(o=>o.name=="Reconstruction ceiling");
 if(existing!=null)UnityEngine.Object.DestroyImmediate(existing);
 if(root.GetComponentsInChildren<Transform>().Any(t=>Path.GetFileName(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)).StartsWith("Ceiling_")))return new JObject{["applied"]=true,["style"]=style,["wall_changes"]=changes,["ceiling"]= "explicit_plan_preserved"};
 var group=new GameObject("Reconstruction ceiling");SceneManager.MoveGameObjectToScene(group,root.scene);
 int nx=Mathf.Max(1,Mathf.CeilToInt(bounds.size.x/3f-.1f)),nz=Mathf.Max(1,Mathf.CeilToInt(bounds.size.z/3f-.1f));if(nx*nz>64)throw new InvalidDataException("Ceiling tile limit exceeded");
 var tiles=new JArray();
 for(int x=0;x<nx;x++)for(int z=0;z<nz;z++){
 var tile=ReferenceAssets.InstantiateAssembly(ceiling,null,root.scene);tile.transform.SetParent(group.transform,false);
 var scale=new Vector3(bounds.size.x/nx/mesh.bounds.size.x,1,bounds.size.z/nz/mesh.bounds.size.z);tile.transform.localScale=scale;
 tile.transform.position=new Vector3(bounds.min.x+(x+.5f)*bounds.size.x/nx,y,bounds.min.z+(z+.5f)*bounds.size.z/nz)-Vector3.Scale(mesh.bounds.center,scale);
 // Pack helper is disabled by Start in play mode; make editor probes consistent.
 foreach(var helper in tile.GetComponentsInChildren<MonoBehaviour>(true).Where(b=>b!=null&&b.GetType().FullName=="FS_Atmo.DisableAtStart")){helper.gameObject.SetActive(false);PrefabUtility.RecordPrefabInstancePropertyModifications(helper.gameObject);}
 PrefabUtility.RecordPrefabInstancePropertyModifications(tile.transform);tiles.Add(new JObject{["prefab"]=Building+"Ceiling_3x3.prefab",["position_m"]=JArray.FromObject(ReferenceAssets.Vec(tile.transform.position)),["scale"]=JArray.FromObject(ReferenceAssets.Vec(scale))});
 }
 return new JObject{["applied"]=true,["style"]=style,["wall_changes"]=changes,["ceiling_underside_y_m"]=y,["tiles"]=tiles};
 }
 }
}
