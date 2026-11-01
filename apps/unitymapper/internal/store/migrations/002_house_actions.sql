-- Rebuild the constrained action table and preserve its dependent outbox atomically.
CREATE TABLE actions_house (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('inspect_scene','reconstruct_reference','refine_reference','learn_assembly_example','inspect_room','stop_run','generate_house')),
 args TEXT NOT NULL, expected_scene_version TEXT, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
 backend_operation_id TEXT, backend_run_id TEXT, state TEXT NOT NULL CHECK(state IN ('queued','preparing','running','verifying','completed','inconclusive','failed','interrupted','recovery_required')),
 result TEXT, stop_requested INTEGER NOT NULL DEFAULT 0 CHECK(stop_requested IN (0,1)),
 FOREIGN KEY(conversation_id,project_id) REFERENCES conversations(id,project_id),
 FOREIGN KEY(message_id,project_id) REFERENCES messages(id,project_id), UNIQUE(project_id,idempotency_key)
);
INSERT INTO actions_house SELECT * FROM actions;
CREATE TEMP TABLE house_outbox_backup AS SELECT * FROM outbox;
DROP TABLE outbox;
DROP TABLE actions;
ALTER TABLE actions_house RENAME TO actions;
CREATE TABLE outbox (
 action_id TEXT PRIMARY KEY REFERENCES actions(id), destination TEXT NOT NULL,
 dispatch_state TEXT NOT NULL CHECK(dispatch_state IN ('pending','sending','acknowledged','unknown')),
 first_sent_at TEXT, remote_id TEXT
);
INSERT INTO outbox SELECT * FROM house_outbox_backup;
DROP TABLE house_outbox_backup;
CREATE INDEX actions_state ON actions(state);
