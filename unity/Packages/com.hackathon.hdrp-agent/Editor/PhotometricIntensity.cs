using System;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEditor;
using UnityEditor.SceneManagement;

namespace HdrpAgent.Editor {
// lightUnit selects the display unit; Unity's intensity remains in native units.
internal static class PhotometricIntensity {
 internal static LightUnit NativeUnit(Light light) {
  switch(light.type){
   case LightType.Directional:case LightType.Box:return LightUnit.Lux;
   case LightType.Rectangle:case LightType.Disc:case LightType.Tube:return LightUnit.Nits;
   default:return LightUnit.Candela;
  }
 }
 internal static void Set(Light light,float value,LightUnit unit) {
  if(float.IsNaN(value)||float.IsInfinity(value)||value<0)throw new InvalidDataException("Finite nonnegative light intensity required");
  light.lightUnit=unit;
  light.intensity=LightUnitUtils.ConvertIntensity(light,value,unit,NativeUnit(light));
 }
 [MenuItem("Tools/HDRP Agent/House/Test photometric units")]
 static void Verify(){
  var scene=EditorSceneManager.NewPreviewScene();
  try{
   var go=new GameObject("Photometric validation");UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(go,scene);var light=go.AddComponent<Light>();
   light.type=LightType.Point;Set(light,810,LightUnit.Lumen);
   float point=light.intensity;bool passed=Mathf.Abs(point-810/(4*Mathf.PI))<.001f;
   light.type=LightType.Spot;light.enableSpotReflector=false;Set(light,810,LightUnit.Lumen);float spot=light.intensity;passed&=Mathf.Abs(spot-point)<.001f;
   light.type=LightType.Directional;Set(light,250,LightUnit.Lux);passed&=Mathf.Abs(light.intensity-250)<.001f;
   string path=Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/reports/photometric-units.json");Directory.CreateDirectory(Path.GetDirectoryName(path));
   File.WriteAllText(path,new JObject{["passed"]=passed,["requested_lumens"]=810,["point_candela"]=point,["spot_without_reflector_candela"]=spot,["directional_lux"]=light.intensity}.ToString());
   if(!passed)throw new InvalidDataException("Photometric conversion failed");
  }finally{EditorSceneManager.ClosePreviewScene(scene);}
 }
}
}
