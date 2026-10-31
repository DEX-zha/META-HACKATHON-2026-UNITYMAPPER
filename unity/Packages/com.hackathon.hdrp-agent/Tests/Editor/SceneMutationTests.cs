using System;
using System.IO;
using System.Linq;
using NUnit.Framework;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using HdrpAgent.Editor;

namespace HdrpAgent.Tests
{
    public class SceneMutationTests
    {
        string original,scope;
        string returnScene;
        [SetUp]public void Setup(){returnScene=SceneManager.GetActiveScene().path;scope="test-"+Guid.NewGuid().ToString("N");original="Assets/AgentWorkspace/Tests/"+scope;Directory.CreateDirectory(original);AssetDatabase.Refresh();var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);var cube=GameObject.CreatePrimitive(PrimitiveType.Cube);var mat=new Material(Shader.Find("HDRP/Lit"));AssetDatabase.CreateAsset(mat,original+"/Source.mat");cube.GetComponent<Renderer>().sharedMaterial=mat;EditorSceneManager.SaveScene(scene,original+"/Source.unity");}
        [TearDown]public void Cleanup(){EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);PatchExecutor.BeforeOperationForTests=null;AssetDatabase.DeleteAsset(original);AssetDatabase.DeleteAsset("Assets/AgentWorkspace/Runs/"+scope);if(!string.IsNullOrEmpty(returnScene))EditorSceneManager.OpenScene(returnScene);}
        [Test]public void WorkingCopyHasNewGuidsAndNeverWritesOriginal(){var before=File.ReadAllBytes(original+"/Source.mat");var working=SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);Assert.AreNotEqual(AssetDatabase.AssetPathToGUID(original+"/Source.unity"),AssetDatabase.AssetPathToGUID(working));var renderer=UnityEngine.Object.FindFirstObjectByType<MeshRenderer>();var copyPath=AssetDatabase.GetAssetPath(renderer.sharedMaterial);Assert.IsTrue(copyPath.StartsWith("Assets/AgentWorkspace/Runs/"+scope+"/"));Assert.AreNotEqual(AssetDatabase.AssetPathToGUID(original+"/Source.mat"),AssetDatabase.AssetPathToGUID(copyPath));renderer.sharedMaterial.SetColor("_BaseColor",Color.red);EditorUtility.SetDirty(renderer.sharedMaterial);AssetDatabase.SaveAssets();CollectionAssert.AreEqual(before,File.ReadAllBytes(original+"/Source.mat"));}
        [Test]public void SnapshotRestoresOwnedFilesAndRemovesNewResources(){SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);var saved=SnapshotStore.Take(scope);var root="Assets/AgentWorkspace/Runs/"+scope;File.WriteAllText(root+"/Created.txt","new");AssetDatabase.Refresh();var after=SnapshotStore.ManifestHash(scope);SnapshotStore.Restore(saved,after);Assert.IsFalse(File.Exists(root+"/Created.txt"));Assert.AreEqual(saved.manifest_hash,SnapshotStore.ManifestHash(scope));}
        [Test]public void ConcurrentEditRefusesRestore(){SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);var saved=SnapshotStore.Take(scope);var expected=SnapshotStore.ManifestHash(scope);File.WriteAllText("Assets/AgentWorkspace/Runs/"+scope+"/Concurrent.txt","operator edit");Assert.Throws<InvalidOperationException>(()=>SnapshotStore.Restore(saved,expected));}
        JObject Patch(params JObject[] operations){return new JObject{["id"]="patch-test",["session_id"]="session-test",["expected_version"]=SceneInspector.Version(),["hypothesis_id"]="hypothesis-test",["expected_effect"]="Test local mutation",["operations"]=new JArray(operations),["needs_bake"]=false};}
        string Target()=>SceneInspector.Bindings.First(b=>b.GetComponent<MeshRenderer>()!=null).logicalKey;
        [Test]public void InspectionExportsMeasuredBoundsAndAtlasAllocationWithoutInventingOccupancy(){
            SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);
            var item=SceneInspector.Inspect()["objects"].First(o=>(string)o["logical_key"]==Target());
            var renderer=item["renderer"];Assert.AreEqual(3,renderer["bounds_size_m"].Count());Assert.AreEqual(4,renderer["lightmap_scale_offset"].Count());
            Assert.AreEqual(JTokenType.Null,renderer["lightmap_atlas_size_px"].Type);Assert.IsNull(renderer["uv_occupancy"]);
            Assert.AreEqual("HDRP/Lit",(string)renderer["material_facts"][0]["shader"]);Assert.AreEqual(4,renderer["material_facts"][0]["base_color_rgba"].Count());Assert.AreEqual("authoring_material_properties",(string)renderer["material_facts"][0]["source"]);
        }
        [Test]public void WorkingCopyPreparesOwnedProbeVolumeAndReportsActualBakeSettings(){
            var settings=new LightingSettings{lightmapper=LightingSettings.Lightmapper.ProgressiveGPU,lightmapResolution=23,lightmapMaxSize=1024,indirectSampleCount=128,autoGenerate=false};
            AssetDatabase.CreateAsset(settings,original+"/Lighting.asset");Lightmapping.lightingSettings=settings;
            EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());EditorSceneManager.SaveScene(SceneManager.GetActiveScene());
            SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);
            Assert.IsTrue(SceneInspector.Bindings.Any(b=>b.GetComponents<Component>().Any(c=>c!=null&&c.GetType().FullName=="UnityEngine.Rendering.ProbeVolume")));
            Assert.IsTrue(AssetDatabase.GetAssetPath(Lightmapping.lightingSettings).StartsWith(SnapshotStore.Root(scope)+"/"));
            var bake=SceneInspector.Inspect()["bake"];
            Assert.AreEqual(23,(float)bake["lightmap_resolution_texels_per_unit"]);
            Assert.AreEqual(1024,(int)bake["lightmap_max_size"]);
            Assert.AreEqual(128,(int)bake["indirect_samples"]);
            Assert.AreEqual("ProgressiveGPU",(string)bake["lightmapper"]);
        }
        [Test]public void PartialPatchRestoresTransformsAndMaterialFiles(){
            SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);var before=SnapshotStore.ManifestHash(scope);
            var move=new JObject{["op"]="set_transform",["target_id"]=Target(),["position_m"]=new JArray(1,2,3),["rotation_deg"]=null,["scale"]=null};
            var color=new JObject{["op"]="set_material",["target_id"]=Target(),["property"]="base_color_rgba",["value"]=new JArray(1,0,0,1)};
            var patch=Patch(move,color);PatchExecutor.BeforeOperationForTests=i=>{if(i==1)throw new IOException("Injected failure after first change");};
            Assert.Throws<IOException>(()=>PatchExecutor.Apply(patch,(string)patch["expected_version"]));
            Assert.AreEqual(before,SnapshotStore.ManifestHash(scope));Assert.AreEqual(Vector3.zero,SceneInspector.Resolve(Target()).transform.position);
        }
        [Test]public void BooleanEmissionAndUnknownOperationsAreRefusedBeforeMutation(){
            SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);var before=SnapshotStore.ManifestHash(scope);
            var op=new JObject{["op"]="set_material",["target_id"]=Target(),["property"]="emission_nits",["value"]=true};var patch=Patch(op);
            Assert.Throws<InvalidDataException>(()=>PatchExecutor.Apply(patch,(string)patch["expected_version"]));Assert.AreEqual(before,SnapshotStore.ManifestHash(scope));
            op["op"]="execute_csharp";patch=Patch(op);Assert.Throws<InvalidDataException>(()=>PatchExecutor.Apply(patch,(string)patch["expected_version"]));
        }
        [Test]public void LumensAreAppliedExplicitlyAndLuxOnPointLightIsRefused(){
            var go=new GameObject("Point");var light=go.AddComponent<Light>();light.type=LightType.Point;
            var hd=System.AppDomain.CurrentDomain.GetAssemblies().Select(a=>a.GetType("UnityEngine.Rendering.HighDefinition.HDAdditionalLightData")).First(t=>t!=null);go.AddComponent(hd);
            EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());EditorSceneManager.SaveScene(SceneManager.GetActiveScene());
            SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);var binding=SceneInspector.Bindings.First(b=>b.GetComponent<Light>()!=null);
            var op=new JObject{["op"]="set_light",["target_id"]=binding.logicalKey,["property"]="intensity_lumen",["value"]=1234};var patch=Patch(op);PatchExecutor.Apply(patch,(string)patch["expected_version"]);
            var copy=SceneInspector.Resolve(binding.logicalKey).GetComponent<Light>();Assert.AreEqual("Lumen",copy.lightUnit.ToString());Assert.AreEqual(1234,copy.intensity);
            op["property"]="illuminance_lux";patch=Patch(op);Assert.Throws<InvalidDataException>(()=>PatchExecutor.Apply(patch,(string)patch["expected_version"]));
        }
        [Test]public void OutOfScopeIsRefused(){Assert.Throws<InvalidDataException>(()=>SnapshotStore.ManifestHash("../outside"));}
        void PrepareGiSource(){var cube=UnityEngine.Object.FindFirstObjectByType<MeshRenderer>();GameObjectUtility.SetStaticEditorFlags(cube.gameObject,StaticEditorFlags.ContributeGI);EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());EditorSceneManager.SaveScene(SceneManager.GetActiveScene());SnapshotStore.CreateWorkingCopy(original+"/Source.unity",scope);}
        [Test]public void UvRepairClonesMeshAndPreservesGeometryAndOriginalUvs(){
            PrepareGiSource();var target=SceneInspector.Resolve(Target());var source=target.GetComponent<MeshFilter>().sharedMesh;var vertices=source.vertices;var triangles=source.triangles;var uv=source.uv2;
            var op=new JObject{["op"]="set_gi",["target_id"]=Target(),["property"]="lightmap_uv_pack_margin",["value"]=.03125};var patch=Patch(op);
            Assert.IsTrue(PatchExecutor.Apply(patch,(string)patch["expected_version"]));var clone=target.GetComponent<MeshFilter>().sharedMesh;
            Assert.AreNotSame(source,clone);Assert.IsTrue(AssetDatabase.GetAssetPath(clone).StartsWith(SnapshotStore.Root(scope)+"/"));CollectionAssert.AreEqual(uv,source.uv2);
            var newVertices=clone.vertices;var newTriangles=clone.triangles;Assert.AreEqual(triangles.Length,newTriangles.Length);
            for(int i=0;i<triangles.Length;i++)Assert.AreEqual(vertices[triangles[i]],newVertices[newTriangles[i]],"UV generation must preserve each triangle position");
            Assert.AreEqual(clone.vertexCount,clone.uv2.Length);
        }
        [Test]public void UvRepairRejectsUnsafeMarginAndRollsBackNewMeshAfterPartialFailure(){
            PrepareGiSource();var before=SnapshotStore.ManifestHash(scope);
            var uv=new JObject{["op"]="set_gi",["target_id"]=Target(),["property"]="lightmap_uv_pack_margin",["value"]=.1};var patch=Patch(uv);
            Assert.Throws<InvalidDataException>(()=>PatchExecutor.Apply(patch,(string)patch["expected_version"]));Assert.AreEqual(before,SnapshotStore.ManifestHash(scope));
            uv["value"]=.03125;var scale=new JObject{["op"]="set_gi",["target_id"]=Target(),["property"]="scale_in_lightmap",["value"]=2};patch=Patch(uv,scale);
            PatchExecutor.BeforeOperationForTests=i=>{if(i==1)throw new IOException("Injected failure after UV clone");};
            Assert.Throws<IOException>(()=>PatchExecutor.Apply(patch,(string)patch["expected_version"]));Assert.AreEqual(before,SnapshotStore.ManifestHash(scope));
        }
    }
}
