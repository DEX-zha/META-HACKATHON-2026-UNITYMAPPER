package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
)

type Conversation struct {
	ID        string `json:"id"`
	ProjectID string `json:"project_id"`
	Title     string `json:"title"`
	Summary   string `json:"summary"`
	Revision  int    `json:"summary_revision"`
}
type ChatMessage struct {
	ID          string   `json:"id"`
	Role        string   `json:"role"`
	Text        string   `json:"text"`
	Status      string   `json:"status"`
	TurnID      string   `json:"turn_id"`
	Attachments []string `json:"attachment_ids"`
}
type Attachment struct {
	ID    string `json:"id"`
	Hash  string `json:"sha256"`
	Mime  string `json:"mime"`
	Name  string `json:"name"`
	Bytes int64  `json:"bytes"`
}

func (s *Store) Conversations(ctx context.Context, project string) ([]Conversation, error) {
	rows, e := s.db.QueryContext(ctx, "SELECT id,project_id,title,summary,summary_revision FROM conversations WHERE project_id=? ORDER BY updated_at DESC LIMIT 100", project)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Conversation{}
	for rows.Next() {
		var c Conversation
		if e = rows.Scan(&c.ID, &c.ProjectID, &c.Title, &c.Summary, &c.Revision); e != nil {
			return nil, e
		}
		out = append(out, c)
	}
	return out, rows.Err()
}
func (s *Store) Conversation(ctx context.Context, id string) (Conversation, error) {
	var c Conversation
	e := s.db.QueryRowContext(ctx, "SELECT id,project_id,title,summary,summary_revision FROM conversations WHERE id=?", id).Scan(&c.ID, &c.ProjectID, &c.Title, &c.Summary, &c.Revision)
	return c, e
}
func (s *Store) Messages(ctx context.Context, conversation string) ([]ChatMessage, error) {
	rows, e := s.db.QueryContext(ctx, "SELECT id,role,text,status,COALESCE(turn_id,'') FROM messages WHERE conversation_id=? ORDER BY rowid DESC LIMIT 100", conversation)
	if e != nil {
		return nil, e
	}
	out := []ChatMessage{}
	for rows.Next() {
		var m ChatMessage
		m.Attachments = []string{}
		if e = rows.Scan(&m.ID, &m.Role, &m.Text, &m.Status, &m.TurnID); e != nil {
			rows.Close()
			return nil, e
		}
		out = append(out, m)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return nil, e
	}
	for i := range out {
		rs, e := s.db.QueryContext(ctx, "SELECT attachment_id FROM message_attachments WHERE message_id=? ORDER BY attachment_id", out[i].ID)
		if e != nil {
			return nil, e
		}
		for rs.Next() {
			var a string
			if e = rs.Scan(&a); e != nil {
				rs.Close()
				return nil, e
			}
			out[i].Attachments = append(out[i].Attachments, a)
		}
		rs.Close()
	}
	for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
		out[i], out[j] = out[j], out[i]
	}
	return out, nil
}
func (s *Store) Attachment(ctx context.Context, project, id string) (Attachment, error) {
	var a Attachment
	e := s.db.QueryRowContext(ctx, "SELECT id,sha256,mime,original_name,byte_length FROM attachments WHERE project_id=? AND id=?", project, id).Scan(&a.ID, &a.Hash, &a.Mime, &a.Name, &a.Bytes)
	return a, e
}
func (s *Store) AddAttachment(ctx context.Context, project string, a Attachment) (Attachment, error) {
	_, e := s.db.ExecContext(ctx, "INSERT INTO attachments(id,project_id,sha256,mime,byte_length,original_name,backend_artifact_hash) VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id,sha256) DO NOTHING", a.ID, project, a.Hash, a.Mime, a.Bytes, a.Name, a.Hash)
	if e != nil {
		return a, e
	}
	e = s.db.QueryRowContext(ctx, "SELECT id FROM attachments WHERE project_id=? AND sha256=?", project, a.Hash).Scan(&a.ID)
	return a, e
}
func (s *Store) ClaimMessage(ctx context.Context, id string) (bool, error) {
	r, e := s.db.ExecContext(ctx, "UPDATE messages SET status='generating' WHERE id=? AND status='persisted' AND NOT EXISTS(SELECT 1 FROM messages AS other WHERE other.conversation_id=messages.conversation_id AND other.status='generating')", id)
	if e != nil {
		return false, e
	}
	n, e := r.RowsAffected()
	return n == 1, e
}
func (s *Store) MessageStatus(ctx context.Context, id, status string) error {
	if status != "failed" && status != "unknown" {
		return errors.New("invalid failure state")
	}
	_, e := s.db.ExecContext(ctx, "UPDATE messages SET status=? WHERE id=? AND status!='complete'", status, id)
	return e
}
func (s *Store) CompleteTurn(ctx context.Context, userID, text string) error {
	tx, e := s.db.BeginTx(ctx, nil)
	if e != nil {
		return e
	}
	defer tx.Rollback()
	var conversation, project, turn, state string
	e = tx.QueryRow("SELECT conversation_id,project_id,turn_id,status FROM messages WHERE id=? AND role='user'", userID).Scan(&conversation, &project, &turn, &state)
	if e != nil {
		return e
	}
	if state == "complete" {
		return nil
	}
	digest, e := hash(text)
	if e != nil {
		return e
	}
	_, e = tx.Exec("INSERT INTO messages(id,conversation_id,project_id,role,text,status,turn_id,idempotency_key,payload_hash,created_at) VALUES(?,?,?,'assistant',?,'complete',?,?,?,?)", userID+"-answer", conversation, project, text, turn, userID+"-answer", digest, now())
	if e != nil {
		return e
	}
	if _, e = tx.Exec("UPDATE messages SET status='complete' WHERE id=?", userID); e != nil {
		return e
	}
	if e = event(tx, conversation, "assistant.completed", userID+"-answer", map[string]string{"message_id": userID + "-answer"}); e != nil {
		return e
	}
	return tx.Commit()
}
func (s *Store) RecordAction(ctx context.Context, id, state string, result json.RawMessage, unknown bool) error {
	if !json.Valid(result) {
		result = json.RawMessage(`{}`)
	}
	switch state {
	case "queued", "preparing", "running", "verifying", "completed", "inconclusive", "failed", "interrupted", "recovery_required":
	default:
		return errors.New("invalid state")
	}
	tx, e := s.db.BeginTx(ctx, nil)
	if e != nil {
		return e
	}
	defer tx.Rollback()
	var conversation string
	if e = tx.QueryRow("SELECT conversation_id FROM actions WHERE id=?", id).Scan(&conversation); e != nil {
		return e
	}
	_, e = tx.Exec("UPDATE actions SET state=?,result=? WHERE id=?", state, string(result), id)
	if e != nil {
		return e
	}
	dispatch := "acknowledged"
	if unknown {
		dispatch = "unknown"
	}
	if _, e = tx.Exec("UPDATE outbox SET dispatch_state=? WHERE action_id=?", dispatch, id); e != nil {
		return e
	}
	if e = event(tx, conversation, "action.progress", id, json.RawMessage(result)); e != nil {
		return e
	}
	return tx.Commit()
}

type ActionView struct {
	ID     string          `json:"id"`
	Kind   string          `json:"kind"`
	State  string          `json:"state"`
	Result json.RawMessage `json:"result"`
}

func (s *Store) Actions(ctx context.Context, conversation string) ([]ActionView, error) {
	rows, e := s.db.QueryContext(ctx, "SELECT id,kind,state,COALESCE(result,'{}') FROM actions WHERE conversation_id=? ORDER BY rowid", conversation)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []ActionView{}
	for rows.Next() {
		var a ActionView
		var raw string
		if e = rows.Scan(&a.ID, &a.Kind, &a.State, &raw); e != nil {
			return nil, e
		}
		a.Result = json.RawMessage(raw)
		out = append(out, a)
	}
	return out, rows.Err()
}
func IsMissing(e error) bool { return errors.Is(e, sql.ErrNoRows) }

func (s *Store) MessageForKey(ctx context.Context, conversation, key string) (string, error) {
	var id string
	e := s.db.QueryRowContext(ctx, "SELECT id FROM messages WHERE conversation_id=? AND idempotency_key=?", conversation, key).Scan(&id)
	return id, e
}

func (s *Store) ActionConversation(ctx context.Context, id string) (string, error) {
	var c string
	e := s.db.QueryRowContext(ctx, "SELECT conversation_id FROM actions WHERE id=?", id).Scan(&c)
	return c, e
}
