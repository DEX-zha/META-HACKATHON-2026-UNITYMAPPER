using System;
using System.Linq;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.Rendering;
using UnityEditor;

namespace HdrpAgent.Editor {
// A ceiling mounting recipe: whole prefabs, native scale, measured upper face.
internal static class HouseLighting {
 internal static JArray Build(GameObject root,JObject building){
  const string path="Assets/AtmosphericHouse/Prefabs/Props/Lamps/Lamp_ceiling_round.prefab";
  var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(path);
  if(!prefab)throw new InvalidDataException("Ceiling luminaire prefab missing: "+path);
  var receipts=new JArray();
  foreach(JObject room in building["rooms"]){
   var poly=(JArray)room["polygon"];float x0=poly.Min(p=>(float)p[0]),x1=poly.Max(p=>(float)p[0]),z0=poly.Min(p=>(float)p[1]),z1=poly.Max(p=>(float)p[1]);
   int nx=Mathf.Max(1,Mathf.CeilToInt((x1-x0)/3)),nz=Mathf.Max(1,Mathf.CeilToInt((z1-z0)/3));
   float lumens=Mathf.Clamp((x1-x0)*(z1-z0)*90/(nx*nz),400,1600);
   for(int x=0;x<nx;x++)for(int z=0;z<nz;z++){
    var go=(GameObject)PrefabUtility.InstantiatePrefab(prefab,root.scene);go.name="Luminaire "+room["id"]+" "+x+"-"+z;go.transform.SetParent(root.transform,false);go.transform.localScale=Vector3.one;
    var renderers=go.GetComponentsInChildren<MeshRenderer>().Where(r=>r.enabled).ToArray();
    if(renderers.Length==0)throw new InvalidDataException("Luminaire has no visible mesh");
    var bounds=renderers[0].bounds;foreach(var r in renderers.Skip(1))bounds.Encapsulate(r.bounds);
    go.transform.position+=new Vector3(x0+(x+.5f)*(x1-x0)/nx-bounds.center.x,2.8f-bounds.max.y,z0+(z+.5f)*(z1-z0)/nz-bounds.center.z);
    PrefabUtility.RecordPrefabInstancePropertyModifications(go.transform);
    var lights=go.GetComponentsInChildren<Light>(true);
    if(lights.Length==0)throw new InvalidDataException("Luminaire has no light source");
    foreach(var light in lights){
     light.gameObject.SetActive(true);light.enabled=true;
     if(!light.GetComponent<HDAdditionalLightData>())light.gameObject.AddComponent<HDAdditionalLightData>();
     light.lightUnit=UnityEngine.Rendering.LightUnit.Lumen;light.intensity=lumens/lights.Length;light.range=5;light.shadows=LightShadows.Soft;light.lightmapBakeType=LightmapBakeType.Realtime;
     light.useColorTemperature=true;light.colorTemperature=3500;light.color=Color.white;light.cullingMask=1<<30;
     if(light.type==LightType.Spot){light.spotAngle=110;light.transform.rotation=Quaternion.LookRotation(Vector3.down,Vector3.forward);PrefabUtility.RecordPrefabInstancePropertyModifications(light.transform);}
     PrefabUtility.RecordPrefabInstancePropertyModifications(light);
    }
    receipts.Add(new JObject{["room_id"]=room["id"],["prefab_path"]=path,["connected"]=PrefabUtility.GetPrefabInstanceStatus(go)==PrefabInstanceStatus.Connected,["native_scale"]=true,["mount_height_m"]=2.8f,["lumens"]=lumens,["temperature_k"]=3500,["source_count"]=lights.Length,["mode"]="realtime_ceiling",["bake_qualified"]=false});
   }
  }
  return receipts;
 }
}
}
