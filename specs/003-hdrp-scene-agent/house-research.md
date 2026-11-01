# Recherche et décisions — génération de maisons

2026-11-01. Recherche fondée sur le dépôt et l’audit local, sans appel fournisseur. Deux revues indépendantes en lecture seule : conception spatiale/catalogue et orchestration/inspection. Aucune capacité externe nouvelle n’est supposée.

| Sujet | Décision | Justification / preuve locale | Alternatives examinées |
|---|---|---|---|
| Complexité | Hiérarchie et lots exhaustifs | `reference_planner.py` impose 20 objets ; la référence contient 1 713 instances sérialisées | Monter simplement le plafond : conserve le problème de complétude et de contexte |
| Espace | IR métrique par étage, frontières partagées | `native_layout.compile_grid` dimensionne globalement les intervalles ; `floorplan` suppose des rectangles disjoints | Étendre la grille actuelle : inflation des pièces et incapacité à exprimer trémies/paliers |
| Orientation | Face avant locale qualifiée | `circulation.service_points` utilise nom et yaw ; les bounds ne distinguent pas 0°/180° | Déduire la face depuis l’image seule : preuve insuffisante pour un prefab ambigu |
| Aménagement | Recettes fonctionnelles paramétriques | `harmonize_seating` ne traite qu’un arrangement canapé/table/TV | Copie des poses de la référence : ne généralise pas ; placement d’objets indépendants : incohérent |
| Détails | Supports réels + rôles + palette | L’audit relève accessoires, rangements, vêtements et 132 decals | Quota aléatoire d’objets : encombrement sans intention |
| Passage | Prétest 2D conservateur puis validation native inter-niveaux | `circulation.check` est local à la pièce et ne vérifie pas escaliers/hauteur libre | NavMesh seul ou présence de colliders : peut manquer une géométrie bloquante non configurée |
| Observation | Inspections dirigées par défaut, dans tous les modes | `reference_worker.inspect_candidate` existe mais reçoit `provider=None` en composition | Plus de captures sans qualité de cadrage ni correction : coût sans bénéfice |
| Correction | Patch typé local + invalidation des dépendances | `floorplan.correct_native` retourne None pour le mode natif, provoquant l’arrêt | Régénération de toute la maison : régressions et consommation inutiles |
| Mémoire | Archive complète + index des obligations/défauts + contexte sélectionné | `reference_memory` réduit les historiques transmis et conservés | Tout envoyer au modèle : coûteux ; garder seulement la queue : oublie les problèmes persistants |
| Exécution/qualité | Deux états distincts et preuves par gate | Le worker actuel finit `completed` même si les contacts échouent | Renommer uniquement le texte UI : laisse une mauvaise logique d’arrêt/reprise |
| Reprise | Jobs durables et reçus réconciliés | Reprise actuelle limitée au pré-build ; réservations budgétaires et versions existent | Rejouer le run à zéro : doublons Unity et coûts incertains |
| Pipeline | Nouveau mode `house_v1` derrière admission existante | Worker historique déjà complexe ; socle d’auth/budget/captures réutilisable | Réécrire tous les services : risque sans bénéfice pour la qualité |
| Rendu | Pièce nocturne qualifiée avant extension maison | Quatre directionnelles actuelles sont diagnostiques ; référence dispose de fill/specular/bake/probes | Copier des intensités sérialisées sans calibration : pas une garantie de rendu |
| Référence native | Preview isolée d’abord, validation de rendu explicite | Audit actuel statique, éditeur occupé lors de l’analyse | Ouvrir directement la scène source pendant un run : conflit ; prétendre mesurer à partir du YAML : faux |

## Incertitudes converties en tâches mesurables

- Sens des prefabs, surfaces et modules d’escalier : mesurer J0, enregistrer confiance et preuve ; utiliser seulement les assets qualifiés dans les gates strictes.
- Cadrages et lumière en preview HDRP : sonde de compatibilité J0/J5 ; copie de validation séparée si nécessaire, résultat déclaré non qualifié jusqu’à la sonde.
- Densité artistique et charge GPU acceptables : atlas natif, puis calibration sur premier palier avant campagne ; pas de seuil universel inventé.
- Coût total d’une maison : profiler coût par job sur pièce témoin puis projection, sans garantie prématurée ; ledger courant comme autorité financière.
- Génération à partir d’un dessin : adaptateur d’observations vers le même HouseProgram/BuildingIR. Le dessin ne fournit pas une métrique exacte ; contraintes métriques viennent des modules et usages.

Ces inconnues n’empêchent pas la conception ; leurs mesures sont des préconditions explicites d’implémentation/qualification, non des fonctionnalités présumées acquises.
