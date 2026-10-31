using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
namespace HdrpAgent.Editor
{
    public static class ReferencePoseGeometry
    {
        public static JArray Export(JArray ids,JArray catalogue){
            if(ids.Count>20||ids.Distinct().Count()!=ids.Count)throw new InvalidDataException("At most twenty distinct candidate meshes");var result=new JArray();
            foreach(var id in ids){
                var asset=catalogue.OfType<JObject>().Single(a=>(string)a["asset_id"]==(string)id);var path=(string)asset["path"];
                if(AssetDatabase.GetAssetDependencyHash(path).ToString()!=(string)asset["dependency_hash"])throw new InvalidDataException("Pose geometry dependency changed");
                var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(path);var meshes=new JArray();int count=0;
                foreach(var filter in prefab.GetComponentsInChildren<MeshFilter>()){
                    var mesh=filter.sharedMesh;var renderer=filter.GetComponent<MeshRenderer>();if(mesh==null||renderer==null||!renderer.enabled)continue;
                    count+=mesh.vertexCount;if(count>100000)throw new InvalidDataException("Pose geometry exceeds vertex bound");
                    var vertices=mesh.vertices.Select(v=>ReferenceAssets.Vec(prefab.transform.InverseTransformPoint(filter.transform.TransformPoint(v)))).ToArray();
                    meshes.Add(new JObject{["vertices"]=JArray.FromObject(vertices),["triangles"]=JArray.FromObject(mesh.triangles)});
                }
                result.Add(new JObject{["asset_id"]=id.DeepClone(),["dependency_hash"]=asset["dependency_hash"].DeepClone(),["meshes"]=meshes});
            }
            return result;
        }
    }
}
