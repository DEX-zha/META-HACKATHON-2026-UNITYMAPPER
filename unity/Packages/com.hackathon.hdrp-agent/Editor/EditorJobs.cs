using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    [InitializeOnLoad]
    public static class EditorJobs
    {
        static EditorJobs(){foreach(var kind in new[]{"inspect","snapshot","apply_patch","restore","bake","capture","prepare_reference_run"})CommandExecutor.Register(kind,c=>new Job(c));}
        sealed class Upload{public byte[] bytes;public string path,type;public Action<string> accept;}
        sealed class Job:ICommandJob
        {
            readonly BridgeCommand command;
            readonly string before;
            readonly List<Upload> uploads=new List<Upload>();
            readonly List<string> hashes=new List<string>();
            bool begun,prepared,uploading,cancelled;
            int next;
            BakeJob bake;
            string captureDirectory,snapshotId,detailsHash;
            JObject details;
            JArray captures=new JArray();
            public CommandResult Result{get;private set;}
            public Job(BridgeCommand command){this.command=command;before=SceneInspector.Version();}
            public void Cancel(){cancelled=true;bake?.Cancel();if(command.kind=="prepare_reference_run")ReferenceWorkflow.Stop();if(command.kind=="capture"&&EditorApplication.isPlaying)EditorApplication.isPlaying=false;}
            void Add(JObject value){uploads.Add(new Upload{bytes=Encoding.UTF8.GetBytes(value.ToString(Newtonsoft.Json.Formatting.None)),type="application/json",accept=h=>detailsHash=h});}
            void Fail(string code,string message,string status="failed"){
                Result=new CommandResult{command_id=command.id,bridge_epoch=command.bridge_epoch,payload_hash=command.payload_hash,before_version=before,after_version=SceneInspector.Version(),status=status,manifest_hash=SnapshotStore.ManifestHash(SceneInspector.Scope),error=new BridgeError{code=code,message=message,command_id=command.id}};
            }
            public void Tick(){
                if(Result!=null)return;
                if(cancelled&&(bake==null||bake.Finished)&&!EditorApplication.isPlayingOrWillChangePlaymode){Fail("CANCELLED","Operation stopped; inspect known changes before recovery","cancelled");return;}
                if(!begun){
                    if(BridgeClient.RequestInProgress)return;
                    begun=true;
                    switch(command.kind){
                        case "prepare_reference_run":details=AppCommandBridge.Prepare(command);prepared=true;break;
                        case "inspect":details=SceneInspector.Inspect();prepared=true;break;
                        case "snapshot":if((string)command.payload["scope_id"]!=SceneInspector.Scope)throw new InvalidDataException("Snapshot scope mismatch");var snapshot=SnapshotStore.Take(SceneInspector.Scope);snapshotId=snapshot.id;details=JObject.FromObject(snapshot);prepared=true;break;
                        case "apply_patch":var needsBake=PatchExecutor.Apply(command.payload,command.expected_version);details=JObject.FromObject(new{schema_version="1.0",before_version=before,after_version=SceneInspector.Version(),needs_bake=needsBake,operations=command.payload["operations"]});prepared=true;break;
                        case "restore":var saved=SnapshotStore.Load((string)command.payload["snapshot_id"]);if(saved.scope_id!=SceneInspector.Scope)throw new InvalidDataException("Snapshot belongs to another scope");SnapshotStore.Restore(saved,(string)command.payload["expected_manifest_hash"]);snapshotId=saved.id;details=JObject.FromObject(new{schema_version="1.0",restored_snapshot=snapshotId,manifest_hash=SnapshotStore.ManifestHash(SceneInspector.Scope)});prepared=true;break;
                        case "bake":if((string)command.payload["lightmapper"]!="progressive_gpu")throw new InvalidDataException("Unsupported bake backend");bake=BakeController.Begin((int)command.payload["timeout_seconds"]);break;
                        case "capture":
                            BridgeClient.Request("GET","/v1/artifacts/"+(string)command.payload["inspection_hash"],null,null,(ok,text)=>{
                                if(!ok){Fail("CAPABILITY_MISSING","Frozen inspection plan could not be read");return;}
                                try{var plan=JObject.Parse(text);if(BridgeJson.CanonicalHash(plan)!=(string)command.payload["inspection_hash"])throw new InvalidDataException("Inspection plan hash mismatch");captureDirectory=CaptureController.Begin(plan,true);}catch(Exception){Fail("CAPTURE_UNSTABLE","Capture preparation failed");}
                            });break;
                    }
                }
                if(bake!=null&&!prepared){if(!bake.Finished)return;if(!bake.Succeeded){Fail("BAKE_INCOMPLETE",bake.Error);return;}details=bake.Journal;prepared=true;}
                if(command.kind=="capture"&&!prepared){
                    if(string.IsNullOrEmpty(captureDirectory)||EditorApplication.isPlayingOrWillChangePlaymode)return;
                    if(File.Exists(Path.Combine(captureDirectory,"interruption.json"))){Fail("CAPTURE_UNSTABLE","Graphical capture was interrupted; no complete evidence produced");return;}
                    var proofPath=Path.Combine(captureDirectory,"editor-proof.json");if(!File.Exists(proofPath))return;
                    var manifest=JObject.Parse(File.ReadAllText(Path.Combine(captureDirectory,"manifest.json")));var proof=JObject.Parse(File.ReadAllText(proofPath));
                    if((string)manifest["status"]!="complete"||(string)manifest["version_id"]!=before||(string)proof["scene_version_after"]!=before){Fail("CAPTURE_UNSTABLE","Capture did not preserve the requested scene version");return;}
                    foreach(var item in (JArray)manifest["frames"]){
                        var frame=(JObject)item;var name=(string)frame["file"];if(Path.GetFileName(name)!=name)throw new InvalidDataException("Invalid frame path");
                        uploads.Add(new Upload{path=Path.Combine(captureDirectory,name),type="image/png",accept=hash=>{
                            var role=(string)frame["role"];var requested=(string)command.payload["role"];if(requested!="all"&&role!=requested)return;
                            captures.Add(new JObject{["artifact_hash"]=hash,["version_id"]=before,["inspection_hash"]=manifest["inspection_hash"],["conditions_hash"]=manifest["conditions_hash"],["role"]=role,["camera_key"]=frame["camera_key"],["frame_index"]=frame["frame_index"],["simulated_time"]=frame["simulated_time"],["render_ready"]=true,["provenance"]="live"});
                        }});
                    }
                    details=new JObject{["schema_version"]="1.0",["manifest"]=manifest,["editor_proof"]=proof,["request"]=JObject.Parse(File.ReadAllText(Path.Combine(captureDirectory,"request.json")))};prepared=true;
                }
                if(!prepared||uploading||BridgeClient.RequestInProgress)return;
                if(details!=null){Add(details);details=null;}
                if(next<uploads.Count){
                    var upload=uploads[next];var bytes=upload.bytes??File.ReadAllBytes(upload.path);uploading=true;
                    BridgeClient.PutArtifact(bytes,upload.type,(ok,hash)=>{uploading=false;if(!ok){Fail("ARTIFACT_UPLOAD_FAILED","Durable evidence could not be acknowledged","unknown");return;}hashes.Add(hash);upload.accept?.Invoke(hash);next++;});return;
                }
                Result=new CommandResult{command_id=command.id,bridge_epoch=command.bridge_epoch,payload_hash=command.payload_hash,status="succeeded",before_version=before,after_version=SceneInspector.Version(),artifact_hashes=hashes.ToArray(),captures=captures,snapshot_id=snapshotId,manifest_hash=SnapshotStore.ManifestHash(SceneInspector.Scope),bake_status=bake!=null?"complete":"not_required",details_artifact_hash=detailsHash};
            }
        }
    }
}
