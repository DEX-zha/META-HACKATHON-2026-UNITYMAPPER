using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HdrpAgent.Editor {
// Meter actual HDRP exposure, then lock one EV for comparable observations.
internal sealed class HouseExposure {
 readonly List<Tuple<string,Vector3,Quaternion>> views;
 readonly List<float> samples=new List<float>();
 readonly JArray observations=new JArray();
 int index,warm;bool verified;
 internal JObject Receipt{get;private set;}
 internal HouseExposure(IEnumerable<Tuple<string,Vector3,Quaternion>> overview){views=overview.ToList();if(views.Count==0)throw new InvalidDataException("Exposure calibration requires overview views");}
 internal string Progress=>verified?"Metering observation exposure "+index+" / "+views.Count:"Verifying HDRP exposure readback";
 internal static HDCamera RequestCamera(Camera camera){
  var field=typeof(HDCamera).GetField("s_Cameras",System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic);
  var entries=field?.GetValue(null) as System.Collections.IDictionary;
  if(entries!=null)foreach(System.Collections.DictionaryEntry entry in entries){
   var key=entry.Key as System.Runtime.CompilerServices.ITuple;
   if(key!=null&&key.Length==3&&ReferenceEquals(key[0],camera)&&key[2].ToString()=="CustomUserHistory0")return (HDCamera)entry.Value;
  }
  return null;
 }
 internal static float ReadEv(Camera camera){
  var hd=RequestCamera(camera);var texture=hd?.GetPreviousFrameRT((int)HDCameraFrameHistoryType.Exposure);
  if(texture?.rt==null)throw new InvalidDataException("HDRP render-request exposure history is unavailable");
  var previous=RenderTexture.active;var pixel=new Texture2D(1,1,TextureFormat.RGBAFloat,false,true);
  try{
   RenderTexture.active=texture.rt;pixel.ReadPixels(new Rect(0,0,1,1),0,0);pixel.Apply();float ev=pixel.GetPixel(0,0).g;
   if(float.IsNaN(ev)||float.IsInfinity(ev))throw new InvalidDataException("Non-finite metered EV100");return ev;
  }finally{RenderTexture.active=previous;UnityEngine.Object.DestroyImmediate(pixel);}
 }
 internal bool Tick(Camera camera,RenderTexture target,VolumeProfile profile){
  if(Receipt!=null)return true;
  if(!profile.TryGet<Exposure>(out var exposure))throw new InvalidDataException("Owned exposure component missing");
  var view=views[index];camera.transform.SetPositionAndRotation(view.Item2,view.Item3);
  RenderPipeline.SubmitRenderRequest(camera,new RenderPipeline.StandardRequest{destination=target});
  if(++warm<32)return false;warm=0;
  float observed=ReadEv(camera);
  if(!verified){
   if(Mathf.Abs(observed-exposure.fixedExposure.value)>.05f)throw new InvalidDataException("Exposure history readback differs from the fixed verification value");
   observations.Add(new JObject{["kind"]="fixed_readback_check",["requested_ev100"]=exposure.fixedExposure.value,["observed_ev100"]=observed});verified=true;
   exposure.mode.Override(ExposureMode.AutomaticHistogram);exposure.adaptationMode.Override(AdaptationMode.Fixed);exposure.limitMin.Override(-4);exposure.limitMax.Override(16);
   return false;
  }
  samples.Add(observed);observations.Add(new JObject{["kind"]="overview_metering",["room_id"]=view.Item1,["position_m"]=new JArray(view.Item2.x,view.Item2.y,view.Item2.z),["yaw_deg"]=view.Item3.eulerAngles.y,["ev100"]=observed});index++;
  if(index<views.Count)return false;
  var ordered=samples.OrderBy(v=>v).ToArray();float locked=(ordered[(ordered.Length-1)/2]+ordered[ordered.Length/2])*.5f;
  exposure.mode.Override(ExposureMode.Fixed);exposure.fixedExposure.Override(locked);PersistedVolumeProfile.Save(profile);
  Receipt=new JObject{["method"]="horizontal_overview_histogram_median",["history_channel"]="CustomUserHistory0",["fixed_readback_verified"]=true,["locked_ev100"]=locked,["samples"]=observations,["artistic_qualified"]=false};return true;
 }
}
}
