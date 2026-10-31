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
    public static class PatchExecutor
    {
        public static Action<int> BeforeOperationForTests;
        static float Number(JToken value,float min,float max){
            if(value==null||(value.Type!=JTokenType.Float&&value.Type!=JTokenType.Integer))throw new InvalidDataException("Expected a numeric value, not boolean or string");
            var n=(double)value;if(double.IsNaN(n)||double.IsInfinity(n)||n<min||n>max)throw new InvalidDataException("Property is outside allowed bounds");return (float)n;
        }
        static bool Boolean(JToken value){if(value?.Type!=JTokenType.Boolean)throw new InvalidDataException("Expected boolean");return (bool)value;}
        static Vector3 Vector(JToken value,float min,float max){var a=value as JArray;if(a==null||a.Count!=3)throw new InvalidDataException("Expected three coordinates");return new Vector3(Number(a[0],min,max),Number(a[1],min,max),Number(a[2],min,max));}
        static void Owned(UnityEngine.Object asset){if(asset==null||!AssetDatabase.GetAssetPath(asset).StartsWith(SnapshotStore.Root(SceneInspector.Scope)+"/",StringComparison.Ordinal))throw new InvalidDataException("Mutable asset must be a local owned clone");}
        public static bool Apply(JObject patch,string expectedVersion){
            if(EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)throw new InvalidOperationException("Editor is busy");
            BridgeJson.Closed(patch,"id","session_id","expected_version","hypothesis_id","expected_effect","operations","needs_bake");
            if((string)patch["expected_version"]!=expectedVersion||SceneInspector.Version()!=expectedVersion||SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("STALE_VERSION");
            var operations=patch["operations"] as JArray;if(operations==null||operations.Count<1||operations.Count>8)throw new InvalidDataException("Patch requires one to eight operations");
            var changes=new List<Action>();bool needsBake=false;
            foreach(var token in operations){
                var op=token as JObject??throw new InvalidDataException("Operation is not an object");
                var kind=(string)op["op"];var target=SceneInspector.Resolve((string)op["target_id"]);
                switch(kind){
                    case "set_transform":{
                        BridgeJson.Closed(op,"op","target_id","position_m","rotation_deg","scale");
                        Vector3? pos=op["position_m"].Type==JTokenType.Null?(Vector3?)null:Vector(op["position_m"],-100,100);
                        Vector3? rot=op["rotation_deg"].Type==JTokenType.Null?(Vector3?)null:Vector(op["rotation_deg"],-360,360);
                        Vector3? scale=op["scale"].Type==JTokenType.Null?(Vector3?)null:Vector(op["scale"],.01f,100);
                        if(pos==null&&rot==null&&scale==null)throw new InvalidDataException("Empty transform");
                        needsBake|=(GameObjectUtility.GetStaticEditorFlags(target)&StaticEditorFlags.ContributeGI)!=0;
                        changes.Add(()=>{if(pos.HasValue)target.transform.position=pos.Value;if(rot.HasValue)target.transform.eulerAngles=rot.Value;if(scale.HasValue)target.transform.localScale=scale.Value;});break;
                    }
                    case "set_light":{
                        BridgeJson.Closed(op,"op","target_id","property","value");
                        var light=target.GetComponent<Light>()??throw new InvalidDataException("Target has no Light");var hd=target.GetComponent<HDAdditionalLightData>()??throw new InvalidDataException("Target has no HDRP light data");
                        var property=(string)op["property"];var value=op["value"];needsBake|=light.lightmapBakeType!=LightmapBakeType.Realtime;
                        switch(property){
                            case "intensity_lumen":var lumens=Number(value,0,100000);if(light.type!=LightType.Point&&light.type!=LightType.Spot)throw new InvalidDataException("Lumens require point or spot light");changes.Add(()=>{light.lightUnit=LightUnit.Lumen;light.intensity=lumens;});break;
                            case "illuminance_lux":var lux=Number(value,0,150000);if(light.type!=LightType.Directional)throw new InvalidDataException("Lux requires directional light");changes.Add(()=>{light.lightUnit=LightUnit.Lux;light.intensity=lux;});break;
                            case "temperature_kelvin":var kelvin=Number(value,1000,20000);changes.Add(()=>{light.useColorTemperature=true;light.colorTemperature=kelvin;});break;
                            case "volumetric_dimmer":var dimmer=Number(value,0,1);changes.Add(()=>hd.volumetricDimmer=dimmer);break;
                            case "use_volumetric":var enabled=Boolean(value);changes.Add(()=>hd.affectsVolumetric=enabled);break;
                            default:throw new InvalidDataException("Unsupported light property");
                        }break;
                    }
                    case "set_fog":{
                        BridgeJson.Closed(op,"op","target_id","property","value");var volume=target.GetComponent<Volume>()??throw new InvalidDataException("Target has no Volume");Owned(volume.sharedProfile);
                        if(!volume.sharedProfile.TryGet<Fog>(out var fog))throw new InvalidDataException("Fog override missing");var property=(string)op["property"];var value=op["value"];
                        switch(property){
                            case "mean_free_path_m":var path=Number(value,1,1000);changes.Add(()=>fog.meanFreePath.Override(path));break;
                            case "anisotropy":var anisotropy=Number(value,-.9f,.9f);changes.Add(()=>fog.anisotropy.Override(anisotropy));break;
                            case "enable_volumetric_fog":var enabled=Boolean(value);changes.Add(()=>fog.enableVolumetricFog.Override(enabled));break;
                            default:throw new InvalidDataException("Unsupported fog property");
                        }changes.Add(()=>{EditorUtility.SetDirty(fog);EditorUtility.SetDirty(volume.sharedProfile);});break;
                    }
                    case "set_material":{
                        BridgeJson.Closed(op,"op","target_id","property","value");var renderer=target.GetComponent<Renderer>()??throw new InvalidDataException("Target has no renderer");
                        if(renderer.sharedMaterials.Length!=1)throw new InvalidDataException("Material slot is ambiguous");var mat=renderer.sharedMaterial;Owned(mat);
                        if(mat.shader.name!="HDRP/Lit")throw new InvalidDataException("Only HDRP/Lit is qualified");
                        var property=(string)op["property"];var value=op["value"];
                        if(property=="base_color_rgba"){
                            var a=value as JArray;if(a==null||a.Count!=4)throw new InvalidDataException("Expected RGBA");var color=new Color(Number(a[0],0,1),Number(a[1],0,1),Number(a[2],0,1),Number(a[3],0,1));changes.Add(()=>mat.SetColor("_BaseColor",color));
                        }else if(property=="emission_nits"){
                            var intensity=Number(value,0,1000);if(!mat.HasProperty("_EmissiveIntensity"))throw new InvalidDataException("Emission intensity unsupported");
                            changes.Add(()=>{mat.SetFloat("_UseEmissiveIntensity",1);mat.SetFloat("_EmissiveIntensityUnit",(float)EmissiveIntensityUnit.Nits);mat.SetFloat("_EmissiveIntensity",intensity);var color=mat.GetColor("_EmissiveColorLDR").linear;mat.SetColor("_EmissiveColor",color*intensity);});
                        }else throw new InvalidDataException("Unsupported material property");
                        needsBake|=(GameObjectUtility.GetStaticEditorFlags(target)&StaticEditorFlags.ContributeGI)!=0;
                        changes.Add(()=>{HDMaterial.ValidateMaterial(mat);EditorUtility.SetDirty(mat);});break;
                    }
                    case "set_gi":{
                        BridgeJson.Closed(op,"op","target_id","property","value");var renderer=target.GetComponent<MeshRenderer>()??throw new InvalidDataException("GI target must be MeshRenderer");
                        var property=(string)op["property"];if(property=="contribute_gi"){var enabled=Boolean(op["value"]);changes.Add(()=>{var flags=GameObjectUtility.GetStaticEditorFlags(target);GameObjectUtility.SetStaticEditorFlags(target,enabled?flags|StaticEditorFlags.ContributeGI:flags&~StaticEditorFlags.ContributeGI);});}
                        else if(property=="scale_in_lightmap"){var scale=Number(op["value"],.1f,4);changes.Add(()=>renderer.scaleInLightmap=scale);}
                        else if(property=="lightmap_uv_pack_margin"){
                            var margin=Number(op["value"],.00390625f,.0625f);var filter=target.GetComponent<MeshFilter>();if(filter==null)throw new InvalidDataException("UV repair requires a static MeshFilter");var source=filter.sharedMesh;
                            if(source==null||!source.isReadable||source.vertexCount<3||source.vertexCount>50000||source.subMeshCount>32||(GameObjectUtility.GetStaticEditorFlags(target)&StaticEditorFlags.ContributeGI)==0)throw new InvalidDataException("UV repair requires a readable GI mesh within the qualified vertex/submesh limits");
                            for(int index=0;index<source.subMeshCount;index++)if(source.GetTopology(index)!=MeshTopology.Triangles)throw new InvalidDataException("UV repair requires triangle topology");
                            changes.Add(()=>{
                                var clone=UnityEngine.Object.Instantiate(source);clone.name=source.name+" Lightmap UV";
                                try{
                                    UnwrapParam settings;UnwrapParam.SetDefaults(out settings);settings.packMargin=margin;
                                    if(!Unwrapping.GenerateSecondaryUVSet(clone,settings))throw new InvalidDataException("UV generation failed");
                                    var root=SnapshotStore.Root(SceneInspector.Scope)+"/Resources";Directory.CreateDirectory(root);AssetDatabase.Refresh();
                                    var path=root+"/UV-"+Guid.NewGuid().ToString("N")+".asset";AssetDatabase.CreateAsset(clone,path);
                                    var importer=AssetImporter.GetAtPath(path);importer.userData=new JObject{["hdrp_agent_uv_pack_margin"]=margin}.ToString(Newtonsoft.Json.Formatting.None);importer.SaveAndReimport();
                                    filter.sharedMesh=AssetDatabase.LoadAssetAtPath<Mesh>(path);EditorUtility.SetDirty(filter);
                                }catch{if(!AssetDatabase.Contains(clone))UnityEngine.Object.DestroyImmediate(clone);throw;}
                            });
                        }else throw new InvalidDataException("Unsupported GI property");needsBake=true;break;
                    }
                    case "set_bake":{
                        BridgeJson.Closed(op,"op","target_id","indirect_samples");if(op["indirect_samples"].Type!=JTokenType.Integer)throw new InvalidDataException("Samples must be integer");var samples=(int)Number(op["indirect_samples"],16,1024);
                        var settings=Lightmapping.lightingSettings;Owned(settings);changes.Add(()=>{settings.lightmapper=LightingSettings.Lightmapper.ProgressiveGPU;settings.indirectSampleCount=samples;EditorUtility.SetDirty(settings);});needsBake=true;break;
                    }
                    default:throw new InvalidDataException("OPERATION_UNKNOWN");
                }
            }
            var snapshot=SnapshotStore.Take(SceneInspector.Scope);
            try{
                for(int i=0;i<changes.Count;i++){BeforeOperationForTests?.Invoke(i);changes[i]();}
                EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());EditorSceneManager.SaveScene(SceneManager.GetActiveScene());AssetDatabase.SaveAssets();
                return needsBake;
            }catch{
                // Persist this known partial state before the conditional restore; no native bake is active here.
                EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());EditorSceneManager.SaveScene(SceneManager.GetActiveScene());AssetDatabase.SaveAssets();
                SnapshotStore.Restore(snapshot,SnapshotStore.ManifestHash(snapshot.scope_id));throw;
            }
        }
    }
}
