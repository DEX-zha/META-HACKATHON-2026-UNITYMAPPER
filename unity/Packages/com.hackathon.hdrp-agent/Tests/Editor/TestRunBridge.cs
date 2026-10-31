using System;
using System.IO;
using Newtonsoft.Json;
using UnityEditor.TestTools.TestRunner.Api;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace HdrpAgent.Tests
{
    [InitializeOnLoad]
    public static class TestRunBridge
    {
        static TestRunnerApi api;
        static TestRunBridge(){if(SessionState.GetBool("HdrpAgent.PlayTests",false)){api=ScriptableObject.CreateInstance<TestRunnerApi>();api.RegisterCallbacks(new Results("unity-capture-tests","HdrpAgent.Tests.CapturePipelineTests"));}}
        static void Run(string filename,string fixture,TestMode mode){
            if(EditorSceneManager.GetActiveScene().isDirty||EditorApplication.isPlayingOrWillChangePlaymode||UnityEditor.Lightmapping.isRunning||HdrpAgent.Editor.LocalValidationRunner.Running||HdrpAgent.Editor.ReferenceWorkflow.Running||HdrpAgent.Editor.CommandExecutor.Busy)throw new InvalidOperationException("Save the scene and wait for native operations before tests; no save dialog is allowed");
            if(SessionState.GetBool("HdrpAgent.TestRunning",false))throw new InvalidOperationException("Wait for the current test run to finish");
            SessionState.SetBool("HdrpAgent.TestRunning",true);SessionState.SetBool("HdrpAgent.PlayTests",mode==TestMode.PlayMode);
            api=ScriptableObject.CreateInstance<TestRunnerApi>();var callback=new Results(filename,fixture);api.RegisterCallbacks(callback);
            try{api.Execute(new ExecutionSettings(new Filter{testMode=mode,testNames=new[]{fixture}}));}
            catch{api.UnregisterCallbacks(callback);SessionState.SetBool("HdrpAgent.TestRunning",false);SessionState.SetBool("HdrpAgent.PlayTests",false);throw;}
        }
        public static void RunCaptureTests()=>Run("unity-capture-tests","HdrpAgent.Tests.CapturePipelineTests",TestMode.PlayMode);
        public static void RunFoundation()=>Run("unity-foundation-tests","HdrpAgent.Tests.BridgeReceiptTests",TestMode.EditMode);
        public static void RunSceneMutation()=>Run("unity-scene-mutation-tests","HdrpAgent.Tests.SceneMutationTests",TestMode.EditMode);
        public static void RunReferenceConstruction()=>Run("unity-reference-construction-tests","HdrpAgent.Tests.ReferenceConstructionTests",TestMode.EditMode);
        class Results:ICallbacks {
            readonly string filename,fixture; public Results(string filename,string fixture){this.filename=filename;this.fixture=fixture;}
            bool ContainsFixture(ITestResultAdaptor result){if(result.FullName==fixture)return true;if(result.HasChildren)foreach(var child in result.Children)if(ContainsFixture(child))return true;return false;}
            public void RunStarted(ITestAdaptor testsToRun){}
            public void TestStarted(ITestAdaptor test){}
            public void TestFinished(ITestResultAdaptor result){}
            public void RunFinished(ITestResultAdaptor result){
                if(!ContainsFixture(result))return;
                TestRunnerApi.UnregisterTestCallback(this);
                SessionState.SetBool("HdrpAgent.TestRunning",false);SessionState.SetBool("HdrpAgent.PlayTests",false);
                var folder=Path.Combine(Directory.GetParent(Application.dataPath).Parent.Parent.FullName,".hdrp-agent","reports");Directory.CreateDirectory(folder);
                File.WriteAllText(Path.Combine(folder,filename+".json"),JsonConvert.SerializeObject(new{suite=fixture,started_utc=result.StartTime.ToUniversalTime(),ended_utc=result.EndTime.ToUniversalTime(),result=result.ResultState,passed=result.PassCount,failed=result.FailCount,skipped=result.SkipCount,duration=result.Duration},Formatting.Indented));
                TestRunnerApi.SaveResultToFile(result,Path.Combine(folder,filename+".xml"));
            }
        }
    }
}
