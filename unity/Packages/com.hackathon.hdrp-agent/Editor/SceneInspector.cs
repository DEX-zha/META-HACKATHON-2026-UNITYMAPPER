using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using HdrpAgent.Runtime;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    [InitializeOnLoad]
    public static class SceneInspector
    {
        static SceneInspector(){CommandExecutor.CurrentVersion=Version;}
        public static string Scope {
            get{
                var path=SceneManager.GetActiveScene().path;var prefix=SnapshotStore.Runs+"/";
                if(!path.StartsWith(prefix,StringComparison.Ordinal))throw new InvalidOperationException("Active scene is not an owned working copy");
                return path.Substring(prefix.Length).Split('/')[0];
            }
        }
        public static CaptureBinding[] Bindings=>SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(o=>o.GetComponentsInChildren<CaptureBinding>(true)).ToArray();
        public static void BindWorkingScene(string source){
            var scene=SceneManager.GetActiveScene();var workingGuid=AssetDatabase.AssetPathToGUID(scene.path);var sourceGuid=AssetDatabase.AssetPathToGUID(source);
            foreach(var go in scene.GetRootGameObjects().SelectMany(o=>o.GetComponentsInChildren<Transform>(true)).Select(t=>t.gameObject)){
                var binding=go.GetComponent<CaptureBinding>()??go.AddComponent<CaptureBinding>();
                if(string.IsNullOrEmpty(binding.logicalKey))binding.logicalKey="object-"+Guid.NewGuid().ToString("N");
                binding.workingGlobalObjectId=GlobalObjectId.GetGlobalObjectIdSlow(go).ToString();
                binding.sourceGlobalObjectId=binding.workingGlobalObjectId.Replace(workingGuid,sourceGuid);
                EditorUtility.SetDirty(binding);
            }
            EditorSceneManager.MarkSceneDirty(scene);EditorSceneManager.SaveScene(scene);
        }
        public static GameObject Resolve(string logicalKey){
            if(EditorApplication.isPlayingOrWillChangePlaymode)throw new InvalidOperationException("Authoring ID resolution is EditMode only");
            var binding=Bindings.SingleOrDefault(b=>b.logicalKey==logicalKey)??throw new InvalidDataException("Unknown owned logical key");
            if(!GlobalObjectId.TryParse(binding.workingGlobalObjectId,out var id))throw new InvalidDataException("Invalid working GlobalObjectId");
            var go=GlobalObjectId.GlobalObjectIdentifierToObjectSlow(id) as GameObject;
            if(go!=binding.gameObject||go.scene!=SceneManager.GetActiveScene())throw new InvalidDataException("Binding resolves outside working scene");
            return go;
        }
        public static string Version(){
            var scene=SceneManager.GetActiveScene();
            if(string.IsNullOrEmpty(scene.path))return "unqualified";
            try{
                var owned=SnapshotStore.Manifest(Scope);
                var external=AssetDatabase.GetDependencies(scene.path,true).Where(p=>!p.StartsWith(SnapshotStore.Root(Scope)+"/",StringComparison.Ordinal)).OrderBy(p=>p,StringComparer.Ordinal).ToDictionary(p=>p,p=>AssetDatabase.GetAssetDependencyHash(p).ToString());
                var settings=new Dictionary<string,string>();
                foreach(var file in new[]{"ProjectSettings/GraphicsSettings.asset","ProjectSettings/QualitySettings.asset","ProjectSettings/ProjectSettings.asset"})if(File.Exists(file))settings[file]=BridgeJson.Hash(File.ReadAllBytes(file));
                return "version-"+BridgeJson.CanonicalHash(JObject.FromObject(new{owned,external,settings}));
            }catch(InvalidOperationException){return "unqualified";}
        }
        static float[] Vec(Vector3 v)=>new[]{v.x,v.y,v.z};
        public static JObject Inspect(){
            var objects=new JArray();
            foreach(var binding in Bindings){
                var go=Resolve(binding.logicalKey);var t=go.transform;
                var item=JObject.FromObject(new{logical_key=binding.logicalKey,source_global_object_id=binding.sourceGlobalObjectId,working_global_object_id=binding.workingGlobalObjectId,name=go.name,active=go.activeInHierarchy,position_m=Vec(t.position),rotation_deg=Vec(t.eulerAngles),scale=Vec(t.localScale)});
                var light=go.GetComponent<Light>();var hd=go.GetComponent<HDAdditionalLightData>();
                if(light!=null)item["light"]=JObject.FromObject(new{type=light.type.ToString(),intensity=light.intensity,unit=light.lightUnit.ToString(),temperature_kelvin=light.colorTemperature,use_temperature=light.useColorTemperature,bake_type=light.lightmapBakeType.ToString(),bounce_intensity=light.bounceIntensity,volumetric_dimmer=hd!=null?hd.volumetricDimmer:0,affect_volumetric=hd!=null&&hd.affectsVolumetric,shadow_normal_bias=hd!=null?(float?)hd.normalBias:null,shadow_normal_bias_unit="shadow_texel_scale_factor",shadow_slope_bias=hd!=null?(float?)hd.slopeBias:null,shadow_near_plane_m=hd!=null?(float?)hd.shadowNearPlane:null});
                var volume=go.GetComponent<Volume>();
                if(volume!=null){var fog=volume.sharedProfile!=null&&volume.sharedProfile.TryGet<Fog>(out var f)?f:null;item["volume"]=JObject.FromObject(new{profile=AssetDatabase.GetAssetPath(volume.sharedProfile),global=volume.isGlobal,weight=volume.weight,fog=fog==null?null:new{mean_free_path_m=fog.meanFreePath.value,anisotropy=fog.anisotropy.value,enable_volumetric_fog=fog.enableVolumetricFog.value}});}
                var renderer=go.GetComponent<Renderer>();
                if(renderer!=null){
                    var index=renderer.lightmapIndex;var maps=LightmapSettings.lightmaps;var atlas=index>=0&&index<maps.Length?maps[index].lightmapColor:null;var allocation=renderer.lightmapScaleOffset;
                    item["renderer"]=JObject.FromObject(new{bounds_center_m=Vec(renderer.bounds.center),bounds_size_m=Vec(renderer.bounds.size),materials=renderer.sharedMaterials.Select(AssetDatabase.GetAssetPath).ToArray(),contribute_gi=(GameObjectUtility.GetStaticEditorFlags(go)&StaticEditorFlags.ContributeGI)!=0,scale_in_lightmap=(renderer as MeshRenderer)?.scaleInLightmap,lightmap_index=index,lightmap_scale_offset=new[]{allocation.x,allocation.y,allocation.z,allocation.w},lightmap_atlas_size_px=atlas!=null?new[]{atlas.width,atlas.height}:null});
                    item["renderer"]["material_property_block_present"]=renderer.HasPropertyBlock();
                    item["renderer"]["material_facts"]=new JArray(renderer.sharedMaterials.Select((material,slot)=>{
                        if(material==null)return JObject.FromObject(new{slot,missing=true});
                        var color=material.HasProperty("_BaseColor")?material.GetColor("_BaseColor"):(Color?)null;
                        return JObject.FromObject(new{slot,shader=material.shader!=null?material.shader.name:null,base_color_rgba=color.HasValue?new[]{color.Value.r,color.Value.g,color.Value.b,color.Value.a}:null,double_sided_gi=material.doubleSidedGI,source="authoring_material_properties"});
                    }));
                }
                var meshFilter=go.GetComponent<MeshFilter>();var mesh=meshFilter!=null?meshFilter.sharedMesh:null;
                if(mesh!=null){
                    float? margin=null;var path=AssetDatabase.GetAssetPath(mesh);var importer=AssetImporter.GetAtPath(path);
                    if(importer!=null&&!string.IsNullOrEmpty(importer.userData)){try{var data=JObject.Parse(importer.userData);var n=data["hdrp_agent_uv_pack_margin"];if(n!=null&&(n.Type==JTokenType.Float||n.Type==JTokenType.Integer)&&(double)n>=.00390625&&(double)n<=.0625)margin=(float)n;}catch(Newtonsoft.Json.JsonException){}}
                    item["mesh"]=JObject.FromObject(new{readable=mesh.isReadable,vertex_count=mesh.vertexCount,submesh_count=mesh.subMeshCount,has_uv2=mesh.isReadable?mesh.uv2.Length==mesh.vertexCount:(bool?)null,uv_pack_margin=margin,uv_repair_supported=mesh.isReadable&&mesh.vertexCount>=3&&mesh.vertexCount<=50000&&mesh.subMeshCount<=32&&(GameObjectUtility.GetStaticEditorFlags(go)&StaticEditorFlags.ContributeGI)!=0&&Enumerable.Range(0,mesh.subMeshCount).All(i=>mesh.GetTopology(i)==MeshTopology.Triangles)});
                }
                objects.Add(item);
            }
            var bake=JObject.FromObject(new{running=Lightmapping.isRunning,lightmap_count=LightmapSettings.lightmaps.Length,lighting_data=AssetDatabase.GetAssetPath(Lightmapping.lightingDataAsset)});
            if(Lightmapping.TryGetLightingSettings(out var settings))bake.Merge(JObject.FromObject(new{lightmapper=settings.lightmapper.ToString(),baked_gi=settings.bakedGI,realtime_gi=settings.realtimeGI,lightmap_resolution_texels_per_unit=settings.lightmapResolution,lightmap_max_size=settings.lightmapMaxSize,lightmap_padding_texels=settings.lightmapPadding,direct_samples=settings.directSampleCount,indirect_samples=settings.indirectSampleCount,environment_samples=settings.environmentSampleCount,mixed_mode=settings.mixedBakeMode.ToString()}));
            return JObject.FromObject(new{schema_version="1.0",version=Version(),scope_id=Scope,scene_path=SceneManager.GetActiveScene().path,objects,bake,capabilities=CommandExecutor.Capabilities});
        }
    }
}
