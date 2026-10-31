package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWorkspaceSymlinkCannotEscape(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	for _, d := range []string{"Assets", "Packages", "ProjectSettings"} {
		os.Mkdir(filepath.Join(outside, d), 0700)
	}
	os.Symlink(outside, filepath.Join(root, "escape"))
	c, e := Load(root, "127.0.0.1:8787", "http://127.0.0.1:8765")
	if e != nil {
		t.Fatal(e)
	}
	if _, e = c.ProjectRoot("escape"); e == nil {
		t.Fatal("escaped workspace")
	}
	if _, e = Load(root, "0.0.0.0:8787", c.Backend); e == nil {
		t.Fatal("public bind accepted")
	}
}
