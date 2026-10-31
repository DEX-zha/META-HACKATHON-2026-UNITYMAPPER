using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace HdrpAgent.Editor
{
    // Candidate meshes only. Never reads transforms or geometry from the reference scene.
    public static class ReferenceContacts
    {
        public static void Validate(JArray supports,JObject plan){
            if(supports==null)throw new InvalidDataException("Support evidence required");
            var keys=new HashSet<string>(((JArray)plan["objects"]).Select(o=>(string)o["key"]));var edges=new Dictionary<string,string>();
            foreach(JObject item in supports){
                if(item.Property("contact_policy")==null)BridgeJson.Closed(item,"object_key","support_key");
                else{
                    BridgeJson.Closed(item,"object_key","support_key","contact_policy","offset_m","evidence_hashes");
                    var policy=(string)item["contact_policy"];
                    if(!new[]{"required_contact","offset_evidenced","unresolved"}.Contains(policy))throw new InvalidDataException("Unknown contact policy");
                    ReferenceSceneBuilder.Number(item["offset_m"],0,.25f);
                    var hashes=item["evidence_hashes"] as JArray;if(hashes==null||hashes.Count>12||hashes.Select(h=>(string)h).Distinct().Count()!=hashes.Count||hashes.Any(h=>h.Type!=JTokenType.String||!System.Text.RegularExpressions.Regex.IsMatch((string)h,"^[a-f0-9]{64}$")))throw new InvalidDataException("Invalid contact evidence");
                    if(policy=="offset_evidenced"&&hashes.Count<2)throw new InvalidDataException("Offset requires multiple visual evidence hashes");
                    if(policy!="offset_evidenced"&&(float)item["offset_m"]!=0)throw new InvalidDataException("Offset without evidence");
                }
                var key=(string)item["object_key"];var parent=(string)item["support_key"];
                if(!keys.Contains(key)||edges.ContainsKey(key)||parent!=null&&(!keys.Contains(parent)||key==parent))throw new InvalidDataException("Invalid support graph");edges.Add(key,parent);
            }
            foreach(var key in edges.Keys){var seen=new HashSet<string>();string next=key;while(next!=null&&edges.ContainsKey(next)){if(!seen.Add(next))throw new InvalidDataException("Cyclic support graph");next=edges[next];}}
        }
        static MeshFilter[] Meshes(GameObject go)=>go.GetComponentsInChildren<MeshFilter>().Where(f=>f.sharedMesh!=null&&f.GetComponent<MeshRenderer>()?.enabled==true).ToArray();
        static Vector3[] Points(GameObject go)=>Meshes(go).SelectMany(f=>f.sharedMesh.vertices.Select(v=>f.transform.TransformPoint(v))).ToArray();
        static Bounds BoundsOf(GameObject go){var points=Points(go);if(points.Length==0)throw new InvalidDataException("Missing candidate contact geometry");var b=new Bounds(points[0],Vector3.zero);foreach(var p in points)b.Encapsulate(p);return b;}
        public static JObject Resolve(GameObject root,JObject plan,JArray supports){
            Validate(supports,plan);var objects=root.transform.Cast<Transform>().ToDictionary(t=>t.name,t=>t.gameObject);
            var edges=supports.OfType<JObject>().ToDictionary(o=>(string)o["object_key"],o=>(string)o["support_key"]);var inferred=new HashSet<string>();var rows=new JArray();var done=new HashSet<string>();
            var policies=supports.OfType<JObject>().ToDictionary(o=>(string)o["object_key"],o=>o);
            // Only infer a missing floor for a tall object over one unambiguous,
            // broad, thin candidate platform. Inference remains explicit evidence.
            foreach(var key in edges.Keys.ToArray()){
                if(edges[key]!=null||(string)policies[key]["contact_policy"]=="unresolved")continue;var child=BoundsOf(objects[key]);if(child.size.y<.5f)continue;
                var floors=objects.Where(pair=>pair.Key!=key&&(!edges.ContainsKey(pair.Key)||edges[pair.Key]==null)).Where(pair=>{
                    var b=BoundsOf(pair.Value);return b.size.y<.25f&&b.size.x>1.5f&&b.size.z>1.5f&&child.min.x>=b.min.x&&child.max.x<=b.max.x&&child.min.z>=b.min.z&&child.max.z<=b.max.z&&Mathf.Abs(child.min.y-b.max.y)<.5f;
                }).Select(pair=>pair.Key).ToArray();
                // Prefer an observed platform over an additional surrounding ground.
                var observed=floors.Where(k=>edges.ContainsKey(k)).ToArray();if(observed.Length==1)floors=observed;
                if(floors.Length==1){edges[key]=floors[0];inferred.Add(key);}
            }
            Action<string> settle=null;settle=key=>{
                if(done.Contains(key))return;var parent=edges.ContainsKey(key)?edges[key]:null;if(parent!=null)settle(parent);done.Add(key);if(parent==null){
                    if(policies.ContainsKey(key)&&(string)policies[key]["contact_policy"]=="unresolved")rows.Add(new JObject{["object_key"]=key,["support_key"]=null,["status"]="unresolved",["reason"]="unknown_support_preserved_without_mutation"});
                    return;
                }
                var child=objects[key];var surface=objects[parent];var row=new JObject{["object_key"]=key,["support_key"]=parent,["evidence"]=inferred.Contains(key)?"inferred_candidate_floor":"reference_analysis",["status"]="unresolved"};rows.Add(row);
                var policy=policies.ContainsKey(key)?policies[key]:null;var mode=(string)policy?["contact_policy"]??"required_contact";
                if(mode=="unresolved"){row["reason"]="ambiguous_contact_preserved_without_mutation";return;}
                float targetGap=mode=="offset_evidenced"?(float)policy["offset_m"]:.001f;
                if(mode=="offset_evidenced"){row["contact_policy"]=mode;row["evidence_hashes"]=policy["evidence_hashes"].DeepClone();row["target_offset_m"]=targetGap;}
                var colliders=new List<MeshCollider>();
                try{
                    var all=Points(child);var bottom=all.Min(p=>p.y);
                    var points=all.Where(p=>p.y<=bottom+.015f).GroupBy(p=>Mathf.RoundToInt(p.x*1000)+":"+Mathf.RoundToInt(p.z*1000)).Select(g=>g.OrderBy(p=>p.y).First()).ToArray();
                    if(points.Length>4096)throw new InvalidDataException("Contact mesh exceeds sampling bound");
                    foreach(var f in Meshes(surface)){var collider=f.gameObject.AddComponent<MeshCollider>();colliders.Add(collider);collider.sharedMesh=f.sharedMesh;collider.convex=false;}
                    Physics.SyncTransforms();var bounds=BoundsOf(surface);var distances=new List<float>();
                    foreach(var point in points){
                        float top=float.NegativeInfinity;var ray=new Ray(new Vector3(point.x,bounds.max.y+.1f,point.z),Vector3.down);
                        foreach(var collider in colliders){RaycastHit hit;if(collider.Raycast(ray,out hit,bounds.size.y+.2f)&&hit.normal.y>.25f)top=Mathf.Max(top,hit.point.y);}
                        if(!float.IsNegativeInfinity(top))distances.Add(top-point.y);
                    }
                    float coverage=points.Length==0?0:(float)distances.Count/points.Length;row["sample_count"]=points.Length;row["supported_fraction"]=coverage;
                    if(coverage<.5f){row["reason"]="insufficient_surface_below_footprint";return;}
                    // Highest required displacement prevents a low foot penetrating
                    // the support. Uneven terrain is reported instead of certified.
                    float shift=distances.Max()+targetGap;row["previous_gap_m"]=-distances.Max();row["required_shift_y_m"]=shift;
                    if(Mathf.Abs(shift)>.5f){row["reason"]="correction_exceeds_half_metre";return;}
                    if(distances.Max()-distances.Min()>.03f){row["reason"]="uneven_support_requires_pose_adjustment";return;}
                    child.transform.position+=Vector3.up*shift;
                    ((JArray)plan["objects"]).OfType<JObject>().Single(o=>(string)o["key"]==key)["position_m"]=JArray.FromObject(ReferenceAssets.Vec(child.transform.position));
                    row["residual_gap_m"]=targetGap;row["max_foot_gap_m"]=shift-distances.Min();row["status"]=mode=="offset_evidenced"?"offset_evidenced":"contact";
                }catch(Exception e){row["reason"]=e.GetType().Name+": "+e.Message;}
                finally{foreach(var c in colliders)UnityEngine.Object.DestroyImmediate(c);}
            };
            foreach(var key in edges.Keys)settle(key);
            return new JObject{["passed"]=rows.All(r=>(string)r["status"]=="contact"||(string)r["status"]=="offset_evidenced"),["checks"]=rows,["scope"]="Inferred support contacts only; not a full collision, stability or fidelity certificate"};
        }
    }
}
