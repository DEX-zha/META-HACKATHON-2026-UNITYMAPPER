package httpapi

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/chat"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/store"
	assets "github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/web"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

func ID() string {
	var b [24]byte
	if _, e := rand.Read(b[:]); e != nil {
		panic(e)
	}
	return hex.EncodeToString(b[:])
}

type Server struct {
	Service            *chat.Service
	Host, Mode         string
	bootstrap, session string
	mu                 sync.Mutex
}

func New(service *chat.Service, host, mode string) *Server {
	return &Server{Service: service, Host: host, Mode: mode, bootstrap: ID(), session: ID()}
}
func (s *Server) LaunchURL() string { return "http://" + s.Host + "/#bootstrap=" + s.bootstrap }
func reply(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(value)
}
func failure(w http.ResponseWriter, status int, code string) {
	reply(w, status, map[string]string{"error": code})
}
func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		failure(w, 415, "json_required")
		return false
	}
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 100000))
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		failure(w, 400, "invalid_input")
		return false
	}
	if d.Decode(&struct{}{}) != io.EOF {
		failure(w, 400, "invalid_input")
		return false
	}
	return true
}
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/auth/bootstrap", func(w http.ResponseWriter, r *http.Request) {
		var data struct {
			Token string `json:"token"`
		}
		if !decode(w, r, &data) {
			return
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		if s.bootstrap == "" || subtle.ConstantTimeCompare([]byte(data.Token), []byte(s.bootstrap)) != 1 {
			failure(w, 401, "invalid_bootstrap")
			return
		}
		s.bootstrap = ""
		http.SetCookie(w, &http.Cookie{Name: "unitymapper_session", Value: s.session, Path: "/", HttpOnly: true, SameSite: http.SameSiteStrictMode, MaxAge: 43200})
		w.WriteHeader(204)
	})
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		reply(w, 200, map[string]string{"status": "ready", "provider_mode": s.Mode, "chat": "connected"})
	})
	mux.HandleFunc("GET /api/projects", func(w http.ResponseWriter, r *http.Request) {
		ps, e := s.Service.Projects(r.Context())
		if e != nil {
			failure(w, 502, "backend_unavailable")
			return
		}
		reply(w, 200, ps)
	})
	mux.HandleFunc("POST /api/actions/{action}/stop", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("action")
		if _, e := s.Service.DB.ActionConversation(r.Context(), id); e != nil {
			failure(w, 404, "action_not_found")
			return
		}
		var result json.RawMessage
		if e := s.Service.Agent.Do(r.Context(), "POST", "/v1/app/actions/"+id+"/stop", map[string]string{"reason": "Stop requested from chat"}, &result); e != nil {
			failure(w, 502, "stop_unconfirmed")
			return
		}
		reply(w, 202, result)
	})
	mux.HandleFunc("GET /api/actions/{action}/live", s.live)
	mux.HandleFunc("GET /api/actions/{action}/inspection", func(w http.ResponseWriter, r *http.Request) {
		data, e := s.Service.Inspection(r.Context(), r.PathValue("action"))
		if e != nil {
			failure(w, 404, "inspection_unavailable")
			return
		}
		reply(w, 200, data)
	})
	mux.HandleFunc("GET /api/actions/{action}/media/{media}", func(w http.ResponseWriter, r *http.Request) {
		data, e := s.Service.Inspection(r.Context(), r.PathValue("action"))
		if e != nil {
			failure(w, 404, "image_unavailable")
			return
		}
		for _, v := range data.Images {
			if v.ID == r.PathValue("media") {
				http.ServeFile(w, r, v.Path)
				return
			}
		}
		failure(w, 404, "image_unavailable")
	})
	mux.HandleFunc("GET /api/budget", func(w http.ResponseWriter, r *http.Request) {
		var data json.RawMessage
		if s.Service.Agent.Do(r.Context(), "GET", "/v1/budget", nil, &data) != nil {
			failure(w, 502, "budget_unavailable")
			return
		}
		reply(w, 200, data)
	})
	mux.HandleFunc("GET /api/projects/{project}/conversations", func(w http.ResponseWriter, r *http.Request) {
		rows, e := s.Service.DB.Conversations(r.Context(), r.PathValue("project"))
		if e != nil {
			failure(w, 500, "storage_error")
			return
		}
		reply(w, 200, rows)
	})
	mux.HandleFunc("POST /api/projects/{project}/conversations", func(w http.ResponseWriter, r *http.Request) {
		var data struct {
			Title string `json:"title"`
		}
		if !decode(w, r, &data) {
			return
		}
		if len(data.Title) > 200 {
			failure(w, 400, "title_too_long")
			return
		}
		p, e := s.Service.Project(r.Context(), r.PathValue("project"))
		if e != nil {
			failure(w, 409, "project_unavailable")
			return
		}
		id := ID()
		if e = s.Service.DB.CreateConversation(r.Context(), id, p.ID, data.Title); e != nil {
			failure(w, 500, "storage_error")
			return
		}
		c, _ := s.Service.DB.Conversation(r.Context(), id)
		reply(w, 201, c)
	})
	mux.HandleFunc("GET /api/conversations/{conversation}", func(w http.ResponseWriter, r *http.Request) {
		c, e := s.Service.DB.Conversation(r.Context(), r.PathValue("conversation"))
		if e != nil {
			failure(w, 404, "conversation_not_found")
			return
		}
		s.Service.Refresh(r.Context(), c)
		messages, e := s.Service.DB.Messages(r.Context(), c.ID)
		if e != nil {
			failure(w, 500, "storage_error")
			return
		}
		actions, e := s.Service.DB.Actions(r.Context(), c.ID)
		if e != nil {
			failure(w, 500, "storage_error")
			return
		}
		reply(w, 200, map[string]any{"conversation": c, "messages": messages, "actions": s.Service.Progress(actions)})
	})
	mux.HandleFunc("POST /api/conversations/{conversation}/messages", func(w http.ResponseWriter, r *http.Request) {
		var data struct {
			Text        string   `json:"text"`
			Key         string   `json:"idempotency_key"`
			Attachments []string `json:"attachment_ids"`
		}
		if !decode(w, r, &data) {
			return
		}
		if len(data.Text) == 0 || len(data.Text) > 16000 || len(data.Key) < 1 || len(data.Key) > 128 || len(data.Attachments) > 3 {
			failure(w, 400, "invalid_message")
			return
		}
		c, e := s.Service.DB.Conversation(r.Context(), r.PathValue("conversation"))
		if e != nil {
			failure(w, 404, "conversation_not_found")
			return
		}
		for _, a := range data.Attachments {
			if _, e = s.Service.DB.Attachment(r.Context(), c.ProjectID, a); e != nil {
				failure(w, 400, "attachment_project_mismatch")
				return
			}
		}
		id := ID()
		mid, e := s.Service.Submit(r.Context(), c, store.Message{ID: id, ConversationID: c.ID, ProjectID: c.ProjectID, Role: "user", Text: data.Text, TurnID: "turn-" + id, IdempotencyKey: data.Key, AttachmentIDs: data.Attachments})
		if e != nil {
			failure(w, 409, "conversation_busy_or_key_conflict")
			return
		}
		reply(w, 202, map[string]string{"message_id": mid})
	})
	mux.HandleFunc("POST /api/projects/{project}/attachments", s.upload)
	mux.HandleFunc("GET /api/projects/{project}/attachments/{attachment}", func(w http.ResponseWriter, r *http.Request) {
		a, e := s.Service.DB.Attachment(r.Context(), r.PathValue("project"), r.PathValue("attachment"))
		if e != nil {
			failure(w, 404, "attachment_not_found")
			return
		}
		w.Header().Set("Content-Type", a.Mime)
		http.ServeFile(w, r, filepath.Join(s.Service.Config.State, "media", a.Hash))
	})
	mux.Handle("GET /", http.FileServer(http.FS(assets.Files)))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
		origin := r.Header.Get("Origin")
		if r.Host != s.Host || (origin != "" && origin != "http://"+s.Host) {
			failure(w, 403, "origin_denied")
			return
		}
		if r.Method != "GET" && r.Method != "HEAD" && origin != "http://"+s.Host {
			failure(w, 403, "origin_required")
			return
		}
		if strings.HasPrefix(r.URL.Path, "/api/") && r.URL.Path != "/api/auth/bootstrap" {
			cookie, e := r.Cookie("unitymapper_session")
			if e != nil || subtle.ConstantTimeCompare([]byte(cookie.Value), []byte(s.session)) != 1 {
				failure(w, 401, "local_session_required")
				return
			}
		}
		mux.ServeHTTP(w, r)
	})
}
func (s *Server) upload(w http.ResponseWriter, r *http.Request) {
	project := r.PathValue("project")
	if _, e := s.Service.Project(r.Context(), project); e != nil {
		failure(w, 409, "project_unavailable")
		return
	}
	data, e := io.ReadAll(http.MaxBytesReader(w, r.Body, 10_000_000))
	if e != nil {
		failure(w, 413, "image_too_large")
		return
	}
	mime := http.DetectContentType(data)
	if mime != "image/png" && mime != "image/jpeg" {
		failure(w, 415, "png_or_jpeg_required")
		return
	}
	sum := sha256.Sum256(data)
	hash := hex.EncodeToString(sum[:])
	if e = s.Service.Agent.PutImage(r.Context(), hash, mime, data); e != nil {
		failure(w, 502, "upload_failed")
		return
	}
	var receipt map[string]any
	if e = s.Service.Agent.Do(r.Context(), "POST", "/v1/chat/attachments", map[string]string{"project_id": project, "artifact_hash": hash}, &receipt); e != nil {
		failure(w, 422, "invalid_image")
		return
	}
	dir := filepath.Join(s.Service.Config.State, "media")
	if e = os.MkdirAll(dir, 0700); e != nil {
		failure(w, 500, "storage_error")
		return
	}
	f, e := os.CreateTemp(dir, "upload-")
	if e != nil {
		failure(w, 500, "storage_error")
		return
	}
	temp := f.Name()
	defer os.Remove(temp)
	_, e = f.Write(data)
	if e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	if e == nil {
		e = ce
	}
	if e == nil {
		e = os.Rename(temp, filepath.Join(dir, hash))
	}
	if e != nil {
		failure(w, 500, "storage_error")
		return
	}
	name := filepath.Base(r.URL.Query().Get("name"))
	if name == "." || len(name) > 180 {
		name = "reference"
	}
	a, e := s.Service.DB.AddAttachment(r.Context(), project, store.Attachment{ID: ID(), Hash: hash, Mime: mime, Name: name, Bytes: int64(len(data))})
	if e != nil {
		failure(w, 500, "storage_error")
		return
	}
	reply(w, 201, a)
}
