using System.Collections.Generic;
using Unity.Collections;
using UnityEditor;
using UnityEngine;

namespace HdrpAgent.Editor {
// Read editor geometry without changing an asset's import flags or mesh data.
internal static class MeasuredMesh {
 internal static (Vector3[] vertices,int[] triangles) Read(Mesh mesh){
  using(var snapshots=MeshUtility.AcquireReadOnlyMeshData(mesh)){
   var data=snapshots[0];Vector3[] vertices;var triangles=new List<int>();
   using(var buffer=new NativeArray<Vector3>(data.vertexCount,Allocator.Temp)){data.GetVertices(buffer);vertices=buffer.ToArray();}
   for(int sub=0;sub<data.subMeshCount;sub++){
    var descriptor=data.GetSubMesh(sub);if(descriptor.topology!=MeshTopology.Triangles)continue;
    using(var indices=new NativeArray<int>(descriptor.indexCount,Allocator.Temp)){data.GetIndices(indices,sub,true);triangles.AddRange(indices.ToArray());}
   }
   return (vertices,triangles.ToArray());
  }
 }
}
}
