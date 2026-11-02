using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using UnityEngine.Rendering;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace HdrpAgent.Editor {
// Preserve visible prefab materials; only candidate-owned GI sidedness changes.
internal static class HouseGiMaterials {
 [MenuItem("Tools/HDRP Agent/House/Audit candidate GI materials")]
 internal static void Audit(){
  string workspace=BridgeClient.ResolveWorkspace();var request=JObject.Parse(File.ReadAllText(Path.Combine(workspace,".hdrp-agent/reopen-audit/request.json")));
  string scene=(string)request["scene_path"];if(!scene.StartsWith("Assets/AgentWorkspace/HouseRuns/",StringComparison.Ordinal)||scene.Contains(".."))throw new InvalidDataException("Candidate required");
  var rows=new JArray();var inputs=JArray.Parse(File.ReadAllText(Path.Combine(Path.GetDirectoryName(scene),"MaterialGI.json")));
  foreach(JObject input in inputs){
   var source=AssetDatabase.LoadAssetAtPath<Material>((string)input["source"]);var candidate=AssetDatabase.LoadAssetAtPath<Material>((string)input["candidate"]);var differences=new JArray();
   if(source.shader!=candidate.shader)differences.Add("shader");if(source.renderQueue!=candidate.renderQueue)differences.Add("renderQueue");
   if(!source.shaderKeywords.OrderBy(k=>k).SequenceEqual(candidate.shaderKeywords.OrderBy(k=>k)))differences.Add("shaderKeywords");
   for(int i=0;i<source.shader.GetPropertyCount();i++){
    string name=source.shader.GetPropertyName(i);if(name=="_DoubleSidedGIMode")continue;
    if(Value(source,name,source.shader.GetPropertyType(i))!=Value(candidate,name,source.shader.GetPropertyType(i)))differences.Add(name);
   }
   rows.Add(new JObject{["source"]=input["source"],["candidate"]=input["candidate"],["source_unchanged"]=BridgeJson.Hash(File.ReadAllBytes((string)input["source"]))==(string)input["source_sha256"],["render_property_differences"]=differences,["double_sided_gi"]=candidate.doubleSidedGI});
  }
  ReferenceWorkflow.Atomic(Path.Combine(workspace,".hdrp-agent/reports/candidate-gi-material-audit.json"),new JObject{["scene"]=scene,["materials"]=rows});
 }
 static string Value(Material material,string name,ShaderPropertyType type){
  switch(type){
   case ShaderPropertyType.Color:return material.GetColor(name).ToString("R");
   case ShaderPropertyType.Vector:return material.GetVector(name).ToString("R");
   case ShaderPropertyType.Texture:return material.GetTexture(name)?.GetInstanceID()+":"+material.GetTextureScale(name).ToString("R")+":"+material.GetTextureOffset(name).ToString("R");
   case ShaderPropertyType.Int:return material.GetInteger(name).ToString();
   default:return material.GetFloat(name).ToString("R",System.Globalization.CultureInfo.InvariantCulture);
  }
 }
 internal static JArray Apply(GameObject root,string folder){
  if(!folder.StartsWith("Assets/AgentWorkspace/HouseRuns/",StringComparison.Ordinal)||folder.Contains(".."))throw new InvalidOperationException("Candidate-owned folder required");
  string destination=folder+"/GI-Materials";if(!AssetDatabase.IsValidFolder(destination))AssetDatabase.CreateFolder(folder,"GI-Materials");
  var copies=new Dictionary<Material,Material>();var receipts=new JArray();
  foreach(var renderer in root.GetComponentsInChildren<MeshRenderer>()){
   var materials=renderer.sharedMaterials;bool changed=false;
   for(int i=0;i<materials.Length;i++){
    var original=materials[i];
    if(!original||original.doubleSidedGI||!original.HasProperty("_DoubleSidedGIMode")||(original.HasProperty("_SurfaceType")&&original.GetFloat("_SurfaceType")!=0))continue;
    if(!copies.TryGetValue(original,out var owned)){
     string source=AssetDatabase.GetAssetPath(original);if(string.IsNullOrEmpty(source)||!File.Exists(source))throw new InvalidDataException("Source material provenance unavailable");
     string hash=BridgeJson.Hash(File.ReadAllBytes(source));owned=UnityEngine.Object.Instantiate(original);owned.name=original.name+" Candidate GI";
     owned.SetFloat("_DoubleSidedGIMode",1);owned.doubleSidedGI=true;
     string path=AssetDatabase.GenerateUniqueAssetPath(destination+"/"+AssetDatabase.AssetPathToGUID(source)+".mat");AssetDatabase.CreateAsset(owned,path);AssetDatabase.SaveAssetIfDirty(owned);
     if(hash!=BridgeJson.Hash(File.ReadAllBytes(source)))throw new InvalidDataException("Source material changed");
     receipts.Add(new JObject{["source"]=source,["source_sha256"]=hash,["candidate"]=path,["candidate_sha256"]=BridgeJson.Hash(File.ReadAllBytes(path)),["original_double_sided_gi"]=original.doubleSidedGI,["candidate_double_sided_gi"]=owned.doubleSidedGI,["render_culling_unchanged"]=true});copies.Add(original,owned);
    }
    materials[i]=owned;changed=true;
   }
   if(changed){renderer.sharedMaterials=materials;PrefabUtility.RecordPrefabInstancePropertyModifications(renderer);}
  }
  return receipts;
 }
}
}
