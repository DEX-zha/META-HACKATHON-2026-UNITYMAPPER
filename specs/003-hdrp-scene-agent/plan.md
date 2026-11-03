# Implementation Plan: Agent de création et de contrôle visuel HDRP

> **Mise à jour utilisateur du 2026-10-28** : plafond de consommation API de **150 USD encore disponibles**, suivi directement en micro-USD ; modèle `muse-spark-1.3-contributor` autorisé explicitement. La confirmation du solde restant est enregistrée une seule fois, sans recharge lors d’une nouvelle session. Cette instruction remplace les anciennes règles Standard/EUR et le blocage faute d’antériorité/changement/frais ; la clé reste dans `.env`, côté Python.

**Branch**: Git `main` ; identifiant Spec Kit `003-hdrp-scene-agent`. Dépôt SSH : `git@github.com:DEX-zha/META-HACKATHON-2026-UNITYMAPPER.git`.

**Date**: 2026-10-28 ; mise à jour 2026-10-31 | **Spec**: [spec.md](spec.md)

**Input**: `specs/003-hdrp-scene-agent/spec.md` — 21 exigences, quatre parcours, huit critères de réussite.

> **Plan actif — 2026-11-01 : [Maisons créatives et mapping détaillé](house-plan.md).** Il gouverne la prochaine livraison et remplace le périmètre « petite pièce d’abord puis forêt » comme direction produit. Les sections historiques ci-dessous documentent le socle ; leurs anciennes limites globales ne s’appliquent pas comme plafonds sémantiques à `house_v1`.

## Summary

Construire un outil Unity qui inspecte le rendu réel d’une scène HDRP, diagnostique un défaut à partir de vues et de données du moteur, applique une correction limitée puis conserve uniquement les versions admissibles. Première preuve : une petite pièce existante, avant la création de pièces et l’extension forêt.

Architecture retenue : fenêtre d’éditeur C# et adaptateur de commandes typées, reliés à un orchestrateur Python local. Muse Spark analyse les images et les courtes séquences ; SAM 3.1 intervient sur les surfaces ciblées, en complément des identités du moteur. L’orchestrateur conserve versions, preuves et budget dans SQLite et des fichiers locaux. Le modèle propose des données validées ; l’adaptateur applique une liste fermée d’opérations.

Le socle est désormais implémenté ; les sections initiales conservent la conception historique du pilote. Le chat Go et son inspecteur visuel sont implémentés ; les résultats historiques sont consignés dans `implementation-status.md`. Le plan actif `house-plan.md` gouverne désormais la prochaine livraison, encore non implémentée.

## Technical Context

**Language/Version**: C# pris en charge par Unity 6000.3 ; Python 3.12 pour le service, à installer avec `uv`. Le Python système 3.14.6 reste indépendant.

**Primary Dependencies**: Unity Editor **6000.3.23f1**, HDRP **17.3.0**, interface Editor existante, Unity Test Framework ; Python FastAPI, Uvicorn, Pydantic 2, HTTPX, Pillow, NumPy, pytest, jsonschema, parseur officiel `meta-sam-parser` ; `ffmpeg` pour assembler les captures. Versions Python exactes figées dans `uv.lock` à l’initialisation, sans inventer de verrouillage absent. API Meta Responses : `muse-spark-1.3-contributor`, `sam-3.1`.

**Storage**: SQLite local transactionnel ; métadonnées et journal d’événements ; médias et instantanés adressés par SHA-256. Grand livre API global indépendant des sessions et scènes. Manifeste de dépendances Unity incluant `.meta`, profils, matériaux et ressources de bake.

**Testing**: pytest pour transitions, admission budgétaire, contrats et reprise ; Unity EditMode pour commandes et restauration ; PlayMode avec GPU pour captures HDRP ; recette réelle selon [workflow.md](contracts/workflow.md). Fournisseurs simulés explicitement pour les tests hors ligne, puis sondes réelles bornées.

**Target Platform**: macOS Apple Silicon, Unity sous Metal. Éditeur 6000.3.23f1, package HDRP 17.3.0, `uv` et `ffmpeg` présents localement. Le projet HDRP de recette existe dans `unity/HDRPValidation`. Bake **Progressive GPU**, soumis à test matériel ; le lightmapper CPU natif Apple Silicon et le ray tracing HDRP Windows/DX12 ne sont pas des solutions de repli sur cette machine.

**Project Type**: Extension d’éditeur Unity et service local monoprocessus ; fenêtre intégrée, CLI de diagnostic/recette ; application locale Go et chat par projet désormais requis par l’amendement du 2026-10-31 ci-dessous.

**Performance Goals**: À 1280 × 720, trois vues fixes de travail, deux vues de contrôle, clip de six secondes à 24 images/s. Cibles à mesurer : capture/assemblage en moins de 90 s hors compilation/bake ; inspection initiale en moins de trois minutes hors bake. Rendu comparé sans readback pour mesurer la performance ; régression de temps de frame médian supérieure à 20 % rejetée sauf contrainte plus stricte du brief. Ces valeurs sont des choix de recette, pas des résultats.

**Constraints**: Plafond API global **150 USD restants**, dépenses précédentes incluses ; trois essais correctifs par défaut ; arrêt de session à 20 minutes et bake à dix minutes par défaut, configurables avant lancement. Critères immuables ; modèles Meta uniquement ; pas de C# arbitraire généré/exécuté par le modèle. Une session et une opération Unity mutante à la fois. Publication et achat d’assets hors parcours.

**Scale/Scope**: Une pièce, trois défauts de référence, un projet de recette ; création d’une petite pièce ensuite. Forêt conditionnelle après preuve de valeur. Animation procédurale, shaders arbitraires et support universel de projets hors MVP.

## Constitution Check

La [constitution](../../.specify/memory/constitution.md) est un gabarit non renseigné. Elle n’introduit aucun principe applicable ni étape d’approbation. Les contrôles ci-dessous proviennent de la spécification et de l’environnement.

| Contrôle | Avant recherche | Après conception |
|---|---|---|
| Scène réelle, preuves comparables, retour arrière | Exigé | Commandes conditionnelles, instantanés et comparaison multivue |
| Budget 150 USD restants partagé sans remise à zéro | Exigé | Grand livre global, réservation atomique, inconnus conservés |
| Modèles Meta et provenance | Exigé | Adaptateurs explicites, ressources autorisées, manifeste |
| Diagnostic borné et incertitude visible | Exigé | Familles limitées, états non concluants, arrêt sur limites |
| Compatibilité matérielle | À établir | Metal documenté ; bake GPU et capture à qualifier à l’exécution |
| Première preuve avant extension | Exigé | Jalons J0 à J5 ci-dessous |

**Verdict de conception : PASS.** Aucune violation constitutionnelle à justifier. Ce verdict permet la décomposition en tâches ; il ne valide pas l’accès effectif aux API, le bake GPU ni les performances.

## Project Structure

### Documentation (this feature)

```text
specs/003-hdrp-scene-agent/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
└── contracts/
    ├── http-api.openapi.json
    ├── domain.schema.json
    ├── editor-bridge.md
    ├── provider.md
    └── workflow.md
```

`tasks.md` contient les tâches historiques et les nouveaux lots T151–T190 ; ne pas réinitialiser les travaux déjà qualifiés.

### Source Code (repository root)

Arborescence de conception du socle (consulter les sources pour l’état effectif) :

```text
pyproject.toml
uv.lock
src/hdrp_agent/
├── cli.py
├── api.py
├── domain.py
├── orchestrator.py
├── store.py
├── budget.py
├── evaluation.py
└── providers/
    ├── meta_responses.py
    ├── sam_decoder.py
    └── fake.py
unity/
├── Packages/com.hackathon.hdrp-agent/
│   ├── package.json
│   ├── Editor/
│   │   ├── AgentWindow.cs
│   │   ├── BridgeClient.cs
│   │   ├── CommandExecutor.cs
│   │   ├── SnapshotStore.cs
│   │   └── CaptureController.cs
│   ├── Runtime/CaptureRig.cs
│   └── Tests/{Editor,Runtime}/
└── HDRPValidation/
    ├── Assets/AgentWorkspace/
    ├── Packages/
    └── ProjectSettings/
fixtures/{briefs,inspection-plans,provider-replies}/
evaluation-private/          # Causes/oracles jamais transmis au modèle
tests/{unit,contract,integration}/
.hdrp-agent/                 # Données locales ignorées par Git
├── global.sqlite3
├── artifacts/
└── reports/
```

**Structure Decision**: Une interface dans Unity, un service et aucune infrastructure distribuée. Le protocole de l’adaptateur est indépendant d’un MCP Unity particulier ; une façade MCP pourra le réutiliser. Le prototype ne dépend pas d’un autre agent pour exécuter des commandes opaques.

## Architecture et flux

1. La fenêtre enregistre projet, scène sauvegardée, capacités, brief, limites et ressources autorisées. Le service gèle critères et plan d’inspection.
2. L’adaptateur exécute une commande à la fois sur le thread principal. Les tâches longues exposent identifiant, battements et résultat durable ; un accusé HTTP n’est jamais la preuve d’un bake terminé.
3. L’éditeur sauvegarde un état restaurable. Le rig lance une capture PlayMode contrôlée puis revient en EditMode. Des scripts utilisateurs non maîtrisés rendent le cas incompatible plutôt que comparable par défaut.
4. Le service contrôle les empreintes et transmet seulement les vues de travail, le clip, les objets candidats et les diagnostics autorisés. SAM est sollicité sur une région utile, avec cache.
5. Muse produit observations, hypothèses et patch structurés. Schéma, références, unités, bornes et préconditions sont vérifiés avant mutation. La cause privée d’un défaut de recette n’est jamais révélée à l’agent.
6. Le patch est appliqué en EditMode. Un bake nécessaire doit se terminer réellement, puis les mêmes captures sont rejouées. Les données de contrôle sont réservées à l’évaluateur.
7. L’évaluateur compare critères objectifs, contraintes du brief et jugement artistique séparé. Il retient ou restaure. Le planificateur ne reçoit pas les images de contrôle ni leurs scores détaillés pour préparer l’essai suivant.
8. La fenêtre montre meilleure version vérifiée, preuves et défauts restants. Une mutation d’issue inconnue impose une réconciliation avant nouvelle commande.

Le service écoute sur `127.0.0.1:8765`, avec jeton local et un seul worker Uvicorn. SQLite contient une file durable qu’une coroutine d’orchestration traite après démarrage. Aucun handler HTTP ne réalise de longue inférence dans sa transaction. Les contrats détaillent rejouabilité et reprise.

## Capture et diagnostic

Capturer le Game View final en PlayMode à fin de frame avec `ScreenCapture`, avec post-traitement HDRP. Préférer le readback asynchrone qualifié ; chemin synchrone borné acceptable pour le premier prototype. Résolution, pipeline, exposition, caméra, graine, temps simulé et état du bake figurent dans le manifeste.

Exposition fixe, remise à zéro des historiques temporels entre prises, échauffement initial de 32 frames, porté jusqu’à 120 si le test de stabilité l’exige. Rejouer aussi les frames d’approche ; avancer la caméra par numéro de frame, pas par horloge murale. Mesurer deux captures sans modification avant d’autoriser un verdict. Un rendu instable est non concluant. GameView doit rester active ; `WaitForEndOfFrame` ne fonctionne pas en Editor batch mode. La recette graphique ne s’exécute pas avec `-nographics`.

Objets sauvegardés identifiés par `GlobalObjectId` en EditMode ; table de clés logiques sérialisée avant PlayMode. Ne pas résoudre `GlobalObjectId` au runtime ni persister `InstanceID` comme identité. Projection/profondeur/raycast pour surfaces opaques simples ; `ObjectIdRequest`, AOV ou Custom Pass deviennent des améliorations si qualifiés. Masques SAM, volumes et transparences gardent une incertitude explicite.

Diagnostics MVP : transforms/bounds, propriétés autorisées des lights et matériaux, profils de volumes, contribution GI, paramètres et état du bake. Ne pas supposer toutes les sorties AOV opérationnelles dès J0.

## Modifications et retour arrière

Liste fermée : primitives/prefabs autorisés dans un root dédié, transforms bornées, paramètres HDRP exposés, copie locale de matériau/profil, contribution GI et paramètres de bake pris en charge. Ni menu arbitraire ni propriété sérialisée libre. Champs, unités et bornes : [editor-bridge.md](contracts/editor-bridge.md).

Les instantanés couvrent scène, `.meta`, ressources modifiables, lightmaps, LightingDataAsset et probes concernés, plus tout nouveau fichier créé dans l’espace de travail. Manifeste avant/après avec hash et journal de restauration. `Undo` ne remplace pas le retour sur disque après bake/redémarrage. Un fichier hors périmètre ou modifié par l’utilisateur provoque un conflit explicite.

Les scènes importées sont travaillées dans une copie isolée avec dépendances modifiables clonées. Pas de modification automatique des réglages globaux du projet. Une dépendance impossible à isoler/restaurer interdit l’opération. Les créations possèdent un root et un dossier dédiés ; leur suppression au retour est enregistrée.

## Budget et modèles

Invariant : `dépensé + réservations actives (inconnues incluses) + nouvel engagement <= 150 USD restants`. Entiers micro-dollars USD arrondis vers le haut ; tarifs, conversion et frais provisionnés sourcés datés. Réservation SQLite `BEGIN IMMEDIATE` avant envoi ; aucune transaction tenue pendant le réseau. Coût inconnu : blocage. Timeout après envoi : réservation conservée, sans retry automatique ni remboursement présumé.

Le décompte de tokens Meta n’est pas une garantie comptable ; voir [provider.md](contracts/provider.md). Pour Spark sans outils hébergés, réserver conservativement la fenêtre entière de 1 048 576 tokens d’entrée et 4 096 tokens de sortie, même si le payload est bien plus petit. Les dimensions et tarifs sont sourcés ; mode refusé si son majorant n’est plus établi. Les tarifs documentés et leurs limites figurent dans la recherche, pas un prix moyen inventé par image Spark.

Répartition indicative **du solde après dépenses antérieures** : 5/150 sondes, 70/150 développement, 35/150 recette, 20/150 démonstration, 20/150 réserve. Ce sont des parts du solde, pas 150 USD restants supplémentaires. Réconciliation du déjà consommé obligatoire avant premier appel ; un montant inconnu ne vaut pas zéro. Les appels externes utilisant la même clé doivent aussi être réconciliés.

Muse reçoit d’abord trois images et un résumé d’état. Vidéo native si accès/coût/valeur validés ; sinon frames horodatées du même clip. Les défauts temporels exigent une observation suffisante, pas une conclusion sur trois images isolées. SAM sur une image ciblée d’abord ; suivi vidéo seulement si utile et borné. Le mode simulé ne produit jamais un verdict de réparation réelle.

## Ordre de livraison et portes d’exécution

| Jalon | Livrable | Condition de passage |
|---|---|---|
| J0 — Faisabilité locale | HDRP verrouillé, fenêtre, capture, bake GPU et restauration sans modèles | Captures comparables, vrai bake terminé puis restauration, aucun fichier partagé écrasé |
| J1 — Contrat Meta | Adaptateurs Muse/SAM, parseurs, cache, grand livre | Schémas invalides refusés, sondes réelles dans enveloppe, majorants établis |
| J2 — Première correction | Une pièce et un défaut non révélé à l’agent | Hypothèse étayée, patch réel, verdict travail + contrôle |
| J3 — Recette de valeur | Trois cas, quatre négatifs, comparaison workflow habituel et ablation SAM | SC-001/002/004/005/006/007 mesurés ; limitations rapportées |
| J4 — Création de pièce | Brief → scène → même contrôle | SC-003, reprise, rapport et provenance |
| J5 — Livraison/extension | Démo trois minutes ; forêt conditionnelle | SC-008 ; extension après preuve et sans dépasser le budget |

Échec de bake GPU : une démonstration temps réel reste possible mais partielle ; elle ne valide pas l’éclairage indirect. Accès fournisseur absent : tests hors ligne utilisables, sans présenter une simulation comme preuve Meta. Ce sont des critères d’arrêt explicites, sans remplacement silencieux d’exigences.

## Couverture et validation de la conception

| Exigences | Conception | Validation prévue |
|---|---|---|
| FR-001–003 | Brief, capacités, constructeur borné | Ouverture, éléments requis, dépendance absente |
| FR-004–008 | Manifeste, rig, identités, diagnostics, SAM | SC-002/007, instabilité, masque erroné |
| FR-009–014 | Critères gelés, patch conditionnel, snapshot/bake, évaluateur | SC-001/005, conflit et retour après redémarrage |
| FR-015–019 | Automate durable, limites et ledger | SC-006, interruption et issue réseau inconnue |
| FR-020 | Meta, manifeste de provenance, recette | Audit, reproduction et SC-008 |
| FR-021 | Même constructeur et contrôles, assets forêt | Recette extension après validation pièce |

La planification se termine avec recherche, modèle de données, contrats et guide de recette. Étape suivante : `$speckit-tasks`. Les tests d’implémentation seront exécutés pendant la réalisation.

Vérifications de cette phase : JSON lisibles, références internes résolues, schémas partagés identiques entre JSON Schema et OpenAPI, paramètres de routes et identifiants d’opérations cohérents, liens locaux valides et gabarits remplacés. Revue documentaire Unity et Meta terminée sans blocage ; limites de fog, commandes d’annulation et identités de la copie précisées. Les validateurs complets JSON Schema/OpenAPI ne sont pas installés dans cet environnement ; leur validation formelle fait partie des contrôles de contrat à l’implémentation. Aucun test de produit ni appel Meta effectué. Aucun fichier de hooks avant/après plan présent.

## Complexity Tracking

Aucune violation à justifier. Les deux runtimes du socle isolent Unity de l’inférence et du budget. L’amendement Go ajoute le troisième runtime demandé pour l’application ; sa responsabilité se limite à l’interface et à son état, sans dupliquer le cœur financier. SQLite suffit ; aucune infrastructure distribuée ni dépendance obligatoire à un MCP tiers.

## Précisions intégrées à l’implémentation

Les états locaux capture_verified et gpu_bake_verified sont distincts : une validation de capture permet une sonde image ou une démonstration temps réel partielle ; un cas indirect exige aussi un bake GPU vérifié. La collecte des temps de frame est implémentée dans le rig avant le premier verdict, T079 consolidant/optimisant les mesures. Le registre des méthodes d’évaluation et la grille SC-004 sont précisés dans le contrat de validation. Les commandes probe/evaluate sont raccordées avant leur utilisation.

## Amendement : contrôle global en une demande

Le diagnostic doit couvrir explicitement toutes les vues de travail et être répété sur la nouvelle version après chaque correction. Des versions techniques provisoires peuvent être chaînées à l’intérieur de la session quand tous les contrôles techniques passent et que seul l’avis artistique indépendant manque. Elles ne remplacent pas la meilleure version admise. Un diagnostic résiduel pilote la correction suivante dans la même enveloppe de trois essais ; un rapport final unique contient la branche candidate et ses limites. Une opération UV2 déterministe et bornée clone un mesh statique possédé avant de recalculer ses UV ; aucun script modèle ni écriture sur le mesh partagé.


## Priorité active — correction de fidélité, 2026-10-29

Le [plan de correction de fidélité](fidelity-plan.md) gouverne désormais la reproduction enregistrée, US5–US9 et tâches T108–T143. Il complète les éléments historiques de ce document, sans relancer le pilote d’éclairage. Limites du parcours de reproduction : six candidats/quarante minutes, grand livre global existant. Les tâches T090–T106 déjà présentes sont à réconcilier selon leurs preuves ; elles ne doivent pas être réimplémentées aveuglément. T107 (croquis) reste différée. Les nouveaux livrables sont de la conception, pas des corrections déjà exécutées.


## Priorité active — pièce cohérente et application Go, 2026-10-31

Cet amendement remplace la limitation historique à une fenêtre Unity. Le produit demandé est une application locale de chat par projet, avec serveur Go, reliée à l’agent Muse/SAM et à Unity. Le MCP reste un accès facultatif. Le plan détaillé, ses décisions et contrats sont dans [chat-plan.md](chat-plan.md), [chat-research.md](chat-research.md), [chat-data-model.md](chat-data-model.md), [chat-api](contracts/chat-api.openapi.json), [actions](contracts/chat-actions.md) et [recette](chat-quickstart.md). Les tâches sont dans le même [tasks.md](tasks.md), T151–T190.

Ordre : (1) versionner le socle et achever les vérifications de murs/plafond ; (2) contrats et stockage du chat ; (3) conversations persistantes avec Muse ; (4) démarrage natif des actions depuis le chat ; (5) preuves, arrêt et reprise ; (6) recette complète sans MCP. Aucune interface Go n’est encore implémentée à cette date. Go 1.27.3 a été installé ; ce n’est pas une preuve de produit.

L’application doit pouvoir suivre « reconstruis cette image avec les prefabs Building, des murs intérieurs cohérents et Ceiling_3x3 », puis « inspecte ce raccord et corrige-le » dans la même conversation. Un message de succès sans run natif, version et captures ne satisfait pas le besoin. Les tests contractuels précèdent les nouveaux appels payants.

La cohérence des murs et le plafond sont des contraintes d’assemblage : famille B par défaut pour cet exemple GP, variantes compatibles avec les ouvertures, vrais prefabs connectés, plafond raccordé aux faces intérieures à 2,8 m (pivot auteur à 3 m), aucun mélange silencieux A/B. Les variantes et plafonds dérivés doivent être déclarés au modèle et dans les reçus ; pas de géométrie cachée au contrôle. Le masque SAM n’établit ni profondeur ni conformité d’un assemblage.

## Réorientation : optimisation de composition depuis un plan — 2026-10-31

**Priorité utilisateur :** les erreurs de contrat corrigées précédemment ne démontrent aucune fidélité. Remplacer le parcours externe dominé par des réécritures globales du LLM par une optimisation mesurée de composition, avec interactions utilisateur indépendantes des captures. Cet amendement est une conception à implémenter, pas une capacité livrée.

### Évidence du défaut

Run `fa3561fcc31e4163ada8917727cc349c` : deux candidats, interruption `Each external frame requires an explicitly estimated camera`. Dernier candidat `1b2c7872f518a046677786984832bea1692f5023ce4e238742a24d26d130d80c` : saturation lumineuse, architecture non fidèle ; deux défauts de faces intérieures signalés. Le plan source décrit un salon à gauche et une chambre à droite, une cloison avec porte, deux fenêtres hautes et une entrée basse. `external_visual` réécrit les poses via le modèle, tandis que `fit_overhead_plan` exige exactement un sol : le cas multi-pièces échappe au solveur initial. Le lien entre déplacement utilisateur et les interruptions rapportées doit être reproduit ; ce dernier arrêt n'est pas une preuve de crash Unity.

### Architecture proposée

1. **Contrat de vue et topologie.** Détecter vue de plan/coupe versus perspective, hypothèses de projection et échelle relative. Conserver l'incertitude : une image unique ne donne pas les dimensions exactes ni les surfaces cachées. Muse propose pièces, ouvertures et relations ; SAM produit des observations avec confiance. Le texte SALON/CHAMBRE est une annotation, pas un objet à créer.
2. **Représentation intermédiaire indépendante d'Unity.** Pièces comme polygones adjacents, murs partagés, ouvertures rattachées à leurs segments, objets associés à leur pièce et leur support. Unité relative commune puis échelle métrique explicite. Murs et cloison ne sont plus des positions libres indépendantes. Conserver les liens image→entité→prefab et les alternatives ambiguës.
3. **Optimisation de grossier à fin.** Ajuster d'abord projection/cadrage et enveloppe, puis cloison/ouvertures, enfin X/Z/yaw/échelle des objets. Réutiliser les solveurs géométriques existants lorsque leur domaine s'applique ; démarrages multiples et recherche sans gradient pour les choix discrets. Aucun entraînement de diffusion requis pour ce premier jalon. Une caméra externe validée appartient à l'état du solveur ; son omission dans un delta de correction ne supprime pas cet état.
4. **Fonction d'erreur explicite.** Recouvrement des masques par objet et pièce, distances entre contours/centres, rapports de dimensions, contacts, collisions, pénétration des murs, dégagement des portes et connectivité. La ressemblance RGB vient après la géométrie et ne peut masquer une régression de topologie. Les seuils de recette doivent être définis sur les données avant la qualification, sans promettre zéro approximation.
5. **Rendu de mesure séparé.** Vue d'identifiants/masques ou rendu neutre non saturé pour le solveur ; vue en coupe qui exclut explicitement les plafonds dans cette capture uniquement, avec provenance, sans supprimer les plafonds de la scène. Vues intérieures indépendantes pour vérifier plafond, murs et raccords. HDRP final, matériaux et exposition ne sont évalués qu'après lisibilité et admissibilité de la composition.
6. **Boucle transactionnelle.** Proposer un delta, rendre, mesurer, accepter ou restaurer le dernier candidat admissible. Checkpoints séparés pour analyse, identification d'assets, disposition et rendu ; pas de nouvel appel payé pour une analyse déjà validée. Les échecs connus de contrat sont expliqués et récupérables ; résultats réseau inconnus jamais rejoués automatiquement.
7. **Interaction utilisateur.** Caméra d'inspection et caméra de mesure séparées, scène de travail isolée, capture hors écran à qualifier sous HDRP/Metal. Un déplacement de vue ou une sélection ne modifie pas l'état du solveur. Une édition réelle du candidat déclenche pause/version/conflit explicite, puis une reprise depuis checkpoint, jamais un écrasement silencieux. Perte de focus invalide uniquement une mesure de performance qui exige le focus, pas automatiquement la validité géométrique.
8. **Contrôle visible.** Afficher cible/candidat, contours superposés, composantes d'erreur, objet en cours, changements acceptés/rejetés et raison d'attente. La progression suit les preuves, sans pourcentage de fidélité inventé.

### Premier jalon de validation

Utiliser le plan salon/chambre fourni comme recette de disposition : deux pièces et une cloison avec porte, ouvertures du bon côté, meubles dans leur pièce, supports corrects et passages non obstrués. Comparer au pipeline actuel avec les mêmes assets et la même référence. Exiger une réduction mesurée des erreurs de composition et aucune régression des contraintes ; rejeter un rendu saturé comme preuve de fidélité. Tester la navigation et sélection pendant l'optimisation, une modification volontaire d'objet, une pause/reprise et un changement de focus. La fidélité photométrique constitue un jalon ultérieur.

Sources techniques : boucle silhouette/rendu de PyTorch3D https://pytorch3d.org/tutorials/fit_textured_mesh et optimisation de caméra https://pytorch3d.org/tutorials/camera_position_optimization_with_differentiable_rendering. Ces exemples étayent le principe de rendu inverse ; ils ne prouvent pas la compatibilité de cette bibliothèque avec notre pile macOS/HDRP. Le backend initial reste à choisir par une qualification locale, avec préférence pour les solveurs déjà présents.

### Implémentation du premier incrément — 2026-10-31

Le backend retenu est un solveur NumPy sans entraînement : rectangles de pièces, segments de murs, ouvertures paramétrées, objets associés aux pièces et supports existants. Le contrat `ModelFloorplanObservation` conserve les bornes normalisées, orientations cardinales, confiance et limites. Les plans non orthographiques sont refusés explicitement pour ce parcours. Ce sous-ensemble ne couvre pas encore des pièces polygonales arbitraires.

Muse reçoit les observations SAM déjà calculées et les identités validées ; extraction cacheable par empreinte de référence/catalogue/analyse/segmentation/consigne/version du solveur. Recherche multidépart sur les boîtes avec pénalités de collision, débordement et dégagement de porte. Compilation des pivots des vrais prefabs ; sols étendus aux axes des murs plutôt qu'aux seules zones visibles. La caméra de mesure est orthographique et conservée hors des deltas d'objets.

`FloorplanCapture` produit une beauté HDRP et un rendu neutre coloré par objet hors écran, sans Play Mode ni exigence de focus. Plafonds masqués temporairement puis restaurés ; caméra, versions, projections, couleurs et empreintes PNG archivées. Mesures des boîtes natives après contacts, correction des résidus X/Z/échelle et classement géométrique. L'optimisation photométrique est suspendue tant que la composition n'est pas qualifiée. Les boîtes parfaites ne valident jamais les ouvertures, les silhouettes ou l'identité visuelle.

Une modification réelle pendant cette capture produit un conflit versionné et une pause ; le menu Unity `Window/HDRP Agent/Resume verified composition capture` exige une scène sauvegardée identique à la version attendue. Il ne restaure ni n'écrase les modifications de l'utilisateur. La durée de pause est exclue du délai d'exécution ; aucun appel modèle n'est rejoué. Cette reprise ne remplace pas la récupération après rechargement de domaine ou redémarrage du service, encore à qualifier.

**Limite bloquante observée sur la recette :** étirer un prefab de mur conserve son ouverture au centre du module et ne reproduit pas l'intervalle d'ouverture extrait. Le prochain incrément doit assembler des modules compatibles et mesurer les ouvertures réelles, avant d'activer la qualification photométrique. Les variantes d'assets et les masques visibles restent des critères indépendants ; le résultat actuel n'est pas certifié fidèle.

### Correction du constructeur après retour utilisateur — 2026-10-31

Les rectangles seuls avaient permis des meubles déformés. Le compilateur conserve désormais une échelle uniforme XYZ des meubles, tapis et objets posés, bornée entre 0,8 et 1,25 ; les corrections résiduelles ne redimensionnent plus ces objets. Les objets posés sont recentrés dans l'emprise de leur support puis soumis au contrôle natif des contacts.

L'architecture est transmise séparément des poses de meubles. Les raccords proches sont alignés, puis chaque mur est assemblé avec des prefabs connectés `WallOut_1x` / `WallIn_<style>_1x` autour des ouvertures explicites. Une cloison reçoit deux faces intérieures. Les portes incluent `Doorframe_in_single` et `Door_parent_A_L` avec échelle uniforme ; les fenêtres utilisent leur prefab dédié. Jambages, extrémités et dessus sont fermés. Les modules structurels peuvent être dimensionnés ; aucun meuble n'est étiré pour couvrir une zone.

Un audit natif échantillonne les triangles orientés des deux côtés : absence de surface sur un panneau attendu et mur qui bouche une ouverture sont des erreurs de construction. Les matériaux des murs doivent être opaques ; les vitres sont exclues de ce contrôle. Les reçus conservent ouvertures, chemins des prefabs, nombre de pièces connectées et résultats des rayons. Cette preuve échantillonnée ne certifie pas encore tous les raccords entre murs ni la fidélité globale au dessin.

Le rendu de construction utilise un éclairage HDRP neutre avec remplissage, sans ombres directionnelles. Il sert à vérifier les volumes et matériaux ; la qualification photométrique finale reste distincte.

### Révision : assemblage natif uniquement — 2026-10-31

La demande utilisateur remplace l'approche de panneaux redimensionnés : aucun étirement, découpage ou clone de mesh. Le plan image fournit les relations et orientations ; un quadrillage métrique adapte les pièces aux modules entiers du catalogue. Les ouvertures utilisent les modules porte/fenêtre complets et leurs accessoires natifs. Sols et plafonds sont pavés de prefabs entiers. Les meubles restent à échelle 1, placés dans les pièces avec marges et contacts. Les corrections image ne doivent pas annuler cet agencement pour retrouver artificiellement les boîtes pixel. Validation séparée : provenance/échelle, surfaces et ouvertures, contacts, puis captures natives ; aucune promesse de fidélité parfaite.

### Correction fonctionnelle : circulation — 2026-10-31

La recette visuelle utilisateur invalide l'agencement natif compact : télé devant la porte, accès au lit et circulation insuffisants. Les contacts et l'absence de chevauchement ne qualifient pas un appartement utilisable. Réserver les dégagements de portes et les zones d'utilisation des meubles ; vérifier par recherche de chemin une largeur de passage explicite, les liaisons entre portes et l'accès aux meubles. Agrandir les pièces par modules entiers si nécessaire, sans réduire les meubles. Cette validation par empreintes doit rester distincte d'une certification de collision des meshes ou d'accessibilité réglementaire.

La sélection compare également les orientations de pavage (dalles natives tournées). Le salon conserve une relation explicite canapé/table basse/télé et les objets posés suivent leur support. La mesure du résultat natif est distincte de la comparaison avec l’image originale : une bonne circulation ne constitue pas un score de fidélité visuelle.

### Topologie et visibilité — 2026-10-31

Une même référence de prefab peut servir plusieurs segments de mur : chaque segment reçoit une identité distincte, utilisée par les ouvertures, tandis que `object_key` conserve le binding au prefab identifié. Les réponses invalides sont conservées avant validation ; une réparation ne doit jamais fusionner des segments géométriquement distincts ni rejouer un appel fournisseur inconnu.

Le chat reçoit un inspecteur de preuves actualisé à partir des fichiers et reçus réellement produits. Référence, zones SAM, planches comparées, captures natives, état et diagnostics sont accessibles uniquement via l'action possédée par la conversation/projet. Aucun chemin de fichier arbitraire, secret ou raisonnement interne du modèle n'est exposé. L'interface annonce la date de chaque capture et n'affirme pas fournir une vidéo en direct.

Validation : 306 tests Python, suites Go et 31 tests Unity de construction passent. Le navigateur affiche les 89 images et 20 observations SAM du run interrompu, sans erreur JavaScript ; les médias sont refusés sans session locale. Les routes Go `/api/actions/{action}/inspection` et `/api/actions/{action}/media/{media}` lisent un manifeste filtré et des images autorisées, sans relancer le worker. Les observations publiques sont exportées à chaque checkpoint ; les captures candidates hors du dossier du run sont recopiées depuis leurs artefacts vérifiés. La réparation de topologie est testée avec réponse fournisseur simulée et assemblage natif ; le run réel interrompu n'a pas été rejoué et sa qualité finale reste à qualifier.

### Référence de qualité maison de jeu — 2026-11-01

La cible utilisateur est une maison explorable et créative au niveau de composition de `House_worn_night.unity` : étages et sous-sol, pièces complètes, ensembles fonctionnels, détails contextuels, finitions/usure et ambiance lumineuse. Voir [l'analyse de référence](house-quality-reference.md). L'audit statique relève 1 713 instances sérialisées et 530 prefabs distincts ; ces nombres ne constituent pas des quotas de génération. La lecture native/visuelle reste à réaliser lorsque l'éditeur ne reconstruit plus.

La stratégie devient hiérarchique : programme du bâtiment → topologie multi-niveaux → architecture modulaire → ensembles fonctionnels orientés → décoration sur supports → matériaux/éclairage → inspection/correction. Chaque étape conserve une liste de besoins et de défauts non résolus. Les limites de requêtes découpent le travail sans tronquer l'inventaire de la maison. SAM fournit des observations visuelles ; la géométrie Unity vérifie les passages et contacts. Une boucle achevée avec inventaire manquant, passage bloqué ou inspection inutilisable ne qualifie pas une maison livrable.

### Native zone recovery (T313)

A zone currently returns immediately on a native support/traversal defect, before the corrective loop sees it. Give repairable support/passage failures a correction attempt with exact native receipts and current images. Preserve the last accepted zone when repair fails; never attempt recovery of changed user content, broken prefab connections/scales or unusable observation coverage. A strict reduction of native defects counts as measured progress only when equipment is retained and visual/exposure checks do not regress. Deployment waits for the active campaign to finish.

### Catalogue-driven detail choices and wall attachment gap

Attempt 5 reviewed a broad child-oriented catalogue but the room policy still named fixed book and stationery prefabs. Remove that preference; retain measured native-scale fit and visual review, letting the model select appropriate objects. This prompt correction alone does not establish varied outputs.

The same attempt explicitly reports posters and curtains as unsupported. Add typed wall attachment targets in a subsequent implementation: room-owned boundary, distance along boundary and mounting height; verify reviewed visible-front/mounting semantics, native bounds, openings, adjacent objects and measured wall contact. Curtains additionally need an explicit compatible window target. Do not treat floor support as a wall attachment or infer qualification from prefab names alone. Native compilation and trials must wait until the active campaign releases Unity.

### Explicit rug groups (T316)

Attempt 5 preflight 3 rejects the entire play group because Carpet_C is treated as solid furniture intersecting a plant. Measured walkable floor prefabs need their own placement pass even when the model includes them as group items. Preserve requested identity, priority, group and preferred pose; place after furniture, keep native size and door reservations, and report unavailable rug space without dropping independent toys/plants. Do not classify arbitrary thin or rug-named assets as walkable.

T316 validation: replayed `layout-repair-child_bedroom_main-2` from run `51dc603a993e4dac8113f9bb48195140` against the measured catalogue. All 19 instances now fit, including the rug/play objects; no missing needs or internal collisions. Report: `.hdrp-agent/reports/bedroom-quality-campaign/group-rug-replay.json`. This is offline geometric evidence only. Attempt 5 was requested to stop during preflight, with zero native commands, to avoid more calls retrying the known classification defect. Await terminal provider settlement before restart.

### Upper wall / ceiling seam qualification (T317, user observation 2026-11-03)

User reports improved overall output but light leaks through upper wall borders. Read-only source YAML confirms Molding_white_clean, Wall_B_plaster_clean and Ceiling_plaster_clean are opaque (`_SurfaceType=0`, alpha clipping disabled) with backface culling (`_CullMode=2`, `_DoubleSidedEnable=0`). This supports investigating single-sided geometry, but does not prove the leak cause. Candidate-owned DoubleSidedGI fixes indirect validity without changing visible culling or proving realtime shadow closure.

Existing `ReferenceArchitecture.Audit` samples 9 vertical cell centres: its uppermost point is roughly 15.6 cm below the 2.8 m ceiling. It cannot qualify the trim seam. Extend an isolated native audit to inspect narrow upper bands and grazing/upward rays on both sides, include actual source/candidate material and shadow-casting settings, and compare sun-on/sun-off renders at matched exposure. Prefer a correctly assembled native closure; any necessary candidate-only shadow override must be separately measured, preserve connected native prefabs, and leave source materials/meshes untouched. Do not certify the seam from existing coarse wall coverage. Source report: `.hdrp-agent/reports/bedroom-quality-campaign/ceiling-seam-source-materials.json`. Native changes wait while attempt 6 owns Unity.

T317 implementation progress: `house_seams.py` distinguishes open geometry, back-facing-only triangles, and unknown material/shadow evidence with narrow upper-perimeter rays. Six focused tests pass, including shared-room sides and scene/manifest/native-receipt binding. `scripts/audit_house_seams.py` writes a new report without overwriting evidence. The read-only submesh exporter is staged in `scripts/native-diagnostics/HouseSeamGeometry.cs.stage`; it is deliberately not loaded into Unity during attempt 6. Compilation, integration with the isolated reopen audit, real candidate export and matched render qualification remain required.

### User acceptance update and fine placement control (2026-11-03, T284/T318)

The user explicitly accepts two different clean, detailed bedrooms as the final repeatability demonstration (previously three). Both must be generated and corrected autonomously, with coherent bedside furniture/plant placement, useful decorative detail, clear circulation, native prefab integrity and convincing lighting. Known wall/ceiling leaks remain defects, not waived by this count change. No success is claimed until both final scenes and their native/visual evidence are inspected.

Current move/rotate controls transform a whole functional group. Add an explicit `adjust_item` operation for one selected item and its transitive supported descendants, preserving all unrelated items. A supported small prop itself cannot be adjusted through this floor-item control: moving it off its parent needs separate support-aware placement. Validate floor/native-scale bounds, collisions and access before native construction; acceptance still requires a new native receipt and visual non-regression. This directly addresses bedside tables or plants that need local correction without moving the bed/play group.

T318 offline implementation: `adjust_item` is available in both strict inspection contracts, planning prompts and repair preflight. It moves a selected floor item plus transitive supported descendants (including those recorded in separate decorative groups), leaves unrelated furniture untouched, rejects detaching supported props/floor coverings and records every affected instance. Tests verify bedside relocation/rotation, retained bed/plant, collision/boundary rejection and repeated-pose rejection. Full Python suite: 436 passed. Deployment and autonomous visual qualification remain pending while attempt 6 is active.

### Placement semantics before geometry (T319)

Attempt 6's initial plan proposes curtains, posters and a pillow with null supports, which currently means floor placement. Valid bounds/contact alone cannot make that placement semantically correct. Extend exact-prefab visual review with evidenced placement modes (floor, horizontal support, wall mount, window mount, or unknown), bound to the dependency hash and preview. Reject incompatible requested support modes before construction and return the real required mode to replanning. Unknown/unsupported mounting stays unresolved until T315 implements it. Keep legacy unreviewed records readable; native geometry imports may not assert placement semantics.

T319 offline implementation: exact-prefab visual review now returns placement modes and persists dependency-bound evidence. Room planning exposes those modes; floor/tabletop requests incompatible with reviewed wall/window/support-only use remain explicit missing needs. Native imports cannot qualify modes, and changed dependencies lose old qualification. Full Python suite: 439 passed. Deployment/live review and actual mounting remain pending.

### Per-item requirement priority (T320)

Attempt 6 repeatedly alternates an unsupported optional pillow between removal and placement on an unqualified bed. All items inherit the mandatory sleeping-group priority, so asset-retention checks make this inferred accessory mandatory forever. Add an explicit per-item priority, defaulting to group priority for old plans. The primary bed and user-requested items remain mandatory; inferred accessories can be preferred/optional without splitting a coherent group. Preserve that priority in all missing-support, collision, deferred-rug and retained-equipment receipts. This does not authorize downgrading an already mandatory requested item during repair.

T320 implementation: per-item priority now survives normal/unsupported placement, missing support, collisions and deferred floor layers; old plans retain group defaults. Mandatory retention uses effective item priority, so an inferred optional pillow can remain explicitly unresolved while the mandatory bed is retained. Regression tests preserve the existing mandatory-furniture rejection and exercise the optional-accessory exception. Full Python suite: 441 passed. Attempt 6 ended with PROVIDER_OUTCOME_UNKNOWN during preflight; its reservation remains intact and no native commands were issued. No artistic success is claimed.

T317 native evidence (2026-11-03): integrated the read-only submesh exporter into the isolated reopen audit; Unity compilation passed. Audit `5d0c7fc49f174300bad8813cd13b3ea5` exported 29 material/submesh records from saved candidate d12771904b58413497f1a8ecacc230eb. Exact artifact bytes, rather than JSON reserialization, bind the manifest to its native receipt. Initial rays originated inside the wall cavity and are retained as superseded diagnostics (`seam-analysis.json`); corrected rays start 30 cm inside the room. All 1,968 corrected samples hit front-facing opaque geometry (`seam-analysis-interior-origin.json`), which does not prove continuous watertightness or HDRP shadow correctness.

Matched EV 1.67214155 sun-on/sun-off views show the bright upper-left molding line disappears without the sun. Temporary two-sided architectural shadow casting (audit `96ffde54002940a59964286bb9c796e9`, 21 renderers) does not fix it; mean top-200-row difference is 0.0000143 on 8-bit RGB. Zero normal/slope sun bias (audit `9b91f1e885cd482e8a78ee0ee9a3b615`, original 0.75/0.5) also leaves the line and adds small surface speckles. Neither override is promoted to production. All three audits completed with user scene and candidate file unchanged. Screen-ray reconstruction at seven molding/wall pixels finds geometric occluders toward the measured sun, including the ceiling within approximately 6–8 cm at the bright seam. Further shadow filtering/thin-shell investigation is required; T317 remains open. The diagnostic candidates are not the two autonomous acceptance rooms.

### Strict provider schema compatibility (T321)

Campaign attempt 7 (`21a6aabf228c4e32939ff8b2c8dcaac6`) ended before native assembly: the provider rejected room planning with HTTP 400 because nested item `priority` was not included in `required`. Keep local optional fields for historical plans, but require all declared properties in the expanded strict provider schema. A recursive regression checks every model object, including the nested room item. All 443 Python tests pass; the live backend was restarted and attempt 8 admitted. The failed request's unknown-usage reservation is retained; no billing settlement is fabricated.

Campaign attempt 8 (`6802f49f2bda4f89a13adefd0411548b`) passed provider schema validation, asset review and layout repairs, then reached native assembly. It terminated with CONCURRENT_EDIT during the first zone bake. The saved conflict contains only the already-loaded source candidate's scene-mode ProbeVolume and its transform: Z changed by approximately 0.24 micrometres and size by 0.95 micrometres, with source dirty state unchanged. Independently, the bake receipt reports that loaded scene `1defa6df9d5a4de7b5959f9eb20de3b4` has probes in another baking set. Cancellation settled; no sessions or commands remain active. Thus broad relaxation of source checks would not solve the bake failure. T322 must isolate the candidate baking context while preserving user scenes and restore that context afterwards. Attempt 8 is a failed partial candidate, not an autonomous bedroom acceptance result. Evidence: `.hdrp-agent/reports/bedroom-quality-campaign/attempt-8.json` and `.hdrp-agent/house/runs/6802f49f2bda4f89a13adefd0411548b/372a78e96749/{source-state-conflict,bake}.json`.

T322 implementation in progress: added a journaled bake isolation scope which refuses dirty/untitled scenes before unloading anything, hashes every original scene file, unloads clean scenes without enrolling them in another APV set, and restores their original loaded/active state. Domain reload recovery retains the journal until restoration succeeds. The first native diagnostic (096eba228c3e43ac9952f92cb7ee6908) removed the cross-set validation error but exposed pending APV cell deletion during the baking-set switch; the failed candidate and receipt remain retained. Drain pending APV operations after unloading and restore original scenes before closing the last candidate to prevent an empty replacement scene. These latest changes still require native qualification; do not mark T322 complete.

T322 native qualification: diagnostic `e6def857d0424eef8a9e2c3d6b5d4df4` crashed inside Unity's APV `InputExtraction.ExtractFromScene` while other scenes remained registered but unloaded. Its unknown command remains unknown; after the editor restart, file hashes and the recovery receipt verified source restoration and the diagnostic session was retired as interrupted. Isolation now removes clean source scenes from the scene manager before preparing the candidate APV set, drains pending APV operations, and restores the original loaded/active states before closing the candidate. It uses SceneManager enumeration because GetSceneManagerSetup omits untitled scenes. Recovery treats an already-active original scene as successfully restored.

Native diagnostic `d36011ab37c947f5b458e250ee7f9a18` completed the GPU bake, calibrated exposure and 27 captures, with `source_scene_unchanged=true` and `source_scenes_restored=true`. The expanded native guard suite also passed: untitled and modified scenes rejected without unloading, candidate is the only registered scene, originally unloaded scenes restored as unloaded, original active scene restored. Report: `.hdrp-agent/reports/bake-isolation-guards.json`. Full Python suite remains 443 passed. Campaign attempt 9 (`cffbe12aea844eaab0429d93994895e3`) now tests the autonomous path; visual quality acceptance is still pending.

### Progressive inspection and repeated exposure checks (T323/T324)

Attempt 9 completed its first autonomous zone bake and eight captures with source preservation. Inspection incorrectly reported planned later-zone furniture as missing during the sleep-zone review. Supply current/deferred instance IDs to both initial and repair inspection, include that scope in request identity, and defer only explicit future missing-instance observations. Current geometry/native faults remain actionable; the final whole-room inspection has no deferrals. Full Python suite: 444 passed.

The sleep-zone correction then failed fixed exposure verification. Inspection/save layers are transient but Volume registration is layer-based, so explicitly refresh enabled owned volumes after changing layers. Record requested, texture-readback and volume-stack EV/mode in exposure-readback.json before enforcing the existing tolerance. Exact failed-manifest replay `c073da9afdce400491970ad510aaf780` passed: requested/readback/stack EV 6, Fixed mode, native GPU bake, eight captures and both source preservation/restoration true. An earlier replay was cancelled while still queued by a compilation epoch change; it never constructed a candidate. Keep artistic lighting qualification separate.

T323/T324 live evidence: attempt 10 (`6070e809a9944178ada4a0e866ebe982`) accepted sleep_zone with no observations and correctly deferred future furniture, then completed successive storage and study builds with source restoration, bake and exposure validation. However, zone corrections were silently skipped because the model returned horizontal `[x,z]` while the executor required a length-three vector. The attempt was deliberately stopped; its in-flight native command settled cancelled and normal stop reconciliation closed recovery_required. This is not an artistic success.

T325 now requests exactly `[x,0,z]` from the strict provider schema while retaining historical local records, normalizes historical horizontal pairs in execution and includes native world-axis-aligned bounds in initial visual inspection. All other geometric/finite bounds remain enforced. The exact paid-model bedside proposal was replayed through the corrected production repair function into native diagnostic `33e0df66dfd143438b7997aada90e6b6`. Ten captures, GPU bake and exposure succeeded; native defects are empty; source preservation/restoration true. Bedside table moved from (2.74386072,-0.0000382,4.2) to (2.14386082,-0.0000382,5.25), lamp followed by the same delta, all other furniture unchanged. Full Python suite: 446 passed. This qualifies correction execution, not the full two-bedroom artistic goal.

Budget-accounted live visual verification after T325 (`call-1e48842c777f40e099d8d393ca27b8dc`, $0.0016972) reviewed four actual overview renders plus measured native bounds and bake receipt using the corrected strict inspection contract. It returned no current-instance defects: bedside table/lamp contact, bed clearance, desk/chair orientation and door route verified; future furniture correctly deferred. Evidence: `.hdrp-agent/reports/bedroom-quality-campaign/model-correction-visual-review.json`. This remains an intermediate sleep/study candidate, not a completed decorated bedroom.
