package chat

import (
	"encoding/json"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/store"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var runID = regexp.MustCompile(`^[a-f0-9]{32}$`)

// Progress is a read-only view of worker-owned evidence. It never changes action state.
// Reading the existing handoff lets the UI observe a running worker without restarting it.
func (s *Service) Progress(actions []store.ActionView) []store.ActionView {
	for i := range actions {
		var result map[string]any
		if json.Unmarshal(actions[i].Result, &result) != nil {
			continue
		}
		id, ok := result["run_id"].(string)
		if !ok || !runID.MatchString(id) {
			continue
		}
		root := filepath.Join(s.Config.Workspace, ".hdrp-agent", "reconstructions")
		directory := filepath.Join(root, id)
		resolved, err := filepath.EvalSymlinks(directory)
		if err != nil || resolved != directory {
			continue
		}
		path := filepath.Join(directory, "status.json")
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() || info.Size() > 64000 {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		var status struct {
			State   string `json:"state"`
			Message string `json:"message"`
		}
		if json.Unmarshal(raw, &status) != nil {
			continue
		}
		latest := info.ModTime()
		previews, renders := 0, 0
		entries, _ := os.ReadDir(directory)
		for _, entry := range entries {
			if !entry.Type().IsRegular() {
				continue
			}
			name := entry.Name()
			if strings.HasPrefix(name, "preview-") && strings.HasSuffix(name, ".png") {
				previews++
			}
			if strings.HasPrefix(name, "render-") && strings.HasSuffix(name, ".json") {
				renders++
			}
			if stat, e := entry.Info(); e == nil && stat.ModTime().After(latest) {
				latest = stat.ModTime()
			}
		}
		result["progress"] = map[string]any{"phase": status.State, "message": status.Message, "phase_started_at": info.ModTime().UTC().Format(time.RFC3339), "last_evidence_at": latest.UTC().Format(time.RFC3339), "preview_images": previews, "render_receipts": renders, "source": "worker_handoff"}
		if value, e := json.Marshal(result); e == nil {
			actions[i].Result = value
		}
	}
	return actions
}
