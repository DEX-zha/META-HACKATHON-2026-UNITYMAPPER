// Package agentclient is the sole Go transport to the Python execution authority.
package agentclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Error struct {
	Code    string
	Status  int
	Unknown bool
}

func (e *Error) Error() string { return "agent: " + e.Code }

type Client struct {
	origin, token string
	http          *http.Client
}

func New(origin, token string) (*Client, error) {
	u, err := url.Parse(origin)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Port() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return nil, errors.New("invalid backend origin")
	}
	token = strings.TrimSpace(token)
	if token == "" || strings.ContainsAny(token, "\r\n") {
		return nil, errors.New("invalid local token")
	}
	transport := &http.Transport{Proxy: nil, DialContext: (&net.Dialer{Timeout: 5 * time.Second}).DialContext, ResponseHeaderTimeout: 180 * time.Second, MaxIdleConns: 4, IdleConnTimeout: 30 * time.Second}
	return &Client{strings.TrimRight(origin, "/"), token, &http.Client{Timeout: 185 * time.Second, Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}
func (c *Client) Close() { c.http.CloseIdleConnections() }

// Do sends once. No idempotency headers are set on HTTP transports: Go may otherwise retry them.
func (c *Client) Do(ctx context.Context, method, path string, input, output any) error {
	if !strings.HasPrefix(path, "/") || strings.HasPrefix(path, "//") || strings.Contains(path, "#") {
		return &Error{Code: "invalid_path"}
	}
	u, e := url.ParseRequestURI(path)
	if e != nil || u.IsAbs() {
		return &Error{Code: "invalid_path"}
	}
	var body io.Reader
	if input != nil {
		raw, e := json.Marshal(input)
		if e != nil {
			return e
		}
		body = bytes.NewReader(raw)
	}
	req, e := http.NewRequestWithContext(ctx, method, c.origin+path, body)
	if e != nil {
		return &Error{Code: "invalid_request"}
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	if input != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	mutation := method != "GET" && method != "HEAD"
	resp, e := c.http.Do(req)
	if e != nil {
		return &Error{Code: "transport_unavailable", Unknown: mutation}
	}
	defer resp.Body.Close()
	raw, e := io.ReadAll(io.LimitReader(resp.Body, (4<<20)+1))
	if e != nil || len(raw) > 4<<20 {
		return &Error{Code: "invalid_response", Status: resp.StatusCode, Unknown: mutation}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		code := "backend_rejected"
		var failure struct {
			Code string `json:"code"`
		}
		if json.Unmarshal(raw, &failure) == nil {
			// Only reviewed codes cross into the UI; arbitrary bodies may contain secrets.
			switch failure.Code {
			case "NOT_FOUND", "STALE_VERSION", "SESSION_ACTIVE", "BUDGET_LIMIT", "COST_BOUND_UNKNOWN", "UNAUTHORIZED", "INVALID_INPUT", "PROJECT_MISMATCH", "IDEMPOTENCY_CONFLICT", "RESPONSE_UNKNOWN":
				code = failure.Code
			}
		}
		return &Error{Code: code, Status: resp.StatusCode, Unknown: mutation && (resp.StatusCode >= 500 || resp.StatusCode < 400)}
	}
	if output != nil && json.Unmarshal(raw, output) != nil {
		return &Error{Code: "invalid_response", Status: resp.StatusCode, Unknown: mutation}
	}
	return nil
}
