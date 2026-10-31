# Contrat de fidélité — conception v1

Statut : **à implémenter**, tâches T109–T112 et T134–T137. Extension de la remise de fichiers Python/Unity existante ; aucun nouvel endpoint public requis.

## Enveloppe et admission

Toute commande de proposition inclut schema_version, ordinal, input_bundle_sha256, catalogue_sha256, expected_version, policy_hash, proposal_id, origin, phase, plan, inspection et supports. Les champs sont fermés, types stricts, valeurs finies, chemins possédés, références d’objets existantes. Une seule mutation par ordinal ; nouveau candidat pour toute autre variante. Étendre conjointement le schéma JSON et la validation C#, sans accepter silencieusement de champs inconnus.

La politique fige avant exécution : six candidats et quarante minutes par défaut, bornes locales, douze images Muse, huit inspections Editor, seuils de mesure et de régression. Aucun seuil appris du rapport de vérité terrain de la scène en cours. Les vieux bundles suivent leur ancienne version ; aucun changement de sens des scores d’un run déjà exécuté.

## Reçu natif et évaluation

Reçu `started` avant mutation, puis `built` avec version/applied_plan/contacts et hashes. Les captures sont liées à cette version. Mesures de silhouettes et de reprojection recalculées sur `applied_plan`, jamais sur une géométrie antérieure aux contacts. Retour `STALE_VERSION` ou `INCOMPLETE_EVIDENCE` si version, protocole, couverture ou mesures requises ne correspondent pas.

Reçus d’inspection existants conservés : images sans gizmos, poses calibrées, hashes et mode `editor_hdrp_probe`, performance non qualifiée. Une image Editor ne prend pas le rôle d’une preuve photométrique GameView. Les images de contrôle ne sont jamais envoyées à Muse/SAM ni utilisées pour choisir un mouvement ; elles peuvent opposer un veto de validation.

## Politique d’acceptation

1. Validité des assets, périmètre, contacts et transformations autorisées.
2. Couverture suffisante et mesures post-contact complètes ; valeurs manquantes explicites.
3. En phase géométrie : amélioration de contours/reprojection supérieure au bruit, aucune régression locale hors seuil ; RGB exclu du classement.
4. En phase apparence : poses/identités/échelles identiques, capture comparable, gain photométrique et contrôles admissibles.
5. Échec ou ambiguïté : conserver le meilleur admissible, consigner le motif ; aucune annonce de convergence sur épuisement de limite.

## Séparation des évaluations exactes

L’audit source lit uniquement une reconstruction terminée et le manifeste de source préservée. Il écrit sous `.hdrp-agent/reports/ground-truth-*.json`. Les lecteurs de mémoire, prompts, métriques de proposition et demandes de caméra excluent ces rapports et leurs champs. Un test à valeurs sentinelles vérifie cette séparation de bout en bout. L’audit d’association ambiguë produit `unqualified`, jamais une correspondance forcée.

## Arrêts et reprise

Motifs distincts : `converged_visual_criteria`, `insufficient_observations`, `no_admissible_progress`, `candidate_limit`, `time_limit`, `budget_limit`, `concurrent_edit`, `native_interrupted`, `provider_unknown`. La convergence visuelle ne vaut pas validation exacte des poses. Limites/interruptions conservent reçus, coûts inconnus et meilleur état restaurable. Aucun rejeu automatique des requêtes/mutations déjà transmises.

## Implémentation `fidelity-3`

La version du solveur fait partie du hash de politique et invalide la mémoire de décisions des versions précédentes. Elle ajoute une acquisition complémentaire unique lorsque la baseline manque d'observations fiables : au plus trois objets, trois vues par objet, douze images dans la requête Muse, puis au plus neuf opérations SAM distinctes. Une transmission identique déjà admise n'est jamais renvoyée ; seule une réponse terminée et facturée peut être relue. Les nouvelles mesures remplacent celles de la baseline avant classement et gardent les mesures précédentes comme diagnostic.

Les régions de moins de 16 pixels dans leur plus petite dimension native, ou de moins de quatre pixels dans le raster de recherche, sont exclues explicitement. Deux vues identiques ou un simple changement de zoom ne constituent pas une couverture de profondeur. Le solveur relatif combine IoU et distance de contour pour sortir du plateau des silhouettes sans recouvrement ; la sélection native conserve ses contrôles par objet et par vue.

La commande v2 accepte en complément `capture_protocol`, uniquement lorsqu'il provient de la capture native enregistrée. Son contrat fermé reprend les conditions de caméra et les modes de tonemapping, jamais les transforms d'objets ou de lumières de la source. Le constructeur applique ces conditions avant capture. Les anciennes captures sans protocole restent comparables à titre diagnostique, mais ne qualifient pas l'apparence. Les chemins Editor probe et GameView restent distincts.

Les essais d'apparence séparent géométrie des lumières, photométrie puis atmosphère. Les identités et transforms d'objets restent figées. Toute comparaison doit disposer des vues de contrôle, de conditions compatibles et d'une preuve de bruit gelée. Le bruit mesuré sur deux reconstructions de plan identique est une preuve limitée à ces conditions, pas une garantie temporelle générale.

### Solver fidelity-4

The frozen policy identifies `fidelity-4`: group rotation composes full XYZ orientation matrices (including tilted children), bounded anchor trials examine pitch/yaw/roll without certifying a unique orientation, and truncated masks cannot establish complete coverage. Optional `scale_mode=evidenced` is a separate `scaling` proposal, requires three independent views and preserves the cumulative ±15% origin bound. Unity exposes this option before launch; default remains `locked`.

The adaptive observation response retains local uniqueness validation, while the provider JSON-schema dialect omits unsupported `uniqueItems`. Unknown historical calls remain reserved and are never resent. Runtime reference capture identities hash the actual float-valued `CapturePlan`, preventing decimal parsing differences from falsely changing capture conditions. This normalization is for capture conditions only; proposal and applied-plan hashes remain exact and version-bound. Historical noise measurements are not re-labelled under the new capture hashes.

### Solver fidelity-5

Pose proposals (except immutable appearance poses) are explicitly serialized at twelve decimal places before experiment identity, validation and hashing; this removes matrix cancellation residue that exceeds .NET Decimal scale without silently weakening the hash check. This explicit quantization is far smaller than the strict scene pose tolerances and does not replace them. The raw provider proposal remains archived. The interrupted fidelity-4 proposal is preserved; a separately normalized copy passed native validation without mutation or replay.
