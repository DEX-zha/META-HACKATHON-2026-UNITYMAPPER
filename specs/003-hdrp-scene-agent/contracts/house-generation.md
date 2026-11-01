# Contrats proposés — génération House v1

Design, non implémenté. Versionner schémas et routes ; ne pas modifier rétroactivement les reçus legacy.

## Admission et suivi

Étendre l’admission existante avec une action `generate_house`, paramètres `schema_version=house.v1`, `brief`, `reference_hashes`, `asset_roots`, `style_policy`, `creative_policy`, `player_clearance` et contraintes de périmètre. IDs projet/conversation/message/action, clé d’idempotence et version Unity attendue restent obligatoires. Identité et références contrôlées côté Python ; les racines d’assets sont limitées au projet autorisé.

L’image est facultative. En mode référence, distinguer disposition observée et compléments créatifs ; en mode libre, ne pas demander une image artificiellement. L’action réserve une opération durable, pas le prix d’une maison entière : chaque appel utilise l’admission budgétaire existante.

Routes proposées côté Python :

| Route | Comportement |
|---|---|
| POST `/v1/app/actions` | Admission existante étendue ; 202 avec run et états séparés |
| GET `/v1/app/actions/{id}/house` | Programme, progression par scope, jobs, gates, défauts, coûts et version ; aucun secret/prompt interne |
| POST `/v1/app/actions/{id}/resume` | Reprise idempotente après vérification des versions, reçus et inconnus ; 409 si réconciliation nécessaire |
| POST `/v1/app/actions/{id}/review` | Revue artistique authentifiée et idempotente : gate, critères, version scène, preuves, verdict/commentaire ; 409 si version périmée. Identité du reviewer issue de la session, jamais d’une réponse modèle |
| POST `/v1/app/actions/{id}/stop` | Arrêt existant propagé aux jobs ; reçu de fin des mutations natives |
| GET `/v1/app/actions/{id}/inspection` | Manifeste public versionné des vues, scopes, observations et validité |

Go expose des proxys `/api/actions/{id}/…` après vérification de possession de l’action ; médias accessibles par ID opaque sous authentification locale. Le proxy Go transmet une identité de revue issue de sa session locale ; une proposition de Muse ne peut pas écrire une revue utilisateur. Toute modification du scope invalide la revue correspondante. Les endpoints Go actuels d’inspection restent compatibles pendant transition. Le navigateur n’accède pas aux fichiers arbitraires, au token Python ou au fournisseur.

États renvoyés : `execution_state`, `quality_state`, `current_scope`, `active_job`, `requirements_summary`, `open_defects`, `coverage`, `last_evidence_at`, `budget_state`, `pause_or_stop_reason`. Les événements comportent `event_id` monotone, `run_id`, `job_id`, `scope_id`, `scene_version`, `timestamp`, `kind` et données publiques ; polling avec curseur suffisant au départ, SSE facultatif.

## Opérations natives typées

Enveloppe : `operation_id`, `command_id`, `job_id`, `scope_id`, `schema_version`, `expected_scene_version`, `bridge_epoch`, `input_hash`, `payload`, `idempotency_key`. Une seule mutation à la fois. Reçu : statut, versions avant/après, objets créés/modifiés, preuves, erreurs et rollback.

| Opération | Contraintes principales |
|---|---|
| `inspect_prefab_semantics` | Chargement preview, géométrie native, aucune modification asset source |
| `inspect_reference_house` | Scène isolée, source hash inchangé, provenance et couverture exportées |
| `build_shell` | IR validé, modules complets, frontières/portails partagés, trémies conservées |
| `place_functional_group` | Recette et sémantiques qualifiées, échelles natives, supports et faces corrects |
| `decorate_surfaces` | Surfaces existantes qualifiées, poses relatives, contraintes d’encombrement |
| `apply_house_patch` | Opérations fermées move/rotate/replace/add/remove/assign_material/set_light ; supprimables uniquement objets possédés par le run ; pas de C# arbitraire |
| `validate_house_geometry` | Géométries/contacts/portails/chemins/capsule/escaliers, résultat par gate et scope |
| `capture_house_inspection` | Position caméra validée, protocole et version figés, vues utiles ou raison de rejet |
| `apply_lighting_design` | Profils/overrides propres au run, sources bornées, bake séparé avec reçu |
| `restore_house_checkpoint` | Dépendances et version vérifiées ; travail utilisateur non écrasé |

Le `player_clearance` décrit capsule, largeur/hauteur libres, marche maximale, pente maximale et exigence d’appui continu. Une traversée d’escalier vérifie ces paramètres sur la géométrie résolue, sans supposer que le NavMesh ou les colliders du pack suffisent.

Une réparation de boundary/portal/stair transporte une révision du BuildingIR, ses préconditions et les modules à recompiler. Commit du checkpoint uniquement après validation conjointe IR/scène/reçu ; invalider groupes, parcours et bake affectés. Aucune mutation de mur isolée ne peut contourner cette transaction.

## Préconditions et erreurs

Avant chaque patch : vérifier catalogue, objets autorisés, version, dépendances et hash du plan. Rejeter explicitement `STALE_VERSION`, `SEMANTICS_UNQUALIFIED`, `REQUIREMENT_UNAVAILABLE`, `PORTAL_BLOCKED`, `STAIR_DISCONNECTED`, `SUPPORT_INVALID`, `CAPTURE_UNUSABLE`, `QUALITY_REGRESSION` ou `BUDGET_UNAVAILABLE`. Une erreur de qualité ouvre un défaut et peut générer un nouveau job ; elle n’est pas une erreur réseau à retenter aveuglément.

Une annulation attend la confirmation native ou reste `stopping`. Un patch partiellement exécuté sans reçu vérifiable impose une réconciliation. Toutes les instances renvoyées gardent leur connexion prefab et leur GUID source.

## Contrats modèle et transport

Réponses distinctes : `HouseProgramProposal`, `RoomProgramProposal`, `FunctionalGroupProposal`, `SurfaceDecorationProposal`, `HouseRepairProposal`, `LightingProposal`. Chaque réponse cible un scope et cite des IDs existants ; les ajouts demandent des IDs nouveaux et une provenance. Validation syntaxique puis sémantique puis native.

Chaque lot porte `batch_id`, `scope_id`, `input_requirements`, `resolved_requirements`, `unresolved_requirements`, `continuation`. Vérifier que l’union résolue/non résolue couvre le lot ; absence de champ ou sortie tronquée n’équivaut pas à « rien à ajouter ». Les limites fournisseur restent par appel ; l’orchestrateur conserve le reste de l’inventaire.
