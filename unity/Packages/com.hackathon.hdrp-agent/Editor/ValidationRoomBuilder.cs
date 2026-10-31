using System;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    public static class ValidationRoomBuilder
    {
        const string Root="Assets/AgentWorkspace/Original";
        static Material Material(string name,Color color){var m=new Material(Shader.Find("HDRP/Lit")){name=name};m.SetColor("_BaseColor",color);m.SetFloat("_Smoothness",.25f);HDMaterial.ValidateMaterial(m);AssetDatabase.CreateAsset(m,Root+"/"+name+".mat");return m;}
        static GameObject Box(string name,Vector3 position,Vector3 size,Material material){
            var go=GameObject.CreatePrimitive(PrimitiveType.Cube);go.name=name;go.transform.position=position;go.transform.localScale=size;go.GetComponent<Renderer>().sharedMaterial=material;
            var mesh=UnityEngine.Object.Instantiate(go.GetComponent<MeshFilter>().sharedMesh);mesh.name=name+" Mesh";Unwrapping.GenerateSecondaryUVSet(mesh);AssetDatabase.CreateAsset(mesh,Root+"/"+name+".asset");go.GetComponent<MeshFilter>().sharedMesh=mesh;
            GameObjectUtility.SetStaticEditorFlags(go,StaticEditorFlags.ContributeGI|StaticEditorFlags.BatchingStatic);go.GetComponent<MeshRenderer>().receiveGI=ReceiveGI.Lightmaps;
            return go;
        }
        [MenuItem("Tools/HDRP Agent/Validation/Prepare Room")]
        public static void Prepare(){
            if(EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning||SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("Save current scene and stop operations first");
            if(AssetDatabase.LoadAssetAtPath<SceneAsset>("Assets/AgentWorkspace/Room.unity")!=null)throw new InvalidOperationException("Room fixture already exists; originals are preserved");
            Directory.CreateDirectory(Root);Directory.CreateDirectory("Assets/AgentWorkspace/Variants");AssetDatabase.Refresh();
            var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
            var plaster=Material("Plaster",new Color(.72f,.7f,.65f));var floor=Material("Floor",new Color(.25f,.2f,.16f));var wood=Material("Wood",new Color(.28f,.12f,.05f));var trim=Material("Trim",new Color(.85f,.84f,.8f));
            Box("Floor",new Vector3(0,-.1f,0),new Vector3(8,.2f,6),floor);
            Box("Ceiling",new Vector3(0,3.3f,0),new Vector3(8,.2f,6),plaster);
            Box("Wall Left",new Vector3(-4,1.6f,0),new Vector3(.25f,3.2f,6),plaster);
            Box("Wall Right",new Vector3(4,1.6f,0),new Vector3(.25f,3.2f,6),plaster);
            Box("Wall Rear Left",new Vector3(-2.5f,1.6f,3),new Vector3(3,3.2f,.25f),plaster);
            Box("Wall Rear Right",new Vector3(2.5f,1.6f,3),new Vector3(3,3.2f,.25f),plaster);
            Box("Wall Rear Lower",new Vector3(0,.5f,3),new Vector3(2,1,.25f),plaster);
            Box("Wall Rear Upper",new Vector3(0,3.1f,3),new Vector3(2,.2f,.25f),plaster);
            Box("Window Sill",new Vector3(0,1.02f,3),new Vector3(2.2f,.12f,.4f),trim);
            Box("Window Frame",new Vector3(0,2.05f,3),new Vector3(.06f,2,.15f),trim);
            Box("Table Top",new Vector3(.2f,.8f,.2f),new Vector3(1.8f,.12f,1),wood);
            for(int x=-1;x<=1;x+=2)for(int z=-1;z<=1;z+=2)Box("Table Leg "+x+" "+z,new Vector3(.2f+x*.72f,.37f,.2f+z*.36f),new Vector3(.1f,.74f,.1f),wood);
            var lightGo=new GameObject("Window Light");var light=lightGo.AddComponent<Light>();light.type=LightType.Spot;lightGo.AddComponent<HDAdditionalLightData>();light.lightUnit=LightUnit.Lumen;light.intensity=8000;light.range=14;light.spotAngle=50;light.shadows=LightShadows.Soft;light.lightmapBakeType=LightmapBakeType.Mixed;lightGo.transform.position=new Vector3(-.5f,2.5f,3.8f);lightGo.transform.rotation=Quaternion.LookRotation(new Vector3(0,.3f,-1)-lightGo.transform.position);
            var sunGo=new GameObject("Day Light");var sun=sunGo.AddComponent<Light>();sun.type=LightType.Directional;sunGo.AddComponent<HDAdditionalLightData>();sun.lightUnit=LightUnit.Lux;sun.intensity=30000;sun.shadows=LightShadows.Soft;sun.lightmapBakeType=LightmapBakeType.Mixed;sunGo.transform.rotation=Quaternion.Euler(35,180,0);
            var volume=new GameObject("Environment").AddComponent<Volume>();volume.isGlobal=true;
            var profile=ScriptableObject.CreateInstance<VolumeProfile>();AssetDatabase.CreateAsset(profile,Root+"/Environment.asset");volume.sharedProfile=profile;
            var visual=profile.Add<VisualEnvironment>(true);visual.skyType.Override((int)SkyType.Gradient);var sky=profile.Add<GradientSky>(true);sky.top.Override(new Color(.18f,.27f,.4f));sky.middle.Override(new Color(.25f,.28f,.32f));sky.bottom.Override(new Color(.1f,.1f,.1f));
            var exposure=profile.Add<Exposure>(true);exposure.mode.Override(ExposureMode.Fixed);exposure.fixedExposure.Override(8);
            var fog=profile.Add<Fog>(true);fog.enabled.Override(true);fog.enableVolumetricFog.Override(true);fog.meanFreePath.Override(18);fog.anisotropy.Override(.25f);fog.baseHeight.Override(0);fog.maximumHeight.Override(4);fog.directionalLightsOnly.Override(false);
            foreach(var component in profile.components)AssetDatabase.AddObjectToAsset(component,profile);EditorUtility.SetDirty(profile);
            var camera=new GameObject("Overview").AddComponent<Camera>();camera.gameObject.AddComponent<HDAdditionalCameraData>();camera.transform.position=new Vector3(0,1.6f,-2.7f);camera.transform.rotation=Quaternion.Euler(5,0,0);
            var lighting=new LightingSettings{name="Room Lighting",lightmapper=LightingSettings.Lightmapper.ProgressiveGPU,bakedGI=true,realtimeGI=false,autoGenerate=false,lightmapResolution=12,lightmapMaxSize=512,directSampleCount=32,indirectSampleCount=64,environmentSampleCount=32,mixedBakeMode=MixedLightingMode.Shadowmask};AssetDatabase.CreateAsset(lighting,Root+"/Lighting.asset");Lightmapping.lightingSettings=lighting;
            EditorSceneManager.SaveScene(scene,"Assets/AgentWorkspace/Room.unity");AssetDatabase.SaveAssets();
            var oracles=new JObject();
            foreach(var code in new[]{"A","B","C"}){
                scene=EditorSceneManager.OpenScene("Assets/AgentWorkspace/Room.unity");
                var spot=GameObject.Find("Window Light");
                if(code=="A")spot.GetComponent<HDAdditionalLightData>().volumetricDimmer=.01f;
                if(code=="B"){
                    var copy=Root+"/Environment B.asset";AssetDatabase.CopyAsset(Root+"/Environment.asset",copy);var p=AssetDatabase.LoadAssetAtPath<VolumeProfile>(copy);GameObject.Find("Environment").GetComponent<Volume>().sharedProfile=p;p.TryGet<Fog>(out var dense);dense.meanFreePath.Override(1);EditorUtility.SetDirty(dense);EditorUtility.SetDirty(p);
                }
                if(code=="C")spot.transform.rotation=Quaternion.Euler(0,90,0);
                EditorSceneManager.MarkSceneDirty(scene);EditorSceneManager.SaveScene(scene,"Assets/AgentWorkspace/Variants/Room-"+code+".unity");AssetDatabase.SaveAssets();
                oracles[code]=new JObject{["cause"]=code=="A"?"Volumetric contribution nearly absent":code=="B"?"Excessive fog density obscures room":"Window spot aimed away from interior",["reference_scene"]="Assets/AgentWorkspace/Room.unity",["required_review"]="Aligned visual evidence and independent artistic review"};
            }
            var workspace=Directory.GetParent(Application.dataPath).Parent.Parent.FullName;Directory.CreateDirectory(Path.Combine(workspace,"evaluation-private"));File.WriteAllText(Path.Combine(workspace,"evaluation-private","room-oracles.json"),oracles.ToString());
            EditorSceneManager.OpenScene("Assets/AgentWorkspace/Room.unity");AssetDatabase.Refresh();
        }
        public static string PrepareWorkingRoom(){
            if(!File.Exists("Assets/AgentWorkspace/Room.unity"))Prepare();
            return SnapshotStore.CreateWorkingCopy("Assets/AgentWorkspace/Room.unity","j0-"+Guid.NewGuid().ToString("N"));
        }
    }
}
