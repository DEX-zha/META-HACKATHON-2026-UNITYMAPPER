# Recette de la correction de fidélité

**Statut : implémentation et qualification documentées ; fidélité stricte non validée.** Projet, API et autorisations existants conservés. Exécuter depuis `/Users/romain/Documents/Meta-Hackaton`.

## 1. Geler le cas et les conditions

Conserver le run `de8919eabdab49d78d38c0ec81384b65`, ses images, calibrations, catalogue, masques et source préservée. T108 produit `tests/fixtures/reference_fidelity/manifest.json` sans poses source. T110 ajoute les variantes déterministes dont les réponses attendues restent dans l’évaluateur. Enregistrer avant campagne seuils, bruit de répétition, limite six candidats/quarante minutes et politique d’échelle. Ne pas remettre le budget global à 150 USD.

## 2. Vérifier hors ligne

Après implémentation des tâches correspondantes :

```sh
.venv/bin/pytest tests/unit/test_reference_geometry.py tests/unit/test_reference_metrics.py tests/unit/test_reference_support_graph.py tests/unit/test_reference_schedule.py tests/integration/test_reference_fidelity.py -q
.venv/bin/pytest -q
```

Les tests sont implémentés ; les résultats natifs et les échecs de recette sont référencés ci-dessous. Attendus : axes/pivots/projections corrects ; lumière seule sans erreur géométrique ; masques tronqués traités ; aucune fuite des transforms source ; correction d’ancrage indépendante de la valeur −16 cm ; mesure post-contact ; rejets et budgets explicites. Le test de régression démontre que l’ancien ajustement XZ ne corrige pas une erreur verticale de −23 cm.

## 3. Vérifier Unity

Éditeur visible et scène sauvegardée, aucun run actif. Exécuter `HdrpAgent.Tests.TestRunBridge.RunReferenceConstruction()` via le bridge existant. Étendre cette suite pour les supports déplacés, les métriques après contact et les captures de visibilité. Vérifier source/hash inchangés, annulation, scène candidate possédée et caméra d’inspection temporaire nettoyée. Captures GameView de contrôle séparées des sondes Editor.

## 4. MVP ancrage global

Activer la politique de fidélité prévue, lancer depuis le panneau Agent la reconstruction de la référence conservée. Ne fournir aucune pose exacte au solveur. Après fermeture du run, utiliser « Comparer aux positions réelles de la démo ». JF1 : biais Y médian <1 cm et réduction ≥80 %, contacts et autres contraintes géométriques préservés. Un échec produit un diagnostic, pas une correction codée en dur de +16 cm.

## 5. Recette complète

Exécuter la démo et les trois variantes réservées, une demande par cas, sans déplacement manuel ni conseil intermédiaire. Journaliser phases, propositions brutes/raffinées distinctes, cibles d’inspection, mesures avant/après contact, contrôles, coûts et arrêt. Vérifier restauration du meilleur et cohérence de la fenêtre Vision. Comparer séparément ancrage, disposition relative, échelle et rendu.

Cible stricte sur chaque objet de démo associé : position ≤1 mm, rotation ≤0,1°, échelle absolue par axe ≤0,001. Si hors seuil, indiquer **fidélité non validée**, même avec un bon rendu. Les objets ambigus et primitives sans correspondance source restent non qualifiés. L’éclairage doit satisfaire ses propres critères gelés ; aucun « pourcentage de fidélité » déduit des pixels.

## 6. Dossier de résultat

T142 écrit `.hdrp-agent/reports/reference-fidelity-qualification.json` et `.html` avec baselines, métriques par objet, couverture, configurations, limites, arrêt, budget, liens aux images natives et audit séparé. Ne modifier aucune preuve ancienne. Le dessin annoté reste hors de cette campagne.


## Couverture RF-01–RF-10

| Exigence | Preuves | Limite de qualification |
|---|---|---|
| RF-01 | `test_reference_geometry.py`, fixtures gelées, test Unity `CaptureIdentityUsesRuntimeFloatsAcrossDecimalRoundTrip` | Les références importées sans calibration restent estimées. |
| RF-02 | Sentinelles privées dans `test_reference_fidelity.py`, générateur évaluateur séparé, audit post-run | Aucun audit source n’est consommé par le solveur. |
| RF-03 | Tests de version/hash/pré-contact, reçus natifs et `applied-evidence` par candidat | Une prédiction locale n’est jamais une mesure native. |
| RF-04 | Tests d’ancrage −23/+11 cm, rotations et supports ; `reference-fidelity-anchor.json` | JF1 démo passe ; pas de généralisation garantie. |
| RF-05 | Tests de visibilité, troncature, faible résolution, symétrie ; raster Unity IoU 1 sur cube | Transparence, clipping et instances ambiguës non certifiés. |
| RF-06 | Propositions séparées, ordinaux et politique gelée ; rapport autonomie | Les variantes rejetées restent archivées. |
| RF-07 | Tests des sous-expériences lumineuses, poses figées et contrôles exclus ; recette apparence séparée | Aucun gain photométrique déduit d’un déplacement d’objet. |
| RF-08 | Tests de mémoire/cache/identité d’expérience ; `fidelity-5` | Images payées réutilisables, décisions périmées invalidées. |
| RF-09 | Tests budgets/délais/reprise/coût inconnu ; reçus d’interruption réels | Les réservations inconnues restent engagées ; une limite n’est pas une convergence. |
| RF-10 | Rapports suites Python/Unity, campagne et audit strict séparé | Fidélité stricte **non validée** ; campagne de diagnostic sur versions successives, pas campagne uniforme de release. |

Le dessin annoté reste T107, différé. Les critères stricts ne sont pas assouplis pour transformer les écarts restants en succès.

Dernier résultat : 239 tests Python, 16 tests Unity ; JF1 et fixture photométrique à poses figées validés. Trois variantes natives diagnostiques exécutées : une terminée hors seuil, deux interrompues et restaurations/engagements conservés. Fidélité stricte non validée. La dernière correction `fidelity-5` a également terminé un passage live complet sur la démo conservée : quatre candidats, trois rejets, restauration vérifiée et arrêt pour observations insuffisantes. Ce passage réutilise l’analyse et le meilleur candidat précédent ; il ne remplace pas une campagne uniforme des trois variantes.
