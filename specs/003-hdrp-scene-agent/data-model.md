# Modèle de données

> Extension active 2026-11-01 — maisons créatives : [house-data-model.md](house-data-model.md). Les sections historiques ci-dessous restent applicables au socle legacy.


> **Mise à jour utilisateur du 2026-10-28** : plafond de consommation API de **150 USD encore disponibles**, suivi directement en micro-USD ; modèle `muse-spark-1.3-contributor` autorisé explicitement. La confirmation du solde restant est enregistrée une seule fois, sans recharge lors d’une nouvelle session. Cette instruction remplace les anciennes règles Standard/EUR et le blocage faute d’antériorité/changement/frais ; la clé reste dans `.env`, côté Python.

**Statut** : conception. [Schémas de transport](contracts/domain.schema.json) et [API](contracts/http-api.openapi.json). Les contraintes relationnelles ci-dessous complètent JSON Schema ; une réponse syntaxiquement valide ne suffit pas.

## Identifiants et stockage

Identifiants opaques générés par le service, dates UTC ISO 8601, SHA-256 hexadécimal pour contenus/manifeste. Distances en mètres, rotations en degrés, températures en kelvins ; chaque réglage lumineux précise son unité. Aucun float pour les sommes : entiers micro-dollars USD ; coûts USD en unités décimales exactes avant conversion et arrondi supérieur.

SQLite avec clés étrangères actives et transactions courtes ; un seul service possède le grand livre. Fichiers déposés temporairement puis renommés atomiquement avant référencement. Un fichier incomplet n’est pas un artefact valide. Le grand livre global n’est pas supprimé avec une session, une scène ou une nouvelle spécification.

## Entités

| Entité | Champs principaux | Relations et règles |
|---|---|---|
| Project | id, chemin enregistré, editor_version, hdrp_version, graphics_api, capabilities, capability_report_hash | Un projet actif ; racines autorisées fixées par inscription locale |
| Scene | id, project_id, source_asset_guid, working_path, owned_root_id, dependency_manifest | Copie de travail isolée ; modifications en EditMode sur scène sauvegardée |
| Brief | id, texte, éléments requis, ambiance, références d’artefact, ressources autorisées, périmètre | Une version immuable par session ; référence esthétique distincte d’un oracle de recette |
| Criterion | id, kind, target, seuils, unité, required, méthode, provenance, frozen_hash | Genre : artifact, visibility, geometry, artistic, performance ; fixé avant premier patch |
| InspectionPlan | id, work_views, control_views, path, fps, duration, conditions, hash | Trois vues de travail, deux de contrôle, six secondes/24 fps par défaut ; rôles non interchangeables |
| Session | id, project_id, scene_id, base_version, brief, criteria_hash, inspection_hash, provider_mode, state, verdict, limits, best_version, current_version, stop_reason | Une seule session active ; bornes fixées avant lancement ; mode live ou offline explicite |
| SceneVersion | id, scene_id, parent_id, scene_hash, manifest_hash, snapshot_id, bake_status, bake_job_id, provenance | Nouvelle version à chaque mutation ; empreinte inclut dépendances visuelles, pas seulement `.unity` |
| Snapshot | id, version_id, fichiers avec path/GUID/hash/taille/ownership, created_at, restore_log | Références aux octets sauvegardés ; couvre ressources nouvelles et supprimées |
| Capture | id, version_id, inspection_hash, conditions_hash, role, camera_key, frame_index, simulated_time, artifact_hash, render_ready, provenance | Même origine graphique et mêmes conditions avant/après ; contrôle inaccessible au planificateur |
| Clip | id, version_id, frame_manifest_hash, fps, frame_count, duration, video_hash, codec | Toutes frames écrites ; durée calculée, ordre et frames manquantes contrôlés |
| Artifact | hash, relative_path, media_type, bytes, width, height, owner_session, provenance | Contenu immuable, racine enregistrée, aucun chemin arbitraire demandé par le modèle |
| ObjectBinding | version_id, logical_key, source_global_object_id, working_global_object_id, runtime_binding, component_capabilities | IDs d’authoring résolus en EditMode ; clé sérialisée utilisée au runtime |
| Region | id, capture_id, bbox, mask_hash, sam_response_id, sam_object_id, candidates, association_evidence | Pixels à l’échelle exacte du média ; IDs SAM propres à une réponse, jamais des IDs Unity |
| Observation | id, capture_refs, region_refs, description, category, confidence | Faits visuels ; au moins une preuve ; catégorie technique/artistique explicite |
| Hypothesis | id, observation_ids, candidate_targets, proposed_cause, evidence, uncertainty, status | suspected, supported, disproved, unresolved ; un masque seul ne peut promouvoir à supported |
| Patch | id, session_id, expected_version, hypothesis_id, operations, expected_effect, needs_bake | Liste fermée, max huit opérations ; validation et snapshot avant application |
| Attempt | id, ordinal, patch_id, before_version, after_version, snapshot_id, state, evaluation_id, timestamps | 1 à max_attempts ; ordinal consommé dès acceptation durable du patch, jamais remis à zéro sur échec |
| Evaluation | id, before_version, after_version, criteria_hash, inspection_hash, evidence, per_criterion, verdict, reason, judge_provenance | improved seulement si critères obligatoires satisfaits et défaut ciblé amélioré ; jugement modèle seul insuffisant |
| EditorCommand | id, session_id, kind, expected_version, payload, state, lease, deadline, result_hash, bridge_epoch | États persistants côté service et reçu durable côté éditeur ; reprise sans double application |
| ProviderCall | id, model, payload_hash, purpose, reservation_id, response_id, state, usage, cost_source, artifact_ids | Réponse et coût indépendants ; pas de retry automatique après envoi d’issue inconnue |
| BudgetLedger | id global, cap_usd_micro=150000000, reconciliation_state, external_spend, price_snapshot, fx_snapshot | Invariant global ; la saisie antérieure inconnue bloque le live |
| BudgetEntry | id, call_id nullable, kind, amount_usd_micro, source_amount, source_currency, source_ref, created_at | Réservations, règlements, rapprochements, corrections auditables ; pas d’effacement comptable |
| SessionReport | id, session_id, best_version, before_after_pairs, observations, attempts, unresolved, cost_summary, stop_reason, provenance | Rapport même après limite/interruption ; replay/offline étiqueté partout |

## Transitions de session

Parcours nominal :

```text
created → preflight → baseline → diagnosing → proposing → applying
        → baking (si nécessaire) → capturing → verifying
        → completed | diagnosing (essai suivant) | restoring
restoring → diagnosing | completed | limit_reached
```

- `completed` signifie boucle terminée, avec verdict séparé `improved` ou `no_improvement`. Cela ne signifie pas perfection ni suppression de tous les défauts.
- Budget/temps/essais atteints → `limit_reached`, motif conservé. En cours de bake, demander arrêt et attendre sa confirmation avant toute restauration.
- Erreur fournisseur/rendu → `interrupted` si l’état est connu ; effet Unity inconnu, conflit de restauration ou reçu perdu → `recovery_required`.
- `recovery_required` bloque mutations et nouveaux essais. Inspection/recherche de reçu/restauration conditionnelle autorisées. Nouvelle session seulement après réconciliation de la scène.
- Pas de relance automatique d’une inférence, d’un bake ou d’un patch après redémarrage. Les tâches purement consultatives peuvent être replanifiées.

## Transitions d’essai et de commande

Essai : `proposed → validated → snapshotted → applying → baking? → capturing → verifying → accepted | rejected | inconclusive`. Rejet/inconclusif après mutation → restauration ou récupération requise. Avant mutation, proposition invalide n’utilise pas un ordinal ; après acceptation durable du patch, un échec compte comme essai. La création initiale de pièce et le bake lui-même ne sont pas des essais correctifs supplémentaires.

Commande : `queued → claimed → running → succeeded | failed | cancelled | unknown`. Une lease expirée après claim n’autorise pas un autre éditeur à rejouer la mutation. L’éditeur garde un reçu durable par command_id, empreinte de payload, version avant/après et résultat. Un doublon identique retrouve le reçu ; un doublon avec payload différent est un conflit. Une commande réellement commencée mais sans preuve de fin devient unknown, avec récupération requise.

Bake : `not_required | pending → running → complete | failed | interrupted`. `complete` exige événement de réussite du job courant, absence d’annulation/erreur et ressources valides. `isRunning=false` seul ne suffit pas. Échec après domain reload sans reçu ne devient pas complete.

## Budget : états et équation

ProviderCall : `prepared → reserved → sent → responded → settled`. Après envoi et issue inconnue : `unknown`, réservation maintenue. Avant envoi, une réservation peut être libérée avec preuve d’absence de transmission. Une réponse invalide peut malgré tout être facturée et doit être réglée ; validité du contenu et coût sont deux décisions distinctes.

Chaque appel possède exactement un engagement actif : reserved/unknown **ou** settled, jamais les deux dans la somme. Dans une transaction `BEGIN IMMEDIATE` :

```text
available = cap - prior_and_external_settled - settled_calls - active_reservations
admit iff reconciliation_state == reconciled and new_upper_bound <= available
```

`unknown` est une sous-catégorie d’engagement actif, pas une seconde charge. Après facture réconciliée, remplacer la réservation par le coût constaté et libérer seulement la différence prouvée. Si une facture dépasse exceptionnellement la réserve, enregistrer la vérité, désactiver le live et signaler une violation ; ne jamais plafonner artificiellement le coût stocké.

Capture/rapport/relecture ne réinitialisent pas le ledger. Les essais sans API ne consomment pas d’argent mais restent soumis à temps/essais. Les frais/taxes et marges de change sont provisionnés sans multiplier deux fois une dépense déjà convertie.

## Invariants de preuve et de comparaison

1. Un patch référence la version courante exacte ; ses cibles existent et appartiennent au périmètre. Aucun objet identifié seulement par son nom.
2. Snapshot complet avant mutation ; préconditions vérifiées de nouveau dans Unity. Une copie locale ne réutilise pas le GUID de l’original ; le manifeste garde la correspondance source/copie.
3. Une capture lie scène, dépendances, critères et conditions. Les caches incluent ces empreintes, modèle, prompt et version de prétraitement.
4. Image LDR PNG évaluée dans son espace couleur déclaré ; pas de comparaison numérique entre LDR tonemappé et sortie HDR linéaire sans conversion explicitée.
5. Contrôle inaccessible aux prompts de diagnostic/proposition. Le planificateur peut apprendre qu’un essai est rejeté, sans recevoir ses pixels ni ses métriques cachées ; le rapport complet est réservé à l’opérateur/évaluateur.
6. Aucun candidat n’est retenu si l’un des critères obligatoires échoue ou reste inconnu. Les critères artistiques nécessitant un humain gardent un verdict provisoire tant qu’il n’a pas évalué.
7. `improved` en live exige preuves de capture live et changements réels. Un fournisseur simulé ou une vidéo rejouée ne satisfait pas SC-001.
8. Après restauration, vérifier fichiers, références et état observé ; une capture fraîche est requise avant de revendiquer une nouvelle vérification visuelle. Une comparaison ancienne reste liée à son ancienne version.
9. La meilleure version n’est mise à jour qu’après évaluation admissible. Si aucune correction n’est acceptée, c’est la référence initiale inspectée, avec défauts visibles ; ne pas la présenter comme corrigée.
10. Les limites d’essais, de calcul et de budget sont conservées après redémarrage. Les coûts locaux et la dépense API sont deux mesures distinctes.

## Conservation et provenance

Médias et snapshots locaux jusqu’à suppression explicite ; pas de rétention distante implicite infinie. Le provider trace les fichiers uploadés et tente leur suppression sans effacer les preuves locales ni cacher un échec. La clé Meta reste dans le service, jamais dans Unity, un rapport ou un événement. Les fixtures de test contiennent uniquement des réponses nettoyées.

La livraison inclut versions/lockfiles, droits des ressources, paramètres d’inspection, provenance des modèles, coûts observés, résultats négatifs et limites. Les dates et numéros présents ici sont des conventions de conception et de recette ; ils ne décrivent pas des performances mesurées.


## Extension fidélité — entités à implémenter

Toutes les distances en mètres, angles en degrés, pixels dans l’image calibrée d’origine. Champs numériques finis et bornés ; propriété manquante distincte d’un zéro.

| Entité | Champs | Invariants |
|---|---|---|
| FidelityPolicy | schema_version, policy_hash, solver_version, phase_limits, image_limits, thresholds, noise_baseline_hash, geometry_gate | Figée avant le premier candidat ; ni vérité terrain ni statistiques de démo dans ses paramètres de correction |
| SupportGraph | roots, nodes(object_key, support_key, relative_pose, scale_policy, contact_policy), frame_hypotheses | DAG ; objets existants ; racines sans support explicites ; toute transformation de groupe est traçable |
| PoseProposal | id, parent_version, origin(muse/local), phase, changed_objects, proposed_plan_hash, objective, evidence_hashes | Proposition brute immuable ; un raffinement produit un nouvel id ; aucune application cachée |
| AppliedPoseEvidence | proposal_id, command_hash, version, applied_plan_hash, contacts_hash, camera_hashes, metrics_hash | Mesures après application native ; aucun résultat de silhouette pré-contact utilisé comme preuve finale |
| ObjectGeometryMetrics | object_key, views, visible_iou, contour_error_px, reprojection_error_px, contact_gap_m, coverage, missing_reasons | Visibilité des autres objets prise en compte ; scores par vue conservés ; inconnues interdisent validation complète |
| AppearanceMetrics | protocol_hash, version, region_errors, shadow_errors, saturation, control_verdict | Même rendu/conditions ; aucune comparaison Editor/GameView non qualifiée |
| FidelityDecision | phase, predecessor, accepted, reasons, missing_evidence, next_action, stop_reason | Pas de score RGB pour accepter une pose ; plafonds de régression et seuils gelés |
| EvaluationTruth — hors inférence | source_hash, association, expected_poses, absolute_errors, relative_errors, global_bias, thresholds, verdict | Accessible uniquement à l’évaluateur post-run ; jamais dans mémoire, prompt, objectifs ou cache de proposition |

L’état du parcours distingue progression, convergence mesurée, résultat partiel et interruption. La mémoire ajoute policy_hash/solver_version ; changements de politique invalident les décisions dérivées, pas les images originales ni les réservations de coût.


## Extension application Go — 2026-10-31

[Données du chat Go](chat-data-model.md) complète ce document pour US10–US13. L’application est planifiée ; ses commandes et endpoints ne sont pas encore livrés. Le budget, les preuves et les automatismes de reprise du socle restent applicables.
