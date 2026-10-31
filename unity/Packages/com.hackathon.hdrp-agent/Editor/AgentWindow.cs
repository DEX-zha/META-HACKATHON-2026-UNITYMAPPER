using System;
using System.IO;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace HdrpAgent.Editor
{
    public sealed class AgentWindow:EditorWindow
    {
        string brief="Une pièce éclairée naturellement, avec une fenêtre, une table et un faisceau volumétrique lisible.";
        string diagnostic="Pipeline local à qualifier avant toute correction autonome.";
        string mode="offline";
        Vector2 scroll;
        Texture2D preview;
        string loaded;
        int comparisonView;
        string sessionId,sessionState="Aucune session",sessionVerdict="pending",budgetStatus="",pendingRoute,pendingBody,pendingMethod;
        bool startWhenRegistered;
        double nextSessionPoll;
        string Workspace=>Directory.GetParent(Application.dataPath).Parent.Parent.FullName;
        void StartSession(){
            if(!BridgeClient.Registered){diagnostic="Connecter le service puis relancer.";return;}
            startWhenRegistered=true;BridgeClient.Connect();
        }
        void QueueSession(){
            var plan=JObject.Parse(File.ReadAllText(Path.Combine(Workspace,"fixtures","inspection-plans","room.json")));
            var frozenBrief=JObject.Parse(File.ReadAllText(Path.Combine(Workspace,"fixtures","briefs","room.json")));
            frozenBrief["text"]=brief;frozenBrief["mutation_scope_id"]=SceneInspector.Scope;
            var criteria=new JArray{
                new JObject{["id"]="visibility",["kind"]="visibility",["target"]="work-front",["method"]="luminance_range",["minimum"]=.01,["maximum"]=.9,["unit"]="normalized",["required"]=true},
                new JObject{["id"]="performance",["kind"]="performance",["target"]="performance",["method"]="frame_time_regression",["minimum"]=null,["maximum"]=.2,["unit"]="ratio",["required"]=true},
                new JObject{["id"]="ambiance",["kind"]="artistic",["target"]="ambiance",["method"]="artistic_review",["minimum"]=null,["maximum"]=null,["unit"]="human",["required"]=true}
            };
            pendingBody=new JObject{["project_id"]=BridgeClient.ProjectId,["scene_id"]=BridgeClient.SceneId,["base_version"]=SceneInspector.Version(),["mode"]="inspect",["brief"]=frozenBrief,["criteria"]=criteria,["inspection"]=plan,["max_attempts"]=3,["session_timeout_seconds"]=1200,["bake_timeout_seconds"]=600,["provider_mode"]=mode}.ToString(Newtonsoft.Json.Formatting.None);
            pendingRoute="/v1/sessions";pendingMethod="POST";
        }
        void PollService(){
            if(!BridgeClient.Registered||BridgeClient.RequestInProgress)return;
            if(startWhenRegistered){startWhenRegistered=false;Try(QueueSession);}
            if(!string.IsNullOrEmpty(pendingRoute)){
                var route=pendingRoute;var body=pendingBody;var method=pendingMethod;pendingRoute=null;pendingBody=null;
                if(string.IsNullOrEmpty(method)){diagnostic="Commande du panneau incomplète après transition ; relancer explicitement.";return;}
                BridgeClient.Request(method,route,body,"ui-"+Guid.NewGuid().ToString("N"),(ok,text)=>{
                    diagnostic=text;if(ok){var data=JObject.Parse(text);if(data["id"]!=null)sessionId=(string)data["id"];}
                });return;
            }
            if(EditorApplication.timeSinceStartup<nextSessionPoll)return;
            nextSessionPoll=EditorApplication.timeSinceStartup+2;
            if(!string.IsNullOrEmpty(sessionId))BridgeClient.Request("GET","/v1/sessions/"+sessionId,null,null,(ok,text)=>{
                if(!ok)return;var data=JObject.Parse(text);sessionState=(string)data["state"];sessionVerdict=(string)data["verdict"];diagnostic=text;
            });
            else BridgeClient.Request("GET","/v1/budget",null,null,(ok,text)=>{if(ok){var data=JObject.Parse(text);budgetStatus=string.Format("Disponible : {0:F4} $ · engagé : {1:F4} $",(double)data["available_usd_micro"]/1000000,(double)data["active_reserved_usd_micro"]/1000000);}});
        }
        readonly Dictionary<string,Texture2D> comparisons=new Dictionary<string,Texture2D>();
        void DrawComparison(){
            var workspace=Directory.GetParent(Application.dataPath).Parent.Parent.FullName;
            var report=Path.Combine(workspace,".hdrp-agent","reports","j0-local-pipeline.json");if(!File.Exists(report))return;
            var data=JObject.Parse(File.ReadAllText(report));if((bool?)data["restored_files_verified"]!=true)return;
            var captures=data["captures"] as JArray;if(captures==null||captures.Count<3||captures[0].Type==JTokenType.Null||captures[2].Type==JTokenType.Null)return;
            var keys=new[]{"work-front","work-right","work-left","control-corner","control-low"};comparisonView=EditorGUILayout.Popup("Même vue",comparisonView,keys);
            EditorGUILayout.LabelField("Avant / après restauration — preuve locale, sans verdict de correction",EditorStyles.wordWrappedLabel);
            EditorGUILayout.BeginHorizontal();
            foreach(var index in new[]{0,2}){
                var path=Path.Combine((string)captures[index],keys[comparisonView]+".png");
                if(!File.Exists(path))continue;
                if(!comparisons.TryGetValue(path,out var texture)){texture=new Texture2D(2,2);texture.LoadImage(File.ReadAllBytes(path));comparisons[path]=texture;}
                GUILayout.Label(texture,GUILayout.Width((position.width-35)/2),GUILayout.Height((position.width-35)*9/32));
            }
            EditorGUILayout.EndHorizontal();
        }
        [MenuItem("Window/HDRP Agent/Agent")]
        public static void Open(){GetWindow<AgentWindow>("HDRP Agent");}
        void OnInspectorUpdate(){PollService();Repaint();}
        void OnGUI(){
            scroll=EditorGUILayout.BeginScrollView(scroll);
            EditorGUILayout.LabelField("Agent de scène HDRP",EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(BridgeClient.Status,BridgeClient.Registered?MessageType.Info:MessageType.Warning);
            using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor&&BridgeClient.Registered)){
                if(GUILayout.Button("Connecter le service local"))BridgeClient.Connect();
            }
            EditorGUILayout.LabelField("Brief");brief=EditorGUILayout.TextArea(brief,GUILayout.MinHeight(60));
            int choice=EditorGUILayout.Popup("Mode demandé",mode=="offline"?0:1,new[]{"Offline — validation locale","Live — après qualification et budget"});mode=choice==0?"offline":"live";
            EditorGUILayout.HelpBox("Maximum : 3 essais · 20 minutes · 10 minutes par bake · budget API restant 150 $ confirmé, partagé entre toutes les sessions.",MessageType.None);
            EditorGUILayout.LabelField("Budget API",budgetStatus);
            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Reproduire une référence",EditorStyles.boldLabel);
            EditorGUILayout.LabelField("Recréer les objets, leur placement et les lumières avec les assets du projet.",EditorStyles.wordWrappedLabel);
            using(new EditorGUI.DisabledScope(ReferenceWorkflow.Running||BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||LocalValidationRunner.Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)){
                SessionState.SetBool("HdrpAgent.EvidencedScale",EditorGUILayout.Toggle(new GUIContent("Ajuster les tailles sur preuve multivue","Les tailles restent verrouillées par défaut. Une correction exige trois vues concordantes et reste bornée à 15 %."),SessionState.GetBool("HdrpAgent.EvidencedScale",false)));
                if(GUILayout.Button("Enregistrer cette scène et la reproduire"))Try(()=>ReferenceWorkflow.RecordCurrent());
                if(GUILayout.Button("Apprendre les assemblages d’une scène exemple…"))Try(()=>{var file=EditorUtility.OpenFilePanel("Scène exemple enregistrée",Application.dataPath,"unity");if(!string.IsNullOrEmpty(file)){var path=FileUtil.GetProjectRelativePath(file);if(!path.StartsWith("Assets/",StringComparison.Ordinal))throw new InvalidOperationException("Choisir une scène enregistrée dans Assets du projet");ReferenceAssemblyExample.Inspect(path);ReferenceAssemblyExample.ValidatePreview();}});
                if(GUILayout.Button("Reproduire un plan de pièce avec les modules Building…"))Try(()=>{var file=EditorUtility.OpenFilePanel("Plan de pièce avec porte et fenêtre","","");if(!string.IsNullOrEmpty(file))ReferenceWorkflow.ImportBuildingPlan(new[]{file});});
                if(GUILayout.Button("Reproduire une image ou une vidéo…"))Try(()=>{var file=EditorUtility.OpenFilePanel("Référence visuelle","","");if(!string.IsNullOrEmpty(file))ReferenceWorkflow.ImportMedia(new[]{file});});
            }
            EditorGUILayout.LabelField(ReferenceWorkflow.Status,EditorStyles.wordWrappedLabel);
            if(GUILayout.Button("Voir la vision de l’agent et les gizmos"))ReferenceVisionWindow.ShowWindow();
            if(ReferenceWorkflow.Running&&GUILayout.Button("Arrêter la reproduction"))ReferenceWorkflow.Stop();
            if(!ReferenceWorkflow.Running&&!string.IsNullOrEmpty(ReferenceWorkflow.LastDirectory)&&File.Exists(Path.Combine(ReferenceWorkflow.LastDirectory,"report.json"))){
                using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode))if(GUILayout.Button("Continuer depuis l’analyse enregistrée"))Try(()=>ReferenceWorkflow.ContinueSavedAnalysis());
                using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode))if(GUILayout.Button("Reconstruire depuis cette référence conservée"))Try(()=>ReferenceWorkflow.RebuildSavedReference());
            }
            var referenceReport=Path.Combine(ReferenceWorkflow.LastDirectory,"comparison.html");
            if(File.Exists(referenceReport)&&GUILayout.Button("Voir la comparaison avec la référence"))Application.OpenURL(new Uri(referenceReport).AbsoluteUri);
            if(!ReferenceWorkflow.Running&&File.Exists(referenceReport)&&GUILayout.Button("Comparer aux positions réelles de la démo"))Try(()=>EditorUtility.RevealInFinder(ReferenceGroundTruthAudit.AuditSavedReference()));
            EditorGUILayout.LabelField("Session",sessionState+" · "+sessionVerdict);
            using(new EditorGUI.DisabledScope(!BridgeClient.Registered||BridgeClient.SessionOwnsEditor||LocalValidationRunner.Running||startWhenRegistered||pendingRoute!=null||CommandExecutor.Busy||EditorApplication.isPlayingOrWillChangePlaymode)){
                if(GUILayout.Button("Inspecter et corriger la copie active"))Try(StartSession);
            }
            if(!string.IsNullOrEmpty(sessionId)){
                if(GUILayout.Button("Demander l’arrêt de la session")){pendingMethod="POST";pendingRoute="/v1/sessions/"+sessionId+"/stop";pendingBody="{\"reason\":\"Arrêt depuis Unity\"}";}
                if(GUILayout.Button("Lire le rapport de session")){pendingMethod="GET";pendingRoute="/v1/sessions/"+sessionId+"/report";pendingBody=null;}
            }
            EditorGUILayout.LabelField("Capacités implémentées",string.Join(", ",CommandExecutor.Capabilities));
            using(new EditorGUI.DisabledScope(BridgeClient.SessionOwnsEditor||CommandExecutor.Busy||LocalValidationRunner.Running||EditorApplication.isPlayingOrWillChangePlaymode||Lightmapping.isRunning)){
                if(GUILayout.Button("Préparer la pièce de validation"))Try(()=>ValidationRoomBuilder.Prepare());
                if(GUILayout.Button("Créer une copie de travail isolée"))Try(()=>ValidationRoomBuilder.PrepareWorkingRoom());
                if(GUILayout.Button("Inspecter la copie active"))Try(()=>diagnostic=SceneInspector.Inspect().ToString());
                if(GUILayout.Button("Valider le pipeline local (J0)"))Try(()=>LocalValidationRunner.Start());
            }
            EditorGUILayout.LabelField("Progression",LocalValidationRunner.Status);
            if(LocalValidationRunner.Running&&GUILayout.Button("Demander l’arrêt"))LocalValidationRunner.Stop();
            if(BakeController.Active!=null)EditorGUILayout.LabelField("Bake GPU",BakeController.Active.Finished?(BakeController.Active.Succeeded?"Vérifié":"Échec / interrompu"):"En cours — annulation native parfois différée");
            EditorGUILayout.LabelField("Diagnostic / état",EditorStyles.boldLabel);EditorGUILayout.SelectableLabel(diagnostic,GUILayout.MinHeight(120));
            var output=CaptureController.LastOutput;var path=Path.Combine(output??"","work-front.png");
            if(path!=loaded&&File.Exists(path)){if(preview!=null)DestroyImmediate(preview);preview=new Texture2D(2,2);preview.LoadImage(File.ReadAllBytes(path));loaded=path;}
            if(preview!=null){EditorGUILayout.LabelField("Dernière capture locale — aucun gain revendiqué");GUILayout.Label(preview,GUILayout.MaxWidth(position.width-30),GUILayout.Height((position.width-30)*9/16));}
            DrawComparison();
            EditorGUILayout.EndScrollView();
        }
        void Try(Action action){try{action();}catch(Exception e){diagnostic=e.GetType().Name+": "+e.Message;}}
        void OnDisable(){if(preview!=null)DestroyImmediate(preview);foreach(var texture in comparisons.Values)DestroyImmediate(texture);comparisons.Clear();}
    }
}
