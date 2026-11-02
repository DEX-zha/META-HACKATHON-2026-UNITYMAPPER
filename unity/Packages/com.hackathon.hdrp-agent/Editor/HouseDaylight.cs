using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HdrpAgent.Editor {
// Reference photometry and environment, adapted to the candidate's actual apertures.
// Realtime inspection is explicitly not evidence of baked indirect illumination.
internal static class HouseDaylight {
 const string Source="Assets/AtmosphericHouse/Scenes/House_clean_day.unity";
 static JArray V(Vector3 p)=>new JArray(p.x,p.y,p.z);
 internal static JObject Apply(GameObject root,VolumeProfile profile){
  string sourceHash=BridgeJson.Hash(File.ReadAllBytes(Source));
  var reference=EditorSceneManager.OpenPreviewScene(Source);
  try{
   var lights=reference.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Light>(true)).ToArray();
   var sourceSun=lights.Single(l=>l.type==LightType.Directional&&l.isActiveAndEnabled);
   var sourceVolume=reference.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Volume>(true))
    .Single(v=>v.isActiveAndEnabled&&v.isGlobal&&v.sharedProfile&&v.sharedProfile.Has<PhysicallyBasedSky>());
   var components=new JArray();
   foreach(var component in sourceVolume.sharedProfile.components){
    if(!component||!component.active)continue;
    // Clone components, never attach mutable reference sub-assets to the candidate.
    var clone=UnityEngine.Object.Instantiate(component);clone.name=component.name;
    profile.components.Add(clone);components.Add(component.GetType().FullName);
   }
   MountWindowSources(root);
   var windows=new JArray();
   var candidateLights=root.GetComponentsInChildren<Light>(true);
   foreach(var light in candidateLights.Where(IsWindow)){
    var prefabLight=PrefabUtility.GetCorrespondingObjectFromSource(light);
    var templates=lights.Where(l=>l.isActiveAndEnabled&&l.type==light.type&&PrefabUtility.GetCorrespondingObjectFromSource(l)==prefabLight).OrderBy(l=>l.intensity).ToArray();
    var template=templates.Length==0?null:templates[templates.Length/2];
    if(!template)throw new InvalidDataException("No measured reference light matches window source: "+light.name);
    CopyPhotometry(template,light);
    // These lights already belong to connected window modules at their native sockets.
    light.enabled=true;light.gameObject.SetActive(true);light.lightmapBakeType=LightmapBakeType.Realtime;
    light.shadows=LightShadows.Soft;light.cullingMask=1<<30;
    PrefabUtility.RecordPrefabInstancePropertyModifications(light);
    windows.Add(new JObject{["name"]=light.name,["position_m"]=V(light.transform.position),["forward"]=V(light.transform.forward),["native_intensity"]=light.intensity,["native_unit"]=PhotometricIntensity.NativeUnit(light).ToString(),["reference_native_intensity"]=template.intensity,["reference_bake_mode"]=template.lightmapBakeType.ToString(),["mode"]="realtime_preview"});
   }
   // A daytime preview keeps the mounted practical fixtures but does not flood
   // the room with an unrelated ceiling grid or accidentally render spec-only lights.
   foreach(var light in candidateLights.Where(l=>!IsWindow(l))){
    light.enabled=false;PrefabUtility.RecordPrefabInstancePropertyModifications(light);
   }
   var sunObject=new GameObject("Reference daylight sun");sunObject.transform.SetParent(root.transform,false);
   var sun=sunObject.AddComponent<Light>();sunObject.AddComponent<HDAdditionalLightData>();CopyPhotometry(sourceSun,sun);
   sun.enabled=true;sun.lightmapBakeType=LightmapBakeType.Realtime;sun.shadows=LightShadows.Soft;sun.cullingMask=1<<30;
   var window=candidateLights.FirstOrDefault(l=>l.enabled&&l.type==LightType.Rectangle);
   Vector3 direction=sourceSun.transform.forward;
   if(window){
    var inward=window.transform.forward;inward.y=0;inward.Normalize();
    float down=Mathf.Abs(sourceSun.transform.forward.y);
    direction=inward*Mathf.Sqrt(Mathf.Max(0,1-down*down))+Vector3.down*down;
   }
   sunObject.transform.rotation=Quaternion.LookRotation(direction);
   if(BridgeJson.Hash(File.ReadAllBytes(Source))!=sourceHash)throw new InvalidDataException("Lighting reference changed while loading");
   return new JObject{["source_scene"]=Source,["source_sha256"]=sourceHash,["source_dependency_hash"]=AssetDatabase.GetAssetDependencyHash(Source).ToString(),["source_profile"]=AssetDatabase.GetAssetPath(sourceVolume.sharedProfile),["owned_volume_components"]=components,["window_sources"]=windows,["sun_native_intensity"]=sun.intensity,["sun_native_unit"]=PhotometricIntensity.NativeUnit(sun).ToString(),["sun_direction"]=V(direction),["mode"]="reference_daylight_realtime_preview",["bake_qualified"]=false,["limitations"]="Reference lightmaps are not copied; candidate indirect illumination and reflection probes still require a separate bake."};
  }finally{EditorSceneManager.ClosePreviewScene(reference);}
 }
 static bool IsWindow(Light light)=>light.type==LightType.Rectangle&&light.GetComponentsInParent<Transform>(true).Any(t=>t.name.StartsWith("AreaLight_window_",StringComparison.Ordinal));
 static void MountWindowSources(GameObject root){
  foreach(var socket in root.GetComponentsInChildren<MonoBehaviour>(true).Where(c=>c&&c.GetType().FullName=="FS_Atmo.SwapPrefab"&&c.name.StartsWith("WallIn_",StringComparison.Ordinal)).ToArray()){
   var data=new SerializedObject(socket);var names=data.FindProperty("additionals");var positions=data.FindProperty("additionalsPos");var rotations=data.FindProperty("additionalsRot");
   if(names==null||!names.isArray)continue;
   for(int i=0;i<names.arraySize;i++){
    string name=names.GetArrayElementAtIndex(i).stringValue;
    if(!name.StartsWith("AreaLight_window_",StringComparison.Ordinal))continue;
    if(socket.GetComponentsInChildren<Transform>(true).Any(t=>Path.GetFileNameWithoutExtension(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject))==name))continue;
    if(positions==null||rotations==null||positions.arraySize<=i||rotations.arraySize<=i)throw new InvalidDataException("Window light socket has incomplete transform data");
    var paths=AssetDatabase.FindAssets(name+" t:Prefab",new[]{"Assets/AtmosphericHouse/Prefabs"}).Select(AssetDatabase.GUIDToAssetPath).Where(p=>Path.GetFileNameWithoutExtension(p)==name).ToArray();
    if(paths.Length!=1)throw new InvalidDataException("Window light prefab must resolve uniquely: "+name);
    var go=ReferenceAssets.InstantiateAssembly(AssetDatabase.LoadAssetAtPath<GameObject>(paths[0]),null,root.scene);
    go.transform.SetParent(socket.transform,false);go.transform.localPosition=positions.GetArrayElementAtIndex(i).vector3Value;go.transform.localRotation=Quaternion.Euler(rotations.GetArrayElementAtIndex(i).vector3Value);go.transform.localScale=Vector3.one;
    PrefabUtility.RecordPrefabInstancePropertyModifications(go.transform);
   }
  }
 }
 static void CopyPhotometry(Light source,Light target){
  EditorUtility.CopySerialized(source,target);
  var sourceHD=source.GetComponent<HDAdditionalLightData>();
  var targetHD=target.GetComponent<HDAdditionalLightData>()??target.gameObject.AddComponent<HDAdditionalLightData>();
  if(sourceHD)EditorUtility.CopySerialized(sourceHD,targetHD);
 }
}
}
