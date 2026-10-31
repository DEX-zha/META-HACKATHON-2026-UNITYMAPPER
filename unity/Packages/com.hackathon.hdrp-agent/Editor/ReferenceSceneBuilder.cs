using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    public static class ReferenceSceneBuilder
    {
        public static JObject LastRoomFinish {get;private set;}
        public static float Number(JToken token,float min,float max){
            if(token==null||(token.Type!=JTokenType.Float&&token.Type!=JTokenType.Integer))throw new InvalidDataException("Finite numeric property required");
            var value=(double)token;if(double.IsNaN(value)||double.IsInfinity(value)||value<min||value>max)throw new InvalidDataException("Reconstruction value outside bounds");return(float)value;
        }
        public static Vector3 Vector(JToken token,float min,float max){var v=token as JArray;if(v==null||v.Count!=3)throw new InvalidDataException("Three coordinates required");return new Vector3(Number(v[0],min,max),Number(v[1],min,max),Number(v[2],min,max));}
        static Color Color3(JToken token){var v=Vector(token,0,1);return new Color(v.x,v.y,v.z,1);}
        public static void Validate(JObject plan,JArray catalogue){
            BridgeJson.Closed(plan,"objects","lights","estimated_views","exposure_ev","sky_color_rgb","fog_mean_free_path_m","notes");
            var objects=plan["objects"] as JArray;if(objects==null||objects.Count<1||objects.Count>20)throw new InvalidDataException("One to twenty objects required");
            var ids=new HashSet<string>();
            foreach(JObject item in objects){
                BridgeJson.Closed(item,"key","asset_id","primitive","position_m","rotation_deg","scale","base_color_rgba");
                var key=(string)item["key"];if(string.IsNullOrWhiteSpace(key)||key.Length>128||!ids.Add(key))throw new InvalidDataException("Unique object keys required");
                Vector(item["position_m"],-100,100);Vector(item["rotation_deg"],-360,360);Vector(item["scale"],.01f,100);
                bool asset=item["asset_id"].Type!=JTokenType.Null,primitive=item["primitive"].Type!=JTokenType.Null;
                if(asset==primitive)throw new InvalidDataException("Exactly one asset or primitive required");
                if(primitive&&!new[]{"cube","sphere","plane","cylinder"}.Contains((string)item["primitive"]))throw new InvalidDataException("Unknown primitive");
                if(asset){
                    var entry=catalogue.OfType<JObject>().SingleOrDefault(a=>(string)a["asset_id"]==(string)item["asset_id"])??throw new InvalidDataException("Unknown catalogue asset");
                    var path=(string)entry["path"];
                    if(!path.StartsWith("Assets/AtmosphericHouse/Prefabs/",StringComparison.Ordinal)||AssetDatabase.AssetPathToGUID(path)!=(string)entry["asset_guid"]||AssetDatabase.GetAssetDependencyHash(path).ToString()!=(string)entry["dependency_hash"])throw new InvalidDataException("Catalogue dependency changed");
                }
                if(item["base_color_rgba"].Type!=JTokenType.Null){var c=item["base_color_rgba"] as JArray;if(c==null||c.Count!=4)throw new InvalidDataException("RGBA required");foreach(var channel in c)Number(channel,0,1);}
            }
            Number(plan["exposure_ev"],-20,30);Color3(plan["sky_color_rgb"]);if(plan["fog_mean_free_path_m"].Type!=JTokenType.Null)Number(plan["fog_mean_free_path_m"],1,1000);
            var lights=plan["lights"] as JArray;if(lights==null||lights.Count>4)throw new InvalidDataException("At most four lights");
            foreach(JObject item in lights){
                BridgeJson.Closed(item,"type","position_m","rotation_deg","intensity","color_rgb","spot_angle_deg");
                if(!new[]{"point","spot","directional"}.Contains((string)item["type"]))throw new InvalidDataException("Unknown light type");
                Vector(item["position_m"],-100,100);Vector(item["rotation_deg"],-360,360);Number(item["intensity"],0,(string)item["type"]=="directional"?150000:100000);Color3(item["color_rgb"]);Number(item["spot_angle_deg"],1,179);
            }
        }
        public static JObject LastContacts { get; private set; }
        public static string Build(JObject plan,JArray catalogue,string scope,JObject inspection,JArray supports=null,JObject captureProtocol=null,string interiorStyle="B",JObject architecture=null){
            if(captureProtocol!=null)ReferenceFidelity.ValidateCaptureProtocol(captureProtocol);
            Validate(plan,catalogue);
            if(architecture!=null&&((JArray)plan["objects"]).Any(o=>(Vector(o["scale"],.01f,100)-Vector3.one).magnitude>.001f))throw new InvalidDataException("Native assembly forbids rescaling any prefab");
            if(supports!=null)ReferenceContacts.Validate(supports,plan);LastContacts=null;var folder=SnapshotStore.Root(scope);
            if(Directory.Exists(folder))throw new InvalidOperationException("Construction scope already exists; no replay");
            if(SceneManager.GetActiveScene().isDirty||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)throw new InvalidOperationException("Saved idle scene required");
            Directory.CreateDirectory(folder+"/Resources");AssetDatabase.Refresh();
            var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
            var root=new GameObject("Reconstruction");
            foreach(JObject item in (JArray)plan["objects"]){
                GameObject go;
                if(item["asset_id"].Type!=JTokenType.Null){
                    var entry=catalogue.OfType<JObject>().Single(a=>(string)a["asset_id"]==(string)item["asset_id"]);
                    go=ReferenceAssets.InstantiateAssembly(AssetDatabase.LoadAssetAtPath<GameObject>((string)entry["path"]),entry["assembly_companions"] as JArray);
                }else go=GameObject.CreatePrimitive((PrimitiveType)Enum.Parse(typeof(PrimitiveType),(string)item["primitive"],true));
                go.name=(string)item["key"];go.transform.SetParent(root.transform,false);go.transform.position=Vector(item["position_m"],-100,100);go.transform.eulerAngles=Vector(item["rotation_deg"],-360,360);go.transform.localScale=Vector(item["scale"],.01f,100);go.SetActive(true);if(PrefabUtility.IsPartOfPrefabInstance(go)){PrefabUtility.RecordPrefabInstancePropertyModifications(go);PrefabUtility.RecordPrefabInstancePropertyModifications(go.transform);}
                if(item["asset_id"].Type==JTokenType.Null||item["base_color_rgba"].Type!=JTokenType.Null){
                    foreach(var renderer in go.GetComponentsInChildren<MeshRenderer>(true)){
                        var materials=renderer.sharedMaterials.Select(original=>{
                            var m=original!=null&&item["asset_id"].Type!=JTokenType.Null?new Material(original):new Material(Shader.Find("HDRP/Lit"));
                            if(item["base_color_rgba"].Type!=JTokenType.Null){var c=(JArray)item["base_color_rgba"];m.SetColor("_BaseColor",new Color((float)c[0],(float)c[1],(float)c[2],(float)c[3]));}
                            AssetDatabase.CreateAsset(m,folder+"/Resources/material-"+Guid.NewGuid().ToString("N")+".mat");return m;
                        }).ToArray();renderer.sharedMaterials=materials;
                    }
                }
            }
            LastRoomFinish=architecture==null?ReferenceRoomFinish.Apply(root,interiorStyle):new JObject{["architecture"]=ReferenceArchitecture.Build(root,architecture,interiorStyle)};
            if(supports!=null)LastContacts=ReferenceContacts.Resolve(root,plan,supports);
            foreach(JObject item in (JArray)plan["lights"]){
                var go=new GameObject("Reference light");go.transform.position=Vector(item["position_m"],-100,100);go.transform.eulerAngles=Vector(item["rotation_deg"],-360,360);
                var light=go.AddComponent<Light>();var type=(string)item["type"];light.type=type=="directional"?LightType.Directional:type=="spot"?LightType.Spot:LightType.Point;
                go.AddComponent<HDAdditionalLightData>();light.lightUnit=type=="directional"?UnityEngine.Rendering.LightUnit.Lux:UnityEngine.Rendering.LightUnit.Lumen;light.intensity=Number(item["intensity"],0,type=="directional"?150000:100000);light.color=Color3(item["color_rgb"]);light.range=30;light.spotAngle=Number(item["spot_angle_deg"],1,179);light.shadows=architecture==null?LightShadows.Soft:LightShadows.None;light.lightmapBakeType=LightmapBakeType.Realtime;
            }
            var volume=new GameObject("Reconstructed atmosphere").AddComponent<Volume>();volume.isGlobal=true;volume.priority=10;
            var profile=ScriptableObject.CreateInstance<VolumeProfile>();AssetDatabase.CreateAsset(profile,folder+"/Resources/Atmosphere.asset");volume.sharedProfile=profile;
            var exposure=profile.Add<Exposure>(true);exposure.mode.Override(ExposureMode.Fixed);exposure.fixedExposure.Override(Number(plan["exposure_ev"],-20,30));
            var environment=profile.Add<VisualEnvironment>(true);environment.skyType.Override((int)SkyType.Gradient);environment.skyAmbientMode.Override(SkyAmbientMode.Dynamic);
            var sky=profile.Add<GradientSky>(true);var color=Color3(plan["sky_color_rgb"]);sky.top.Override(color);sky.middle.Override(color);sky.bottom.Override(color);
            if(plan["fog_mean_free_path_m"].Type!=JTokenType.Null){var fog=profile.Add<Fog>(true);fog.enabled.Override(true);fog.enableVolumetricFog.Override(true);fog.meanFreePath.Override(Number(plan["fog_mean_free_path_m"],1,1000));}
            EditorUtility.SetDirty(profile);
            var camera=new GameObject("Main Camera").AddComponent<Camera>();camera.tag="MainCamera";camera.allowHDR=true;camera.nearClipPlane=.05f;camera.farClipPlane=100;camera.gameObject.AddComponent<HDAdditionalCameraData>();
            if(captureProtocol!=null){
                var protocol=JsonUtility.FromJson<HdrpAgent.Runtime.ReferenceRenderProtocol>(captureProtocol.ToString());HdrpAgent.Runtime.ReferenceRenderProtocol.Apply(camera,protocol);
                var tone=profile.Add<Tonemapping>(true);tone.mode.Override((TonemappingMode)Enum.Parse(typeof(TonemappingMode),protocol.tonemapping_mode));EditorUtility.SetDirty(profile);
            }
            var view=(JObject)((JArray)inspection["work_views"])[0];camera.transform.position=Vector(view["position_m"],-100,100);camera.transform.eulerAngles=Vector(view["rotation_deg"],-360,360);camera.fieldOfView=Number(view["fov_deg"],5,120);
            var destination=folder+"/Reconstruction.unity";EditorSceneManager.SaveScene(scene,destination);SceneInspector.BindWorkingScene(destination);AssetDatabase.SaveAssets();return destination;
        }
    }
}
