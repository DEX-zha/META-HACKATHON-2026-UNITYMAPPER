using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;

namespace HdrpAgent.Editor
{
    public interface ICommandJob { void Tick(); void Cancel(); CommandResult Result {get;} }

    [InitializeOnLoad]
    public static class CommandExecutor
    {
        static readonly Dictionary<string,Func<BridgeCommand,ICommandJob>> handlers=new Dictionary<string,Func<BridgeCommand,ICommandJob>>();
        static ICommandJob job;
        static BridgeCommand command;
        static Action<CommandResult> completion;
        public static Func<string> CurrentVersion = ()=>"unqualified";
        public static ReceiptStore Receipts {get;set;}
        public static bool Busy=>command!=null;
        public static string[] Capabilities=>handlers.Keys.OrderBy(s=>s).ToArray();
        static CommandExecutor(){EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=BeforeReload;}
        public static void Register(string kind,Func<BridgeCommand,ICommandJob> factory){handlers[kind]=factory;}
        public static void Start(BridgeCommand incoming,string epoch,Action<CommandResult> completed)
        {
            if(Busy)throw new InvalidOperationException("One command is already active");
            incoming.Validate();
            if(incoming.bridge_epoch!=epoch)throw new InvalidOperationException("Stale bridge epoch");
            Receipts.Start(incoming);command=incoming;completion=completed;
            if(LocalValidationRunner.Running){Finish(Failure("EDITOR_BUSY","Local graphical qualification still owns the scene"));return;}
            if(DateTimeOffset.Parse(incoming.deadline_utc)<=DateTimeOffset.UtcNow){Finish(Failure("DEADLINE","Deadline expired","cancelled"));return;}
            if(!handlers.TryGetValue(incoming.kind,out var handler)){Finish(Failure("CAPABILITY_MISSING","Command kind is not implemented"));return;}
            if(incoming.kind!="inspect" && incoming.expected_version!=CurrentVersion()){Finish(Failure("STALE_VERSION","Scene version changed"));return;}
            try{job=handler(incoming);}catch(Exception){Finish(Failure("COMMAND_FAILED","Command initialization failed"));}
        }
        public static CommandResult Failure(string code,string message,string status="failed") => new CommandResult {
            command_id=command.id,bridge_epoch=command.bridge_epoch,payload_hash=command.payload_hash,status=status,
            before_version=CurrentVersion(),after_version=CurrentVersion(),
            error=new BridgeError{code=code,message=message,command_id=command.id}
        };
        public static void Cancel(){job?.Cancel();}
        static void Tick(){
            if(job==null)return;
            try{if(DateTimeOffset.UtcNow>=DateTimeOffset.Parse(command.deadline_utc))job.Cancel();job.Tick();if(job.Result!=null)Finish(job.Result);}
            catch(Exception){Finish(Failure("COMMAND_OUTCOME_UNKNOWN","Execution interrupted; inspect before recovery","unknown"));}
        }
        static void Finish(CommandResult result){
            Receipts.Complete(result);job=null;command=null;var done=completion;completion=null;done?.Invoke(result);
        }
        static void BeforeReload(){
            // A reload never marks an in-flight native operation as successfully completed.
            if(command!=null) {Receipts.Complete(Failure("DOMAIN_RELOAD","Editor reloaded during execution","unknown"));job=null;command=null;}
        }
    }
}
