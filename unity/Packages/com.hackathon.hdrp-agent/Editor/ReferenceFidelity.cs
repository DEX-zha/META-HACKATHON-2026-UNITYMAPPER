using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace HdrpAgent.Editor
{
    public static class ReferenceFidelity
    {
        public static void ValidateCaptureProtocol(JObject protocol){
            var fields=new[]{"schema_version","render_path","unity_version","graphics_api","pipeline_asset","hdr","physical_camera","custom_frame_settings","dynamic_resolution","near_clip","far_clip","focal_length","sensor_size","lens_shift","viewport","gate_fit","culling_mask","volume_layer_mask","clear_mode","anti_aliasing","frame_settings","frame_overrides","exposure_mode","tonemapping_mode"};
            var version=(string)protocol["schema_version"];if(version!="1.0"&&version!="1.1")throw new InvalidDataException("Unknown capture protocol");
            BridgeJson.Closed(protocol,version=="1.1"?fields.Concat(new[]{"background_rgba"}).ToArray():fields);
            if((string)protocol["render_path"]!="native_gameview"||(string)protocol["unity_version"]!=UnityEngine.Application.unityVersion||(string)protocol["graphics_api"]!=UnityEngine.SystemInfo.graphicsDeviceType.ToString()||(string)protocol["anti_aliasing"]!="None"||(bool)protocol["dynamic_resolution"])throw new InvalidDataException("Incompatible native capture protocol");
            foreach(var key in new[]{"hdr","physical_camera","custom_frame_settings","dynamic_resolution"})if(protocol[key].Type!=JTokenType.Boolean)throw new InvalidDataException("Boolean camera condition required");
            ReferenceSceneBuilder.Number(protocol["near_clip"],.001f,100);ReferenceSceneBuilder.Number(protocol["far_clip"],.01f,10000);ReferenceSceneBuilder.Number(protocol["focal_length"],1,1000);
            if((float)protocol["far_clip"]<=(float)protocol["near_clip"])throw new InvalidDataException("Invalid camera clipping range");
            foreach(var spec in new[]{("sensor_size",2,1f,100f),("lens_shift",2,-2f,2f),("viewport",4,0f,1f)}){
                var values=protocol[spec.Item1] as JArray;if(values==null||values.Count!=spec.Item2)throw new InvalidDataException("Invalid camera vector");foreach(var value in values)ReferenceSceneBuilder.Number(value,spec.Item3,spec.Item4);
            }
            if(version=="1.1"){var color=protocol["background_rgba"] as JArray;if(color==null||color.Count!=4)throw new InvalidDataException("Invalid clear color");foreach(var value in color)ReferenceSceneBuilder.Number(value,0,10000);}
            foreach(var key in new[]{"frame_settings","frame_overrides"}){var raw=(string)protocol[key];if(raw==null||raw.Length>5000)throw new InvalidDataException("Unbounded frame settings");JObject.Parse(raw);}
            var typed=UnityEngine.JsonUtility.FromJson<HdrpAgent.Runtime.ReferenceRenderProtocol>(protocol.ToString());
            if(!Enum.IsDefined(typeof(UnityEngine.Camera.GateFitMode),typed.gate_fit)||!Enum.TryParse<UnityEngine.Rendering.HighDefinition.HDAdditionalCameraData.ClearColorMode>(typed.clear_mode,out _)||!Enum.TryParse<UnityEngine.Rendering.HighDefinition.TonemappingMode>(typed.tonemapping_mode,out _))throw new InvalidDataException("Unknown camera or tonemapping mode");
        }
        public static void ValidateCommand(JObject command,JObject policy,string expectedVersion){
            var fields=new[]{"schema_version","ordinal","input_bundle_sha256","catalogue_sha256","plan","inspection","supports","expected_version","policy_hash","proposal"};
            BridgeJson.Closed(command,command.Property("capture_protocol")==null?fields:fields.Concat(new[]{"capture_protocol"}).ToArray());
            if(command.Property("capture_protocol")!=null)ValidateCaptureProtocol((JObject)command["capture_protocol"]);
            BridgeJson.Closed(policy,"schema_version","solver_version","max_candidates","max_seconds","max_local_evaluations","max_local_seconds","max_images","max_inspection_views","min_geometry_views","min_anchor_views","minimum_geometry_gain","object_regression_bound","view_regression_bound","geometry_iou_gate","geometry_contour_gate_px","scale_change_bound","scale_mode","noise_baseline_hash");
            if((string)command["schema_version"]!="2.0"||(string)command["expected_version"]!=expectedVersion||(string)command["policy_hash"]!=BridgeJson.CanonicalHash(policy))throw new InvalidDataException("Fidelity policy/version differs");
            if((string)policy["schema_version"]!="1.0"||!new[]{"fidelity-1","fidelity-2","fidelity-3","fidelity-4","fidelity-5"}.Contains((string)policy["solver_version"]))throw new InvalidDataException("Unknown fidelity solver");
            foreach(var pair in new[]{("max_candidates",6f),("max_seconds",2400f),("max_local_evaluations",2000f),("max_local_seconds",120f),("max_images",12f),("max_inspection_views",8f)}){
                if(policy[pair.Item1]?.Type!=JTokenType.Integer)throw new InvalidDataException("Integer limit required");ReferenceSceneBuilder.Number(policy[pair.Item1],1,pair.Item2);
            }
            ReferenceSceneBuilder.Number(policy["max_seconds"],1200,2400);
            foreach(var pair in new[]{("min_geometry_views",2f),("min_anchor_views",3f)}){
                if(policy[pair.Item1]?.Type!=JTokenType.Integer)throw new InvalidDataException("Integer view count required");ReferenceSceneBuilder.Number(policy[pair.Item1],pair.Item2,8);
            }
            foreach(var field in new[]{"object_regression_bound","view_regression_bound"})ReferenceSceneBuilder.Number(policy[field],0,.1f);
            ReferenceSceneBuilder.Number(policy["minimum_geometry_gain"],.0001f,.1f);ReferenceSceneBuilder.Number(policy["geometry_iou_gate"],.9f,1);
            ReferenceSceneBuilder.Number(policy["geometry_contour_gate_px"],0,5);ReferenceSceneBuilder.Number(policy["scale_change_bound"],0,.15f);
            if(!new[]{"locked","evidenced"}.Contains((string)policy["scale_mode"]))throw new InvalidDataException("Unknown scale policy");
            Func<JToken,bool> hash=t=>t?.Type==JTokenType.String&&System.Text.RegularExpressions.Regex.IsMatch((string)t,"^[a-f0-9]{64}$");
            if(policy["noise_baseline_hash"].Type!=JTokenType.Null&&!hash(policy["noise_baseline_hash"]))throw new InvalidDataException("Invalid noise evidence hash");
            var proposal=command["proposal"] as JObject??throw new InvalidDataException("Proposal evidence missing");
            BridgeJson.Closed(proposal,"schema_version","proposal_id","origin","phase","parent_version","policy_hash","proposed_plan_hash","evidence_hashes");
            if((string)proposal["schema_version"]!="1.0"||(string)proposal["parent_version"]!=expectedVersion||(string)proposal["policy_hash"]!=(string)command["policy_hash"]||(string)proposal["proposed_plan_hash"]!=BridgeJson.CanonicalHash(command["plan"]))throw new InvalidDataException("Proposal does not describe the applied experiment");
            if(!new[]{"baseline","local","muse"}.Contains((string)proposal["origin"])||!new[]{"baseline","anchoring","arranging","scaling","placement","appearance"}.Contains((string)proposal["phase"]))throw new InvalidDataException("Unknown proposal phase");
            if(proposal["proposal_id"]?.Type!=JTokenType.String||string.IsNullOrWhiteSpace((string)proposal["proposal_id"])||((string)proposal["proposal_id"]).Length>200)throw new InvalidDataException("Invalid proposal identity");
            var evidence=proposal["evidence_hashes"] as JArray;if(evidence==null||evidence.Count==0||evidence.Count>12||evidence.Any(t=>!hash(t)))throw new InvalidDataException("Invalid proposal evidence hashes");
        }
    }
}
