using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using Unity.Collections;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
// Read-only export from HouseReopenAudit's owned, isolated candidate.
internal static class HouseSeamGeometry {
 static JArray A(Vector3 v)=>new JArray(v.x,v.y,v.z);
 internal static void Export(Scene scene,string directory){
  if(!scene.IsValid()||!scene.isLoaded||!scene.path.StartsWith("Assets/AgentWorkspace/HouseRuns/",StringComparison.Ordinal))throw new InvalidOperationException("Loaded owned candidate required");
  var rows=new JArray();
  foreach(var filter in scene.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<MeshFilter>())){
   var renderer=filter.GetComponent<MeshRenderer>();var mesh=filter.sharedMesh;
   if(renderer==null||!renderer.enabled||!renderer.gameObject.activeInHierarchy||mesh==null)continue;
   string prefab=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(filter.gameObject);
   if(!prefab.StartsWith("Assets/AtmosphericHouse/Prefabs/Building/",StringComparison.Ordinal))continue;
   using(var snapshots=MeshUtility.AcquireReadOnlyMeshData(mesh)){
    var data=snapshots[0];Vector3[] vertices;
    using(var buffer=new NativeArray<Vector3>(data.vertexCount,Allocator.Temp)){data.GetVertices(buffer);vertices=buffer.ToArray();}
    for(int sub=0;sub<data.subMeshCount;sub++){
     var descriptor=data.GetSubMesh(sub);if(descriptor.topology!=MeshTopology.Triangles)continue;
     var triangles=new JArray();
     using(var indices=new NativeArray<int>(descriptor.indexCount,Allocator.Temp)){
      data.GetIndices(indices,sub,true);
      for(int i=0;i<indices.Length;i+=3)triangles.Add(new JArray(A(filter.transform.TransformPoint(vertices[indices[i]])),A(filter.transform.TransformPoint(vertices[indices[i+1]])),A(filter.transform.TransformPoint(vertices[indices[i+2]]))));
     }
     var material=sub<renderer.sharedMaterials.Length?renderer.sharedMaterials[sub]:null;
     // Alpha-clipped or unknown shaders cannot certify opaque triangle coverage.
     JToken opaque=JValue.CreateNull();
     if(material&&material.HasProperty("_SurfaceType")){
      bool clipped=material.HasProperty("_AlphaCutoffEnable")&&material.GetFloat("_AlphaCutoffEnable")!=0;
      if(!clipped)opaque=new JValue(material.GetFloat("_SurfaceType")==0);
     }
     var row=new JObject{["renderer_id"]=GlobalObjectId.GetGlobalObjectIdSlow(renderer).ToString()+"/submesh-"+sub,["prefab"]=prefab,["prefab_dependency_hash"]=AssetDatabase.GetAssetDependencyHash(prefab).ToString(),["mesh"]=AssetDatabase.GetAssetPath(mesh),["material"]=material?AssetDatabase.GetAssetPath(material):null,["opaque"]=opaque,["casts_shadows"]=renderer.shadowCastingMode!=ShadowCastingMode.Off,["shadow_casting_mode"]=renderer.shadowCastingMode.ToString(),["triangles_world"]=triangles};
     if(material){row["double_sided_gi"]=material.doubleSidedGI;foreach(string property in new[]{"_SurfaceType","_CullMode","_CullModeForward","_DoubleSidedEnable","_DoubleSidedGIMode"})if(material.HasProperty(property))row[property]=material.GetFloat(property);}
     rows.Add(row);
    }
   }
  }
  ReferenceWorkflow.Atomic(Path.Combine(directory,"seam-geometry.json"),new JObject{["method"]="editor_read_only_submesh_triangles_world_metres",["scene_path"]=scene.path,["scene_sha256"]=BridgeJson.Hash(File.ReadAllBytes(scene.path)),["meshes"]=rows,["lighting_qualified"]=false});
 }
}
}
