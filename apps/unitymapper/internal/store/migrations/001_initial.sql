CREATE TABLE projects (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, canonical_root TEXT NOT NULL UNIQUE,
 backend_project_id TEXT NOT NULL UNIQUE, capabilities TEXT NOT NULL DEFAULT '[]', last_seen_at TEXT NOT NULL
);
CREATE TABLE conversations (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), title TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', summary_revision INTEGER NOT NULL DEFAULT 0,
 UNIQUE(id,project_id)
);
CREATE TABLE messages (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, project_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('user','assistant','tool')), text TEXT NOT NULL CHECK(length(text)<=32000),
 status TEXT NOT NULL CHECK(status IN ('persisted','generating','complete','failed','unknown')),
 turn_id TEXT, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(conversation_id,project_id) REFERENCES conversations(id,project_id),
 UNIQUE(conversation_id,idempotency_key), UNIQUE(id,project_id)
);
CREATE TABLE attachments (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 mime TEXT NOT NULL, byte_length INTEGER NOT NULL CHECK(byte_length>0 AND byte_length<=20971520), original_name TEXT NOT NULL,
 backend_artifact_hash TEXT, UNIQUE(id,project_id), UNIQUE(project_id,sha256)
);
CREATE TABLE message_attachments (
 message_id TEXT NOT NULL, attachment_id TEXT NOT NULL, project_id TEXT NOT NULL,
 PRIMARY KEY(message_id,attachment_id),
 FOREIGN KEY(message_id,project_id) REFERENCES messages(id,project_id),
 FOREIGN KEY(attachment_id,project_id) REFERENCES attachments(id,project_id)
);
CREATE TABLE actions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('inspect_scene','reconstruct_reference','refine_reference','learn_assembly_example','inspect_room','stop_run')),
 args TEXT NOT NULL, expected_scene_version TEXT, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
 backend_operation_id TEXT, backend_run_id TEXT, state TEXT NOT NULL CHECK(state IN ('queued','preparing','running','verifying','completed','inconclusive','failed','interrupted','recovery_required')),
 result TEXT, stop_requested INTEGER NOT NULL DEFAULT 0 CHECK(stop_requested IN (0,1)),
 FOREIGN KEY(conversation_id,project_id) REFERENCES conversations(id,project_id),
 FOREIGN KEY(message_id,project_id) REFERENCES messages(id,project_id), UNIQUE(project_id,idempotency_key)
);
CREATE TABLE events (
 conversation_id TEXT NOT NULL REFERENCES conversations(id), sequence INTEGER NOT NULL,
 kind TEXT NOT NULL, entity_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(conversation_id,sequence)
);
CREATE TABLE outbox (
 action_id TEXT PRIMARY KEY REFERENCES actions(id), destination TEXT NOT NULL,
 dispatch_state TEXT NOT NULL CHECK(dispatch_state IN ('pending','sending','acknowledged','unknown')),
 first_sent_at TEXT, remote_id TEXT
);
CREATE INDEX actions_state ON actions(state);
