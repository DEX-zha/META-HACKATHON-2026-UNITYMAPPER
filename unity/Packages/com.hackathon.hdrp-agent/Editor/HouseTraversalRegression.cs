using System;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEditor;
using UnityEngine.SceneManagement;
using UnityEditor.SceneManagement;
namespace HdrpAgent.Editor {
public static class HouseTraversalRegression {
 [MenuItem("Tools/HDRP Agent/House/Run traversal regression")]
 public static void Run(){
  var original=SceneManager.GetActiveScene();bool dirty=original.isDirty;var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);SceneManager.SetActiveScene(scene);var results=new JArray();
  try{
   var root=new GameObject("Traversal regression");var floor=Cube(root,"room-floor",new Vector3(3,-.1f,1.5f),new Vector3(6,.2f,3));
   var manifest=JObject.Parse("{\"building\":{\"rooms\":[{\"id\":\"room\",\"polygon\":[[0,0],[6,0],[6,3],[0,3]]}]},\"access\":[{\"room_id\":\"room\",\"points\":[[0.75,1.5],[5.25,1.5]]}]}");
   Check(results,"supported_open_path",root,manifest,true);
   var blocker=Cube(root,"blocked-door",new Vector3(3,1.5f,1.5f),new Vector3(.2f,3,3));Check(results,"wall_blocks_passage",root,manifest,false);UnityEngine.Object.DestroyImmediate(blocker);
   // The same proxy type used by the builder handles assets without authored colliders.
   UnityEngine.Object.DestroyImmediate(floor.GetComponent<BoxCollider>());floor.AddComponent<MeshCollider>().sharedMesh=floor.GetComponent<MeshFilter>().sharedMesh;Check(results,"mesh_support_without_authored_collider",root,manifest,true);
   UnityEngine.Object.DestroyImmediate(floor);Check(results,"missing_floor_rejected",root,manifest,false);
  }catch(Exception e){results.Add(new JObject{["case"]="exception",["passed"]=false,["message"]=e.Message});}
  finally{EditorSceneManager.CloseScene(scene,true);SceneManager.SetActiveScene(original);results.Add(new JObject{["case"]="source_scene_preserved",["passed"]=original.isDirty==dirty});ReferenceWorkflow.Atomic(Path.Combine(BridgeClient.ResolveWorkspace(),".hdrp-agent/house/traversal-regression.json"),new JObject{["created_at"]=DateTime.UtcNow.ToString("o"),["cases"]=results});}
 }
 static GameObject Cube(GameObject root,string name,Vector3 position,Vector3 size){var go=GameObject.CreatePrimitive(PrimitiveType.Cube);go.name=name;go.layer=30;go.transform.SetParent(root.transform,false);go.transform.position=position;go.transform.localScale=size;return go;}
 static void Check(JArray results,string name,GameObject root,JObject manifest,bool expected){Physics.SyncTransforms();var proof=HouseTraversal.Check(root,manifest);results.Add(new JObject{["case"]=name,["passed"]=(bool)proof["passed"]==expected,["expected_traversable"]=expected,["proof"]=proof});}
}
}
