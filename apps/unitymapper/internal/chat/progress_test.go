package chat

import (
	"encoding/json"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/config"
	"github.com/DEX-zha/META-HACKATHON-2026-UNITYMAPPER/apps/unitymapper/internal/store"
	"os"
	"path/filepath"
	"testing"
)

func TestProgressReadsEvidenceWithoutChangingActionState(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	id := "28f29e0c89444f0db70bbccb96395768"
	dir := filepath.Join(root, ".hdrp-agent", "reconstructions", id)
	os.MkdirAll(dir, 0700)
	os.WriteFile(filepath.Join(dir, "status.json"), []byte(`{"state":"previewing","message":"Comparaison des assets"}`), 0600)
	os.WriteFile(filepath.Join(dir, "preview-one.png"), []byte("fixture"), 0600)
	os.WriteFile(filepath.Join(dir, "composition-metrics-2.json"), []byte(`{"bounds_admissible":true,"composition_qualified":false,"per_object":{"bed":{}}}`), 0600)
	os.WriteFile(filepath.Join(dir, "composition-metrics-10.json"), []byte(`{"bounds_admissible":false,"composition_qualified":false,"per_object":{"bed":{},"sofa":{}}}`), 0600)
	s := Service{Config: config.Config{Workspace: root}}
	a := s.Progress([]store.ActionView{{State: "running", Result: json.RawMessage(`{"run_id":"` + id + `"}`)}})
	var result map[string]any
	json.Unmarshal(a[0].Result, &result)
	p := result["progress"].(map[string]any)
	if a[0].State != "running" || p["phase"] != "previewing" || p["preview_images"] != float64(1) {
		t.Fatal(a, p)
	}
	if p["composition_ordinal"] != float64(10) || p["composition"].(map[string]any)["bounds_admissible"] != false {
		t.Fatal("latest numeric composition evidence missing", p)
	}
	os.RemoveAll(dir)
	os.Symlink(t.TempDir(), dir)
	a = s.Progress([]store.ActionView{{Result: json.RawMessage(`{"run_id":"` + id + `"}`)}})
	if string(a[0].Result) != `{"run_id":"`+id+`"}` {
		t.Fatal("symlink accepted")
	}
	a = s.Progress([]store.ActionView{{Result: json.RawMessage(`{"run_id":"../../secret"}`)}})
	if string(a[0].Result) != `{"run_id":"../../secret"}` {
		t.Fatal("invalid run accepted")
	}
}
