# Contrat d’actions Go → Python → Unity (conception v1)

Le contrat Go public est [chat-api.openapi.json](chat-api.openapi.json). Les routes ci-dessous sont des ajouts prévus, pas des capacités déjà exposées par le serveur.

## Enveloppe fermée

`schema_version`, `action_id`, `project_id`, `conversation_id`, `message_id`, `kind`, `expected_scene_version`, `artifact_hashes`, `parameters`, `idempotency_key`. Python valide les champs, la racine projet, les hashes appartenant au projet, l’epoch/connexion et la capacité avant de réserver une exécution. Aucun argument `code`, `script`, `shell`, URL distante arbitraire ou chemin absolu modèle.

| Kind | Paramètres spécifiques | Résultat minimum |
|---|---|---|
| inspect_scene | brief, inspection_policy_id | run_id, version, captures, observations, limits |
| reconstruct_reference | brief, reference_hashes, building_policy, interior_style, ceiling_prefab | run_id, retained_scene_id, version, receipts, limits |
| refine_reference | brief, parent_run_id | nouveau run lié au parent, candidat retenu, preuves et régressions |
| learn_assembly_example | registered_scene_id | profil, hash de scène, relations constatées ; source inchangée |
| inspect_room | mode=panorama/detail, poses bornées facultatives | captures natives/version, audit et masques ; pas de preuve de performance |
| stop_run | run_id | arrêt demandé puis état réellement observé ; réservations inconnues maintenues |

`building_policy` désigne une politique enregistrée ; `interior_style` dans A/B/C, défaut B pour la démo ; `ceiling_prefab` est un ID du catalogue résolu vers Ceiling_3x3. Les pièces jointes ont été importées avant admission. Une action ne s’invente pas de fichier local depuis une chaîne utilisateur.

## API interne à ajouter

- `GET /v1/projects` : projets enregistrés, connexion/epoch, scène et capacités vérifiées.
- `POST /v1/chat/turns` : contexte borné, conversation/project/turn IDs, attachements par hash ; réponse Muse structurée, appels et coûts sous grand livre existant. Clé idempotente obligatoire ; réponse terminale persistée ou unknown.
- `POST /v1/app/actions` : admission durable d’une action fermée, retourne operation_id/run_id si disponible ; 202 ne signifie pas terminé.
- `GET /v1/app/actions/{action_id}` : état autoritaire et preuves ; 404 distingué de résultat inconnu.
- `GET /v1/app/events?after=...&project_id=...` : événements durables filtrés avec curseur.
- `POST /v1/app/actions/{action_id}/stop` : demande d’arrêt idempotente.

Go utilise exclusivement ces routes et les routes budget/artifacts existantes, avec le bearer local sans Origin navigateur. Le modèle propose les outils ; le contrôleur valide et exécute. Une réponse de texte seul reste une réponse de discussion et ne démarre rien.

## Protocole de préparation Unity

Une commande `prepare_reference_run` typée dans le pont existant contient operation_id/session_id, projet/epoch/version attendus, références déjà matérialisées dans le dossier propriétaire, brief et politique. Le pont vérifie possession/idle, préserve la scène puis prépare catalogue/bundle via un point d’entrée public borné de ReferenceWorkflow. Le reçu contient mêmes identités, bundle_hash et répertoire propriétaire. Le worker adopte la session réservée ; aucune seconde session active n’est créée.

Une version modifiée, opération concurrente, import invalide ou absence d’éditeur refuse avant mutation. Si la commande a été envoyée mais son résultat est perdu, le contrôleur consulte son journal/receipt ; pas de replay aveugle. Les chemins sont dérivés du workspace configuré, jamais du seul nombre de parents de Assets.

## Événements et limites

Kinds : message.persisted, assistant.started, assistant.completed, action.queued, action.started, action.progress, evidence.available, action.stop_requested, action.completed, action.failed, action.recovery_required, budget.updated. Chaque événement porte project_id, conversation_id, sequence, entity_id et timestamp. Les événements de contrôle sont issus du backend, pas du texte libre du modèle. Les tokens fournisseur ne sont pas streamés dans cette version : SSE livre la progression réelle puis la réponse complète.

Erreurs typées : invalid_input, project_mismatch, stale_version, editor_unavailable, busy, budget_exhausted, provider_unknown, recovery_required. L’interface les traduit sans inventer une réussite. Un second projet peut attendre ; il ne vole jamais l’éditeur au premier.
