using System.Collections;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using System;
using System.Linq;

namespace HdrpAgent.Tests
{
    public class CapturePipelineTests
    {
        [UnityTest]public IEnumerator CaptureWaitsForRenderedFrameAndReturnsRequestedDimensions(){
            if(Application.isBatchMode||SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null)Assert.Ignore("Requires graphical GameView qualification, not batch rendering");
            var go=new GameObject("Capture test");var camera=go.AddComponent<Camera>();camera.backgroundColor=Color.gray;camera.clearFlags=CameraClearFlags.SolidColor;
            int width=Screen.width,height=Screen.height;
            byte[] png=null;var rig=AppDomain.CurrentDomain.GetAssemblies().Select(a=>a.GetType("HdrpAgent.Runtime.CaptureRig")).FirstOrDefault(t=>t!=null);
            Assert.IsNotNull(rig,"Capture implementation must be present before qualification");
            yield return (IEnumerator)rig.GetMethod("CaptureStill").Invoke(null,new object[]{camera,width,height,(Action<byte[]>)(bytes=>png=bytes)});
            Assert.IsNotNull(png);var image=new Texture2D(2,2);Assert.IsTrue(image.LoadImage(png));Assert.AreEqual(width,image.width);Assert.AreEqual(height,image.height);
            UnityEngine.Object.Destroy(image);UnityEngine.Object.Destroy(go);
        }
        [UnityTest]public IEnumerator RepeatedFramesAreFreshOrderedAndStable(){
            if(Application.isBatchMode||SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null)Assert.Ignore("Graphical GameView required");
            var go=new GameObject("Sequence witness");var camera=go.AddComponent<Camera>();camera.backgroundColor=Color.gray;camera.clearFlags=CameraClearFlags.SolidColor;
            var rig=AppDomain.CurrentDomain.GetAssemblies().Select(a=>a.GetType("HdrpAgent.Runtime.CaptureRig")).First(t=>t!=null);var method=rig.GetMethod("CaptureStill");
            for(int i=0;i<32;i++)yield return new WaitForEndOfFrame();
            int previous=-1;Color32[] baseline=null;
            for(int i=0;i<3;i++){
                byte[] png=null;int rendered=-1;
                yield return (IEnumerator)method.Invoke(null,new object[]{camera,Screen.width,Screen.height,(Action<byte[]>)(bytes=>{png=bytes;rendered=Time.renderedFrameCount;})});
                Assert.Greater(rendered,previous,"Each sequential readback must follow a fresh rendered frame");previous=rendered;
                var image=new Texture2D(2,2);image.LoadImage(png);var pixels=image.GetPixels32();UnityEngine.Object.Destroy(image);
                if(baseline!=null){double error=0;for(int n=0;n<pixels.Length;n++){var a=baseline[n];var b=pixels[n];float la=.2126f*Mathf.GammaToLinearSpace(a.r/255f)+.7152f*Mathf.GammaToLinearSpace(a.g/255f)+.0722f*Mathf.GammaToLinearSpace(a.b/255f);float lb=.2126f*Mathf.GammaToLinearSpace(b.r/255f)+.7152f*Mathf.GammaToLinearSpace(b.g/255f)+.0722f*Mathf.GammaToLinearSpace(b.b/255f);error+=Math.Abs(la-lb);}Assert.LessOrEqual(error/pixels.Length,.01,"Stationary witness must meet the frozen linear luminance threshold");}
                baseline=pixels;
            }
            var invalid=(IEnumerator)method.Invoke(null,new object[]{camera,Screen.width+1,Screen.height,(Action<byte[]>)(_=>Assert.Fail("Invalid dimensions cannot produce proof"))});
            Assert.IsTrue(invalid.MoveNext());yield return invalid.Current;Assert.Throws<IOException>(()=>invalid.MoveNext());
            UnityEngine.Object.Destroy(go);
        }
    }
}
