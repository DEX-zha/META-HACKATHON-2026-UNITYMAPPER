using System;
using System.Collections;
using System.Linq;
using UnityEngine;
namespace HdrpAgent.Runtime
{
    [Serializable] public sealed class PerformanceSample {public int frame_count,v_sync_count,target_frame_rate;public double median_frame_ms;public string method="editor_wall_frame_time_no_readback";public bool capture_framerate_disabled,focused,focus_stable;}
    public static class PerformanceSampler
    {
        public static IEnumerator Measure(Action<PerformanceSample> done,int count=120){
            if(count!=120)throw new ArgumentException("Performance witness requires 120 frames");
            var previous=Time.captureFramerate;Time.captureFramerate=0;
            var samples=new double[count];
            try{
                for(int i=0;i<10;i++)yield return null;
                bool focused=Application.isFocused,stable=true;int sync=QualitySettings.vSyncCount,cap=Application.targetFrameRate;
                for(int i=0;i<count;i++){yield return null;samples[i]=Time.unscaledDeltaTime*1000.0;stable&=Application.isFocused==focused&&QualitySettings.vSyncCount==sync&&Application.targetFrameRate==cap;}
                Array.Sort(samples);done(new PerformanceSample{frame_count=count,median_frame_ms=(samples[59]+samples[60])/2,capture_framerate_disabled=true,focused=focused,focus_stable=stable,v_sync_count=sync,target_frame_rate=cap});
            }finally{Time.captureFramerate=previous;}
        }
    }
}
