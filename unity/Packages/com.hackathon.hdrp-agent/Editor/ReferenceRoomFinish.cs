using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
 public static class ReferenceRoomFinish {
 const string Building="Assets/AtmosphericHouse/Prefabs/Building/";
 public const string CeilingGroup="Reconstruction ceiling";
 static string PrefabName(GameObject obj)=>Path.GetFileNameWithoutExtension(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(obj));
 static JObject Pose(Transform t)=>new JObject{["position_m"]=JArray.FromObject(ReferenceAssets.Vec(t.position)),["rotation_deg"]=JArray.FromObject(ReferenceAssets.Vec(t.eulerAngles)),["scale"]=JArray.FromObject(ReferenceAssets.Vec(t.localScale))};
 // Validate cell coverage, not only total area: overlaps can otherwise hide holes.
 static Bounds Rectangle(Transform[] floors){
 var boxes=new List<Bounds>();
 foreach(var floor in floors){
 var rs=floor.GetComponentsInChildren<MeshRenderer>();if(rs.Length==0)throw new InvalidDataException("Floor has no surface");
 foreach(var r in rs){var axis=r.transform.right;var forward=r.transform.forward;if(Mathf.Abs(axis.y)>.001f||Mathf.Abs(forward.y)>.001f||Mathf.Max(Mathf.Abs(axis.x),Mathf.Abs(axis.z))<.999f)throw new InvalidDataException("Ceiling needs axis-aligned floors");}
 var b=rs[0].bounds;foreach(var r in rs.Skip(1))b.Encapsulate(r.bounds);if(b.size.x<.01f||b.size.z<.01f)throw new InvalidDataException("Empty floor footprint");boxes.Add(b);
 }
 var bounds=boxes[0];foreach(var b in boxes.Skip(1))bounds.Encapsulate(b);
 var xs=boxes.SelectMany(b=>new[]{b.min.x,b.max.x}).Distinct().OrderBy(x=>x).ToArray();var zs=boxes.SelectMany(b=>new[]{b.min.z,b.max.z}).Distinct().OrderBy(x=>x).ToArray();
 for(int x=1;x<xs.Length;x++)for(int z=1;z<zs.Length;z++){
 if(xs[x]-xs[x-1]<.001f||zs[z]-zs[z-1]<.001f)continue;
 float cx=(xs[x]+xs[x-1])/2,cz=(zs[z]+zs[z-1])/2;
 if(boxes.Count(b=>cx>b.min.x&&cx<b.max.x&&cz>b.min.z&&cz<b.max.z)!=1)throw new InvalidDataException("Ceiling needs a rectangular floor footprint without gaps or overlaps");
 }
 return bounds;
 }
 public static JObject Apply(GameObject root,string style="B"){
 if(root==null)throw new ArgumentNullException(nameof(root));
 if(!new[]{"A","B","C"}.Contains(style))throw new InvalidDataException("Unknown wall style");
 var walls=root.transform.Cast<Transform>().Where(t=>PrefabName(t.gameObject).StartsWith("WallOut_")).ToArray();
 var floors=root.transform.Cast<Transform>().Where(t=>PrefabName(t.gameObject).StartsWith("Floor_")).ToArray();
 if(walls.Length<4||floors.Length==0)return new JObject{["applied"]=false};
 var replacements=new List<(Transform old,GameObject source,Transform wall)>();
 foreach(var wall in walls){
 var interiors=wall.GetComponentsInChildren<Transform>().Where(t=>PrefabName(t.gameObject).StartsWith("WallIn_")&&PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)).ToArray();
 if(interiors.Length==0)throw new InvalidDataException("Missing interior wall companion: "+wall.name);
 foreach(var old in interiors){
 var name=PrefabName(old.gameObject);if(name.Length<10||name[8]!='_')throw new InvalidDataException("Invalid interior wall variant: "+name);
 var desired="WallIn_"+style+name.Substring(8);if(name==desired)continue;
 var source=AssetDatabase.LoadAssetAtPath<GameObject>(Building+desired+".prefab");
 if(source==null)throw new InvalidDataException("Missing coherent interior variant: "+desired);
 var before=old.GetComponent<MeshFilter>()?.sharedMesh;var after=source.GetComponent<MeshFilter>()?.sharedMesh;
 if(before==null||after==null||(before.bounds.size-after.bounds.size).magnitude>.03f||(before.bounds.center-after.bounds.center).magnitude>.03f)throw new InvalidDataException("Incompatible interior variant geometry: "+desired);
 replacements.Add((old,source,wall));
 }}
 var explicitCeiling=root.GetComponentsInChildren<Transform>(true).Any(t=>PrefabName(t.gameObject).StartsWith("Ceiling_"));
 var existing=root.scene.GetRootGameObjects().FirstOrDefault(o=>o.name==CeilingGroup);
 Bounds bounds=default;float y=0;int nx=0,nz=0;GameObject ceiling=null;Mesh mesh=null;
 if(!explicitCeiling){
 bounds=Rectangle(floors);
 var inward=walls.SelectMany(t=>t.GetComponentsInChildren<MeshRenderer>()).Where(r=>PrefabName(r.gameObject).StartsWith("WallIn_")).ToArray();
 if(inward.Length==0)throw new InvalidDataException("Missing interior surfaces");
 y=inward.Min(r=>r.bounds.max.y);if(inward.Any(r=>Mathf.Abs(r.bounds.max.y-y)>.02f))throw new InvalidDataException("Uneven interior wall tops");
 ceiling=AssetDatabase.LoadAssetAtPath<GameObject>(Building+"Ceiling_3x3.prefab");mesh=ceiling?.GetComponent<MeshFilter>()?.sharedMesh;
 if(mesh==null||mesh.bounds.size.x<=0||mesh.bounds.size.z<=0)throw new InvalidDataException("Missing valid Ceiling_3x3 prefab");
 nx=Mathf.Max(1,Mathf.CeilToInt(bounds.size.x/mesh.bounds.size.x-.001f));nz=Mathf.Max(1,Mathf.CeilToInt(bounds.size.z/mesh.bounds.size.z-.001f));
 if((long)nx*nz>64)throw new InvalidDataException("Ceiling tile limit exceeded");
 }
 // Stage all instances before deleting originals. Invalid geometry leaves the scene intact.
 var staged=new List<GameObject>();var changes=new JArray();var tiles=new JArray();GameObject group=null;
 try{
 foreach(var entry in replacements){
 var replacement=ReferenceAssets.InstantiateAssembly(entry.source,null,root.scene);staged.Add(replacement);
 replacement.transform.SetParent(entry.old.parent,false);replacement.transform.localPosition=entry.old.localPosition;replacement.transform.localRotation=entry.old.localRotation;replacement.transform.localScale=entry.old.localScale;
 PrefabUtility.RecordPrefabInstancePropertyModifications(replacement.transform);
 changes.Add(new JObject{["wall"]=entry.wall.name,["from"]=PrefabName(entry.old.gameObject),["to"]=entry.source.name,["pose"]=Pose(replacement.transform)});
 }
 if(!explicitCeiling){
 group=new GameObject(CeilingGroup);SceneManager.MoveGameObjectToScene(group,root.scene);
 for(int x=0;x<nx;x++)for(int z=0;z<nz;z++){
 var tile=ReferenceAssets.InstantiateAssembly(ceiling,null,root.scene);staged.Add(tile);tile.transform.SetParent(group.transform,false);
 var scale=new Vector3(bounds.size.x/nx/mesh.bounds.size.x,1,bounds.size.z/nz/mesh.bounds.size.z);tile.transform.localScale=scale;
 tile.transform.position=new Vector3(bounds.min.x+(x+.5f)*bounds.size.x/nx,y,bounds.min.z+(z+.5f)*bounds.size.z/nz)-Vector3.Scale(new Vector3(mesh.bounds.center.x,mesh.bounds.min.y,mesh.bounds.center.z),scale);
 foreach(var helper in tile.GetComponentsInChildren<MonoBehaviour>(true).Where(b=>b!=null&&b.GetType().FullName=="FS_Atmo.DisableAtStart")){helper.gameObject.SetActive(false);PrefabUtility.RecordPrefabInstancePropertyModifications(helper.gameObject);}
 PrefabUtility.RecordPrefabInstancePropertyModifications(tile.transform);
 var receipt=Pose(tile.transform);receipt["prefab"]=Building+"Ceiling_3x3.prefab";receipt["asset_dependency_hash"]=AssetDatabase.GetAssetDependencyHash(Building+"Ceiling_3x3.prefab").ToString();receipt["connected"]=PrefabUtility.GetPrefabInstanceStatus(tile)==PrefabInstanceStatus.Connected;tiles.Add(receipt);
 }
 }
 }catch{foreach(var obj in staged)if(obj!=null)UnityEngine.Object.DestroyImmediate(obj);if(group!=null)UnityEngine.Object.DestroyImmediate(group);throw;}
 foreach(var entry in replacements)UnityEngine.Object.DestroyImmediate(entry.old.gameObject);
 if(existing!=null)UnityEngine.Object.DestroyImmediate(existing);
 return new JObject{["applied"]=true,["style"]=style,["wall_changes"]=changes,["ceiling"]=explicitCeiling?"explicit_plan_preserved":"derived_rectangle",["ceiling_underside_y_m"]=explicitCeiling?(float?)null:y,["tiles"]=tiles,["limitation"]="Geometry and prefab connectivity only; lighting, seams and visual fidelity require rendered inspection."};
 }
 }
}
