using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace HdrpAgent.Editor
{
    public static class BridgeJson
    {
        public static readonly JsonSerializerSettings Settings = new JsonSerializerSettings {
            MissingMemberHandling = MissingMemberHandling.Error, DateParseHandling = DateParseHandling.None,
            FloatParseHandling = FloatParseHandling.Decimal, Culture = CultureInfo.InvariantCulture,
            NullValueHandling = NullValueHandling.Include
        };
        public static T Read<T>(string text) => JsonConvert.DeserializeObject<T>(text, Settings);
        public static string Write(object value) => JsonConvert.SerializeObject(value, Settings);
        public static void Closed(JObject data, params string[] fields)
        {
            if (data == null || data.Properties().Any(p => !fields.Contains(p.Name)) || fields.Any(f => data.Property(f) == null))
                throw new InvalidDataException("Closed DTO fields do not match the reviewed contract");
        }
        public static string Hash(byte[] bytes) {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
        // Python canonical JSON sorts object keys recursively; arrays retain their order.
        static JToken Sorted(JToken token) {
            if (token is JObject o) return new JObject(o.Properties().OrderBy(p=>p.Name,StringComparer.Ordinal).Select(p=>new JProperty(p.Name,Sorted(p.Value))));
            if (token is JArray a) return new JArray(a.Select(Sorted));
            if (token.Type==JTokenType.Float) return new JRaw(((decimal)token).ToString("0.############################",CultureInfo.InvariantCulture));
            return token.DeepClone();
        }
        public static string CanonicalHash(JToken token) => Hash(Encoding.UTF8.GetBytes(Sorted(token).ToString(Formatting.None)));
    }

    [JsonObject(MemberSerialization.OptIn)]
    public sealed class BridgeCommand
    {
        [JsonProperty(Required=Required.Always)] public string id;
        [JsonProperty(Required=Required.Always)] public string session_id;
        [JsonProperty(Required=Required.Always)] public string kind;
        [JsonProperty(Required=Required.Always)] public string expected_version;
        [JsonProperty(Required=Required.Always)] public string payload_hash;
        [JsonProperty(Required=Required.Always)] public JObject payload;
        [JsonProperty(Required=Required.Always)] public string deadline_utc;
        [JsonProperty(Required=Required.Always)] public string bridge_epoch;
        public void Validate() {
            if (new[]{id,session_id,kind,expected_version,payload_hash,bridge_epoch}.Any(string.IsNullOrWhiteSpace)) throw new InvalidDataException("Missing command identity");
            DateTimeOffset.Parse(deadline_utc, CultureInfo.InvariantCulture);
            if (payload_hash != BridgeJson.CanonicalHash(payload)) throw new InvalidDataException("Payload hash mismatch");
            switch(kind) {
                case "build_house": BridgeJson.Closed(payload,"run_id","manifest_hash"); break;
                case "prepare_reference_run": AppCommandBridge.Validate(payload); break;
                case "inspect": BridgeJson.Closed(payload,"diagnostic_keys");
                    var keys=payload["diagnostic_keys"] as JArray;
                    var allowed=new[]{"geometry","lights","volumes","materials","gi","bake_state"};
                    if(keys==null||keys.Count<1||keys.Count>6||keys.Any(k=>k.Type!=JTokenType.String||!allowed.Contains((string)k))) throw new InvalidDataException("Invalid inspection keys"); break;
                case "snapshot": BridgeJson.Closed(payload,"scope_id"); break;
                case "capture": BridgeJson.Closed(payload,"inspection_hash","role"); break;
                case "apply_patch": BridgeJson.Closed(payload,"id","session_id","expected_version","hypothesis_id","expected_effect","operations","needs_bake"); break;
                case "bake": BridgeJson.Closed(payload,"lightmapper","timeout_seconds"); break;
                case "restore": BridgeJson.Closed(payload,"snapshot_id","expected_manifest_hash"); break;
                default: throw new InvalidDataException("Unknown command kind");
            }
        }
    }
    [JsonObject(MemberSerialization.OptIn)]
    public sealed class CommandBatch { [JsonProperty(Required=Required.Always)] public BridgeCommand[] commands; [JsonProperty(Required=Required.Always)] public bool session_active; }
    [JsonObject(MemberSerialization.OptIn)]
    public sealed class CommandControl {
        [JsonProperty(Required=Required.Always)] public string command_id;
        [JsonProperty(Required=Required.Always)] public string directive;
        [JsonProperty(Required=Required.Always)] public string deadline_utc;
    }
    [JsonObject(MemberSerialization.OptIn)]
    public sealed class BridgeError {
        [JsonProperty] public string code;
        [JsonProperty] public string message;
        [JsonProperty] public bool retryable = false;
        [JsonProperty] public string command_id;
    }
    [JsonObject(MemberSerialization.OptIn)]
    public sealed class CommandResult {
        [JsonProperty] public string command_id;
        [JsonProperty] public string bridge_epoch;
        [JsonProperty] public string payload_hash;
        [JsonProperty] public string status;
        [JsonProperty] public string before_version;
        [JsonProperty] public string after_version;
        [JsonProperty] public string[] artifact_hashes = Array.Empty<string>();
        [JsonProperty] public JArray captures = new JArray();
        [JsonProperty] public string snapshot_id;
        [JsonProperty] public string manifest_hash = new string('0',64);
        [JsonProperty] public string bake_status = "not_required";
        [JsonProperty] public string details_artifact_hash;
        [JsonProperty] public BridgeError error;
    }

    public sealed class ReceiptStore
    {
        public readonly string Root;
        public ReceiptStore(string root) { Root=Path.GetFullPath(root); Directory.CreateDirectory(Root); }
        string ReceiptPath(string id) {
            if(string.IsNullOrEmpty(id)||id.Length>128||id.Any(c=>!char.IsLetterOrDigit(c)&&c!='-'&&c!='_')) throw new InvalidDataException("Invalid receipt ID");
            return Path.Combine(Root,id+".json");
        }
        public JObject Get(string id) { var p=ReceiptPath(id); return File.Exists(p)?JObject.Parse(File.ReadAllText(p)):null; }
        public IEnumerable<JObject> Pending() => Directory.GetFiles(Root,"*.json").Select(p=>JObject.Parse(File.ReadAllText(p))).Where(p=>(bool?)p["acknowledged"]!=true);
        void Save(string id,JObject body) {
            var target=ReceiptPath(id); var temporary=target+".writing";
            var bytes=Encoding.UTF8.GetBytes(BridgeJson.Write(body));
            using(var stream=new FileStream(temporary,FileMode.Create,FileAccess.Write,FileShare.None)) {stream.Write(bytes,0,bytes.Length);stream.Flush(true);}
            if(File.Exists(target)) File.Replace(temporary,target,null); else File.Move(temporary,target);
        }
        public void Start(BridgeCommand command) {
            var prior=Get(command.id);
            if(prior!=null) throw new InvalidOperationException((string)prior["payload_hash"]==command.payload_hash?"Command already started; reconcile receipt":"Contradictory command payload");
            Save(command.id,new JObject { ["command_id"]=command.id,["payload_hash"]=command.payload_hash,["bridge_epoch"]=command.bridge_epoch,["command"]=JObject.FromObject(command),["status"]="started",["result"]=null,["acknowledged"]=false });
        }
        public void Complete(CommandResult result) {
            var prior=Get(result.command_id)??throw new InvalidOperationException("Missing started receipt");
            if((string)prior["payload_hash"]!=result.payload_hash||(string)prior["bridge_epoch"]!=result.bridge_epoch) throw new InvalidDataException("Receipt identity conflict");
            var next=JObject.FromObject(result);
            if(prior["result"].Type!=JTokenType.Null&&!JToken.DeepEquals(prior["result"],next)) throw new InvalidOperationException("Contradictory terminal receipt");
            prior["result"]=next;prior["status"]=result.status;Save(result.command_id,prior);
        }
        public void Acknowledge(string id) {var receipt=Get(id);if(receipt==null||receipt["result"].Type==JTokenType.Null)throw new InvalidOperationException("No terminal receipt");receipt["acknowledged"]=true;Save(id,receipt);}
    }
}
