# Données du chat projet

Base Go séparée : `.hdrp-agent/chat/chat.sqlite3`. Migrations versionnées ; clés étrangères actives ; écritures transactionnelles ; un serveur Go propriétaire du workspace.

| Entité | Champs et relations | Invariants |
|---|---|---|
| Project | id, label, canonical_root, backend_project_id, capabilities, last_seen_at | racine sous workspace autorisé ; identité Python vérifiée ; un changement de projet n’emporte pas les messages |
| Conversation | id, project_id, title, created_at, updated_at, summary, summary_revision | FK projet ; résumé ne remplace jamais les messages ou reçus |
| Message | id, conversation_id, role, text, status, turn_id, created_at | roles user/assistant/tool ; texte borné ; texte non fiable rendu sans HTML actif |
| Attachment | id, project_id, sha256, mime, byte_length, original_name, backend_artifact_hash | contenu immuable ; image PNG/JPEG <=10 MiB, vidéo MP4/MOV/WebM <=20 MiB ; pas de chemin du client accepté |
| MessageAttachment | message_id, attachment_id | même projet ; relation durable avant envoi modèle |
| Action | id, project_id, conversation_id, message_id, kind, args, expected_scene_version, idempotency_key, payload_hash, backend_operation_id, backend_run_id, state, result | même clé + même payload = même action ; payload différent =409 ; le run backend est autorité d’exécution |
| Event | conversation_id, sequence, kind, entity_id, payload, created_at | séquence monotone durable ; relecture SSE après curseur ; unique(conversation_id,sequence) |
| Outbox | action_id, destination, dispatch_state, first_sent_at, remote_id | intention sauvegardée avant envoi ; issue ambiguë réconciliée par identité avant tout nouvel envoi |

Budget : données en lecture depuis Python (micro-USD). Aucune table Go n’a autorité sur le solde ou les réservations. Les hashes de scènes, captures et masques restent dans les artefacts backend et sont référencés, pas copiés comme de nouvelles preuves.

États message : `persisted → generating → complete | failed | unknown`. États action : `queued → preparing → running → verifying → completed | inconclusive | failed | interrupted | recovery_required`. `stop_requested` est un attribut persistant jusqu’au reçu d’arrêt ; il n’est pas équivalent à `interrupted`. Une coupure UI ne change pas l’action. Après redémarrage Go, les actions non terminales sont relues chez Python ; aucune construction n’est rejouée automatiquement.

Admission Python : operation_id et session_id sont créés une fois ; le pont prépare le bundle avec cette même identité, puis le worker adopte la session. Unicité sur l’action/idempotency_key ; conflit de scène/version avant toute mutation. Le statut de préparation et la réponse perdue sont durables. Le projet et l’epoch reçus de Unity doivent correspondre à l’action.
