using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
namespace HdrpAgent.Editor {
    public static class ReferenceAssemblyExample {
        public static void Inspect(string path){
            var before=File.ReadAllBytes(path);
            var scene=EditorSceneManager.OpenPreviewScene(path);
            try {
                var nodes=scene.GetRootGameObjects().SelectMany(r=>r.GetComponentsInChildren<Transform>(true)).Where(t=>PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)).ToArray();
                var rows=new JArray();
                foreach(var node in nodes){
                    var parent=node.parent;
                    while(parent!=null&&!PrefabUtility.IsAnyPrefabInstanceRoot(parent.gameObject))parent=parent.parent;
                    rows.Add(new JObject{["name"]=node.name,["prefab_path"]=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(node.gameObject),["parent_prefab_path"]=parent==null?null:PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(parent.gameObject),["position_relative_to_parent_m"]=JArray.FromObject(ReferenceAssets.Vec(parent==null?node.position:parent.InverseTransformPoint(node.position))),["rotation_relative_to_parent_deg"]=JArray.FromObject(ReferenceAssets.Vec((parent==null?node.rotation:Quaternion.Inverse(parent.rotation)*node.rotation).eulerAngles)),["declared_companions"]=ReferenceAssets.Companions(node.gameObject)});
                }
                var report=Path.Combine(Directory.GetParent(Application.dataPath).Parent.Parent.FullName,".hdrp-agent/reports/gp-native-assembly.json");
                File.WriteAllText(report,new JObject{["source_scene"]=path,["source_sha256"]=BridgeJson.Hash(before),["purpose"]="Assembly example only; not target-image ground truth",["instances"]=rows}.ToString());
            } finally {EditorSceneManager.ClosePreviewScene(scene);}
            if(!before.SequenceEqual(File.ReadAllBytes(path)))throw new InvalidDataException("Example scene changed during inspection");
        }
        [MenuItem("Tools/HDRP Agent/Validate assembly in preview scene")]
        public static void ValidatePreview(){
            var scene=EditorSceneManager.NewPreviewScene();var rows=new JArray();
            try{
                foreach(var name in new[]{"WallOut_3x","WallOut_3x_door","WallOut_3x_window_static"}){
                    var path="Assets/AtmosphericHouse/Prefabs/Building/"+name+".prefab";var asset=AssetDatabase.LoadAssetAtPath<GameObject>(path);
                    var expected=ReferenceAssets.CatalogueCompanions(asset);var root=ReferenceAssets.InstantiateAssembly(asset,expected,scene);
                    if(PrefabUtility.GetPrefabInstanceStatus(root)!=PrefabInstanceStatus.Connected)throw new InvalidDataException("Root prefab disconnected");
                    foreach(JObject row in expected){
                        var children=root.transform.Cast<Transform>().Where(t=>t.name==(string)row["name"]).ToArray();
                        if(children.Length!=1||PrefabUtility.GetPrefabInstanceStatus(children[0])!=PrefabInstanceStatus.Connected)throw new InvalidDataException("Missing or duplicate connected companion");
                        var v=row["local_position_m"];if(Vector3.Distance(children[0].localPosition,new Vector3((float)v[0],(float)v[1],(float)v[2]))>.001f)throw new InvalidDataException("Incorrect companion offset");
                    }
                    rows.Add(new JObject{["prefab"]=path,["connected"]=true,["verified_companions"]=expected});
                }
                var pathReport=Path.Combine(Directory.GetParent(Application.dataPath).Parent.Parent.FullName,".hdrp-agent/reports/gp-assembly-preview-tests.json");
                File.WriteAllText(pathReport,new JObject{["result"]="Passed",["utc"]=DateTime.UtcNow.ToString("o"),["assemblies"]=rows}.ToString());
            }finally{EditorSceneManager.ClosePreviewScene(scene);}
        }
        [MenuItem("Tools/HDRP Agent/Inspect gp assembly example")]
        static void InspectExample()=>Inspect("Assets/gp.unity");
    }
}
