using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;
using UnityEditor;
using UnityEditor.SceneManagement;

namespace HdrpAgent.Editor {
public static class HouseLightingReference {
 const string Source="Assets/AtmosphericHouse/Scenes/House_clean_day.unity";
 static string PathOf(Transform t)=>t.parent==null?t.name:PathOf(t.parent)+"/"+t.name;
 static JArray V(Vector3 v)=>new JArray(v.x,v.y,v.z);
 static JObject Serialized(UnityEngine.Object o)=>o==null?null:JObject.Parse(EditorJsonUtility.ToJson(o));
 [MenuItem("Tools/HDRP Agent/House/Export clean day lighting data")]
 public static void Export(){
  if(CommandExecutor.Busy||HouseReferenceAudit.Running||Lightmapping.isRunning)throw new InvalidOperationException("Editor is busy");
  var active=SceneManager.GetActiveScene();bool dirty=active.isDirty;string hash=BridgeJson.Hash(File.ReadAllBytes(Source));
  var scene=EditorSceneManager.OpenPreviewScene(Source);
  try{
   var ts=scene.GetRootGameObjects().SelectMany(r=>r.GetComponentsInChildren<Transform>(true)).ToArray();
   var lights=new JArray();foreach(var l in ts.SelectMany(t=>t.GetComponents<Light>())){
    var hd=l.GetComponent<HDAdditionalLightData>();
    lights.Add(new JObject{["hierarchy"]=PathOf(l.transform),["active"]=l.isActiveAndEnabled,["type"]=l.type.ToString(),["unit"]=l.lightUnit.ToString(),["intensity"]=l.intensity,["position_m"]=V(l.transform.position),["rotation_deg"]=V(l.transform.eulerAngles),["range_m"]=l.range,["bake_mode"]=l.lightmapBakeType.ToString(),["color"]=new JArray(l.color.r,l.color.g,l.color.b),["temperature_k"]=l.colorTemperature,["use_temperature"]=l.useColorTemperature,["shadows"]=l.shadows.ToString(),["spot_angle"]=l.spotAngle,["inner_spot_angle"]=l.innerSpotAngle,["light_serialized"]=Serialized(l),["hdrp_serialized"]=Serialized(hd)});
   }
   var volumes=new JArray();foreach(var v in ts.SelectMany(t=>t.GetComponents<Volume>())){
    var p=v.sharedProfile;var components=new JArray();if(p)foreach(var component in p.components)if(component)components.Add(new JObject{["type"]=component.GetType().FullName,["active"]=component.active,["parameters"]=Serialized(component)});
    volumes.Add(new JObject{["hierarchy"]=PathOf(v.transform),["active"]=v.isActiveAndEnabled,["global"]=v.isGlobal,["priority"]=v.priority,["weight"]=v.weight,["profile_path"]=AssetDatabase.GetAssetPath(p),["components"]=components});
   }
   const string settingsPath="Assets/AtmosphericHouse/Scenes/House_clean_daySettings.lighting";
   var settings=AssetDatabase.LoadAssetAtPath<LightingSettings>(settingsPath);
   var materials=new JArray();foreach(var m in ts.SelectMany(t=>t.GetComponents<Renderer>()).SelectMany(r=>r.sharedMaterials).Where(m=>m).Distinct())materials.Add(new JObject{["path"]=AssetDatabase.GetAssetPath(m),["shader"]=m.shader?m.shader.name:null,["supported"]=m.shader&&m.shader.isSupported,["serialized"]=Serialized(m)});
   var probes=new JArray();foreach(var p in ts.SelectMany(t=>t.GetComponents<ReflectionProbe>()))probes.Add(new JObject{["hierarchy"]=PathOf(p.transform),["position_m"]=V(p.transform.position),["settings"]=Serialized(p)});
   var lightProbes=new JArray();foreach(var p in ts.SelectMany(t=>t.GetComponents<LightProbeGroup>()))lightProbes.Add(new JObject{["hierarchy"]=PathOf(p.transform),["count"]=p.probePositions.Length,["settings"]=Serialized(p)});
   var apv=new JArray();foreach(var p in ts.SelectMany(t=>t.GetComponents<ProbeVolume>()))apv.Add(new JObject{["hierarchy"]=PathOf(p.transform),["settings"]=Serialized(p)});
   var report=new JObject{["schema_version"]="house-lighting-reference.v1",["source_scene"]=Source,["source_sha256"]=hash,["unity_version"]=Application.unityVersion,["source_dependency_hash"]=AssetDatabase.GetAssetDependencyHash(Source).ToString(),["lights"]=lights,["volumes"]=volumes,["materials"]=materials,["reflection_probes"]=probes,["light_probe_groups"]=lightProbes,["adaptive_probe_volumes"]=apv,["lighting_settings_path"]=settingsPath,["lighting_settings"]=Serialized(settings),["source_unchanged"]=BridgeJson.Hash(File.ReadAllBytes(Source))==hash,["active_scene_unchanged"]=SceneManager.GetActiveScene()==active&&active.isDirty==dirty,["limitations"]="Native loaded reference values, not a new bake or proof of visual equivalence. Global LightmapSettings deliberately not read from the active user scene. Never transplant reference lightmaps to different geometry."};
   string dir=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/references/clean-day");Directory.CreateDirectory(dir);ReferenceWorkflow.Atomic(Path.Combine(dir,"lighting.json"),report);
  }finally{EditorSceneManager.ClosePreviewScene(scene);}
 }
}
}
