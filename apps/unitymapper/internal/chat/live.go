package chat

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"
)

// LiveFrame uses the action's owned run, never a path supplied by the browser.
func (s *Service) LiveFrame(ctx context.Context, action string) ([]byte, time.Time, error) {
	conversation, err := s.DB.ActionConversation(ctx, action)
	if err != nil {
		return nil, time.Time{}, err
	}
	actions, err := s.DB.Actions(ctx, conversation)
	if err != nil {
		return nil, time.Time{}, err
	}
	for _, a := range actions {
		if a.ID != action || a.Kind != "generate_house" {
			continue
		}
		var result struct {
			Run string `json:"run_id"`
		}
		if json.Unmarshal(a.Result, &result) != nil || !runID.MatchString(result.Run) {
			break
		}
		root := filepath.Join(s.Config.Workspace, ".hdrp-agent", "house", "runs", result.Run)
		return readLiveFrame(root, time.Now())
	}
	return nil, time.Time{}, errors.New("live action unavailable")
}
func readLiveFrame(root string, now time.Time) ([]byte, time.Time, error) {
	path := filepath.Join(root, "live.jpg")
	if !safeEvidence(root, path, 4<<20) {
		return nil, time.Time{}, errors.New("live frame unavailable")
	}
	st, err := os.Stat(path)
	if err != nil {
		return nil, time.Time{}, err
	}
	if now.Sub(st.ModTime()) > 3*time.Second || st.ModTime().After(now.Add(time.Second)) {
		return nil, time.Time{}, errors.New("live frame stale")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, time.Time{}, err
	}
	if len(data) < 4 || data[0] != 0xff || data[1] != 0xd8 || data[len(data)-2] != 0xff || data[len(data)-1] != 0xd9 {
		return nil, time.Time{}, errors.New("invalid JPEG frame")
	}
	return data, st.ModTime(), nil
}
