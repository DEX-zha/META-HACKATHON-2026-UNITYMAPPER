using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    // Source geometry is used only to aim cameras at image regions. Neither the
    // selected instance identity nor its bounds/transform are returned to Muse.
    public static class ReferenceDetails
    {
        static float[] Project(Bounds bounds,Camera camera){
            var min=new Vector2(1,1);var max=Vector2.zero;
            for(int i=0;i<8;i++){
                var p=camera.WorldToViewportPoint(bounds.center+Vector3.Scale(bounds.extents,new Vector3((i&1)==0?-1:1,(i&2)==0?-1:1,(i&4)==0?-1:1)));
                if(p.z<=camera.nearClipPlane)return null;
                var uv=new Vector2(p.x,1-p.y);min=Vector2.Min(min,uv);max=Vector2.Max(max,uv);
            }
            return new[]{Mathf.Clamp01(min.x),Mathf.Clamp01(min.y),Mathf.Clamp01(max.x),Mathf.Clamp01(max.y)};
        }
        static float Overlap(float[] a,float[] b){
            if(a==null)return 0;float area=Mathf.Max(0,Mathf.Min(a[2],b[2])-Mathf.Max(a[0],b[0]))*Mathf.Max(0,Mathf.Min(a[3],b[3])-Mathf.Max(a[1],b[1]));
            return area/Mathf.Max(.000001f,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area);
        }
        public static JObject Plan(JArray objects,JObject overview){
            if(objects.Count>20)throw new InvalidDataException("At most twenty detail targets");
            var targets=new List<Bounds>();
            foreach(var root in SceneManager.GetActiveScene().GetRootGameObjects()){
                if(!(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(root)??"").StartsWith("Assets/AtmosphericHouse/",StringComparison.Ordinal))continue;
                var renderers=root.GetComponentsInChildren<MeshRenderer>().Where(r=>r.enabled).ToArray();if(renderers.Length==0)continue;
                var bounds=renderers[0].bounds;foreach(var renderer in renderers)bounds.Encapsulate(renderer.bounds);targets.Add(bounds);
            }
            if(targets.Count==0)targets.AddRange(UnityEngine.Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None).Where(r=>r.enabled).Select(r=>r.bounds));
            var views=new JArray();var limits=new JArray();var utility=new PreviewRenderUtility();var camera=utility.camera;camera.enabled=false;camera.aspect=1280f/720;camera.nearClipPlane=.001f;
            try{
                var keys=new HashSet<string>();
                foreach(JObject item in objects){
                    BridgeJson.Closed(item,"key","view_boxes");var key=(string)item["key"];
                    if(string.IsNullOrEmpty(key)||key.Length>80||!keys.Add(key))throw new InvalidDataException("Invalid detail target key");
                    var observations=(JArray)item["view_boxes"];if(observations.Count<1||observations.Count>4)throw new InvalidDataException("Invalid detail observations");
                    float best=-1;Bounds selected=default;
                    foreach(var bounds in targets){
                        float score=0;
                        foreach(JObject box in observations){
                            BridgeJson.Closed(box,"view_key","bbox_xyxy");var pose=overview["work_views"].Single(v=>(string)v["key"]==(string)box["view_key"]);
                            camera.transform.SetPositionAndRotation(ReferenceSceneBuilder.Vector(pose["position_m"],-100,100),Quaternion.Euler(ReferenceSceneBuilder.Vector(pose["rotation_deg"],-360,360)));camera.fieldOfView=(float)pose["fov_deg"];
                            var rect=box["bbox_xyxy"].Values<float>().ToArray();if(rect.Length!=4||rect.Any(x=>!float.IsFinite(x)||x<0||x>1)||rect[2]<=rect[0]||rect[3]<=rect[1])throw new InvalidDataException("Invalid detail region");
                            score+=Overlap(Project(bounds,camera),rect);
                        }
                        score/=observations.Count;if(score>best){best=score;selected=bounds;}
                    }
                    if(best<.1f){limits.Add(key+": no reliable camera target for the visible regions");continue;}
                    var first=overview["work_views"].Single(v=>(string)v["key"]==(string)observations[0]["view_key"]);var delta=ReferenceSceneBuilder.Vector(first["position_m"],-100,100)-selected.center;float azimuth=Mathf.Atan2(delta.x,delta.z);
                    for(int i=0;i<3;i++){
                        float elevation=(i==2?70:20)*Mathf.Deg2Rad,angle=azimuth+(i==1?Mathf.PI:0);float fov=38;
                        // The bounding sphere fits within 76% of the image height.
                        float distance=Mathf.Max(.12f,selected.extents.magnitude/Mathf.Sin(fov*.5f*Mathf.Deg2Rad)/.76f);
                        var position=selected.center+new Vector3(Mathf.Sin(angle)*Mathf.Cos(elevation),Mathf.Sin(elevation),Mathf.Cos(angle)*Mathf.Cos(elevation))*distance;
                        views.Add(JObject.FromObject(new{key="detail-"+views.Count.ToString("D3"),object_key=key,angle=i==0?"front":i==1?"back":"top",position_m=ReferenceAssets.Vec(position),rotation_deg=ReferenceAssets.Vec(Quaternion.LookRotation(selected.center-position,Vector3.up).eulerAngles),fov_deg=fov}));
                    }
                }
            }finally{utility.Cleanup();}
            return new JObject{["views"]=views,["limits"]=limits};
        }
    }
}
