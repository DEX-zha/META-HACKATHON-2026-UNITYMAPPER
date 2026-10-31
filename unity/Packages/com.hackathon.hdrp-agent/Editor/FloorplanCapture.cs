using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor {
// A read-only offscreen camera: user selection, SceneView navigation and focus are irrelevant.
[InitializeOnLoad] public static class FloorplanCapture {
 static Camera camera; static RenderTexture target; static JObject settings; static string directory,version,scenePath; static int warm,phase;
 static readonly Dictionary<Renderer,bool> hidden=new Dictionary<Renderer,bool>();
 static readonly Dictionary<Renderer,Material[]> originals=new Dictionary<Renderer,Material[]>();
 static readonly List<Material> temporary=new List<Material>(); static GameObject neutralVolume;
 static JArray projections,colors; static double began;
 public static bool Running=>camera!=null;
 static FloorplanCapture(){EditorApplication.update+=Tick;AssemblyReloadEvents.beforeAssemblyReload+=()=>Cancel("Domain reload during offscreen capture");}
 public static void Begin(JObject value,string destination,string expectedVersion){
  if(Running||EditorApplication.isPlayingOrWillChangePlaymode||SceneManager.GetActiveScene().isDirty)throw new InvalidOperationException("Saved idle scene required");
  settings=(JObject)value.DeepClone();directory=destination;version=expectedVersion;scenePath=SceneManager.GetActiveScene().path;
  int width=(int)value["width"],height=(int)value["height"];if(width<32||height<32||width>1280||height>720)throw new InvalidDataException("Invalid capture dimensions");
  if(SceneInspector.Version()!=version)throw new InvalidDataException("Stale floorplan candidate");
  Directory.CreateDirectory(directory);ReferenceWorkflow.Atomic(Path.Combine(directory,"request.json"),new JObject{["camera"]=value.DeepClone(),["version"]=version,["scene_path"]=scenePath});
  try{
   var go=new GameObject("Floorplan measurement camera"){hideFlags=HideFlags.HideAndDontSave};camera=go.AddComponent<Camera>();camera.enabled=false;camera.allowHDR=true;camera.nearClipPlane=.05f;camera.farClipPlane=100;camera.orthographic=true;camera.orthographicSize=ReferenceSceneBuilder.Number(value["orthographic_size"],.1f,30);camera.aspect=(float)width/height;
   camera.transform.SetPositionAndRotation(new Vector3(0,40,0),Quaternion.Euler(90,0,0));var hd=go.AddComponent<HDAdditionalCameraData>();hd.clearColorMode=HDAdditionalCameraData.ClearColorMode.Color;hd.backgroundColorHDR=Color.white;hd.allowDynamicResolution=false;hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.None;
   target=new RenderTexture(width,height,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB){hideFlags=HideFlags.HideAndDontSave};target.Create();
   var root=SceneManager.GetActiveScene().GetRootGameObjects().Single(o=>o.name=="Reconstruction");var ceilingKeys=new HashSet<string>(((JArray)value["ceiling_keys"]).Values<string>());
   foreach(var r in SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(o=>o.GetComponentsInChildren<Renderer>(true))){
    bool ceiling=r.transform.root.name==ReferenceRoomFinish.CeilingGroup||r.GetComponentsInParent<Transform>(true).Any(t=>ceilingKeys.Contains(t.name));
    if(ceiling&&(bool)value["cutaway"]){hidden[r]=r.forceRenderingOff;r.forceRenderingOff=true;}
   }
   projections=new JArray();colors=new JArray();int index=0;
   foreach(Transform t in root.transform){var rs=t.GetComponentsInChildren<Renderer>().Where(r=>r.enabled&&!r.forceRenderingOff).ToArray();if(rs.Length==0)continue;var bounds=rs[0].bounds;foreach(var r in rs.Skip(1))bounds.Encapsulate(r.bounds);
    Vector2 lo=Vector2.one*float.PositiveInfinity,hi=Vector2.one*float.NegativeInfinity;
    for(int x=-1;x<=1;x+=2)for(int y=-1;y<=1;y+=2)for(int z=-1;z<=1;z+=2){var v=camera.WorldToViewportPoint(bounds.center+Vector3.Scale(bounds.extents,new Vector3(x,y,z)));var p=new Vector2(v.x,1-v.y);lo=Vector2.Min(lo,p);hi=Vector2.Max(hi,p);}
    projections.Add(new JObject{["object_key"]=t.name,["bbox_xyxy"]=new JArray(lo.x,lo.y,hi.x,hi.y)});index++;var color=Color.HSVToRGB((index*.61803398875f)%1,.75f,.8f);colors.Add(new JObject{["object_key"]=t.name,["rgb"]=new JArray(color.r,color.g,color.b)});
   }
   warm=0;phase=0;began=EditorApplication.timeSinceStartup;
  }catch{Cleanup();throw;}
 }
 static void Neutral(){
  neutralVolume=new GameObject("Neutral geometry measurement"){hideFlags=HideFlags.HideAndDontSave};var volume=neutralVolume.AddComponent<Volume>();volume.isGlobal=true;volume.priority=100000;volume.profile=ScriptableObject.CreateInstance<VolumeProfile>();volume.profile.hideFlags=HideFlags.HideAndDontSave;
  var exposure=volume.profile.Add<Exposure>(true);exposure.mode.Override(ExposureMode.Fixed);exposure.fixedExposure.Override(0);var tone=volume.profile.Add<Tonemapping>(true);tone.mode.Override(TonemappingMode.None);
  var root=SceneManager.GetActiveScene().GetRootGameObjects().Single(o=>o.name=="Reconstruction");
  foreach(JObject entry in colors){var t=root.transform.Cast<Transform>().Single(x=>x.name==(string)entry["object_key"]);var rgb=(JArray)entry["rgb"];var material=new Material(Shader.Find("HDRP/Unlit")){hideFlags=HideFlags.HideAndDontSave};material.SetColor("_UnlitColor",new Color((float)rgb[0],(float)rgb[1],(float)rgb[2]));if(material.HasProperty("_ExposureWeight"))material.SetFloat("_ExposureWeight",0);temporary.Add(material);
   foreach(var r in t.GetComponentsInChildren<Renderer>()){if(r.forceRenderingOff)continue;originals[r]=r.sharedMaterials;r.sharedMaterials=r.sharedMaterials.Select(_=>material).ToArray();}
  }
  HDCamera.GetOrCreate(camera).Reset();
 }
 static void Tick(){
  if(!Running)return;
  try{
   if(SceneManager.GetActiveScene().isDirty||SceneManager.GetActiveScene().path!=scenePath){Cancel("CONCURRENT_EDIT: capture paused; restore saved candidate before retrying");return;}
   if(EditorApplication.timeSinceStartup-began>180)throw new TimeoutException("Offscreen render timeout");
   RenderPipeline.SubmitRenderRequest(camera,new RenderPipeline.StandardRequest{destination=target});if(++warm<32)return;
   var old=RenderTexture.active;var image=new Texture2D(target.width,target.height,TextureFormat.RGB24,false);try{RenderTexture.active=target;image.ReadPixels(new Rect(0,0,target.width,target.height),0,0);image.Apply();File.WriteAllBytes(Path.Combine(directory,phase==0?"beauty.png":"geometry.png"),image.EncodeToPNG());}finally{RenderTexture.active=old;UnityEngine.Object.DestroyImmediate(image);}
   if(phase==0){phase=1;warm=0;Neutral();return;}
   var proof=new JObject{["status"]="complete",["mode"]="floorplan_offscreen",["version"]=version,["scene_path"]=scenePath,["camera"]=settings.DeepClone(),["projected_objects"]=projections,["object_colors"]=colors,["beauty_sha256"]=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"beauty.png"))),["geometry_sha256"]=BridgeJson.Hash(File.ReadAllBytes(Path.Combine(directory,"geometry.png"))),["ceilings_hidden_for_capture"]=new JArray(hidden.Keys.Select(r=>r.name)),["performance_qualified"]=false,["focus_required"]=false};
   Cleanup();if(SceneInspector.Version()!=version)throw new InvalidDataException("Candidate version changed during offscreen measurement");ReferenceWorkflow.Atomic(Path.Combine(directory,"result.json"),proof);
  }catch(Exception e){Cancel(e.GetType().Name+": "+e.Message);}
 }
 public static void Cancel(string reason){if(directory!=null&&Running)ReferenceWorkflow.Atomic(Path.Combine(directory,"interruption.json"),new JObject{["reason"]=reason,["version"]=version});Cleanup();}
 static void Cleanup(){foreach(var pair in originals)if(pair.Key)pair.Key.sharedMaterials=pair.Value;originals.Clear();foreach(var pair in hidden)if(pair.Key)pair.Key.forceRenderingOff=pair.Value;hidden.Clear();foreach(var m in temporary)if(m)UnityEngine.Object.DestroyImmediate(m);temporary.Clear();if(neutralVolume){var p=neutralVolume.GetComponent<Volume>().profile;UnityEngine.Object.DestroyImmediate(neutralVolume);UnityEngine.Object.DestroyImmediate(p);}if(camera)UnityEngine.Object.DestroyImmediate(camera.gameObject);camera=null;if(target){target.Release();UnityEngine.Object.DestroyImmediate(target);}target=null;}
}
}
