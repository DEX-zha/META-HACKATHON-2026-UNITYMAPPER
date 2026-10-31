package agentclient

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestLostMutationResponseIsUnknownAndNeverRetried(t *testing.T) {
	var calls atomic.Int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Header.Get("Authorization") != "Bearer private" || r.Header.Get("Origin") != "" {
			t.Error("invalid boundary")
		}
		conn, _, _ := w.(http.Hijacker).Hijack()
		conn.Close()
	}))
	defer s.Close()
	c, e := New(s.URL, "private")
	if e != nil {
		t.Fatal(e)
	}
	defer c.Close()
	e = c.Do(context.Background(), "POST", "/v1/app/actions", map[string]string{"id": "a"}, nil)
	var failure *Error
	if !errors.As(e, &failure) || !failure.Unknown || calls.Load() != 1 {
		t.Fatal(e, calls.Load())
	}
}
func TestRedirectDoesNotLeakToken(t *testing.T) {
	var leaked atomic.Bool
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { leaked.Store(true) }))
	defer other.Close()
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, other.URL, 307) }))
	defer s.Close()
	c, _ := New(s.URL, "private")
	defer c.Close()
	e := c.Do(context.Background(), "POST", "/v1/app/actions", nil, nil)
	if e == nil || leaked.Load() {
		t.Fatal("redirect followed", e)
	}
}
