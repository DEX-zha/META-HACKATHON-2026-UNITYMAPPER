package chat

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/agentclient"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/config"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/store"
	"sync"
	"time"
)

type Project struct {
	Connected    bool     `json:"connected"`
	ID           string   `json:"id"`
	Label        string   `json:"label"`
	Root         string   `json:"canonical_root"`
	Version      string   `json:"scene_version"`
	Scene        string   `json:"scene_path"`
	Capabilities []string `json:"capabilities"`
}
type Service struct {
	DB     *store.Store
	Agent  *agentclient.Client
	Config config.Config
	mu     sync.Mutex
}

func (s *Service) Projects(ctx context.Context) ([]Project, error) {
	var ps []Project
	if e := s.Agent.Do(ctx, "GET", "/v1/projects", nil, &ps); e != nil {
		return nil, e
	}
	out := []Project{}
	for _, p := range ps {
		root, e := s.Config.ProjectRoot(p.Root)
		if e != nil {
			continue
		}
		if e = s.DB.LinkProject(ctx, p.ID, p.Label, root, p.ID); e != nil {
			return nil, e
		}
		out = append(out, p)
	}
	return out, nil
}
func (s *Service) Project(ctx context.Context, id string) (Project, error) {
	ps, e := s.Projects(ctx)
	if e != nil {
		return Project{}, e
	}
	for _, p := range ps {
		if p.ID == id {
			return p, nil
		}
	}
	return Project{}, store.ErrOwnership
}

type Tool struct {
	Kind       string          `json:"kind"`
	Parameters json.RawMessage `json:"parameters"`
}
type Turn struct {
	ID           string `json:"turn_id"`
	Project      string `json:"project_id"`
	Conversation string `json:"conversation_id"`
	Message      string `json:"message_id"`
	State        string `json:"state"`
	Error        string `json:"error_code"`
	Response     *struct {
		Text  string `json:"text"`
		Tools []Tool `json:"tools"`
	} `json:"response"`
}

// Submit persists the message before acknowledging it. Dispatch is claimed exactly once.
func (s *Service) Submit(ctx context.Context, c store.Conversation, m store.Message) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, e := s.DB.MessageForKey(ctx, c.ID, m.IdempotencyKey); e == nil {
		return s.DB.SaveMessage(ctx, m)
	} else if !store.IsMissing(e) {
		return "", e
	}
	history, e := s.DB.Messages(ctx, c.ID)
	if e != nil {
		return "", e
	}
	for _, old := range history {
		if old.Status == "generating" {
			return "", errors.New("a turn is already running")
		}
	}
	id, e := s.DB.SaveMessage(ctx, m)
	if e != nil {
		return "", e
	}
	ok, e := s.DB.ClaimMessage(ctx, id)
	if e != nil {
		return "", e
	}
	if ok {
		go s.generate(c, id)
	}
	return id, nil
}
func (s *Service) generate(c store.Conversation, id string) {
	ctx, cancel := context.WithTimeout(context.Background(), 190*time.Second)
	defer cancel()
	fail := func() { s.DB.MessageStatus(context.Background(), id, "unknown") }
	project, e := s.Project(ctx, c.ProjectID)
	if e != nil {
		fail()
		return
	}
	history, e := s.DB.Messages(ctx, c.ID)
	if e != nil {
		fail()
		return
	}
	var current store.ChatMessage
	for _, m := range history {
		if m.ID == id {
			current = m
			break
		}
	}
	messages := []map[string]string{}
	size := 0
	for i := len(history) - 1; i >= 0 && len(messages) < 20; i-- {
		m := history[i]
		if m.ID != id && m.Status != "complete" {
			continue
		}
		if m.Role != "user" && m.Role != "assistant" {
			continue
		}
		if size+len(m.Text) > 50000 {
			break
		}
		messages = append(messages, map[string]string{"role": m.Role, "text": m.Text})
		size += len(m.Text)
	}
	for i, j := 0, len(messages)-1; i < j; i, j = i+1, j-1 {
		messages[i], messages[j] = messages[j], messages[i]
	}
	hashes := []string{}
	attachmentIDs := current.Attachments
	if len(attachmentIDs) == 0 {
		for i := len(history) - 1; i >= 0; i-- {
			if len(history[i].Attachments) > 0 {
				attachmentIDs = history[i].Attachments
				break
			}
		}
	}
	for _, a := range attachmentIDs {
		item, e := s.DB.Attachment(ctx, c.ProjectID, a)
		if e != nil {
			fail()
			return
		}
		hashes = append(hashes, item.Hash)
	}
	request := map[string]any{"schema_version": "1.0", "turn_id": current.TurnID, "project_id": c.ProjectID, "conversation_id": c.ID, "message_id": id, "idempotency_key": current.TurnID, "messages": messages, "artifact_hashes": hashes, "memory": map[string]any{"revision": c.Revision, "summary": c.Summary, "constraints": []string{"Connected project prefabs; preserve source; default wall family B and Ceiling_3x3"}, "scene_version": project.Version, "parent_run_id": nil}}
	var turn Turn
	e = s.Agent.Do(ctx, "POST", "/v1/chat/turns", request, &turn)
	if e != nil {
		fail()
		return
	}
	s.accept(ctx, c, current, project, hashes, turn)
}
func (s *Service) accept(ctx context.Context, c store.Conversation, m store.ChatMessage, p Project, hashes []string, t Turn) {
	if t.Project != c.ProjectID || t.Conversation != c.ID || t.Message != m.ID || t.ID != m.TurnID {
		s.DB.MessageStatus(ctx, m.ID, "unknown")
		return
	}
	if t.State != "complete" || t.Response == nil {
		state := "failed"
		if t.State == "unknown" || t.State == "generating" {
			state = "unknown"
		}
		s.DB.MessageStatus(ctx, m.ID, state)
		return
	}
	// Persist tool intentions before completing the visible answer. Deterministic IDs avoid duplicate native actions.
	for i, tool := range t.Response.Tools {
		if i >= 4 {
			break
		}
		aid := fmt.Sprintf("%s-tool-%d", m.ID, i)
		_, e := s.DB.QueueAction(ctx, store.Action{ID: aid, ProjectID: c.ProjectID, ConversationID: c.ID, MessageID: m.ID, Kind: tool.Kind, Args: tool.Parameters, ExpectedSceneVersion: p.Version, IdempotencyKey: aid})
		if e != nil {
			continue
		}
		ok, e := s.DB.ClaimDispatch(ctx, aid)
		if e != nil || !ok {
			continue
		}
		if tool.Kind != "reconstruct_reference" {
			s.DB.RecordAction(ctx, aid, "failed", json.RawMessage(`{"error_code":"CAPABILITY_MISSING"}`), false)
			continue
		}
		request := map[string]any{"schema_version": "1.0", "action_id": aid, "project_id": c.ProjectID, "conversation_id": c.ID, "message_id": m.ID, "kind": tool.Kind, "expected_scene_version": p.Version, "artifact_hashes": hashes, "parameters": tool.Parameters, "idempotency_key": aid}
		var result json.RawMessage
		e = s.Agent.Do(ctx, "POST", "/v1/app/actions", request, &result)
		if e != nil {
			state := "failed"
			var failure *agentclient.Error
			if errors.As(e, &failure) && failure.Unknown {
				state = "recovery_required"
			}
			s.DB.RecordAction(ctx, aid, state, json.RawMessage(`{"error_code":"ACTION_DELIVERY_FAILED"}`), state == "recovery_required")
			continue
		}
		var status struct {
			State string `json:"state"`
		}
		json.Unmarshal(result, &status)
		s.DB.RecordAction(ctx, aid, status.State, result, false)
	}
	s.DB.CompleteTurn(ctx, m.ID, t.Response.Text)
}
func (s *Service) Refresh(ctx context.Context, c store.Conversation) {
	actions, _ := s.DB.Actions(ctx, c.ID)
	for _, a := range actions {
		switch a.State {
		case "completed", "failed", "interrupted", "inconclusive":
			continue
		}
		var result json.RawMessage
		if s.Agent.Do(ctx, "GET", "/v1/app/actions/"+a.ID, nil, &result) != nil {
			continue
		}
		var state struct {
			State string `json:"state"`
		}
		if json.Unmarshal(result, &state) == nil && string(result) != string(a.Result) {
			s.DB.RecordAction(ctx, a.ID, state.State, result, false)
		}
	}
	history, _ := s.DB.Messages(ctx, c.ID)
	for _, m := range history {
		if m.Status != "unknown" {
			continue
		}
		var t Turn
		if s.Agent.Do(ctx, "GET", "/v1/chat/turns/"+m.TurnID, nil, &t) != nil {
			continue
		}
		if t.State == "complete" && t.Response != nil {
			// A recovered model answer is not proof that its tools were dispatched.
			existing, _ := s.DB.Actions(ctx, c.ID)
			known := map[string]bool{}
			for _, a := range existing {
				known[a.ID] = true
			}
			for i, tool := range t.Response.Tools {
				aid := fmt.Sprintf("%s-tool-%d", m.ID, i)
				if known[aid] {
					continue
				}
				if _, e := s.DB.QueueAction(ctx, store.Action{ID: aid, ProjectID: c.ProjectID, ConversationID: c.ID, MessageID: m.ID, Kind: tool.Kind, Args: tool.Parameters, IdempotencyKey: aid}); e == nil {
					s.DB.RecordAction(ctx, aid, "recovery_required", json.RawMessage(`{"error_code":"ACTION_NOT_DISPATCHED_AFTER_RECOVERY"}`), true)
				}
			}
			s.DB.CompleteTurn(ctx, m.ID, t.Response.Text)
		}
	}
}
