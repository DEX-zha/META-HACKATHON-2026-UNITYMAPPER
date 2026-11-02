using System;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEditor;
namespace HdrpAgent.Editor {
// Mesh colliders are temporary measurement proxies, including meshes with no authored collider.
public static class HouseTraversal {
 const float Step=.25f,Radius=.4f,Height=2f;
 static bool Owned(Collider c,GameObject root)=>c!=null&&c.gameObject.scene==root.scene&&c.transform.IsChildOf(root.transform);
 public static JObject Check(GameObject root,JObject manifest){
  var coverings=new HashSet<Transform>();
  foreach(JObject item in manifest["instances"]){
   if((string)item["role"]!="floor_covering")continue;
   string path=AssetDatabase.GUIDToAssetPath((string)item["prefab_guid"]);
   if(!path.StartsWith("Assets/AtmosphericHouse/Prefabs/Props/Carpets/",StringComparison.Ordinal)&&!path.StartsWith("Assets/AtmosphericHouse/Prefabs/Decals/Decal_papers_",StringComparison.Ordinal))throw new InvalidOperationException("Unapproved walkable floor detail");
   var t=root.transform.Find((string)item["id"]);if(t==null)throw new InvalidOperationException("Floor detail missing");
   var renderers=t.GetComponentsInChildren<MeshRenderer>();if(renderers.Length==0)throw new InvalidOperationException("Floor detail has no measured mesh");
   var b=renderers[0].bounds;foreach(var r in renderers.Skip(1))b.Encapsulate(r.bounds);
   if(b.size.y>.051f||b.min.y<-.005f||b.max.y>.06f)throw new InvalidOperationException("Floor detail exceeds walkable thickness");
   coverings.Add(t);
  }
  Func<Collider,bool> walkable=c=>c.GetComponentsInParent<Transform>().Any(t=>t.name.EndsWith("-floor")||coverings.Contains(t));
  var building=(JObject)manifest["building"];var rooms=((JArray)building["rooms"]).OfType<JObject>().ToArray();
  float x0=rooms.Min(r=>((JArray)r["polygon"]).Min(p=>(float)p[0])),z0=rooms.Min(r=>((JArray)r["polygon"]).Min(p=>(float)p[1]));
  float x1=rooms.Max(r=>((JArray)r["polygon"]).Max(p=>(float)p[0])),z1=rooms.Max(r=>((JArray)r["polygon"]).Max(p=>(float)p[1]));
  int nx=Mathf.CeilToInt((x1-x0)/Step),nz=Mathf.CeilToInt((z1-z0)/Step);var valid=new HashSet<Vector2Int>();var floors=new Dictionary<Vector2Int,float>();
  for(int x=0;x<nx;x++)for(int z=0;z<nz;z++){
   var cell=new Vector2Int(x,z);var origin=new Vector3(x0+(x+.5f)*Step,.3f,z0+(z+.5f)*Step);
   var hits=Physics.RaycastAll(origin,Vector3.down,.6f,1<<30,QueryTriggerInteraction.Ignore).Where(h=>Owned(h.collider,root)&&walkable(h.collider)&&h.normal.y>=Mathf.Cos(45*Mathf.Deg2Rad)).OrderBy(h=>h.distance).ToArray();
   if(hits.Length==0)continue;float y=hits[0].point.y;var bottom=new Vector3(origin.x,y+Radius+.015f,origin.z);var top=bottom+Vector3.up*(Height-2*Radius);
   if(Physics.OverlapCapsule(bottom,top,Radius,1<<30,QueryTriggerInteraction.Ignore).Any(c=>Owned(c,root)))continue;
   valid.Add(cell);floors[cell]=y;
  }
  Func<Vector2Int,Vector3> world=c=>new Vector3(x0+(c.x+.5f)*Step,floors.ContainsKey(c)?floors[c]:0,z0+(c.y+.5f)*Step);
  var points=new JArray();var targets=new List<Vector2Int>();var defects=new JArray();
  foreach(JObject entry in manifest["access"])foreach(JArray point in entry["points"]){
   var p=new Vector3((float)point[0],0,(float)point[1]);var nearby=valid.Where(c=>Vector3.Distance(world(c),p)<.55f).OrderBy(c=>Vector3.Distance(world(c),p)).ToArray();
   if(nearby.Length==0){defects.Add(new JObject{["room_id"]=entry["room_id"],["kind"]="passage",["message"]="No capsule clearance near required access point",["position"]=point.DeepClone()});continue;}
   targets.Add(nearby[0]);points.Add(new JObject{["room_id"]=entry["room_id"],["position"]=point.DeepClone(),["cell"]=new JArray(nearby[0].x,nearby[0].y)});
  }
  var reached=new HashSet<Vector2Int>();var queue=new Queue<Vector2Int>();if(targets.Count>0){reached.Add(targets[0]);queue.Enqueue(targets[0]);}
  var directions=new[]{Vector2Int.right,Vector2Int.left,Vector2Int.up,Vector2Int.down};
  while(queue.Count>0){var c=queue.Dequeue();foreach(var d in directions){var next=c+d;if(!valid.Contains(next)||reached.Contains(next)||Mathf.Abs(floors[c]-floors[next])>.25f)continue;
   var from=world(c)+Vector3.up*(Radius+.015f);var to=world(next)+Vector3.up*(Radius+.015f);var delta=to-from;
   if(Physics.CapsuleCastAll(from,from+Vector3.up*(Height-2*Radius),Radius,delta.normalized,delta.magnitude,1<<30,QueryTriggerInteraction.Ignore).Any(h=>Owned(h.collider,root)))continue;
   reached.Add(next);queue.Enqueue(next);
  }}
  for(int i=0;i<targets.Count;i++)if(!reached.Contains(targets[i]))defects.Add(new JObject{["kind"]="passage",["message"]="Required access point is disconnected on native geometry",["target"]=points[i].DeepClone()});
  return new JObject{["method"]="native_mesh_capsule_grid",["width_m"]=Radius*2,["height_m"]=Height,["step_m"]=Step,["max_step_m"]=.25f,["max_slope_deg"]=45,["support_required"]=true,["valid_cells"]=valid.Count,["reachable_cells"]=reached.Count,["targets"]=points,["defects"]=defects,["passed"]=targets.Count>0&&defects.Count==0,["limitations"]="Ground floor path qualification; portal leaf opening and exterior approach require separate checks"};
 }
}
}
