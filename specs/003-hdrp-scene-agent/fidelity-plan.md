# Plan de correction de la fidélité

**Date** : 2026-10-29 · **Identifiant** : `003-hdrp-scene-agent` (pas de branche Git physique).
**Statut** : conception prête pour implémentation ; aucune correction exécutée par ce plan.
**Entrées** : [US5–US9 et RF-01–RF-10](spec.md), [état de la reconstruction](reference-reconstruction.md), [tâches T108–T143](tasks.md#correction-de-la-fidélité--t108t143).

## Résultat recherché

Une demande déclenche une reconstruction qui améliore réellement sa géométrie puis son rendu, avec des mesures fiables et un résultat conservé automatiquement. Priorité : supprimer la dérive globale et les erreurs locales visibles sur `work-top-front`, en préservant les autres angles. Le dessin/croquis annoté reste une extension future T107.

## Point de départ mesuré et diagnostic

Essai `de8919eabdab49d78d38c0ec81384b65` : six candidats, 48 inspections Editor, dix prefabs ; candidat ordinal 4 retenu ; contacts satisfaits. Audit séparé : décalage Y médian −0,159 m, sol −0,160 m, erreur totale maximale 0,2713 m ; variations d’échelle du pot et du bol proches de +13,7 %. Aucun des dix objets ne passe l’audit strict. Sources locales : `.hdrp-agent/reports/scene-vision-qualification.json` et `ground-truth-de8919eabdab49d78d38c0ec81384b65.json`.

Le code confirme que `reference_pose.py` optimise X/Z, yaw et échelle, mais pas Y. `ReferenceContacts.cs` règle les contacts en partant des supports ; il ne détermine pas une hauteur globale correcte. `reference_worker.py` classe encore les candidats avec des écarts RGB et de gradient, et les scores de silhouettes décrivent un état antérieur à la résolution native des contacts. Le solveur dessine chaque objet isolément, sans traiter les occultations par ses voisins. L’origine initiale exacte du sol à 0,84 m reste une hypothèse à tester, pas une cause établie.

## Contexte technique

Réutiliser C#/Unity 6000.3.23f1/HDRP, Python 3.12, NumPy/Pillow, SQLite, le stockage d’artefacts et les adaptateurs Muse/SAM existants. Pas de nouveau modèle, matériel, service ou dépendance nécessaire à ce plan. Optimisation numérique locale bornée ; validation graphique dans le projet `unity/HDRPValidation` sous Metal. Caméras enregistrées calibrées d’abord ; reconstruction métrique depuis médias externes non calibrés hors de cette recette.

Limites conservées : six candidats natifs par défaut, quarante minutes maximum, douze images par demande Muse, huit gros plans Editor par inspection. Les évaluations locales ont une limite propre gelée au lancement : 2 000 évaluations de fonction et 120 secondes par proposition, incluses dans le délai global, arrêt coopératif obligatoire. Si ces bornes ne suffisent pas, rendre le meilleur résultat avec le motif précis ; aucune augmentation automatique.

## Contrôles de conception

La constitution locale est toujours un gabarit, sans règle ratifiée supplémentaire. Gates avant/après conception : source préservée ; vérité terrain uniquement en évaluation ; budget global conservé ; mutations natives typées et une seule opération propriétaire ; preuves versionnées après contact ; contrôles hors inférence ; seuils gelés ; pas de fidélité garantie par un score moyen. **PASS pour la conception**, sous réserve des tests d’implémentation listés. Aucun nouveau seuil n’est déjà qualifié.

## Architecture et ordre de réalisation

### 1. Fiabiliser le diagnostic — US5

Créer un benchmark figé à partir du cas actuel et de trois variantes déterministes de validation (hauteur/repère, petits objets, éclairage). Le moteur d’inférence reçoit images, caméras admissibles et catalogue ; l’évaluateur conserve à part les transforms exacts. Les valeurs d’erreur ne deviennent jamais des paramètres du solveur. Vérifier conversion pixels/crops/masques, conventions Euler, pivot et repère monde, correspondance prefab, projection aller-retour et reproductibilité des rendus.

Séparer erreur de translation globale, erreur locale relative au support, rotation, échelle, contact, silhouette et apparence. Conserver les erreurs absolues : une mesure après réalignement ne doit pas cacher le décalage Y. Mesurer deux captures sans mutation pour fixer le bruit de rendu avant de comparer des propositions.

### 2. Corriger le repère et les supports — US6, premier MVP utile

Introduire un graphe de supports sans cycle, avec racines explicites et transformations relatives. Estimer le repère du sol depuis contours/masks fiables et dimensions intrinsèques du catalogue sur au moins trois vues spatialement distinctes. Optimiser d’abord translation XYZ du groupe ; ouvrir roll/pitch/yaw seulement si les observations les contraignent. Les caméras calibrées restent figées et les échelles restent fixes pendant cette étape. Les racines sans support ne sont pas forcées à Y=0.

Une relation de support reste une hypothèse : distinguer contact requis, offset étayé par la vision et relation indéterminée. Ne pas forcer une pose source intentionnellement décalée à respecter un contact supposé.

Déplacer support et descendants de façon cohérente, appliquer la correction native des contacts, puis refaire les mesures sur le plan effectivement appliqué. Tester plusieurs initialisations bornées pour ne pas rester piégé par le seed. Ne jamais introduire « +16 cm » dans l’algorithme : cette valeur est un diagnostic du cas connu.

**Jalon intermédiaire** : ramener le biais Y médian de la démo sous 1 cm et le réduire d’au moins 80 %, avec contacts satisfaits et sans dégradation géométrique locale au-delà du bruit gelé. Ce jalon ne remplace pas la cible finale de 1 mm.

### 3. Corriger chaque objet — US7

Pour chaque support, traiter ses objets comme un groupe de contraintes relatives : positions dans son plan, orientations, contact, espacement, non-intersection selon la géométrie. Calculer les contours visibles candidats avec profondeur de toute la scène candidate, y compris les supports simples. Ne pas comparer une silhouette complète au fragment visible d’un masque SAM. Poids selon qualité de segmentation, diversité des vues et occultation ; un masque de faible confiance n’est pas un objectif rigide.

Verrouiller l’échelle au facteur de référence d’asset admis lors de l’initialisation ; pour le benchmark, assets canoniques à échelle unité. Un déverrouillage est une expérience distincte, bornée cumulativement par rapport à l’échelle d’origine (pas une marge renouvelée à chaque essai), appuyée par plusieurs vues, jamais une compensation par défaut d’une mauvaise hauteur ou d’un mauvais masque. Travailler du grossier au fin, avec mesure finale en résolution native ; ne pas annoncer une précision millimétrique issue du seul raster réduit à 256 pixels.

Évaluer séparément proposition Muse brute et raffinement numérique. Chaque construction native consomme un candidat ; pas de double candidat caché sous un ordinal. Garder les transforms exacts, paramètres, raisons de rejet et vues d’appui. Recalculer toutes les métriques de pose après correction des contacts.

**Classement géométrique** : admissibilité des contrats/contacts d’abord ; couverture minimale requise ; amélioration des contours/reprojections sur les vues de travail avec seuil au-dessus du bruit ; refus d’une régression locale dépassant le seuil gelé sur une vue ou un objet. RGB ne départage pas les essais géométriques. Une métrique indisponible empêche le verdict « vérifié ».

### 4. Corriger le rendu — US8

Ouvrir la phase d’apparence seulement lorsque les critères visuels de géométrie prévus sont satisfaits ou qu’une limite explicite impose un résultat partiel. Geler identité, transforms et supports. Qualifier l’équivalence des conditions de capture : exposition, tonemapping, volume, résolution, stabilisation et chemin HDRP. Les sondes Editor restent utiles pour la pose ; aucune comparaison photométrique croisée Editor/GameView non qualifiée.

Ajuster successivement direction/position des lumières, intensité/exposition puis paramètres d’ambiance autorisés. Mesurer régions comparables, faces éclairées, contours d’ombres et saturation ; éviter qu’une moyenne globale favorise une scène uniformément plus sombre. Les deux vues de contrôle sont évaluées sans entrer dans les prompts ni dans le calcul des propositions.

### 5. Orchestrer selon les écarts — US9

Remplacer `phase_for(ordinal)` par un choix explicite selon couverture, ancrage, erreurs locales et admissibilité du rendu. Réutiliser les gros plans existants, puis demander une nouvelle observation pour un objet ambigu si elle apporte une information différente. Les références manquantes ne sont pas inventées. Sélectionner les cibles selon les erreurs géométriques et le manque de couverture, plutôt que la seule différence RGB.

Transitions : `observing → anchoring → arranging → appearance → verifying → completed|partial|interrupted`. Une phase peut revenir à l’observation ; chaque transition, son motif et son coût sont conservés. Le meilleur état admissible est la base des propositions suivantes. Une modification de calibration/politique de score/solveur invalide les scores antérieurs, tout en conservant les preuves brutes. Les caches de requêtes payées et leur règle de non-rejeu restent distincts de cette invalidation.

Terminer pour convergence mesurée, ambiguïté persistante, absence de progrès admissible sur deux expériences distinctes après couverture requise, ou limites fixes. « Convergence » exige toutes les mesures obligatoires présentes et leurs seuils atteints ; « limite atteinte » reste partiel. L’audit exact de la démo se lance seulement après la fermeture du parcours.

## Jalons et recette

| Jalon | Critère | Preuve attendue |
|---|---|---|
| JF0 | Mesures/projections validées, fuite source impossible dans les fixtures | Tests + manifeste du benchmark |
| JF1 — MVP | Correction globale et contacts cohérents ; biais Y <1 cm et réduction ≥80 % | Avant/après absolu et relatif, audit post-run |
| JF2 | Disposition locale améliorée sans changement d’échelle injustifié | Erreurs par objet, occultations, poses après contact |
| JF3 | Apparence améliorée à géométrie figée | Captures même protocole, contrôles et hashes de poses |
| JF4 | Une invocation complète sur démo et variantes réservées | Rapport, budget, arrêts, restauration du meilleur |

La cible finale reste celle de RF-10 : 1 mm / 0,1° / 0,001 d’échelle pour tous les objets de démo associés sans ambiguïté. Si elle n’est pas atteinte, publier les erreurs et considérer la fidélité comme non validée. Réserver les variantes d’évaluation avant le développement pour limiter le sur-ajustement à la démo. L’appréciation artistique finale reste distincte et ne bloque pas les itérations autonomes internes.

## Fichiers et contrats

- Python existant : `reference_geometry.py`, `reference_pose.py`, `reference_worker.py`, `reference_planner.py`, `reference_memory.py`, `reference_inspection.py`, `reference_comparison.py`.
- Nouveaux modules prévus : `reference_metrics.py`, `reference_support_graph.py`, `reference_schedule.py`.
- Unity existant : `ReferenceContacts.cs`, `ReferencePoseGeometry.cs`, `ReferenceSceneBuilder.cs`, `ReferenceVision.cs`, `ReferenceWorkflow.cs`, `ReferenceGroundTruthAudit.cs`, `AgentWindow.cs`.
- Données/transport : [modèle](data-model.md#extension-fidélité--entités-à-implémenter), [contrat versionné](contracts/reference-fidelity.md). Les schémas exécutables seront modifiés dans les tâches, pas pendant cette planification.
- Tests : unitaires géométrie/visibilité/mesures, intégration provenance/politique/budget, Unity contacts/captures/audit, puis [recette](fidelity-quickstart.md).

## Risques et décisions de repli

Occultation ou symétrie : observations supplémentaires bornées, puis ambiguïté déclarée. Divergence raster CPU/Unity : comparer à une fixture native, refuser la qualification si hors seuil. Sol mal segmenté : utiliser plusieurs contours/vues et supports admissibles, sans fixer une hauteur arbitraire. Coût élevé : cache et recherche locale bornée, arrêt partiel explicite. Baked GI non équivalente : conserver une limitation de rendu, sans déformer les objets pour la masquer.
