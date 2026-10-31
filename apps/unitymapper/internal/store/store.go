package store

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	_ "modernc.org/sqlite"
	"net/url"
	"os"
	"path/filepath"
	"time"
)

//go:embed migrations/*.sql
var migrations embed.FS
var ErrConflict = errors.New("idempotency key reused with different payload")
var ErrOwnership = errors.New("entity not owned by this project and conversation")

type Store struct{ db *sql.DB }

func Open(path string) (*Store, error) {
	if info, err := os.Lstat(path); err == nil && info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("chat database cannot be a symlink")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	f.Close()
	u := url.URL{Scheme: "file", Path: path}
	q := u.Query()
	q.Add("_pragma", "foreign_keys(1)")
	q.Add("_pragma", "busy_timeout(5000)")
	q.Add("_pragma", "journal_mode(WAL)")
	u.RawQuery = q.Encode()
	db, err := sql.Open("sqlite", u.String())
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	s := &Store{db}
	if err = s.migrate(); err != nil {
		db.Close()
		return nil, err
	}
	return s, nil
}
func (s *Store) Close() error { return s.db.Close() }
func (s *Store) migrate() error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.Exec("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY)"); err != nil {
		return err
	}
	entries, err := migrations.ReadDir("migrations")
	if err != nil {
		return err
	}
	for _, entry := range entries {
		var n int
		if err = tx.QueryRow("SELECT count(*) FROM schema_migrations WHERE version=?", entry.Name()).Scan(&n); err != nil {
			return err
		}
		if n > 0 {
			continue
		}
		raw, e := migrations.ReadFile("migrations/" + entry.Name())
		if e != nil {
			return e
		}
		if _, err = tx.Exec(string(raw)); err != nil {
			return err
		}
		if _, err = tx.Exec("INSERT INTO schema_migrations VALUES(?)", entry.Name()); err != nil {
			return err
		}
	}
	return tx.Commit()
}
func now() string { return time.Now().UTC().Format(time.RFC3339Nano) }
func hash(v any) (string, error) {
	b, e := json.Marshal(v)
	if e != nil {
		return "", e
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}
func (s *Store) LinkProject(ctx context.Context, id, label, root, backend string) error {
	// Relinking the identity to a different directory is never an upsert.
	_, err := s.db.ExecContext(ctx, `INSERT INTO projects(id,label,canonical_root,backend_project_id,last_seen_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,last_seen_at=excluded.last_seen_at WHERE projects.canonical_root=excluded.canonical_root AND projects.backend_project_id=excluded.backend_project_id`, id, label, root, backend, now())
	if err != nil {
		return err
	}
	var r, b string
	if err = s.db.QueryRowContext(ctx, "SELECT canonical_root,backend_project_id FROM projects WHERE id=?", id).Scan(&r, &b); err != nil {
		return err
	}
	if r != root || b != backend {
		return ErrConflict
	}
	return nil
}
func (s *Store) CreateConversation(ctx context.Context, id, project, title string) error {
	_, e := s.db.ExecContext(ctx, "INSERT INTO conversations(id,project_id,title,created_at,updated_at) VALUES(?,?,?,?,?)", id, project, title, now(), now())
	return e
}
func event(tx *sql.Tx, conversation, kind, id string, payload any) error {
	raw, e := json.Marshal(payload)
	if e != nil {
		return e
	}
	_, e = tx.Exec(`INSERT INTO events(conversation_id,sequence,kind,entity_id,payload,created_at) SELECT ?,COALESCE(MAX(sequence),0)+1,?,?,?,? FROM events WHERE conversation_id=?`, conversation, kind, id, string(raw), now(), conversation)
	return e
}

type Message struct {
	ID, ConversationID, ProjectID, Role, Text, Status, TurnID, IdempotencyKey string
	AttachmentIDs                                                             []string
}

func (s *Store) SaveMessage(ctx context.Context, m Message) (string, error) {
	h, e := hash(struct {
		Project, Role, Text string
		Attachments         []string
	}{m.ProjectID, m.Role, m.Text, m.AttachmentIDs})
	if e != nil {
		return "", e
	}
	tx, e := s.db.BeginTx(ctx, nil)
	if e != nil {
		return "", e
	}
	defer tx.Rollback()
	var id, prior string
	e = tx.QueryRow("SELECT id,payload_hash FROM messages WHERE conversation_id=? AND idempotency_key=?", m.ConversationID, m.IdempotencyKey).Scan(&id, &prior)
	if e == nil {
		if prior != h {
			return "", ErrConflict
		}
		return id, nil
	}
	if !errors.Is(e, sql.ErrNoRows) {
		return "", e
	}
	_, e = tx.Exec(`INSERT INTO messages(id,conversation_id,project_id,role,text,status,turn_id,idempotency_key,payload_hash,created_at) VALUES(?,?,?,?,?,'persisted',?,?,?,?)`, m.ID, m.ConversationID, m.ProjectID, m.Role, m.Text, m.TurnID, m.IdempotencyKey, h, now())
	if e != nil {
		return "", e
	}
	for _, a := range m.AttachmentIDs {
		if _, e = tx.Exec("INSERT INTO message_attachments VALUES(?,?,?)", m.ID, a, m.ProjectID); e != nil {
			return "", e
		}
	}
	if e = event(tx, m.ConversationID, "message.persisted", m.ID, map[string]string{"message_id": m.ID}); e != nil {
		return "", e
	}
	_, e = tx.Exec("UPDATE conversations SET updated_at=? WHERE id=?", now(), m.ConversationID)
	if e != nil {
		return "", e
	}
	return m.ID, tx.Commit()
}

type Action struct {
	ID, ProjectID, ConversationID, MessageID, Kind, ExpectedSceneVersion, IdempotencyKey string
	Args                                                                                 json.RawMessage
}

func (s *Store) QueueAction(ctx context.Context, a Action) (string, error) {
	if !json.Valid(a.Args) {
		return "", errors.New("invalid action arguments")
	}
	// Local IDs do not participate in semantic identity.
	h, e := hash(struct {
		Project, Conversation, Message, Kind, Version string
		Args                                          json.RawMessage
	}{a.ProjectID, a.ConversationID, a.MessageID, a.Kind, a.ExpectedSceneVersion, a.Args})
	if e != nil {
		return "", e
	}
	tx, e := s.db.BeginTx(ctx, nil)
	if e != nil {
		return "", e
	}
	defer tx.Rollback()
	var id, prior string
	e = tx.QueryRow("SELECT id,payload_hash FROM actions WHERE project_id=? AND idempotency_key=?", a.ProjectID, a.IdempotencyKey).Scan(&id, &prior)
	if e == nil {
		if h != prior {
			return "", ErrConflict
		}
		return id, nil
	}
	if !errors.Is(e, sql.ErrNoRows) {
		return "", e
	}
	var owner string
	if e = tx.QueryRow("SELECT conversation_id FROM messages WHERE id=? AND project_id=?", a.MessageID, a.ProjectID).Scan(&owner); e != nil || owner != a.ConversationID {
		return "", ErrOwnership
	}
	_, e = tx.Exec(`INSERT INTO actions(id,project_id,conversation_id,message_id,kind,args,expected_scene_version,idempotency_key,payload_hash,state) VALUES(?,?,?,?,?,?,?,?,?,'queued')`, a.ID, a.ProjectID, a.ConversationID, a.MessageID, a.Kind, string(a.Args), a.ExpectedSceneVersion, a.IdempotencyKey, h)
	if e != nil {
		return "", e
	}
	if _, e = tx.Exec("INSERT INTO outbox(action_id,destination,dispatch_state) VALUES(?,'python','pending')", a.ID); e != nil {
		return "", e
	}
	if e = event(tx, a.ConversationID, "action.queued", a.ID, map[string]string{"action_id": a.ID}); e != nil {
		return "", e
	}
	return a.ID, tx.Commit()
}

// ClaimDispatch is committed BEFORE I/O. A crash afterwards requires reconciliation, never replay.
func (s *Store) ClaimDispatch(ctx context.Context, id string) (bool, error) {
	r, e := s.db.ExecContext(ctx, "UPDATE outbox SET dispatch_state='sending',first_sent_at=? WHERE action_id=? AND dispatch_state='pending'", now(), id)
	if e != nil {
		return false, e
	}
	n, e := r.RowsAffected()
	return n == 1, e
}
func (s *Store) RecoverUncertain(ctx context.Context) error {
	tx, e := s.db.BeginTx(ctx, nil)
	if e != nil {
		return e
	}
	defer tx.Rollback()
	if _, e = tx.Exec("UPDATE outbox SET dispatch_state='unknown' WHERE dispatch_state='sending'"); e != nil {
		return e
	}
	if _, e = tx.Exec("UPDATE actions SET state='recovery_required' WHERE id IN (SELECT action_id FROM outbox WHERE dispatch_state='unknown') AND state NOT IN ('completed','failed','interrupted','inconclusive')"); e != nil {
		return e
	}
	if _, e = tx.Exec("UPDATE messages SET status='unknown' WHERE status='generating'"); e != nil {
		return e
	}
	return tx.Commit()
}

type Event struct {
	Sequence  int64           `json:"sequence"`
	Kind      string          `json:"kind"`
	EntityID  string          `json:"entity_id"`
	Payload   json.RawMessage `json:"payload"`
	CreatedAt string          `json:"created_at"`
}

func (s *Store) Events(ctx context.Context, project, conversation string, after int64) ([]Event, error) {
	var owner string
	if e := s.db.QueryRowContext(ctx, "SELECT project_id FROM conversations WHERE id=?", conversation).Scan(&owner); e != nil || owner != project {
		return nil, ErrOwnership
	}
	rows, e := s.db.QueryContext(ctx, "SELECT sequence,kind,entity_id,payload,created_at FROM events WHERE conversation_id=? AND sequence>? ORDER BY sequence LIMIT 200", conversation, after)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	result := []Event{}
	for rows.Next() {
		var v Event
		var payload string
		if e = rows.Scan(&v.Sequence, &v.Kind, &v.EntityID, &payload, &v.CreatedAt); e != nil {
			return nil, e
		}
		v.Payload = json.RawMessage(payload)
		result = append(result, v)
	}
	return result, rows.Err()
}
