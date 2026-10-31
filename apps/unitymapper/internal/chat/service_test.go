package chat

import (
	"context"
	"encoding/json"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/agentclient"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/config"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/store"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

func TestConversationDispatchPersistenceAndAction(t *testing.T) {
	root := t.TempDir()
	project := filepath.Join(root, "project")
	for _, dir := range []string{"Assets", "ProjectSettings", "Packages"} {
		os.MkdirAll(filepath.Join(project, dir), 0700)
	}
	var turns, actions atomic.Int32
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/v1/projects":
			json.NewEncoder(w).Encode([]Project{{ID: "p", Label: "Project", Root: project, Version: "v", Capabilities: []string{"prepare_reference_run"}}})
		case "/v1/chat/turns":
			turns.Add(1)
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			time.Sleep(40 * time.Millisecond)
			json.NewEncoder(w).Encode(map[string]any{"turn_id": body["turn_id"], "project_id": "p", "conversation_id": "c", "message_id": "m", "state": "complete", "response": map[string]any{"text": "Préparation demandée.", "tools": []map[string]any{{"kind": "reconstruct_reference", "parameters": map[string]any{"brief": "x"}}}}})
		case "/v1/app/actions":
			actions.Add(1)
			json.NewEncoder(w).Encode(map[string]any{"state": "preparing", "run_id": "run"})
		default:
			w.WriteHeader(404)
		}
	}))
	defer backend.Close()
	cfg, e := config.Load(root, "127.0.0.1:8787", backend.URL)
	if e != nil {
		t.Fatal(e)
	}
	db, e := store.Open(filepath.Join(root, "chat.sqlite3"))
	if e != nil {
		t.Fatal(e)
	}
	agent, _ := agentclient.New(backend.URL, "secret")
	defer agent.Close()
	s := &Service{DB: db, Agent: agent, Config: cfg}
	ctx := context.Background()
	if _, e = s.Projects(ctx); e != nil {
		t.Fatal(e)
	}
	db.CreateConversation(ctx, "c", "p", "Test")
	c, _ := db.Conversation(ctx, "c")
	m := store.Message{ID: "m", ConversationID: "c", ProjectID: "p", Role: "user", Text: "Reproduis", TurnID: "t", IdempotencyKey: "k"}
	if _, e = s.Submit(ctx, c, m); e != nil {
		t.Fatal(e)
	}
	if _, e = s.Submit(ctx, c, m); e != nil {
		t.Fatal(e)
	}
	deadline := time.Now().Add(3 * time.Second)
	for {
		messages, _ := db.Messages(ctx, "c")
		if len(messages) == 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("turn did not finish", messages)
		}
		time.Sleep(10 * time.Millisecond)
	}
	if turns.Load() != 1 || actions.Load() != 1 {
		t.Fatal(turns.Load(), actions.Load())
	}
	db.Close()
	db, e = store.Open(filepath.Join(root, "chat.sqlite3"))
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	messages, _ := db.Messages(ctx, "c")
	if len(messages) != 2 || messages[1].Text != "Préparation demandée." {
		t.Fatal(messages)
	}
	a, _ := db.Actions(ctx, "c")
	if len(a) != 1 || a[0].State != "preparing" {
		t.Fatal(a)
	}
}
