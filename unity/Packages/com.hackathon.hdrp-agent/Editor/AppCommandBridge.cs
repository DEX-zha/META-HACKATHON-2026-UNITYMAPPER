using System;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
    // Model arguments never contain local paths or executable code.
    public static class AppCommandBridge {
        public static void Validate(JObject value){
            BridgeJson.Closed(value,"operation_id","run_id","project_id","brief","media","building_policy","interior_style","ceiling_prefab");
            foreach(var key in new[]{"operation_id","project_id"})if(value[key]?.Type!=JTokenType.String||!Regex.IsMatch((string)value[key],"^[A-Za-z0-9_.:-]{1,128}$"))throw new InvalidDataException("Invalid admission identity");
            if(value["run_id"]?.Type!=JTokenType.String||!Regex.IsMatch((string)value["run_id"],"^[a-f0-9]{32}$"))throw new InvalidDataException("Invalid run identity");
            if(value["brief"]?.Type!=JTokenType.String||((string)value["brief"]).Length>16000)throw new InvalidDataException("Invalid brief");
            if((string)value["building_policy"]!="atmospheric-house"||(string)value["ceiling_prefab"]!="Ceiling_3x3"||!new[]{"A","B","C"}.Contains((string)value["interior_style"]))throw new InvalidDataException("Unknown building policy");
            var media=value["media"] as JArray;if(media==null||media.Count<1||media.Count>3)throw new InvalidDataException("One video or up to three images required");
            foreach(var item in media){var row=item as JObject;if(row==null)throw new InvalidDataException("Invalid media");BridgeJson.Closed(row,"artifact_hash","extension");
                if(row["artifact_hash"]?.Type!=JTokenType.String||!Regex.IsMatch((string)row["artifact_hash"],"^[a-f0-9]{64}$")||!new[]{".png",".jpg",".mp4"}.Contains((string)row["extension"]))throw new InvalidDataException("Invalid media identity");
                if((string)row["extension"]==".mp4"&&media.Count!=1)throw new InvalidDataException("Only one video supported");
            }
        }
        public static JObject Prepare(BridgeCommand command){
            Validate(command.payload);
            if(!CommandExecutor.Owns(command)||command.bridge_epoch!=BridgeClient.Epoch||(string)command.payload["project_id"]!=BridgeClient.ProjectId||command.session_id!="reference-"+(string)command.payload["run_id"])throw new InvalidOperationException("Preparation ownership mismatch");
            if(command.expected_version!=SceneInspector.Version()||SceneManager.GetActiveScene().isDirty||ReferenceWorkflow.Running||ReferenceVision.Running||EditorApplication.isPlayingOrWillChangePlaymode)throw new InvalidOperationException("Save the scene and wait for the current operation");
            var workspace=BridgeClient.ResolveWorkspace();var run=(string)command.payload["run_id"];
            if(Directory.Exists(Path.Combine(workspace,".hdrp-agent","reconstructions",run)))throw new InvalidOperationException("Run already exists; no replay");
            var media=(JArray)command.payload["media"];var contents=media.Select(item=>{
                var hash=(string)item["artifact_hash"];var path=Path.Combine(workspace,".hdrp-agent","artifacts",hash.Substring(0,2),hash);if(new FileInfo(path).Length>((string)item["extension"]==".mp4"?20000000:10000000))throw new InvalidDataException("Media too large");var data=File.ReadAllBytes(path);
                if(data.Length>((string)item["extension"]==".mp4"?20000000:10000000)||BridgeJson.Hash(data)!=hash)throw new InvalidDataException("Media hash or size mismatch");return data;
            }).ToArray();
            var temp=Path.Combine(workspace,".hdrp-agent","app-inputs",run);if(Directory.Exists(temp))throw new InvalidOperationException("Preparation input already exists");Directory.CreateDirectory(temp);
            var paths=new string[media.Count];for(int i=0;i<paths.Length;i++){paths[i]=Path.Combine(temp,"input-"+i+(string)media[i]["extension"]);File.WriteAllBytes(paths[i],contents[i]);}
            // Keep immutable preparation inputs on failure for reconciliation.
            return ReferenceWorkflow.PrepareAdmitted(command,paths);
        }
    }
}
