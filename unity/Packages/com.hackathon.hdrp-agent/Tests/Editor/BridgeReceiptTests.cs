using System;
using System.IO;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using HdrpAgent.Editor;

namespace HdrpAgent.Tests
{
    public class BridgeReceiptTests
    {
        string root;
        ReceiptStore store;
        [SetUp] public void Setup(){root=Path.Combine(Path.GetTempPath(),"hdrp-receipts-"+Guid.NewGuid().ToString("N"));store=new ReceiptStore(root);}
        [TearDown] public void Cleanup(){Directory.Delete(root,true);}
        BridgeCommand Command(){var p=JObject.Parse("{\"diagnostic_keys\":[\"lights\"]}");return new BridgeCommand{id="command-test",session_id="session-test",kind="inspect",expected_version="version-test",payload=p,payload_hash=BridgeJson.CanonicalHash(p),deadline_utc=DateTimeOffset.UtcNow.AddMinutes(2).ToString("O"),bridge_epoch="epoch-test"};}
        CommandResult Result(BridgeCommand c)=>new CommandResult{command_id=c.id,bridge_epoch=c.bridge_epoch,payload_hash=c.payload_hash,status="failed",before_version=c.expected_version,after_version=c.expected_version};
        [Test] public void StartedReceiptSurvivesReloadAndCannotExecuteTwice(){var c=Command();store.Start(c);var reloaded=new ReceiptStore(root);Assert.AreEqual("started",(string)reloaded.Get(c.id)["status"]);Assert.Throws<InvalidOperationException>(()=>reloaded.Start(c));}
        [Test] public void SameTerminalReceiptIsIdempotentAndConflictsAreRejected(){var c=Command();store.Start(c);var r=Result(c);store.Complete(r);store.Complete(r);r.status="succeeded";Assert.Throws<InvalidOperationException>(()=>store.Complete(r));}
        [Test] public void PayloadConflictAndPathTraversalRejected(){var c=Command();store.Start(c);c.payload_hash=new string('b',64);Assert.Throws<InvalidOperationException>(()=>store.Start(c));Assert.Throws<InvalidDataException>(()=>store.Get("../outside"));}
        [Test] public void ClosedEnvelopeRejectsUnknownFields(){Assert.Throws<Newtonsoft.Json.JsonSerializationException>(()=>BridgeJson.Read<CommandBatch>("{\"commands\":[],\"execute_script\":true}"));}
        [Test] public void NumericCanonicalizationIsStable(){Assert.AreEqual(BridgeJson.CanonicalHash(JObject.Parse("{\"z\":1.0,\"a\":0.000001}")),BridgeJson.CanonicalHash(JObject.Parse("{\"a\":1e-6,\"z\":1}")));}
        [Test] public void AcknowledgementRequiresTerminalReceipt(){var c=Command();store.Start(c);Assert.Throws<InvalidOperationException>(()=>store.Acknowledge(c.id));store.Complete(Result(c));store.Acknowledge(c.id);Assert.IsTrue((bool)store.Get(c.id)["acknowledged"]);}
    }
}
