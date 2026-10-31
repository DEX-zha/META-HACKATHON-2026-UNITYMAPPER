using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    // Evaluation only. No workflow/planner calls this class or reads its output.
    public static class ReferenceGroundTruthAudit
    {
        public static JObject PoseDelta(Vector3 expectedPosition,Quaternion expectedRotation,Vector3 expectedScale,Vector3 actualPosition,Quaternion actualRotation,Vector3 actualScale){
            var delta=actualPosition-expectedPosition;var scale=actualScale-expectedScale;float angle=Quaternion.Angle(expectedRotation,actualRotation);
            return new JObject{["position_delta_m"]=JArray.FromObject(ReferenceAssets.Vec(delta)),["position_error_m"]=delta.magnitude,["rotation_error_deg"]=angle,["scale_delta"]=JArray.FromObject(ReferenceAssets.Vec(scale)),["max_scale_error"]=Mathf.Max(Mathf.Abs(scale.x),Mathf.Abs(scale.y),Mathf.Abs(scale.z)),["within_pose_tolerance"]=delta.magnitude<=.001f&&angle<=.1f&&Mathf.Max(Mathf.Abs(scale.x),Mathf.Abs(scale.y),Mathf.Abs(scale.z))<=.001f};
        }
        static JObject Pose(Transform t)=>new JObject{["position_m"]=JArray.FromObject(ReferenceAssets.Vec(t.position)),["rotation_deg"]=JArray.FromObject(ReferenceAssets.Vec(t.eulerAngles)),["scale"]=JArray.FromObject(ReferenceAssets.Vec(t.lossyScale))};
        static Vector3 Vector(JToken t)=>new Vector3((float)t[0],(float)t[1],(float)t[2]);
        static float Median(float[] values){var sorted=values.OrderBy(x=>x).ToArray();return sorted.Length%2==1?sorted[sorted.Length/2]:(sorted[sorted.Length/2-1]+sorted[sorted.Length/2])*.5f;}
        public static JObject GroupErrors(JArray rows,JArray contacts){
            var matched=rows.OfType<JObject>().ToDictionary(r=>(string)r["key"]);var relative=new JArray();
            foreach(JObject contact in contacts){
                var key=(string)contact["object_key"];var support=(string)contact["support_key"];
                if(key==null||support==null||!matched.ContainsKey(key)||!matched.ContainsKey(support)){relative.Add(new JObject{["object_key"]=key,["support_key"]=support,["qualified"]=false,["reason"]="missing_unique_source_mapping"});continue;}
                var child=matched[key];var parent=matched[support];var sourceParent=parent["source_pose"];var actualParent=parent["candidate_pose"];
                var expected=Quaternion.Inverse(Quaternion.Euler(Vector(sourceParent["rotation_deg"])))*(Vector(child["source_pose"]["position_m"])-Vector(sourceParent["position_m"]));
                var actual=Quaternion.Inverse(Quaternion.Euler(Vector(actualParent["rotation_deg"])))*(Vector(child["candidate_pose"]["position_m"])-Vector(actualParent["position_m"]));
                var delta=actual-expected;
                relative.Add(new JObject{["object_key"]=key,["support_key"]=support,["qualified"]=true,["frame"]="support rotation, metre distances without parent scale normalization",["position_delta_m"]=JArray.FromObject(ReferenceAssets.Vec(delta)),["position_error_m"]=delta.magnitude});
            }
            var bias=rows.Count==0?null:new JArray(Enumerable.Range(0,3).Select(axis=>Median(rows.Select(r=>(float)r["position_delta_m"][axis]).ToArray())));
            return new JObject{["median_position_delta_m"]=bias,["matched_count"]=rows.Count,["relative_to_support"]=relative,["evaluation_only"]=true};
        }
        public static string AuditSavedReference(){
            if(ReferenceWorkflow.Running||ReferenceVision.Running||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning||SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("Wait for a completed, saved reconstruction before ground-truth evaluation");
            var directory=ReferenceWorkflow.LastDirectory;var report=JObject.Parse(File.ReadAllText(Path.Combine(directory,"report.json")));var job=(JObject)report["job"];
            if((string)job["bundle"]?["kind"]!="recorded")throw new InvalidDataException("An imported image has no Unity ground-truth source scene; pose audit is unavailable");
            if((string)job["state"]!="completed")throw new InvalidDataException("Ground truth is evaluation of a completed run only");
            var best=(int)(job["retained_ordinal"]??job["best_ordinal"]);var attempt=((JArray)job["attempts"]).OfType<JObject>().Single(a=>(int)a["ordinal"]==best);
            var active=SceneManager.GetActiveScene();if(active.path!=(string)attempt["native"]["scene_path"]||SceneInspector.Version()!=(string)attempt["native"]["version"])throw new InvalidDataException("Activate the retained, unchanged candidate first");
            var preserved=JObject.Parse(File.ReadAllText(Path.Combine(directory,"source-private.json")));var sourcePath=(string)preserved["source_scene"];
            if(!sourcePath.StartsWith("Assets/AgentWorkspace/References/",StringComparison.Ordinal)||BridgeJson.Hash(File.ReadAllBytes(sourcePath))!=(string)preserved["source_scene_sha256"])throw new InvalidDataException("Preserved source changed");
            var catalogue=JArray.Parse(File.ReadAllText(Path.Combine(directory,"catalogue.json")));var before=BridgeJson.Hash(File.ReadAllBytes(active.path));var source=EditorSceneManager.OpenPreviewScene(sourcePath);
            var rows=new JArray();var unmatched=new JArray();
            try{
                var sourceRoots=source.GetRootGameObjects().SelectMany(go=>go.GetComponentsInChildren<Transform>(true)).Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)).ToArray();
                var root=active.GetRootGameObjects().Single(go=>go.name=="Reconstruction").transform;
                foreach(JObject item in (JArray)attempt["applied_plan"]["objects"]){
                    if(item["asset_id"].Type==JTokenType.Null){unmatched.Add(new JObject{["key"]=item["key"],["reason"]="Generated primitive: no unique source prefab identity"});continue;}
                    var asset=catalogue.OfType<JObject>().Single(a=>(string)a["asset_id"]==(string)item["asset_id"]);var assetPath=(string)asset["path"];
                    var matches=sourceRoots.Where(t=>PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)==assetPath).ToArray();
                    if(matches.Length!=1){unmatched.Add(new JObject{["key"]=item["key"],["reason"]=matches.Length==0?"No source instance for selected prefab":"Ambiguous repeated source prefab",["source_match_count"]=matches.Length});continue;}
                    var actual=root.Cast<Transform>().Single(t=>t.name==(string)item["key"]);var expected=matches[0];var row=PoseDelta(expected.position,expected.rotation,expected.lossyScale,actual.position,actual.rotation,actual.lossyScale);
                    row["key"]=item["key"].DeepClone();row["asset_name"]=asset["name"].DeepClone();row["source_pose"]=Pose(expected);row["candidate_pose"]=Pose(actual);rows.Add(row);
                }
            }finally{EditorSceneManager.ClosePreviewScene(source);}
            if(active.isDirty||BridgeJson.Hash(File.ReadAllBytes(active.path))!=before||BridgeJson.Hash(File.ReadAllBytes(sourcePath))!=(string)preserved["source_scene_sha256"])throw new InvalidDataException("Scene changed during evaluation");
            var value=new JObject{["kind"]="post_run_ground_truth_pose_audit",["run_id"]=job["id"],["candidate_ordinal"]=best,["evaluated_utc"]=DateTime.UtcNow.ToString("o"),["source_sha256"]=preserved["source_scene_sha256"],["candidate_scene"]=active.path,["source_transforms_used_for_inference"]=false,["mapping"]="Unique source prefab asset identity; repeated or absent instances are unqualified",["tolerances"]=new JObject{["position_m"]=.001,["rotation_deg"]=.1,["scale_absolute"]=.001},["objects"]=rows,["unqualified_objects"]=unmatched,["matched_objects_passed"]=rows.Count>0&&rows.All(r=>(bool)r["within_pose_tolerance"]),["exact_fidelity_verified"]=false,["limits"]="Pose audit only. Generated primitives and ambiguous instances are not certified. Materials, lighting, appearance, occlusion and mesh deformation require independent checks."};
            value["group_errors"]=GroupErrors(rows,(JArray)attempt["native"]["contacts"]["checks"]);
            var workspace=Directory.GetParent(Application.dataPath).Parent.Parent.FullName;var destination=Path.Combine(workspace,".hdrp-agent","reports","ground-truth-"+(string)job["id"]+".json");ReferenceWorkflow.Atomic(destination,value);return destination;
        }
    }
}
