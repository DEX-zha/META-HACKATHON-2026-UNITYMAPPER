using System;
using System.IO;
using System.Collections;
using UnityEngine.TestTools;
using System.Linq;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using HdrpAgent.Editor;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Tests
{
    public sealed class ReferenceConstructionTests
    {
        [Test] public void ArchitecturalPartitionHasDoorAndFrontFacesOnBothSides(){
            var root=new GameObject("Reconstruction");var wall=ReferenceAssets.InstantiateAssembly(AssetDatabase.LoadAssetAtPath<GameObject>("Assets/AtmosphericHouse/Prefabs/Building/WallIn_B_3x_door.prefab"));wall.name="partition";wall.transform.SetParent(root.transform,false);
            var spec=JObject.Parse("{\"height_m\":2.8,\"thickness_m\":0.2,\"lighting\":\"neutral_construction\",\"walls\":[{\"object_key\":\"partition\",\"start_m\":[-1.5,0,0],\"end_m\":[1.5,0,0],\"partition\":true,\"openings\":[{\"key\":\"passage\",\"kind\":\"door\",\"start\":0.3,\"end\":0.7}]}]}");
            var proof=ReferenceArchitecture.Build(root,spec,"B");Assert.True((bool)proof["walls"][0]["surface_audit"]["passed"]);Assert.True((bool)proof["walls"][0]["openings"][0]["insert_present"]);
            var parts=root.GetComponentsInChildren<Transform>().Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)).ToArray();
            Assert.True(parts.Any(t=>PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject).EndsWith("Door_parent_A_L.prefab")));
            Assert.True(parts.All(t=>PrefabUtility.GetPrefabInstanceStatus(t.gameObject)==PrefabInstanceStatus.Connected));
            Assert.False(parts.Any(t=>PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject).Contains("WallOut_")));
            var group=root.transform.Find("partition/Connected structural modules");group.GetComponentInChildren<MeshRenderer>().enabled=false;
            Assert.False((bool)ReferenceArchitecture.Audit(group,3,2.8f,(JArray)proof["walls"][0]["openings"])["passed"]);

        }
        GameObject FinishFixture(){
            var root=new GameObject("Reconstruction");
            foreach(var suffix in new[]{"Floor_3x3","WallOut_3x","WallOut_3x","WallOut_3x","WallOut_3x"}){
                var prefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/AtmosphericHouse/Prefabs/Building/"+suffix+".prefab");
                var obj=ReferenceAssets.InstantiateAssembly(prefab);obj.transform.SetParent(root.transform,false);
            }
            return root;
        }
        [Test]public void FinishesPreserveSocketsAndAreIdempotent(){
            var root=FinishFixture();var originals=root.GetComponentsInChildren<Transform>().Where(t=>t.name=="WallIn_A_3x").Select(t=>(t.localPosition,t.localRotation,t.localScale)).ToArray();
            Assert.AreEqual(4,originals.Length);
            var receipt=ReferenceRoomFinish.Apply(root);Assert.AreEqual(4,((JArray)receipt["wall_changes"]).Count);
            var interiors=root.GetComponentsInChildren<Transform>().Where(t=>t.name=="WallIn_B_3x").ToArray();Assert.AreEqual(4,interiors.Length);
            for(int i=0;i<4;i++){Assert.AreEqual(originals[i].Item1,interiors[i].localPosition);Assert.AreEqual(originals[i].Item2,interiors[i].localRotation);Assert.AreEqual(originals[i].Item3,interiors[i].localScale);Assert.AreEqual(PrefabInstanceStatus.Connected,PrefabUtility.GetPrefabInstanceStatus(interiors[i].gameObject));}
            var again=ReferenceRoomFinish.Apply(root);Assert.AreEqual(0,((JArray)again["wall_changes"]).Count);Assert.AreEqual(receipt["tiles"].ToString(),again["tiles"].ToString());
            var groups=root.scene.GetRootGameObjects().Where(g=>g.name==ReferenceRoomFinish.CeilingGroup).ToArray();Assert.AreEqual(1,groups.Length);Assert.AreEqual(1,groups[0].transform.childCount);
            var renderer=groups[0].GetComponentInChildren<MeshRenderer>();Assert.That(renderer.bounds.min.y,Is.EqualTo((float)receipt["ceiling_underside_y_m"]).Within(.001));
            var floor=root.transform.GetChild(0).GetComponent<MeshRenderer>().bounds;Assert.That(renderer.bounds.size.x,Is.EqualTo(floor.size.x).Within(.001));Assert.That(renderer.bounds.size.z,Is.EqualTo(floor.size.z).Within(.001));
            Assert.True(groups[0].GetComponentsInChildren<MonoBehaviour>(true).Where(b=>b!=null&&b.GetType().FullName=="FS_Atmo.DisableAtStart").All(b=>!b.gameObject.activeSelf));
        }
        [Test]public void InvalidFloorLeavesWallFamilyAndExistingCeilingUnchanged(){
            var root=FinishFixture();var floor=root.transform.GetChild(0);var extra=ReferenceAssets.InstantiateAssembly(AssetDatabase.LoadAssetAtPath<GameObject>("Assets/AtmosphericHouse/Prefabs/Building/Floor_3x3.prefab"));extra.transform.SetParent(root.transform,false);extra.transform.position=floor.position+new Vector3(3,0,3);
            var existing=new GameObject(ReferenceRoomFinish.CeilingGroup);var child=new GameObject("Preserved");child.transform.SetParent(existing.transform);
            Assert.Throws<InvalidDataException>(()=>ReferenceRoomFinish.Apply(root));Assert.AreEqual(4,root.GetComponentsInChildren<Transform>().Count(t=>t.name=="WallIn_A_3x"));Assert.AreEqual(1,existing.transform.childCount);
        }
        [Test]public void MissingVariantRejectsBeforeReplacingAnyWall(){
            var root=FinishFixture();var path="Assets/AgentWorkspace/WallIn_A_missing_"+Guid.NewGuid().ToString("N")+".prefab";
            var obj=GameObject.CreatePrimitive(PrimitiveType.Cube);
            try{var source=PrefabUtility.SaveAsPrefabAsset(obj,path);UnityEngine.Object.DestroyImmediate(obj);var instance=(GameObject)PrefabUtility.InstantiatePrefab(source);instance.transform.SetParent(root.transform.GetChild(1),false);
                Assert.Throws<InvalidDataException>(()=>ReferenceRoomFinish.Apply(root));Assert.AreEqual(4,root.GetComponentsInChildren<Transform>().Count(t=>t.name=="WallIn_A_3x"));Assert.False(root.scene.GetRootGameObjects().Any(o=>o.name==ReferenceRoomFinish.CeilingGroup));
            }finally{if(obj!=null)UnityEngine.Object.DestroyImmediate(obj);AssetDatabase.DeleteAsset(path);}
        }
        [Test]public void ExplicitCeilingIsPreserved(){
            var root=FinishFixture();var ceiling=ReferenceAssets.InstantiateAssembly(AssetDatabase.LoadAssetAtPath<GameObject>("Assets/AtmosphericHouse/Prefabs/Building/Ceiling_3x3.prefab"));ceiling.transform.SetParent(root.transform,false);ceiling.transform.position=new Vector3(0,3,0);int id=ceiling.GetInstanceID();
            var result=ReferenceRoomFinish.Apply(root);Assert.AreEqual("explicit_plan_preserved",(string)result["ceiling"]);Assert.AreEqual(id,ceiling.GetInstanceID());Assert.AreEqual(new Vector3(0,3,0),ceiling.transform.position);Assert.False(root.scene.GetRootGameObjects().Any(o=>o.name==ReferenceRoomFinish.CeilingGroup));
        }
        [Test]public void AppPreparationIsClosedAndCannotBypassCommandOwnership(){
            var data=new JObject{["operation_id"]="operation-test",["project_id"]="project-test",["run_id"]=new string('a',32),["brief"]="Preserve this user brief",["building_policy"]="atmospheric-house",["interior_style"]="B",["ceiling_prefab"]="Ceiling_3x3",["media"]=new JArray(new JObject{["artifact_hash"]=new string('a',64),["extension"]=".png"})};
            AppCommandBridge.Validate(data);
            var before=File.ReadAllBytes(temporary);var command=new BridgeCommand{payload=data};Assert.Throws<InvalidOperationException>(()=>AppCommandBridge.Prepare(command));Assert.AreEqual(before,File.ReadAllBytes(temporary));
            data["script"]="forbidden";Assert.Throws<InvalidDataException>(()=>AppCommandBridge.Validate(data));data.Remove("script");
            data["media"][0]["artifact_hash"]="../../outside";Assert.Throws<InvalidDataException>(()=>AppCommandBridge.Validate(data));
        }
        [Test]public void NormalizedMatrixPoseMatchesPythonHash(){
            var value=BridgeJson.Read<JObject>("{\"value\":[0.0,0.0,-14.0,0.02]}");
            Assert.AreEqual("6a4a6779e53758141c194cee346a2ed500187e4d07625589cdced3d00798b64d",BridgeJson.CanonicalHash(value));
        }
        [Test]public void CaptureIdentityUsesRuntimeFloatsAcrossDecimalRoundTrip(){
            var original=JObject.Parse("{\"work_views\":[{\"key\":\"work\",\"position_m\":[0.123456789123,1,2],\"rotation_deg\":[0,0,0],\"fov_deg\":50}],\"width\":1280,\"height\":720}");
            var decimalRead=BridgeJson.Read<JObject>(original.ToString());
            Assert.AreEqual(BridgeJson.CanonicalHash(CaptureController.RuntimePlan(original)),BridgeJson.CanonicalHash(CaptureController.RuntimePlan(decimalRead)));
            decimalRead["work_views"][0]["position_m"][0]=.13;
            Assert.AreNotEqual(BridgeJson.CanonicalHash(CaptureController.RuntimePlan(original)),BridgeJson.CanonicalHash(CaptureController.RuntimePlan(decimalRead)));
        }
        [Test]public void NumericalProposalHashPreservesPythonDecimalText(){
            var value=BridgeJson.Read<JObject>("{\"value\":[0.15999999999999998,0.020000000000000004,1.2345678901234567]}");
            Assert.AreEqual("cb5ba6f05894c754fbd92a9918b3a26c7d5d330fad338767c83a9ddecdfcb940",BridgeJson.CanonicalHash(value));
        }
        [Test]public void CandidateCameraUsesRecordedPhysicalCaptureConditions(){
            var go=new GameObject("Protocol source camera");var source=go.AddComponent<Camera>();source.allowHDR=false;source.usePhysicalProperties=true;source.nearClipPlane=.3f;source.farClipPlane=1000;source.sensorSize=new Vector2(36,24);
            var hd=go.AddComponent<UnityEngine.Rendering.HighDefinition.HDAdditionalCameraData>();hd.antialiasing=UnityEngine.Rendering.HighDefinition.HDAdditionalCameraData.AntialiasingMode.None;hd.allowDynamicResolution=false;
            var protocol=JObject.FromObject(HdrpAgent.Runtime.ReferenceRenderProtocol.Read(source,"native_gameview"));protocol["exposure_mode"]="Fixed";protocol["tonemapping_mode"]="Neutral";
            UnityEngine.Object.DestroyImmediate(go);EditorSceneManager.SaveScene(SceneManager.GetActiveScene());
            ReferenceSceneBuilder.Build(Plan(),new JArray(),scope,Inspection(),null,protocol);
            var actual=Camera.main;Assert.False(actual.allowHDR);Assert.True(actual.usePhysicalProperties);Assert.AreEqual(.3f,actual.nearClipPlane);Assert.AreEqual(1000,actual.farClipPlane);Assert.AreEqual(new Vector2(36,24),actual.sensorSize);
            protocol["execute_script"]="forbidden";Assert.Throws<InvalidDataException>(()=>ReferenceFidelity.ValidateCaptureProtocol(protocol));
        }
        [Test]public void AuditSeparatesGlobalBiasFromRelativeSupportError(){
            var rows=new JArray();
            foreach(var entry in new[]{("floor",Vector3.zero),("prop",Vector3.up)}){
                Func<Vector3,JObject> pose=p=>new JObject{["position_m"]=JArray.FromObject(ReferenceAssets.Vec(p)),["rotation_deg"]=new JArray(0,0,0),["scale"]=new JArray(1,1,1)};
                var shift=new Vector3(.02f,-.23f,.04f);
                var row=ReferenceGroundTruthAudit.PoseDelta(entry.Item2,Quaternion.identity,Vector3.one,entry.Item2+shift,Quaternion.identity,Vector3.one);
                row["key"]=entry.Item1;row["source_pose"]=pose(entry.Item2);row["candidate_pose"]=pose(entry.Item2+shift);rows.Add(row);
            }
            var summary=ReferenceGroundTruthAudit.GroupErrors(rows,new JArray(new JObject{["object_key"]="prop",["support_key"]="floor"}));
            Assert.That((float)summary["median_position_delta_m"][1],Is.EqualTo(-.23f).Within(1e-6));
            Assert.That((float)summary["relative_to_support"][0]["position_error_m"],Is.LessThan(1e-6));
            Assert.True((bool)summary["evaluation_only"]);
        }
        [Test]public void EvidencedOffsetIsPreservedAndAmbiguousContactIsNotForced(){
            var root=new GameObject("Offset test root");
            try{
                var floor=GameObject.CreatePrimitive(PrimitiveType.Cube);floor.name="floor";floor.transform.SetParent(root.transform);floor.transform.position=new Vector3(0,-.1f,0);floor.transform.localScale=new Vector3(3,.2f,3);UnityEngine.Object.DestroyImmediate(floor.GetComponent<Collider>());
                var prop=GameObject.CreatePrimitive(PrimitiveType.Cube);prop.name="prop";prop.transform.SetParent(root.transform);prop.transform.localScale=Vector3.one*.2f;prop.transform.position=new Vector3(0,.2f,0);UnityEngine.Object.DestroyImmediate(prop.GetComponent<Collider>());
                var plan=new JObject{["objects"]=new JArray(new JObject{["key"]="floor",["position_m"]=new JArray(0,-.1,0)},new JObject{["key"]="prop",["position_m"]=new JArray(0,.2,0)})};
                var relation=new JObject{["object_key"]="prop",["support_key"]="floor",["contact_policy"]="offset_evidenced",["offset_m"]=.1,["evidence_hashes"]=new JArray(new string('a',64),new string('b',64))};
                var report=ReferenceContacts.Resolve(root,plan,new JArray(relation));
                Assert.True((bool)report["passed"]);Assert.AreEqual("offset_evidenced",(string)report["checks"][0]["status"]);Assert.That(prop.transform.position.y,Is.EqualTo(.2f).Within(.001));
                relation["contact_policy"]="unresolved";relation["offset_m"]=0;prop.transform.position=new Vector3(0,.4f,0);
                report=ReferenceContacts.Resolve(root,plan,new JArray(relation));Assert.False((bool)report["passed"]);Assert.AreEqual(.4f,prop.transform.position.y);
            }finally{UnityEngine.Object.DestroyImmediate(root);}
        }
        string original,temporary,scope;
        JObject Plan()=>JObject.Parse(@"{""objects"":[{""key"":""block"",""asset_id"":null,""primitive"":""cube"",""position_m"":[1,0.5,2],""rotation_deg"":[0,20,0],""scale"":[1,1,1],""base_color_rgba"":[0.4,0.2,0.1,1]}],""lights"":[{""type"":""spot"",""position_m"":[1,3,2],""rotation_deg"":[90,0,0],""intensity"":900,""color_rgb"":[1,0.9,0.8],""spot_angle_deg"":45}],""estimated_views"":null,""exposure_ev"":0,""sky_color_rgb"":[0.1,0.1,0.1],""fog_mean_free_path_m"":null,""notes"":[]}");
        JObject Inspection()=>JObject.Parse(@"{""work_views"":[{""key"":""front"",""position_m"":[0,2,-4],""rotation_deg"":[0,0,0],""fov_deg"":50}]}");
        [SetUp]public void SetUp(){original=SceneManager.GetActiveScene().path;scope="reference-test-"+Guid.NewGuid().ToString("N");temporary="Assets/AgentWorkspace/ReferenceTest-"+Guid.NewGuid().ToString("N")+".unity";var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);EditorSceneManager.SaveScene(scene,temporary);}
        [TearDown]public void TearDown(){EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);AssetDatabase.DeleteAsset(SnapshotStore.Root(scope));AssetDatabase.DeleteAsset(temporary);if(!string.IsNullOrEmpty(original))EditorSceneManager.OpenScene(original,OpenSceneMode.Single);}
        [Test]public void GroundTruthPoseMetricsMeasureTranslationRotationAndScale(){
            var exact=ReferenceGroundTruthAudit.PoseDelta(Vector3.zero,Quaternion.identity,Vector3.one,Vector3.zero,Quaternion.Euler(0,360,0),Vector3.one);Assert.True((bool)exact["within_pose_tolerance"]);
            var delta=ReferenceGroundTruthAudit.PoseDelta(Vector3.zero,Quaternion.identity,Vector3.one,new Vector3(.03f,0,.04f),Quaternion.Euler(0,90,0),new Vector3(1.2f,1,1));
            Assert.AreEqual(.05f,(float)delta["position_error_m"],.000001f);Assert.AreEqual(90,(float)delta["rotation_error_deg"],.001f);Assert.AreEqual(.2f,(float)delta["max_scale_error"],.000001f);Assert.False((bool)delta["within_pose_tolerance"]);
        }
        [UnityTest]public IEnumerator EditorVisionRendersWithoutPlayModeOrSceneMutation(){
            var path=ReferenceSceneBuilder.Build(Plan(),new JArray(),scope,Inspection());
            var material=GameObject.Find("block").GetComponent<MeshRenderer>().sharedMaterial;material.shader=Shader.Find("HDRP/Unlit");material.SetColor("_UnlitColor",Color.red);EditorUtility.SetDirty(material);AssetDatabase.SaveAssets();
            var shaderUtils=AppDomain.CurrentDomain.GetAssemblies().Select(a=>a.GetType("UnityEditor.Rendering.HighDefinition.HDShaderUtils")).First(t=>t!=null);
            shaderUtils.GetMethod("ResetMaterialKeywords").Invoke(null,new object[]{material});EditorUtility.SetDirty(material);AssetDatabase.SaveAssets();
            AssetDatabase.ImportAsset(AssetDatabase.GetAssetPath(material),ImportAssetOptions.ForceSynchronousImport|ImportAssetOptions.ForceUpdate);
            yield return null;yield return null;EditorSceneManager.SaveScene(SceneManager.GetActiveScene());
            var saved=File.ReadAllBytes(path);var version=SceneInspector.Version();
            var view=(JObject)Inspection()["work_views"][0].DeepClone();view["object_key"]="block";view["angle"]="front";
            var command=new JObject{["ordinal"]=0,["scene_path"]=path,["version"]=version,["views"]=new JArray(view),["objects"]=new JArray(new JObject{["key"]="block",["support_key"]=null,["residual"]=.2})};
            var destination=Path.Combine(Path.GetTempPath(),"hdrp-vision-test-"+Guid.NewGuid().ToString("N"));
            try{
                var invalid=(JObject)command.DeepClone();invalid["views"][0]["position_m"][0]=101;Assert.Throws<InvalidDataException>(()=>ReferenceVision.Begin(invalid,destination));Assert.False(Directory.Exists(destination));
                ReferenceVision.Begin(command,destination);var deadline=EditorApplication.timeSinceStartup+120;
                while(ReferenceVision.Running&&EditorApplication.timeSinceStartup<deadline)yield return null;
                Assert.False(ReferenceVision.Running);Assert.False(EditorApplication.isPlaying);Assert.False(SceneManager.GetActiveScene().isDirty);Assert.AreEqual(version,SceneInspector.Version());Assert.AreEqual(saved,File.ReadAllBytes(path));
                Assert.True(File.Exists(Path.Combine(destination,"result.json")),File.Exists(Path.Combine(destination,"interruption.json"))?File.ReadAllText(Path.Combine(destination,"interruption.json")):"Missing inspection result");
                var receipt=JObject.Parse(File.ReadAllText(Path.Combine(destination,"result.json")));Assert.AreEqual("editor_hdrp_probe",(string)receipt["mode"]);Assert.False((bool)receipt["performance_qualified"]);Assert.False((bool)receipt["gizmos_in_images"]);
                Assert.AreEqual(BridgeJson.Hash(File.ReadAllBytes(Path.Combine(destination,"view-00.png"))),(string)receipt["frames"][0]["sha256"]);
                var reports=Path.Combine(Directory.GetParent(Application.dataPath).Parent.Parent.FullName,".hdrp-agent","reports");Directory.CreateDirectory(reports);
                File.Copy(Path.Combine(destination,"view-00.png"),Path.Combine(reports,"reference-fidelity-raster-fixture.png"),true);
                ReferenceWorkflow.Atomic(Path.Combine(reports,"reference-fidelity-raster-fixture.json"),new JObject{["kind"]="synthetic_unlit_cube_visibility_fixture",["plan"]=Plan(),["view"]=Inspection()["work_views"][0],["native_receipt"]=receipt,["known_color"]="red",["evaluator_only"]=true});
                Assert.False(SceneManager.GetActiveScene().GetRootGameObjects().Any(go=>go.name=="Agent editor inspection camera"));
            }finally{ReferenceVision.Cancel("Test cleanup");if(Directory.Exists(destination))Directory.Delete(destination,true);}
        }
        [Test]public void UnknownAssetAndUnboundedValuesRefusedBeforeMutation(){
            var plan=Plan();plan["objects"][0]["asset_id"]="asset-invented";plan["objects"][0]["primitive"]=null;
            Assert.Throws<InvalidDataException>(()=>ReferenceSceneBuilder.Build(plan,new JArray(),scope,Inspection()));Assert.AreEqual(temporary,SceneManager.GetActiveScene().path);Assert.False(Directory.Exists(SnapshotStore.Root(scope)));
            plan=Plan();plan["objects"][0]["position_m"][0]=101;Assert.Throws<InvalidDataException>(()=>ReferenceSceneBuilder.Validate(plan,new JArray()));
            plan=Plan();plan["objects"][0]["scale"][1]=0;Assert.Throws<InvalidDataException>(()=>ReferenceSceneBuilder.Validate(plan,new JArray()));
        }
        [Test]public void DuplicateAndExecutableFieldsAreRefused(){var plan=Plan();((JArray)plan["objects"]).Add(plan["objects"][0].DeepClone());Assert.Throws<InvalidDataException>(()=>ReferenceSceneBuilder.Validate(plan,new JArray()));plan=Plan();plan["execute_script"]="forbidden";Assert.Throws<InvalidDataException>(()=>ReferenceSceneBuilder.Validate(plan,new JArray()));}
        [Test]public void ConnectedWallAssemblyPreservesCompanionAfterSaveReload(){
            const string path="Assets/AtmosphericHouse/Prefabs/Building/WallOut_3x.prefab";
            var source=AssetDatabase.LoadAssetAtPath<GameObject>(path);Assert.NotNull(source);
            var root=ReferenceAssets.InstantiateAssembly(source);root.name="Assembly fixture";
            Assert.AreEqual(path,PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(root));
            var companion=root.GetComponentsInChildren<Transform>().First(t=>t!=root.transform&&t.name=="WallIn_A_3x");
            Assert.AreEqual(new Vector3(-3,0,0),companion.localPosition);Assert.Less(Quaternion.Angle(Quaternion.Euler(0,180,0),companion.localRotation),.01);
            Assert.True(PrefabUtility.IsPartOfPrefabInstance(companion.gameObject));
            Assert.Greater(root.GetComponentsInChildren<Collider>(true).Length,0);
            EditorSceneManager.SaveScene(SceneManager.GetActiveScene());EditorSceneManager.OpenScene(temporary);
            root=GameObject.Find("Assembly fixture");Assert.AreEqual(PrefabInstanceStatus.Connected,PrefabUtility.GetPrefabInstanceStatus(root));
            Assert.AreEqual(1,root.GetComponentsInChildren<Transform>().Count(t=>t.name=="WallIn_A_3x"));
        }
        [Test]public void BareSixMetreExteriorGetsConnectedInwardFaceEvenWithOldEmptyCatalogue(){
            var source=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/AtmosphericHouse/Prefabs/Building/WallOut_6x.prefab");
            Assert.NotNull(source);var parent=new GameObject("Reconstruction fixture");
            var root=ReferenceAssets.InstantiateAssembly(source,new JArray());root.transform.SetParent(parent.transform);
            var child=root.GetComponentsInChildren<Transform>().Single(t=>t.name=="WallIn_B_6x");
            Assert.AreEqual(PrefabInstanceStatus.Connected,PrefabUtility.GetPrefabInstanceStatus(child.gameObject));
            Assert.AreEqual(new Vector3(-6,0,0),child.localPosition);Assert.Less(Quaternion.Angle(child.localRotation,Quaternion.Euler(0,180,0)),.01);
            var audit=ReferenceRoomAudit.Inspect(parent.transform,new Vector3(-3,1.5f,-2));
            Assert.AreEqual(1,((JArray)audit["walls"]).Count);Assert.False((bool)audit["walls"][0]["outward_axis_points_to_observer"]);
            var surface=((JArray)audit["walls"][0]["surfaces"]).Single(r=>((string)r["prefab"]).Contains("WallIn_B_6x"));
            Assert.Greater((double)surface["front_fraction_from_observer"],.9);
        }
        [Test]public void StaticCopyPreservesMeshAndTransformWithoutInstantiatingScripts(){
            var source=GameObject.CreatePrimitive(PrimitiveType.Cube);source.transform.localPosition=new Vector3(2,3,4);source.AddComponent<ReferenceTestBehaviour>();
            var clone=ReferenceAssets.CloneStatic(source);
            try{Assert.AreEqual(source.GetComponent<MeshFilter>().sharedMesh,clone.GetComponent<MeshFilter>().sharedMesh);Assert.AreEqual(source.transform.localPosition,clone.transform.localPosition);Assert.AreEqual(0,clone.GetComponentsInChildren<MonoBehaviour>(true).Length);}finally{UnityEngine.Object.DestroyImmediate(source);UnityEngine.Object.DestroyImmediate(clone);}
        }
        [Test]public void BuildsOwnedGeometryLightAndMaterialAndRefusesReplay(){
            var before=File.ReadAllBytes(temporary);var destination=ReferenceSceneBuilder.Build(Plan(),new JArray(),scope,Inspection());
            Assert.AreEqual(SnapshotStore.Root(scope)+"/Reconstruction.unity",destination);Assert.False(SceneManager.GetActiveScene().isDirty);
            var block=GameObject.Find("block");Assert.AreEqual(new Vector3(1,.5f,2),block.transform.position);Assert.AreEqual(900,GameObject.Find("Reference light").GetComponent<Light>().intensity);
            Assert.True(AssetDatabase.GetAssetPath(block.GetComponent<Renderer>().sharedMaterial).StartsWith(SnapshotStore.Root(scope)+"/Resources/"));Assert.AreEqual(before,File.ReadAllBytes(temporary));
            Assert.Throws<InvalidOperationException>(()=>ReferenceSceneBuilder.Build(Plan(),new JArray(),scope,Inspection()));
        }
        [Test]public void ContactSolverSettlesFurnitureThenContentsAndRemovesTemporaryColliders(){
            var root=new GameObject("Owned test reconstruction");
            Func<string,Vector3,Vector3,GameObject> cube=(key,pos,scale)=>{var go=GameObject.CreatePrimitive(PrimitiveType.Cube);go.name=key;go.transform.SetParent(root.transform);go.transform.position=pos;go.transform.localScale=scale;UnityEngine.Object.DestroyImmediate(go.GetComponent<Collider>());return go;};
            var floor=cube("floor",new Vector3(0,-.1f,0),new Vector3(4,.2f,4));
            var table=cube("table",new Vector3(0,.7f,0),new Vector3(1,1,1));
            var prop=cube("prop",new Vector3(0,1.5f,0),Vector3.one*.2f);
            var bin=cube("bin",new Vector3(1,.5f,0),Vector3.one*.6f);
            var plan=new JObject{["objects"]=new JArray(root.transform.Cast<Transform>().Select(t=>new JObject{["key"]=t.name,["position_m"]=JArray.FromObject(ReferenceAssets.Vec(t.position))}))};
            var supports=JArray.Parse(@"[{""object_key"":""prop"",""support_key"":""table""},{""object_key"":""table"",""support_key"":""floor""},{""object_key"":""bin"",""support_key"":null},{""object_key"":""floor"",""support_key"":null}]");
            var result=ReferenceContacts.Resolve(root,plan,supports);
            Assert.True((bool)result["passed"],result.ToString());Assert.AreEqual(.501f,table.transform.position.y,.0001f);Assert.AreEqual(1.102f,prop.transform.position.y,.0001f);Assert.AreEqual(.301f,bin.transform.position.y,.0001f);
            Assert.AreEqual(0,root.GetComponentsInChildren<Collider>().Length);Assert.AreEqual("inferred_candidate_floor",(string)((JArray)result["checks"]).Single(c=>(string)c["object_key"]=="bin")["evidence"]);
            Assert.AreEqual(prop.transform.position.y,(float)((JArray)plan["objects"]).Single(o=>(string)o["key"]=="prop")["position_m"][1],.00001f);
        }
        [Test]public void UnsupportedObjectsAndCyclicGraphsAreNotCertified(){
            var root=new GameObject("Owned unsupported test");var floor=GameObject.CreatePrimitive(PrimitiveType.Cube);floor.name="floor";floor.transform.SetParent(root.transform);var child=GameObject.CreatePrimitive(PrimitiveType.Cube);child.name="child";child.transform.SetParent(root.transform);child.transform.position=new Vector3(10,1,0);
            var plan=JObject.Parse(@"{""objects"":[{""key"":""floor"",""position_m"":[0,0,0]},{""key"":""child"",""position_m"":[10,1,0]}]}");
            var supports=JArray.Parse(@"[{""object_key"":""child"",""support_key"":""floor""},{""object_key"":""floor"",""support_key"":null}]");
            var report=ReferenceContacts.Resolve(root,plan,supports);Assert.False((bool)report["passed"]);Assert.AreEqual(new Vector3(10,1,0),child.transform.position);
            supports[1]["support_key"]="child";Assert.Throws<InvalidDataException>(()=>ReferenceContacts.Validate(supports,plan));
        }
        [Test]public void RecordingCoversFrontBackSidesAndOverheadWithoutExportingSourceObjects(){
            var camera=new GameObject("Reference Camera").AddComponent<Camera>();
            var plan=ReferenceWorkflow.CreateRecordingPlan(camera);var views=(JArray)plan["work_views"];
            Assert.AreEqual(8,views.Count);Assert.AreEqual(2,((JArray)plan["control_views"]).Count);
            var front=views.Single(v=>(string)v["key"]=="work-front");var back=views.Single(v=>(string)v["key"]=="work-back");
            var a=Quaternion.Euler(ReferenceSceneBuilder.Vector(front["rotation_deg"],-360,360))*Vector3.forward;var b=Quaternion.Euler(ReferenceSceneBuilder.Vector(back["rotation_deg"],-360,360))*Vector3.forward;
            Assert.Less(Vector3.Dot(new Vector3(a.x,0,a.z).normalized,new Vector3(b.x,0,b.z).normalized),-.99f);
            Assert.True(views.Any(v=>(string)v["key"]=="work-top-front"));Assert.False(plan.ToString().Contains("objects"));UnityEngine.Object.DestroyImmediate(camera.gameObject);
        }
        [Test]public void DetailCamerasZoomIntoImageRegionWithoutExportingInstanceIdentity(){
            var cube=GameObject.CreatePrimitive(PrimitiveType.Cube);cube.name="PRIVATE_SOURCE_IDENTITY";cube.transform.position=new Vector3(0,0,4);
            var camera=new GameObject("Region camera").AddComponent<Camera>();camera.transform.position=Vector3.zero;
            var overview=ReferenceWorkflow.CreateRecordingPlan(camera);
            // A known camera and its visible unit-cube region, not a source ID.
            overview["work_views"]=JArray.Parse(@"[{""key"":""front"",""position_m"":[0,0,0],""rotation_deg"":[0,0,0],""fov_deg"":60}]");
            var targets=JArray.Parse(@"[{""key"":""observed-object"",""view_boxes"":[{""view_key"":""front"",""bbox_xyxy"":[0.43,0.37,0.57,0.63]}]}]");
            EditorSceneManager.SaveScene(SceneManager.GetActiveScene());var preserved=File.ReadAllBytes(temporary);
            try{
                var details=ReferenceDetails.Plan(targets,overview);var views=(JArray)details["views"];Assert.AreEqual(3,views.Count);Assert.AreEqual("observed-object",(string)views[0]["object_key"]);
                float distance=(ReferenceSceneBuilder.Vector(views[0]["position_m"],-100,100)-cube.transform.position).magnitude;Assert.Less(distance,4);
                Assert.False(details.ToString().Contains("PRIVATE_SOURCE_IDENTITY"));Assert.False(details.ToString().Contains("asset_id"));Assert.AreEqual("back",(string)views[1]["angle"]);Assert.AreEqual("top",(string)views[2]["angle"]);
                Assert.False(SceneManager.GetActiveScene().GetRootGameObjects().Any(go=>go.name=="Anonymous image region camera"));
                Assert.False(SceneManager.GetActiveScene().isDirty);Assert.AreEqual(preserved,File.ReadAllBytes(temporary));
            }finally{UnityEngine.Object.DestroyImmediate(camera.gameObject);UnityEngine.Object.DestroyImmediate(cube);}
        }
    }
    public sealed class ReferenceTestBehaviour:MonoBehaviour{}
}
