# Recherche et décisions — Agent HDRP

> Extension active 2026-11-01 — maisons créatives : [house-research.md](house-research.md). Les sections historiques ci-dessous restent applicables au socle legacy.


**Date de consultation : 2026-10-28.** Sources primaires officielles ; inspection locale en lecture seule. Aucun accès modèle, bake ni capture de projet exécuté. Les choix d’ingénierie ci-dessous sont distingués des capacités documentées.

## R1 — Versions et capacité de la machine

**Décision** : Unity 6000.3.23f1 + HDRP 17.3.0, Metal et Progressive GPU Lightmapper. Verrouiller les versions du projet de recette. Exclure le ray tracing HDRP du MVP Mac.

**Raison** : l’éditeur installé est dans `/Applications/Unity/Hub/Editor/6000.3.23f1/Unity.app`. Son package intégré `com.unity.render-pipelines.high-definition/package.json` déclare 17.3.0. Les docs HDRP couvrent Metal ; le lightmapper CPU n’est pas pris en charge dans l’éditeur Apple Silicon natif. Les fonctions ray tracing HDRP requièrent DX12/Windows, indépendamment du GPU lightmapper. La compatibilité documentaire ne garantit pas le succès d’un bake sur le matériel réel.

**Alternatives** : CPU natif rejeté car non pris en charge ; machine Windows/ray tracing hors moyens du premier prototype ; URP ne répond pas au besoin HDRP.

**Validation d’exécution** : petite pièce aux UV valides, vrai bake GPU avec fichiers attendus puis restauration. Si échec, marquer la partie éclairage indirect non livrée ; aucune substitution silencieuse par une simple lumière temps réel.

Sources : [HDRP 17.3 : systèmes](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.3/manual/System-Requirements.html), [Lightmapper 6000.3](https://docs.unity.com/en-us/engine/6000.3/manual/lighting-overview/direct-and-indirect-lighting/lightmapping/baking-before-runtime/configure/progressive-lightmapper), [systèmes Unity](https://docs.unity.com/en-us/engine/6000.3/manual/get-started/install-and-upgrade/getting-started-installing-unity/system-requirements), [ray tracing HDRP](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.3/manual/Ray-Tracing-Getting-Started.html).

## R2 — Capture finale et répétabilité

**Décision** : une caméra active dans une fixture PlayMode ; GameView 1280 × 720 ; `WaitForEndOfFrame` puis `ScreenCapture.CaptureScreenshotIntoRenderTexture` et `AsyncGPUReadback`. Fallback synchrone borné. PNG sources et MP4/H.264 dérivé sans audio par ffmpeg.

**Raison** : capture du rendu final avec post-traitement. `WaitForEndOfFrame` nécessite le GameView et ne tourne pas en Editor batch mode ; les recettes graphiques doivent rester dans l’éditeur interactif. `Time.captureFramerate` fixe le temps simulé, sans mesurer la performance réelle. Mesurer celle-ci séparément, sans readback.

**Choix de recette** : 24 fps, six secondes, poses indexées par frame ; exposition Fixed, même EV/tonemap, graines et état initial. 32 frames de chauffe après remise à zéro, jusqu’à 120 sur instabilité ; seuils définis avant essais à partir d’un témoin répété. Aucun nombre de frames ne garantit à lui seul la convergence temporelle.

**Alternatives** : capture SceneView rejetée pour la preuve finale ; `Camera.Render` ne doit pas être supposée équivalente en SRP. `SubmitRenderRequest`/`StandardRequest` offre une alternative HDRP documentée, avec historique distinct et sans AOV : à qualifier avant de changer de chaîne de capture.

Sources : [ScreenCapture](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityengine/screencapture/capturescreenshotintorendertexture), [fin de frame](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityengine/waitforendofframe), [temps de capture](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityengine/time/captureframerate), [exposition](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.3/manual/reference-override-exposure.html), [RenderRequest](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityengine/rendering/renderpipeline/submitrenderrequest).

## R3 — Bake asynchrone et retour persistant

**Décision** : automate explicite autour de `BakeAsync`, `bakeStarted`, `bakeCompleted`, `bakeCancelled`, `isRunning` et `Cancel`. Contrôler la version et les ressources produites avant validation. Après timeout, annuler et attendre l’arrêt avant restauration.

**Raison** : acceptation du démarrage et absence de tâche en cours ne prouvent pas une réussite. Un rechargement de domaine ou crash sans résultat durable produit une interruption. Les modifications doivent s’exécuter via le thread principal de l’éditeur, dont `EditorApplication.update` n’est pas une horloge fixe.

**Choix de restauration** : scène, ressources mutables, `.meta`, LightingDataAsset, lightmaps et probes concernés dans un manifeste hashé ; inventorier aussi les fichiers nouvellement produits. Copie de travail et dépendances clonées ; suppression des seuls fichiers possédés par l’essai. Vérifier les modifications concurrentes avant toute restauration. Les caches régénérables ne sont pas une preuve de version.

**Alternatives** : `Undo` seul insuffisant pour fichiers générés/redémarrage ; `ClearLightingDataAsset` n’est pas une annulation puisqu’il supprime des ressources.

Sources : [Lightmapping](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityeditor/lightmapping), [BakeAsync](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityeditor/lightmapping/bakeasync), [dépendances](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityeditor/assetdatabase/getdependencies), [boucle d’éditeur](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityeditor/editorapplication).

## R4 — Objet, masque et causalité

**Décision** : identités persistantes `GlobalObjectId` en EditMode après sauvegarde ; clés logiques sérialisées dans la copie de travail pour la capture PlayMode. Projection/profondeur/raycast d’abord. SAM désigne une région, sans lui attribuer une cause ni une identité Unity.

**Raison** : `GlobalObjectId` est une API d’authoring exclue du runtime ; `InstanceID` n’est pas stable entre sessions. `ObjectIdRequest` peut aider dans l’éditeur, mais son fallback géométrique HDRP doit être qualifié sur matériaux/transparences. Les AOV peuvent exposer normales, albedo et contributions lumineuses ; leur présence n’implique pas une intégration déjà réalisée.

**Alternatives** : SAM seul ne distingue pas réglage, UV, réflexion ou brouillard ; IDs moteur seuls ne décrivent pas toutes les régions visuelles. Comparaison expérimentale des deux sur dix régions, sans imposer une amélioration.

Sources : [GlobalObjectId](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityeditor/globalobjectid), [ObjectIdRequest](https://docs.unity.com/en-us/engine/6000.3/script-reference/unityengine/rendering/objectidrequest), [AOV HDRP](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.3/manual/AOVs.html).

## R5 — Modèles et format Meta

**Décision** : adaptateurs Responses `muse-spark-1.3` pour analyse/proposition et `sam-3.1` pour segmentation. Base `https://api.meta.ai/v1`. Spark avec JSON strict via `text.format`, SAM avec son parseur officiel `meta-sam-parser`.

**Raison** : Spark accepte images/vidéos. SAM utilise Responses et renvoie un flux de tokens de segmentation, pas un objet JSON ni des identités Unity. Le parseur officiel gère l’encodage base85 et les masques. Un résultat sans correspondance est valide ; des frames peuvent arriver hors ordre. Muse Wonder n’est pas requis dans ce parcours.

**Transport** : images inline bornées ; clips MP4 uploadés avec `purpose=user_data`, puis `input_video.file_id`. Pas d’URL publique nécessaire. Supprimer les seuls fichiers distants créés par l’application après exploitation. Meta indique 50 images/requête, 50 000 000 octets inline, 1 GiB par upload et 100 GiB de stockage équipe sans expiration automatique. Le prototype reste largement sous ces limites.

**Alternatives** : frames horodatées pour analyse si vidéo native indisponible ; ne pas conclure à l’absence d’un défaut temporel sous-échantillonné. Fournisseur non Meta exclu par FR-020. L’accès de cette équipe reste à vérifier par sonde, indépendamment des docs publiques.

Sources : [modèles](https://dev.meta.ai/docs/models), [authentification](https://dev.meta.ai/docs/authentication), [images](https://dev.meta.ai/docs/image-understanding), [vidéo](https://dev.meta.ai/docs/video-understanding), [fichiers](https://dev.meta.ai/docs/file-handling), [JSON structuré](https://dev.meta.ai/docs/structured-output), [Responses](https://dev.meta.ai/docs/api-reference/responses/schemas), [SAM](https://dev.meta.ai/docs/sam/segmenting), [résultats SAM](https://dev.meta.ai/docs/sam/reading-segmentation), [parseurs officiels](https://dev.meta.ai/docs/sam/client-libraries), [disponibilité](https://dev.meta.ai/help/accounts-and-login/supported-countries).

## R6 — Tarifs et plafond global

**Décision** : Standard, sans Contributor, et sans outils hébergés. Grand livre global en euros, réservation atomique au majorant avant réseau, conservation des engagements d’issue inconnue. Les sondes sont facturées sur la même enveloppe que le produit.

**Tarifs USD documentés à la consultation** :

| Dimension | Tarif |
|---|---:|
| Spark Standard entrée / million tokens | 1,25 USD |
| Spark entrée cachée / million | 0,15 USD |
| Spark sortie / million | 4,25 USD |
| SAM / 1 000 images | 2,50 USD |
| SAM / 1 000 frames vidéo | 0,20 USD |

SAM vidéo facture au minimum 50 frames par requête ; utiliser `max(50, frames facturables majorées)` pour la réservation. Ne pas transférer ces prix aux images Spark, qui sont tokenisées. Réserver les entrées Spark au tarif non caché ; une réduction éventuelle est constatée après réponse. Contributor implique une décision d’usage des contenus pour entraînement et n’est pas activé par défaut.

L’alerte de dépense Meta n’est pas un plafond bloquant. Le guide token counting indique que le contexte rendu ne prédit pas directement la facture ; il peut inclure du contexte ajouté par Meta. Les outils hébergés ajoutent aussi des étapes. Le décompte sert au contrôle de taille et à une estimation conservatrice validée, jamais seul à la garantie des 150 EUR. Voir le [contrat fournisseur](contracts/provider.md) pour l’admission.

**Alternatives** : nombre fixe d’appels ou coût moyen par capture insuffisants ; compter le cache comme acquis fragilise le plafond ; relâcher une réservation sur timeout peut doubler la dépense. Usage externe de la même clé : réconciliation obligatoire, pas de garantie globale sans visibilité sur cet usage.

**Majorant retenu** : la fenêtre multimodale Spark documentée vaut 1 048 576 tokens. Sans outils et avec 4 096 tokens maximum de sortie, réserver toute cette entrée au tarif non caché plus cette sortie donne 1,328128 USD avant conversion/provisions. C’est une borne conservatrice déduite de la documentation, sans hypothèse de coût moyen par image ni assimilation du décompte de contexte à la facture ; elle ne constitue pas un engagement monétaire du fournisseur.

Sources : [prix et limites](https://dev.meta.ai/docs/pricing-rate-limits), [modèles](https://dev.meta.ai/docs/models), [schémas Responses](https://dev.meta.ai/docs/api-reference/responses/schemas), [alerte budgétaire](https://dev.meta.ai/help/billing/spend-limit-alert), [token counting](https://dev.meta.ai/docs/token-counting).

## R7 — Architecture locale et contrats

**Décision d’ingénierie** : UI Toolkit dans Unity ; service Python 3.12 FastAPI/Pydantic ; HTTP loopback avec polling sortant Unity ; SQLite pour commandes, états et argent ; fichiers hashés pour médias. Un worker et une session.

**Raison** : pas d’obligation de recréer une interface web ni d’utiliser un MCP tiers pour chaque réglage. La file reste persistante ; la coroutine d’orchestration démarre via le lifespan du service, pas une tâche mémoire supposée survivre à un crash. SQLite permet un seul écrivain à la fois et `BEGIN IMMEDIATE` pour l’admission budgétaire. Les réponses modèle sont revalidées avec types stricts et champs supplémentaires refusés.

**Alternatives** : C# seul réduit les runtimes mais complique parseur SAM, médias et ledger ; React ajoute un produit à construire sans améliorer la première preuve ; Redis/Celery disproportionnés ; intégration MCP optionnelle après stabilité du contrat.

Sources : [transactions SQLite](https://www.sqlite.org/lang_transaction.html), [lifespan FastAPI](https://fastapi.tiangolo.com/advanced/events/), [validation Pydantic](https://pydantic.dev/docs/validation/2.12/concepts/models/).

## R8 — Recette et cause réelle

**Décision d’ingénierie** : trois cas aux causes privées, préqualifiés avant mesure : GI indirecte dégradée sur UV valides, volumétrie incohérente avec le brief et défaut de répartition lumineuse/volumétrique spatial. Un cas géométrique complète la création de pièce. Les oracles restent dans `evaluation-private/` et ne sont jamais chargés par le planificateur.

**Raison** : un vrai artefact visible et reproductible doit exister avant de mesurer sa réparation. Certains défauts exigent un unwrap ou un shader hors MVP ; les diagnostiquer comme non pris en charge est préférable à masquer le symptôme par exposition ou suppression d’effet. Le ghosting est un cas temporel intéressant, mais ne doit pas être l’unique preuve positive.

**Alternatives** : note esthétique globale auto-attribuée insuffisante ; images avant/après sur des caméras différentes non probantes ; vues de contrôle communiquées après chaque échec risquent de devenir des vues d’entraînement.

Sources de limites techniques : [artefacts de lightmapping](https://docs.unity.com/en-us/engine/6000.3/manual/lighting-overview/direct-and-indirect-lighting/lightmapping/baking-before-runtime/troubleshooting/troubleshooting-lightmapping-artifacts), [volumétriques HDRP](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.3/manual/Volumetric-Lighting.html).

## Résolution et portes de réalisation

Les choix d’architecture, de version, de transport et de validation sont arrêtés. Aucun choix de conception n’attend une clarification utilisateur. Restent des preuves d’exécution, consignées comme tests J0/J1 : stabilité des captures et GPU bake ; accès réel Muse/SAM ; décodage et majorants de coûts ; valeur du diagnostic sur les fixtures. Un test échoué donne un statut explicite et ferme le parcours correspondant. Cette recherche ne les annonce pas réussis.


## Recherche locale — correction de fidélité, 2026-10-29

Sources : code actuel `src/hdrp_agent/reference_{pose,geometry,memory,worker,inspection}.py`, `ReferenceContacts.cs`, rapports `scene-vision-qualification.json` et `ground-truth-de8919eabdab49d78d38c0ec81384b65.json`. Recherche sur l’implémentation locale ; aucune nouvelle affirmation de capacité fournisseur ni dépendance externe à vérifier.

| Décision | Justification observée | Alternatives considérées |
|---|---|---|
| Optimiser un ancrage XYZ et les relations de support | Y absent de la recherche de poses ; contacts corrects malgré dérive commune | Ajouter +0,16 m : rejeté, sur-ajustement à la vérité terrain |
| Évaluer après contact natif | IoU actuel calculé avant mutation finale des poses | Score pré-contact : ne décrit pas la scène livrée |
| Séparer géométrie et rendu | RGB/gradient horizontal dominent actuellement le classement, même en placement | Modifier seulement les poids : ne retire pas la confusion pose/lumière |
| Traiter visibilité et occultation | Raster isolé de chaque prefab contre masque visible | Forcer tous les masques : risque de faux déplacement/échelle |
| Échelle verrouillée, déverrouillage explicite | Pot/bol s’écartent d’environ 13,7 % de la taille de référence | Libre adaptation de taille : peut masquer mauvais ancrage ou masque |
| Propositions Muse et solveur séparées | Le raffinement peut modifier le déplacement proposé avant mesure | Enchaînement silencieux : impossible d’attribuer l’amélioration ou l’échec |
| Ordonnancement par erreur, bornes conservées | Six phases fixes ne démontrent aucune convergence | Multiplier les essais sans métriques fiables : risque de coût sans gain |
| Vérité terrain après exécution uniquement | Autorisation utilisateur pour vérifier, pas pour fournir la solution | Comparaison seulement visuelle : insuffisante pour qualifier la fidélité |

Incertitude restante transformée en test d’implémentation : origine exacte du Y initial erroné (seed, triangulation de centres visibles, conventions ou support). Aucun besoin d’information utilisateur supplémentaire ; T113/T117 doivent trancher avec perturbations contrôlées. Les objectifs numériques du plan sont des choix de recette, jamais des résultats acquis.


## Extension application Go — 2026-10-31

[Décisions du chat Go](chat-research.md) complète ce document pour US10–US13. L’application est planifiée ; ses commandes et endpoints ne sont pas encore livrés. Le budget, les preuves et les automatismes de reprise du socle restent applicables.
