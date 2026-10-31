using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HdrpAgent.Runtime
{
    [Serializable]public sealed class CapturePose{public string key;public float[] position_m,rotation_deg;public float fov_deg;public Vector3 Position=>new Vector3(position_m[0],position_m[1],position_m[2]);public Quaternion Rotation=>Quaternion.Euler(rotation_deg[0],rotation_deg[1],rotation_deg[2]);}
    [Serializable]public sealed class CapturePlan{public CapturePose[] work_views,control_views;public string path_key;public int fps,width,height,seed,warmup_frames;public float duration_seconds,fixed_ev;}
    [Serializable]public sealed class CaptureRequest{public string capture_id,output_directory,version_id,inspection_hash,conditions_hash,scope_id,scene_manifest_hash,bake_status,bake_job_id;public CapturePlan plan;public bool include_clip=true,preserve_camera_settings;}
    [Serializable]public sealed class FrameRecord{public string file,role,camera_key;public int frame_index;public float simulated_time;}
    [Serializable]public sealed class CaptureOutput{public string schema_version="1.0",capture_id,version_id,inspection_hash,conditions_hash,status="running",error;public bool render_ready;public FrameRecord[] frames;public PerformanceSample performance;public ReferenceRenderProtocol render_protocol;public int width,height,fps,warmup_frames;public string color_space="sRGB_LDR_gameview";}

    public sealed class CaptureRig:MonoBehaviour
    {
        CaptureRequest request;
        CaptureOutput output;
        Camera cameraRig;
        bool previousRunInBackground;
        int previousVSync,previousTargetFrameRate,previousCaptureFramerate;
        readonly List<FrameRecord> frames=new List<FrameRecord>();
        public void Configure(CaptureRequest capture){previousRunInBackground=Application.runInBackground;previousVSync=QualitySettings.vSyncCount;previousTargetFrameRate=Application.targetFrameRate;previousCaptureFramerate=Time.captureFramerate;Application.runInBackground=true;request=capture;StartCoroutine(Guarded(Run()));}
        IEnumerator Guarded(IEnumerator run){
            var stack=new Stack<IEnumerator>();stack.Push(run);
            while(stack.Count>0){
                bool next;object yielded=null;
                try{next=stack.Peek().MoveNext();if(next)yielded=stack.Peek().Current;}
                catch(Exception e){WriteFailure(e.GetType().Name+": "+e.Message);yield break;}
                if(!next){stack.Pop();continue;}
                if(yielded is IEnumerator nested){stack.Push(nested);continue;}
                yield return yielded;
            }
        }
        public static IEnumerator CaptureStill(Camera camera,int width,int height,Action<byte[]> done){
            if(!Application.isPlaying||SystemInfo.graphicsDeviceType==GraphicsDeviceType.Null)throw new InvalidOperationException("Graphical PlayMode is required");
            if(camera==null||!camera.enabled||camera.targetTexture!=null)throw new InvalidOperationException("One GameView camera is required");
            yield return new WaitForEndOfFrame();
            var texture=ScreenCapture.CaptureScreenshotAsTexture();
            if(texture==null)throw new IOException("GameView readback returned no texture");
            try{if(texture.width!=width||texture.height!=height)throw new IOException("GameView resolution does not match the frozen plan");done(texture.EncodeToPNG());}finally{Destroy(texture);}
        }
        void WriteFailure(string error){if(output==null)output=new CaptureOutput();output.status="interrupted";output.error=error;output.render_ready=false;Save();}
        void Save(){Directory.CreateDirectory(request.output_directory);var path=Path.Combine(request.output_directory,"manifest.json");File.WriteAllText(path+".writing",JsonUtility.ToJson(output,true));if(File.Exists(path))File.Delete(path);File.Move(path+".writing",path);}
        void Pose(CapturePose pose){cameraRig.transform.SetPositionAndRotation(pose.Position,pose.Rotation);cameraRig.fieldOfView=pose.fov_deg;HDCamera.GetOrCreate(cameraRig).Reset();UnityEngine.Random.InitState(request.plan.seed);}
        IEnumerator Warm(){for(int i=0;i<request.plan.warmup_frames;i++)yield return new WaitForEndOfFrame();}
        IEnumerator Record(string file,string role,string key,int index,float time){
            byte[] png=null;yield return CaptureStill(cameraRig,request.plan.width,request.plan.height,b=>png=b);
            if(png==null)throw new IOException("Missing frame readback");File.WriteAllBytes(Path.Combine(request.output_directory,file),png);
            frames.Add(new FrameRecord{file=file,role=role,camera_key=key,frame_index=index,simulated_time=time});
        }
        IEnumerator Run(){
            var plan=request.plan;
            if(plan.width!=1280||plan.height!=720||plan.fps!=24||plan.warmup_frames<32||plan.warmup_frames>120||plan.work_views.Length<3||plan.work_views.Length>(request.preserve_camera_settings?8:3)||plan.control_views.Length!=2)throw new InvalidDataException("Unsupported capture plan");
            Directory.CreateDirectory(request.output_directory);
            output=new CaptureOutput{capture_id=request.capture_id,version_id=request.version_id,inspection_hash=request.inspection_hash,conditions_hash=request.conditions_hash,width=plan.width,height=plan.height,fps=plan.fps,warmup_frames=plan.warmup_frames};Save();
            var originalCamera=Camera.main??FindObjectsByType<Camera>(FindObjectsSortMode.None).FirstOrDefault(c=>c.enabled);
            foreach(var camera in FindObjectsByType<Camera>(FindObjectsSortMode.None))camera.enabled=false;
            cameraRig=new GameObject("HDRP Agent Capture Camera").AddComponent<Camera>();cameraRig.nearClipPlane=.05f;cameraRig.farClipPlane=100;cameraRig.allowHDR=true;cameraRig.targetDisplay=0;
            var hd=cameraRig.gameObject.AddComponent<HDAdditionalCameraData>();
            if(request.preserve_camera_settings){
                if(originalCamera==null)throw new InvalidDataException("A reference camera is required");
                cameraRig.CopyFrom(originalCamera);cameraRig.enabled=true;cameraRig.targetTexture=null;
                var originalHD=originalCamera.GetComponent<HDAdditionalCameraData>();if(originalHD!=null)JsonUtility.FromJsonOverwrite(JsonUtility.ToJson(originalHD),hd);
            }else{
                var volume=new GameObject("HDRP Agent Fixed Exposure").AddComponent<Volume>();volume.isGlobal=true;volume.priority=10000;volume.weight=1;
                var exposure=volume.profile.Add<Exposure>(true);exposure.mode.Override(ExposureMode.Fixed);exposure.fixedExposure.Override(plan.fixed_ev);
            }
            hd.allowDynamicResolution=false;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;
            UnityEngine.Random.InitState(plan.seed);QualitySettings.vSyncCount=0;Application.targetFrameRate=-1;
            Pose(plan.work_views[0]);yield return Warm();
            output.render_protocol=ReferenceRenderProtocol.Read(cameraRig,"native_gameview");
            yield return PerformanceSampler.Measure(p=>output.performance=p);
            Time.captureFramerate=plan.fps;
            foreach(var role in new[]{"work","control"})foreach(var pose in role=="work"?plan.work_views:plan.control_views){Pose(pose);yield return Warm();yield return Record(pose.key+".png",role,pose.key,0,0);}
            if(request.include_clip){
                Pose(plan.work_views[0]);yield return Warm();var count=Mathf.RoundToInt(plan.duration_seconds*plan.fps);
                for(int i=0;i<count;i++){
                    float path=(float)i/count*plan.work_views.Length;int a=Mathf.FloorToInt(path);var from=plan.work_views[a];var to=plan.work_views[(a+1)%plan.work_views.Length];
                    cameraRig.transform.SetPositionAndRotation(Vector3.Lerp(from.Position,to.Position,path-a),Quaternion.Slerp(from.Rotation,to.Rotation,path-a));
                    yield return Record("frame-"+i.ToString("D4")+".png","work",plan.path_key,i,(float)i/plan.fps);
                }
            }
            output.frames=frames.ToArray();output.status="complete";output.render_ready=true;Save();Time.captureFramerate=0;
        }
        void OnDestroy(){Time.captureFramerate=previousCaptureFramerate;Application.runInBackground=previousRunInBackground;QualitySettings.vSyncCount=previousVSync;Application.targetFrameRate=previousTargetFrameRate;}
    }
}
