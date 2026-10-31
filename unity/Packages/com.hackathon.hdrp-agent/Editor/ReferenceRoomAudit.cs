using System;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace HdrpAgent.Editor
{
    // Native geometry is evidence about the candidate only, never source truth.
    public static class ReferenceRoomAudit
    {
        static JArray V(Vector3 v)=>new JArray(v.x,v.y,v.z);
        static JArray Ceilings(Transform root){
            var rows=new JArray();
            var generated=root.gameObject.scene.GetRootGameObjects().FirstOrDefault(o=>o.name==ReferenceRoomFinish.CeilingGroup);
            var transforms=root.GetComponentsInChildren<Transform>().AsEnumerable();if(generated!=null)transforms=transforms.Concat(generated.GetComponentsInChildren<Transform>());
            foreach(var t in transforms.Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)&&System.IO.Path.GetFileName(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)).StartsWith("Ceiling_"))){
                var path=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject);var surfaces=new JArray();
                foreach(var filter in t.GetComponentsInChildren<MeshFilter>()){
                    var r=filter.GetComponent<MeshRenderer>();if(r==null||!r.enabled||filter.sharedMesh==null)continue;
                    var row=new JObject{["renderer"]=r.name,["bounds_center_m"]=V(r.bounds.center),["bounds_size_m"]=V(r.bounds.size)};
                    try{var vertices=filter.sharedMesh.vertices;var indices=filter.sharedMesh.triangles;double down=0,up=0;
                        for(int i=0;i+2<indices.Length;i+=3){var a=filter.transform.TransformPoint(vertices[indices[i]]);var b=filter.transform.TransformPoint(vertices[indices[i+1]]);var c=filter.transform.TransformPoint(vertices[indices[i+2]]);var n=Vector3.Cross(b-a,c-a);if(n.normalized.y<-.5f)down+=n.magnitude*.5;else if(n.normalized.y>.5f)up+=n.magnitude*.5;}
                        row["downward_area_m2"]=down;row["upward_area_m2"]=up;
                    }catch(Exception e){row["geometry_unavailable"]=e.GetType().Name;}
                    surfaces.Add(row);
                }
                rows.Add(new JObject{["prefab"]=path,["connected"]=PrefabUtility.GetPrefabInstanceStatus(t.gameObject)==PrefabInstanceStatus.Connected,["position_m"]=V(t.position),["rotation_deg"]=V(t.eulerAngles),["scale"]=V(t.localScale),["derived"]=generated!=null&&t.IsChildOf(generated.transform),["surfaces"]=surfaces});
            }
            return rows;
        }
        public static JObject Inspect(Transform root,Vector3 observer)
        {
            var walls=new JArray();
            if(root==null)return new JObject{["walls"]=walls};
            foreach(Transform obj in root)
            {
                string path=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(obj.gameObject);
                if(!System.IO.Path.GetFileName(path).StartsWith("WallOut_",StringComparison.Ordinal)&&obj.Find("Connected structural modules")==null)continue;
                var surfaces=new JArray();
                foreach(var filter in obj.GetComponentsInChildren<MeshFilter>())
                {
                    var mesh=filter.sharedMesh;var renderer=filter.GetComponent<MeshRenderer>();
                    if(mesh==null||renderer==null||!renderer.enabled)continue;
                    string prefab=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(filter.gameObject);
                    var materials=new JArray(renderer.sharedMaterials.Select(m=>m==null?new JObject():new JObject{["name"]=m.name,["surface_type"]=m.HasProperty("_SurfaceType")?(float?)m.GetFloat("_SurfaceType"):null,["cull_mode"]=m.HasProperty("_CullMode")?(float?)m.GetFloat("_CullMode"):null}));
                    var row=new JObject{["renderer"]=filter.name,["prefab"]=prefab,["bounds_center_m"]=V(renderer.bounds.center),["bounds_size_m"]=V(renderer.bounds.size),["materials"]=materials};
                    // Readable imported meshes only. Do not mutate import settings.
                    try
                    {
                        var vertices=mesh.vertices;var triangles=mesh.triangles;double front=0,back=0;Vector3 summed=Vector3.zero;
                        for(int i=0;i+2<triangles.Length;i+=3)
                        {
                            var a=filter.transform.TransformPoint(vertices[triangles[i]]);var b=filter.transform.TransformPoint(vertices[triangles[i+1]]);var c=filter.transform.TransformPoint(vertices[triangles[i+2]]);
                            var normal=Vector3.Cross(b-a,c-a);float area=normal.magnitude*.5f;if(area<1e-8)continue;
                            if(Mathf.Abs(normal.normalized.y)>.5f)continue; // exclude caps/floor-like surfaces
                            if(Vector3.Dot(normal,observer-(a+b+c)/3)>0)front+=area;else back+=area;
                            summed+=normal;
                        }
                        row["vertical_front_area_m2"]=front;row["vertical_back_area_m2"]=back;row["area_weighted_normal"]=V(summed.normalized);
                        row["front_fraction_from_observer"]=front+back>0?(double?)(front/(front+back)):null;
                    }
                    catch(Exception e){row["geometry_unavailable"]=e.GetType().Name;}
                    surfaces.Add(row);
                }
                walls.Add(new JObject{["object_key"]=obj.name,["prefab"]=path,["position_m"]=V(obj.position),["rotation_deg"]=V(obj.eulerAngles),["local_plus_z_world"]=V(obj.forward),["outward_axis_points_to_observer"]=Vector3.Dot(obj.forward,observer-obj.position)>0,["surfaces"]=surfaces});
            }
            return new JObject{["observer_m"]=V(observer),["walls"]=walls,["ceilings"]=Ceilings(root),["limitation"]="Triangle winding and materials describe candidate surfaces; openings, occlusion and visibility need image inspection. Local +Z is the AtmosphericHouse assembly convention, not measured visibility."};
        }
        public static JArray Project(Transform root,Camera camera)
        {
            var result=new JArray();if(root==null)return result;
            foreach(Transform obj in root)
            {
                var rs=obj.GetComponentsInChildren<Renderer>().Where(r=>r.enabled).ToArray();if(rs.Length==0)continue;
                var b=rs[0].bounds;foreach(var r in rs.Skip(1))b.Encapsulate(r.bounds);
                var lo=new Vector2(float.PositiveInfinity,float.PositiveInfinity);var hi=new Vector2(float.NegativeInfinity,float.NegativeInfinity);bool behind=false;
                for(int i=0;i<8;i++){var p=camera.WorldToViewportPoint(b.center+Vector3.Scale(b.extents,new Vector3((i&1)==0?-1:1,(i&2)==0?-1:1,(i&4)==0?-1:1)));if(p.z<=camera.nearClipPlane){behind=true;break;}lo=Vector2.Min(lo,new Vector2(p.x,1-p.y));hi=Vector2.Max(hi,new Vector2(p.x,1-p.y));}
                if(behind||hi.x<=0||hi.y<=0||lo.x>=1||lo.y>=1)continue;
                result.Add(new JObject{["target_id"]=obj.name,["bbox_xyxy"]=new JArray(Mathf.Clamp01(lo.x),Mathf.Clamp01(lo.y),Mathf.Clamp01(hi.x),Mathf.Clamp01(hi.y)),["bounds_center_m"]=V(b.center),["bounds_size_m"]=V(b.size),["association"]="projected AABB; occlusion unverified"});
            }
            return result;
        }
    }
}
