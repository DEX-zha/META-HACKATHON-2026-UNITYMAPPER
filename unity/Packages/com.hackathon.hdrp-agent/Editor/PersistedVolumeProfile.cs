using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HdrpAgent.Editor {
// Volume components are separate ScriptableObjects; saving only the profile loses them.
internal static class PersistedVolumeProfile {
 internal static void Save(VolumeProfile profile) {
  string path=AssetDatabase.GetAssetPath(profile);
  if(string.IsNullOrEmpty(path))throw new InvalidOperationException("Create the profile asset before saving its components");
  foreach(var component in profile.components) {
   if(!component)throw new InvalidDataException("Volume profile contains a missing component");
   if(!AssetDatabase.Contains(component))AssetDatabase.AddObjectToAsset(component,profile);
   if(AssetDatabase.GetAssetPath(component)!=path)throw new InvalidDataException("Volume component belongs to another asset");
   EditorUtility.SetDirty(component);
  }
  EditorUtility.SetDirty(profile);AssetDatabase.SaveAssetIfDirty(profile);
 }
 [MenuItem("Tools/HDRP Agent/House/Test volume profile persistence")]
 static void VerifyPersistence() {
  const string folder="Assets/AgentWorkspace/ProfileValidation";
  Directory.CreateDirectory(folder);AssetDatabase.Refresh();
  string path=AssetDatabase.GenerateUniqueAssetPath(folder+"/Lighting.asset");
  var profile=ScriptableObject.CreateInstance<VolumeProfile>();AssetDatabase.CreateAsset(profile,path);
  profile.Add<Exposure>(true).fixedExposure.Override(6.25f);
  profile.Add<Tonemapping>(true).mode.Override(TonemappingMode.ACES);
  Save(profile);
  // Inspect the serialized file and re-import; live in-memory references alone hide this bug.
  string yaml=File.ReadAllText(path);
  foreach(var component in profile.components.ToArray())Resources.UnloadAsset(component);
  Resources.UnloadAsset(profile);
  AssetDatabase.ImportAsset(path,ImportAssetOptions.ForceUpdate);
  var loaded=AssetDatabase.LoadAssetAtPath<VolumeProfile>(path);
  bool passed=loaded.components.Count==2&&loaded.components.All(c=>c&&AssetDatabase.GetAssetPath(c)==path)&&AssetDatabase.LoadAllAssetsAtPath(path).OfType<VolumeComponent>().Count()==2
   &&loaded.TryGet<Exposure>(out var exposure)&&exposure.fixedExposure.overrideState&&Mathf.Approximately(exposure.fixedExposure.value,6.25f)
   &&loaded.TryGet<Tonemapping>(out var tone)&&tone.mode.value==TonemappingMode.ACES
   &&yaml.Contains("fixedExposure:")&&yaml.Contains("6.25")&&!yaml.Contains("- {fileID: 0}");
  string output=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reports/profile-persistence.json");
  Directory.CreateDirectory(Path.GetDirectoryName(output));
  File.WriteAllText(output,new JObject{["passed"]=passed,["asset_path"]=path,["component_count"]=loaded.components.Count,["component_paths"]=new JArray(loaded.components.Select(AssetDatabase.GetAssetPath)),["asset_objects"]=new JArray(AssetDatabase.LoadAllAssetsAtPath(path).Select(o=>o.name+":"+AssetDatabase.IsSubAsset(o))),["subassets"]=new JArray(loaded.components.Select(c=>c&&AssetDatabase.IsSubAsset(c))),["exposure"]=loaded.TryGet<Exposure>(out var e)?(float?)e.fixedExposure.value:null,["tone"]=loaded.TryGet<Tonemapping>(out var t)?t.mode.value.ToString():null,["serialized_components"]=yaml.Contains("fixedExposure:")&&!yaml.Contains("- {fileID: 0}"),["serialized_sha256"]=BridgeJson.Hash(File.ReadAllBytes(path))}.ToString());
  if(!passed)throw new InvalidDataException("Profile persistence validation failed");
 }
}
}
