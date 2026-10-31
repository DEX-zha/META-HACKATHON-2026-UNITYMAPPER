package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/agentclient"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/config"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/store"
	"golang.org/x/sys/unix"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"
)

func run() error {
	workspace := flag.String("workspace", "", "explicit UnityMapper workspace")
	listen := flag.String("listen", "127.0.0.1:8787", "loopback address")
	backend := flag.String("backend", "http://127.0.0.1:8765", "Python authority origin")
	flag.Parse()
	cfg, err := config.Load(*workspace, *listen, *backend)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(cfg.State, 0700); err != nil {
		return err
	}
	lock, err := os.OpenFile(filepath.Join(cfg.State, "server.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	defer lock.Close()
	if err = unix.Flock(int(lock.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		return errors.New("another chat server owns this workspace")
	}
	defer unix.Flock(int(lock.Fd()), unix.LOCK_UN)
	raw, err := os.ReadFile(cfg.TokenFile)
	if err != nil {
		return errors.New("Python local token unavailable; start the agent first")
	}
	agent, err := agentclient.New(cfg.Backend, string(raw))
	if err != nil {
		return err
	}
	defer agent.Close()
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	check, stop := context.WithTimeout(ctx, 5*time.Second)
	var health struct {
		Status string `json:"status"`
		Schema string `json:"schema_version"`
		Mode   string `json:"provider_mode"`
	}
	err = agent.Do(check, "GET", "/health", nil, &health)
	stop()
	if err != nil {
		return fmt.Errorf("backend health check failed: %w", err)
	}
	if health.Schema != "1.0" || (health.Mode != "live" && health.Mode != "fixture") || (health.Status != "ready" && health.Status != "recovery_required") {
		return errors.New("unsupported backend health response")
	}
	db, err := store.Open(filepath.Join(cfg.State, "chat.sqlite3"))
	if err != nil {
		return err
	}
	defer db.Close()
	if err = db.RecoverUncertain(ctx); err != nil {
		return err
	}
	mux := http.NewServeMux()
	// Foundation endpoint only. Product APIs are added by the subsequent chat tasks.
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "foundation_ready", "chat": "not_implemented", "provider_mode": health.Mode})
	})
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != cfg.Listen || r.Header.Get("Origin") != "" {
			http.Error(w, "invalid local origin", http.StatusForbidden)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		mux.ServeHTTP(w, r)
	})
	server := &http.Server{Addr: cfg.Listen, Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 190 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	listener, err := net.Listen("tcp4", cfg.Listen)
	if err != nil {
		return err
	}
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	log.Printf("UnityMapper foundation listening on http://%s (chat integration pending)", cfg.Listen)
	select {
	case err = <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-ctx.Done():
	}
	shutdown, release := context.WithTimeout(context.Background(), 5*time.Second)
	defer release()
	return server.Shutdown(shutdown)
}
func main() {
	if err := run(); err != nil {
		log.Print(err)
		os.Exit(1)
	}
}
