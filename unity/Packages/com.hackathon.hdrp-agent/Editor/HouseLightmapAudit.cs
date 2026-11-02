using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using Unity.Collections;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace HdrpAgent.Editor {
internal static class HouseLightmapAudit {
 [MenuItem("Tools/HDRP Agent/House/Audit native architectural UVs")]
 internal static void Run(){
  if(CommandExecutor.Busy||Lightmapping.isRunning)throw new InvalidOperationException("Idle editor required");
  var rows=new JArray();
  foreach(string name in new[]{"WallIn_B_6x","WallIn_B_3x","WallOut_6x","Ceiling_6x3","Floor_6x3"}){
   string path="Assets/AtmosphericHouse/Prefabs/Building/"+name+".prefab";
   var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(path);
   foreach(var filter in prefab.GetComponentsInChildren<MeshFilter>(true)){
    var mesh=filter.sharedMesh;var channels=new JArray();
    using(var data=MeshUtility.AcquireReadOnlyMeshData(mesh)){
     for(int channel=0;channel<2;channel++){
      var attribute=channel==0?VertexAttribute.TexCoord0:VertexAttribute.TexCoord1;
      bool present=mesh.HasVertexAttribute(attribute);var row=new JObject{["channel"]=channel,["present"]=present};
      if(present){using(var uv=new NativeArray<Vector2>(mesh.vertexCount,Allocator.Temp)){
       data[0].GetUVs(channel,uv);float minX=float.PositiveInfinity,minY=minX,maxX=float.NegativeInfinity,maxY=maxX;
       foreach(var v in uv){minX=Mathf.Min(minX,v.x);minY=Mathf.Min(minY,v.y);maxX=Mathf.Max(maxX,v.x);maxY=Mathf.Max(maxY,v.y);}
       row["bounds"]=new JArray(minX,minY,maxX,maxY);
      }}channels.Add(row);
     }
    }
    rows.Add(new JObject{["prefab"]=path,["mesh"]=AssetDatabase.GetAssetPath(mesh),["vertices"]=mesh.vertexCount,["channels"]=channels});
   }
  }
  ReferenceWorkflow.Atomic(Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reports/native-architecture-uvs.json"),new JObject{["method"]="editor_read_only_mesh_data",["meshes"]=rows});
 }
}
}
