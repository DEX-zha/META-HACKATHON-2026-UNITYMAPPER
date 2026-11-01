package store

import (
	"context"
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"testing"
)

func fixture(t *testing.T) (*Store, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "chat.sqlite3")
	s, e := Open(path)
	if e != nil {
		t.Fatal(e)
	}
	ctx := context.Background()
	for _, p := range []string{"p1", "p2"} {
		if e = s.LinkProject(ctx, p, p, "/"+p, p); e != nil {
			t.Fatal(e)
		}
		if e = s.CreateConversation(ctx, "c"+p, p, "test"); e != nil {
			t.Fatal(e)
		}
	}
	return s, path
}
func TestDurableDispatchAndIdempotence(t *testing.T) {
	s, path := fixture(t)
	ctx := context.Background()
	m := Message{ID: "m1", ConversationID: "cp1", ProjectID: "p1", Role: "user", Text: "inspect", IdempotencyKey: "mk"}
	if _, e := s.SaveMessage(ctx, m); e != nil {
		t.Fatal(e)
	}
	m.ID = "other"
	if id, e := s.SaveMessage(ctx, m); e != nil || id != "m1" {
		t.Fatal(id, e)
	}
	m.Text = "changed"
	if _, e := s.SaveMessage(ctx, m); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	a := Action{ID: "a1", ProjectID: "p1", ConversationID: "cp1", MessageID: "m1", Kind: "inspect_room", Args: json.RawMessage(`{"mode":"panorama"}`), IdempotencyKey: "ak"}
	if _, e := s.QueueAction(ctx, a); e != nil {
		t.Fatal(e)
	}
	if ok, e := s.ClaimDispatch(ctx, "a1"); e != nil || !ok {
		t.Fatal(ok, e)
	}
	s.Close()
	s, e := Open(path)
	if e != nil {
		t.Fatal(e)
	}
	defer s.Close()
	if e = s.RecoverUncertain(ctx); e != nil {
		t.Fatal(e)
	}
	if ok, e := s.ClaimDispatch(ctx, "a1"); e != nil || ok {
		t.Fatal("ambiguous mutation replayed", ok, e)
	}
	var state string
	if e = s.db.QueryRow("SELECT state FROM actions WHERE id='a1'").Scan(&state); e != nil || state != "recovery_required" {
		t.Fatal(state, e)
	}
	events, e := s.Events(ctx, "p1", "cp1", 0)
	if e != nil || len(events) != 2 || events[0].Sequence != 1 || events[1].Sequence != 2 {
		t.Fatal(events, e)
	}
	events, e = s.Events(ctx, "p1", "cp1", 1)
	if e != nil || len(events) != 1 {
		t.Fatal(events, e)
	}
	if _, e = s.Events(ctx, "p2", "cp1", 0); !errors.Is(e, ErrOwnership) {
		t.Fatal(e)
	}
}
func TestCrossProjectAttachmentRollback(t *testing.T) {
	s, _ := fixture(t)
	defer s.Close()
	ctx := context.Background()
	_, e := s.db.Exec("INSERT INTO attachments VALUES('file','p2',?,'image/png',10,'x.png',NULL)", strings.Repeat("a", 64))
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.SaveMessage(ctx, Message{ID: "m", ProjectID: "p1", ConversationID: "cp1", Role: "user", Text: "x", IdempotencyKey: "k", AttachmentIDs: []string{"file"}})
	if e == nil {
		t.Fatal("cross-project attachment accepted")
	}
	var count int
	s.db.QueryRow("SELECT count(*) FROM messages").Scan(&count)
	if count != 0 {
		t.Fatal("partial message committed")
	}
	events, e := s.Events(ctx, "p1", "cp1", 0)
	if e != nil || len(events) != 0 {
		t.Fatal(events, e)
	}
}

func TestActionConflictDoesNotEnqueueTwice(t *testing.T) {
	s, _ := fixture(t)
	defer s.Close()
	ctx := context.Background()
	_, e := s.SaveMessage(ctx, Message{ID: "m", ProjectID: "p1", ConversationID: "cp1", Role: "user", Text: "inspect", IdempotencyKey: "m"})
	if e != nil {
		t.Fatal(e)
	}
	a := Action{ID: "a", ProjectID: "p1", ConversationID: "cp1", MessageID: "m", Kind: "inspect_room", Args: json.RawMessage(`{"mode":"panorama"}`), IdempotencyKey: "k"}
	if _, e = s.QueueAction(ctx, a); e != nil {
		t.Fatal(e)
	}
	a.ID = "b"
	if id, e := s.QueueAction(ctx, a); e != nil || id != "a" {
		t.Fatal(id, e)
	}
	a.Args = json.RawMessage(`{"mode":"detail"}`)
	if _, e = s.QueueAction(ctx, a); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	var n int
	if e = s.db.QueryRow("SELECT count(*) FROM outbox").Scan(&n); e != nil || n != 1 {
		t.Fatal(n, e)
	}
}

func TestHouseActionDispatchIsDurable(t *testing.T) {
	s, path := fixture(t)
	ctx := context.Background()
	_, err := s.SaveMessage(ctx, Message{ID: "house-message", ConversationID: "cp1", ProjectID: "p1", Role: "user", Text: "Create house", IdempotencyKey: "house-message"})
	if err != nil {
		t.Fatal(err)
	}
	action := Action{ID: "house-action", ProjectID: "p1", ConversationID: "cp1", MessageID: "house-message", Kind: "generate_house", Args: json.RawMessage(`{"schema_version":"house.v1"}`), IdempotencyKey: "house-action"}
	if _, err = s.QueueAction(ctx, action); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s, err = Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if ok, err := s.ClaimDispatch(ctx, action.ID); err != nil || !ok {
		t.Fatal(ok, err)
	}
}
