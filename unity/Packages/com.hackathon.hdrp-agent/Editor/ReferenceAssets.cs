using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HdrpAgent.Editor
{
    public static class ReferenceAssets
    {
        public static float[] Vec(Vector3 v)=>new[]{v.x,v.y,v.z};
        public static JArray Catalogue(string root){
            if(root!="Assets/AtmosphericHouse/Prefabs")throw new InvalidDataException("Only the local AtmosphericHouse catalogue is qualified");
            var assets=new JArray();
            foreach(var guid in AssetDatabase.FindAssets("t:Prefab",new[]{root}).OrderBy(v=>v,StringComparer.Ordinal)){
                var path=AssetDatabase.GUIDToAssetPath(guid);var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if(prefab==null)continue;
                var renderers=prefab.GetComponentsInChildren<MeshRenderer>(true).Where(r=>r.GetComponent<MeshFilter>()?.sharedMesh!=null).ToArray();
                if(renderers.Length==0)continue;
                var bounds=new Bounds();bool first=true;
                foreach(var renderer in renderers){
                    var local=renderer.GetComponent<MeshFilter>().sharedMesh.bounds;
                    for(int i=0;i<8;i++){
                        var p=local.center+Vector3.Scale(local.extents,new Vector3((i&1)==0?-1:1,(i&2)==0?-1:1,(i&4)==0?-1:1));
                        p=prefab.transform.InverseTransformPoint(renderer.transform.TransformPoint(p));
                        if(first){bounds=new Bounds(p,Vector3.zero);first=false;}else bounds.Encapsulate(p);
                    }
                }
                var materials=renderers.SelectMany(r=>r.sharedMaterials).Where(m=>m!=null).Distinct().ToArray();
                assets.Add(JObject.FromObject(new{asset_id="asset-"+assets.Count.ToString("D4"),asset_guid=guid,path,name=prefab.name,bounds_center_m=Vec(bounds.center),bounds_size_m=Vec(bounds.size),dependency_hash=AssetDatabase.GetAssetDependencyHash(path).ToString(),static_clone=false,construction_mode="connected_prefab_with_companions",assembly_companions=CatalogueCompanions(prefab),material_names=materials.Select(m=>m.name).ToArray(),transparent_materials=materials.Count(m=>(m.HasProperty("_SurfaceType")&&m.GetFloat("_SurfaceType")>.5f)||m.renderQueue>=3000),preserved_behaviours=prefab.GetComponentsInChildren<MonoBehaviour>(true).Where(b=>b!=null).Select(b=>b.GetType().FullName).Distinct().ToArray()}));
                if(assets.Count>1000)throw new InvalidDataException("Catalogue exceeds qualified bound");
            }
            if(assets.Count==0)throw new InvalidDataException("Local static prefab catalogue is empty");
            return assets;
        }
        public static JArray Companions(GameObject prefab){
            var rows=new JArray();
            var swap=prefab.GetComponents<MonoBehaviour>().FirstOrDefault(b=>b!=null&&b.GetType().FullName=="FS_Atmo.SwapPrefab");
            if(swap==null)return CompleteWallCompanions(prefab,rows);
            var data=new SerializedObject(swap);var names=data.FindProperty("spawnAlongs");
            var positions=data.FindProperty("spawnAlongsPos");var rotations=data.FindProperty("spawnAlongsRot");
            if(names==null||!names.isArray)return CompleteWallCompanions(prefab,rows);
            for(int i=0;i<names.arraySize;i++)rows.Add(new JObject{["name"]=names.GetArrayElementAtIndex(i).stringValue,["local_position_m"]=JArray.FromObject(Vec(positions!=null&&positions.arraySize>i?positions.GetArrayElementAtIndex(i).vector3Value:Vector3.zero)),["local_rotation_deg"]=JArray.FromObject(Vec(rotations!=null&&rotations.arraySize>i?rotations.GetArrayElementAtIndex(i).vector3Value:Vector3.zero))});
            return CompleteWallCompanions(prefab,rows);
        }
        public static JArray CatalogueCompanions(GameObject prefab){
            var profilePath=Path.Combine(Directory.GetParent(Application.dataPath).Parent.Parent.FullName,".hdrp-agent/reports/gp-native-assembly.json");
            if(!File.Exists(profilePath))return Companions(prefab);
            var profile=JObject.Parse(File.ReadAllText(profilePath));var scene=(string)profile["source_scene"];
            if(!File.Exists(scene)||BridgeJson.Hash(File.ReadAllBytes(scene))!=(string)profile["source_sha256"])return Companions(prefab);
            var path=AssetDatabase.GetAssetPath(prefab);
            var observed=((JArray)profile["instances"]).OfType<JObject>().Where(row=>(string)row["parent_prefab_path"]==path&&((string)row["prefab_path"]).StartsWith("Assets/AtmosphericHouse/Prefabs/",StringComparison.Ordinal)).GroupBy(row=>(string)row["prefab_path"]).ToArray();
            if(observed.Length==0)return Companions(prefab);
            var result=new JArray();
            foreach(var group in observed){
                var row=group.First();
                // Repeated instances must agree on the attachment, not just asset identity.
                if(group.Any(other=>Vector3.Distance(ReadVec(other["position_relative_to_parent_m"]),ReadVec(row["position_relative_to_parent_m"]))>.01f||Quaternion.Angle(Quaternion.Euler(ReadVec(other["rotation_relative_to_parent_deg"])),Quaternion.Euler(ReadVec(row["rotation_relative_to_parent_deg"])))>1f))return Companions(prefab);
                result.Add(new JObject{["name"]=Path.GetFileNameWithoutExtension(group.Key),["local_position_m"]=row["position_relative_to_parent_m"].DeepClone(),["local_rotation_deg"]=row["rotation_relative_to_parent_deg"].DeepClone(),["evidence_scene_sha256"]=profile["source_sha256"]});
            }
            return CompleteWallCompanions(prefab,result);
        }
        static JArray CompleteWallCompanions(GameObject prefab,JArray rows){
            const string prefix="WallOut_";
            if(!prefab.name.StartsWith(prefix,StringComparison.Ordinal)||rows.Any(r=>((string)r["name"]).StartsWith("WallIn_",StringComparison.Ordinal)))return rows;
            // Some pack modules have no SwapPrefab component (notably WallOut_6x).
            // Match the exact opening/size suffix; never plug a window with a solid wall.
            var suffix=prefab.name.Substring(prefix.Length);
            var directory=Path.GetDirectoryName(AssetDatabase.GetAssetPath(prefab)).Replace('\\','/');
            var mesh=prefab.GetComponent<MeshFilter>()?.sharedMesh;
            if(mesh==null)return rows;
            foreach(var style in new[]{"B","A","C"}){
                string name="WallIn_"+style+"_"+suffix;
                var interior=AssetDatabase.LoadAssetAtPath<GameObject>(directory+"/"+name+".prefab");
                var inner=interior?.GetComponent<MeshFilter>()?.sharedMesh;
                if(inner==null||Mathf.Abs(inner.bounds.size.x-mesh.bounds.size.x)>.02f)continue;
                float offset=mesh.bounds.center.x+inner.bounds.center.x;
                rows.Add(new JObject{["name"]=name,["local_position_m"]=new JArray(offset,0,0),["local_rotation_deg"]=new JArray(0,180,0),["evidence"]="Exact AtmosphericHouse module suffix and matching mesh width; opposite face socket aligned by local bounds"});
                break;
            }
            return rows;
        }
        static Vector3 ReadVec(JToken v)=>new Vector3((float)v[0],(float)v[1],(float)v[2]);
        public static GameObject InstantiateAssembly(GameObject source,JArray companions=null,UnityEngine.SceneManagement.Scene? destination=null){
            var paths=AssetDatabase.FindAssets("t:Prefab",new[]{"Assets/AtmosphericHouse/Prefabs"}).Select(AssetDatabase.GUIDToAssetPath).ToArray();
            return InstantiateAssembly(source,paths,0,companions,destination);
        }
        static GameObject InstantiateAssembly(GameObject source,string[] paths,int depth,JArray companions=null,UnityEngine.SceneManagement.Scene? destination=null){
            if(source==null||!PrefabUtility.IsPartOfPrefabAsset(source)||depth>4)throw new InvalidDataException("Invalid or cyclic prefab assembly");
            var root=(GameObject)PrefabUtility.InstantiatePrefab(source,destination??UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            try{
                // The pack normally creates companions when its custom inspector opens.
                // Resolve them explicitly so headless placement has the same structure.
                foreach(var swap in root.GetComponentsInChildren<MonoBehaviour>(true).Where(b=>b!=null&&b.GetType().FullName=="FS_Atmo.SwapPrefab")){
                    var data=new SerializedObject(swap);var placed=data.FindProperty("placed");
                    if(placed!=null){placed.boolValue=true;data.ApplyModifiedPropertiesWithoutUndo();PrefabUtility.RecordPrefabInstancePropertyModifications(swap);}
                }
                foreach(JObject row in CompleteWallCompanions(source,companions??Companions(source))){
                    var name=(string)row["name"];var matches=paths.Where(p=>Path.GetFileNameWithoutExtension(p)==name).ToArray();
                    if(matches.Length!=1)throw new InvalidDataException("Companion prefab must resolve uniquely: "+name);
                    if(root.GetComponentsInChildren<Transform>(true).Any(t=>t!=root.transform&&PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject)==matches[0]))continue;
                    var child=InstantiateAssembly(AssetDatabase.LoadAssetAtPath<GameObject>(matches[0]),paths,depth+1,null,root.scene);
                    child.transform.SetParent(root.transform,false);child.transform.localPosition=new Vector3((float)row["local_position_m"][0],(float)row["local_position_m"][1],(float)row["local_position_m"][2]);
                    child.transform.localRotation=Quaternion.Euler((float)row["local_rotation_deg"][0],(float)row["local_rotation_deg"][1],(float)row["local_rotation_deg"][2]);
                    PrefabUtility.RecordPrefabInstancePropertyModifications(child.transform);
                }
                return root;
            }catch{UnityEngine.Object.DestroyImmediate(root);throw;}
        }
        // Copy render geometry only: no prefab script is ever instantiated or run.
        public static GameObject CloneStatic(GameObject source){
            var root=new GameObject(source.name);CopyNode(source.transform,root.transform);return root;
        }
        static void CopyNode(Transform source,Transform target){
            target.localPosition=source.localPosition;target.localRotation=source.localRotation;target.localScale=source.localScale;target.gameObject.SetActive(source.gameObject.activeSelf);
            var filter=source.GetComponent<MeshFilter>();var renderer=source.GetComponent<MeshRenderer>();
            if(filter!=null&&renderer!=null){
                target.gameObject.AddComponent<MeshFilter>().sharedMesh=filter.sharedMesh;
                var copy=target.gameObject.AddComponent<MeshRenderer>();copy.sharedMaterials=renderer.sharedMaterials;copy.enabled=renderer.enabled;copy.shadowCastingMode=renderer.shadowCastingMode;copy.receiveShadows=renderer.receiveShadows;
            }
            foreach(Transform child in source){var go=new GameObject(child.name);go.transform.SetParent(target,false);CopyNode(child,go.transform);}
        }
        public static bool SavePreview(JObject asset,string output){
            var path=(string)asset["path"];if(AssetDatabase.AssetPathToGUID(path)!=(string)asset["asset_guid"]||AssetDatabase.GetAssetDependencyHash(path).ToString()!=(string)asset["dependency_hash"])throw new InvalidDataException("Preview asset changed");
            var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(path);var utility=new PreviewRenderUtility();var previous=RenderTexture.active;
            var image=new Texture2D(1280,640,TextureFormat.RGB24,false);var target=RenderTexture.GetTemporary(640,640,24,RenderTextureFormat.ARGB32);
            try{
                var clone=InstantiateAssembly(prefab,asset["assembly_companions"] as JArray);clone.transform.SetPositionAndRotation(Vector3.zero,Quaternion.identity);clone.transform.localScale=Vector3.one;utility.AddSingleGO(clone);
                var renderers=clone.GetComponentsInChildren<MeshRenderer>();var bounds=renderers[0].bounds;foreach(var renderer in renderers)bounds.Encapsulate(renderer.bounds);
                var camera=utility.camera;camera.fieldOfView=35;camera.nearClipPlane=.005f;camera.farClipPlane=100;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.12f,.14f,.16f);camera.allowHDR=true;
                camera.gameObject.AddComponent<HDAdditionalCameraData>();var direction=new Vector3(1,.7f,-1).normalized;camera.transform.position=bounds.center+direction*Mathf.Max(.1f,bounds.extents.magnitude/Mathf.Sin(17.5f*Mathf.Deg2Rad)/.8f);camera.transform.LookAt(bounds.center);
                utility.lights[0].transform.rotation=Quaternion.Euler(35,-35,0);utility.lights[0].intensity=1;utility.lights[1].intensity=.5f;utility.ambientColor=Color.gray;
                foreach(var light in utility.lights){light.gameObject.AddComponent<HDAdditionalLightData>();light.intensity=2;}
                var volume=new GameObject("Asset preview exposure");utility.AddSingleGO(volume);var v=volume.AddComponent<Volume>();v.isGlobal=true;v.priority=10000;v.profile=ScriptableObject.CreateInstance<VolumeProfile>();var exposure=v.profile.Add<Exposure>(true);exposure.mode.Override(ExposureMode.Fixed);exposure.fixedExposure.Override(0);
                for(int angle=0;angle<2;angle++){
                    direction=new Vector3(angle==0?1:-1,.7f,angle==0?1:-1).normalized;camera.transform.position=bounds.center+direction*Mathf.Max(.1f,bounds.extents.magnitude/Mathf.Sin(17.5f*Mathf.Deg2Rad)/.8f);camera.transform.LookAt(bounds.center);
                    utility.lights[0].transform.rotation=camera.transform.rotation*Quaternion.Euler(20,-25,0);utility.lights[1].transform.rotation=camera.transform.rotation*Quaternion.Euler(-10,65,0);
                    utility.BeginPreview(new Rect(0,0,640,640),GUIStyle.none);utility.Render(true,true);var preview=utility.EndPreview();
                    Graphics.Blit(preview,target);RenderTexture.active=target;image.ReadPixels(new Rect(0,0,640,640),angle*640,0);
                }
                image.Apply();File.WriteAllBytes(output,image.EncodeToPNG());UnityEngine.Object.DestroyImmediate(v.profile);return true;
            }finally{RenderTexture.active=previous;RenderTexture.ReleaseTemporary(target);UnityEngine.Object.DestroyImmediate(image);utility.Cleanup();}
        }
    }
}
