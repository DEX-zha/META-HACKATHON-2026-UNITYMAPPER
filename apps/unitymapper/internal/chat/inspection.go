package chat

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"time"
)

var visualDirectory = regexp.MustCompile(`^(floorplan-[0-9]+(-resume-[a-f0-9]{32})?|(inspection|capture)-[0-9]+)$`)
var visualFile = regexp.MustCompile(`^(input-[0-9]+\.(png|jpg)|asset-matching-[0-9]+\.png|preview-[a-f0-9]+\.png|(floorplan-[0-9]+(-resume-[a-f0-9]{32})?|inspection-[0-9]+|capture-[0-9]+)/[a-zA-Z0-9_-]+\.png)$`)

type Visual struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Name    string `json:"name"`
	Updated string `json:"updated_at"`
	Path    string `json:"-"`
}
type Inspection struct {
	State        string          `json:"state"`
	Message      string          `json:"message"`
	Images       []Visual        `json:"images"`
	Observations json.RawMessage `json:"observations"`
}

func safeEvidence(root, path string, limit int64) bool {
	resolved, e := filepath.EvalSymlinks(path)
	if e != nil || resolved != path {
		return false
	}
	rel, e := filepath.Rel(root, path)
	if e != nil || rel == ".." || len(rel) > 2 && rel[:3] == "../" {
		return false
	}
	st, e := os.Lstat(path)
	return e == nil && st.Mode().IsRegular() && st.Size() <= limit
}

// Inspection only exposes allowlisted visual evidence belonging to a locally admitted action.
func (s *Service) Inspection(ctx context.Context, action string) (Inspection, error) {
	out := Inspection{Images: []Visual{}, Observations: json.RawMessage(`{}`)}
	conversation, e := s.DB.ActionConversation(ctx, action)
	if e != nil {
		return out, e
	}
	actions, e := s.DB.Actions(ctx, conversation)
	if e != nil {
		return out, e
	}
	id := ""
	for _, a := range actions {
		if a.ID == action {
			var r struct {
				Run string `json:"run_id"`
			}
			json.Unmarshal(a.Result, &r)
			id = r.Run
		}
	}
	if !runID.MatchString(id) {
		return out, errors.New("run unavailable")
	}
	root := filepath.Join(s.Config.Workspace, ".hdrp-agent", "reconstructions", id)
	resolved, e := filepath.EvalSymlinks(root)
	if e != nil || resolved != root {
		return out, errors.New("evidence unavailable")
	}
	filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		if d.IsDir() {
			if rel != "." && !visualDirectory.MatchString(rel) {
				return filepath.SkipDir
			}
			return nil
		}
		if !visualFile.MatchString(filepath.ToSlash(rel)) || !safeEvidence(root, path, 32<<20) {
			return nil
		}
		st, _ := os.Stat(path)
		sum := sha256.Sum256([]byte(rel))
		kind := "prefab"
		switch {
		case rel[:6] == "input-":
			kind = "reference"
		case len(rel) > 14 && rel[:14] == "asset-matching":
			kind = "comparison"
		case filepath.Dir(rel) != ".":
			kind = "unity"
		}
		out.Images = append(out.Images, Visual{hex.EncodeToString(sum[:]), kind, rel, st.ModTime().UTC().Format(time.RFC3339Nano), path})
		return nil
	})
	sort.Slice(out.Images, func(i, j int) bool { return out.Images[i].Updated < out.Images[j].Updated })
	statusPath := filepath.Join(root, "status.json")
	if safeEvidence(root, statusPath, 64000) {
		raw, _ := os.ReadFile(statusPath)
		var status struct {
			State   string `json:"state"`
			Message string `json:"message"`
		}
		if json.Unmarshal(raw, &status) == nil {
			out.State = status.State
			out.Message = status.Message
		}
	}
	path := filepath.Join(root, "visual-observations.json")
	if safeEvidence(root, path, 1<<20) {
		raw, err := os.ReadFile(path)
		if err == nil && json.Valid(raw) {
			out.Observations = raw
		}
	}
	return out, nil
}
