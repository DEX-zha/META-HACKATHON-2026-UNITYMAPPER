using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HdrpAgent.Editor
{
    public static class ReferenceRoomControls
    {
        static JArray V(Vector3 value)=>new JArray(value.x,value.y,value.z);
        static Transform Root()=>SceneManager.GetActiveScene().GetRootGameObjects().FirstOrDefault(o=>o.name=="Reconstruction")?.transform??throw new InvalidOperationException("Open a reconstructed candidate scene first");
        static JObject View(string key,string target,string angle,Vector3 position,Vector3 rotation,float fov)=>new JObject{["key"]=key,["object_key"]=target,["angle"]=angle,["position_m"]=V(position),["rotation_deg"]=V(rotation),["fov_deg"]=fov};
        static void Begin(Transform root,JArray views){
            var objects=new JArray(root.Cast<Transform>().Select(o=>new JObject{["key"]=o.name,["support_key"]=null,["residual"]=null}));
            var request=new JObject{["ordinal"]=0,["version"]=SceneInspector.Version(),["scene_path"]=SceneManager.GetActiveScene().path,["views"]=views,["objects"]=objects};
            var folder=Path.Combine(Directory.GetParent(Application.dataPath).Parent.Parent.FullName,".hdrp-agent/reports/room-inspection-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,6));
            ReferenceVision.Begin(request,folder);
        }
        [MenuItem("Tools/HDRP Agent/Inspect room 360")]
        public static void Survey(){
            var root=Root();var floors=root.Cast<Transform>().Where(o=>Path.GetFileName(PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(o.gameObject)).StartsWith("Floor_",StringComparison.Ordinal)).ToArray();
            var rs=floors.SelectMany(o=>o.GetComponentsInChildren<Renderer>()).ToArray();if(rs.Length==0)throw new InvalidOperationException("A mapped floor is required");
            var bounds=rs[0].bounds;foreach(var r in rs.Skip(1))bounds.Encapsulate(r.bounds);var center=bounds.center+Vector3.up*1.5f;
            var views=new JArray();for(int i=0;i<8;i++)views.Add(View("room-"+i,floors[0].name,"room_sweep",center,new Vector3(0,i*45,0),75));Begin(root,views);
        }
        [MenuItem("Tools/HDRP Agent/Inspect current Scene camera")]
        public static void InspectSceneCamera(){
            var root=Root();var camera=SceneView.lastActiveSceneView?.camera??throw new InvalidOperationException("Open and position the Scene view camera first");
            var selected=Selection.activeTransform;while(selected!=null&&selected.parent!=root)selected=selected.parent;
            var target=selected??root.Cast<Transform>().First();
            Begin(root,new JArray(View("scene-detail",target.name,"interior_detail",camera.transform.position,camera.transform.eulerAngles,camera.fieldOfView)));
        }
    }
}
