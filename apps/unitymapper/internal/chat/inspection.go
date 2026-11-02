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
	Live         bool            `json:"live"`
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
	house := false
	for _, a := range actions {
		if a.ID == action {
			house = a.Kind == "generate_house"
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
	if house {
		root = filepath.Join(s.Config.Workspace, ".hdrp-agent", "house", "runs", id)
		var progress json.RawMessage
		if s.Agent.Do(ctx, "GET", "/v1/app/actions/"+action+"/house", nil, &progress) == nil {
			out.Observations = progress
			var p struct {
				State   string `json:"state"`
				Message string `json:"message"`
			}
			if json.Unmarshal(progress, &p) == nil {
				out.State = p.State
				out.Message = p.Message
			}
		}
	}
	if house {
		_, _, err := readLiveFrame(root, time.Now())
		out.Live = err == nil
	}
	resolved, e := filepath.EvalSymlinks(root)
	if e != nil || resolved != root {
		if house {
			return out, nil
		}
		return out, errors.New("evidence unavailable")
	}
	filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		if d.IsDir() {
			if rel != "." && !visualDirectory.MatchString(filepath.ToSlash(rel)) && !(house && regexp.MustCompile(`^[a-f0-9]{12}$`).MatchString(rel)) {
				return filepath.SkipDir
			}
			return nil
		}
		allowed := visualFile.MatchString(filepath.ToSlash(rel))
		if house {
			allowed = regexp.MustCompile(`^([a-f0-9]{12}/)?(sam-)?view-[0-9]+\.png$`).MatchString(filepath.ToSlash(rel))
		}
		if !allowed || !safeEvidence(root, path, 32<<20) {
			return nil
		}
		st, _ := os.Stat(path)
		sum := sha256.Sum256([]byte(rel))
		kind := "prefab"
		if house {
			kind = "unity"
		}
		switch {
		case len(rel) >= 6 && rel[:6] == "input-":
			kind = "reference"
		case len(rel) > 14 && rel[:14] == "asset-matching":
			kind = "comparison"
		case filepath.Dir(rel) != ".":
			kind = "unity"
		}
		if house && regexp.MustCompile(`(^|/)sam-view-`).MatchString(filepath.ToSlash(rel)) {
			kind = "segmentation"
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
