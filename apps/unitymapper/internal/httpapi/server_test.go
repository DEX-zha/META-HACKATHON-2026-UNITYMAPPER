package httpapi

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestLocalSessionOriginAndSingleUseBootstrap(t *testing.T) {
	s := New(nil, "127.0.0.1:8787", "offline")
	handler := s.Handler()
	token := s.bootstrap
	call := func(method, path, origin, body string, cookie *http.Cookie) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, "http://127.0.0.1:8787"+path, bytes.NewBufferString(body))
		if origin != "" {
			r.Header.Set("Origin", origin)
		}
		r.Header.Set("Content-Type", "application/json")
		if cookie != nil {
			r.AddCookie(cookie)
		}
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	if w := call("GET", "/api/projects", "", "", nil); w.Code != 401 {
		t.Fatal(w.Code)
	}
	body := `{"token":"` + token + `"}`
	if w := call("POST", "/api/auth/bootstrap", "http://evil.example", body, nil); w.Code != 403 {
		t.Fatal(w.Code)
	}
	w := call("POST", "/api/auth/bootstrap", "http://127.0.0.1:8787", body, nil)
	if w.Code != 204 {
		t.Fatal(w.Code, w.Body.String())
	}
	cookies := w.Result().Cookies()
	if len(cookies) != 1 || !cookies[0].HttpOnly || cookies[0].SameSite != http.SameSiteStrictMode {
		t.Fatal(cookies)
	}
	if w = call("POST", "/api/auth/bootstrap", "http://127.0.0.1:8787", body, nil); w.Code != 401 {
		t.Fatal(w.Code)
	}
	w = call("GET", "/", "", "", nil)
	if w.Code != 200 || !strings.Contains(w.Body.String(), "UnityMapper") {
		t.Fatal(w.Code)
	}
}
