package chat

import (
	"bytes"
	"image"
	"image/jpeg"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLiveFrameRejectsStaleSymlinkAndInvalidMedia(t *testing.T) {
	root, resolveErr := filepath.EvalSymlinks(t.TempDir())
	if resolveErr != nil {
		t.Fatal(resolveErr)
	}
	path := filepath.Join(root, "live.jpg")
	var b bytes.Buffer
	jpeg.Encode(&b, image.NewRGBA(image.Rect(0, 0, 8, 8)), nil)
	os.WriteFile(path, b.Bytes(), 0600)
	data, _, err := readLiveFrame(root, time.Now())
	if err != nil || !bytes.Equal(data, b.Bytes()) {
		t.Fatal("fresh frame unavailable", err)
	}
	old := time.Now().Add(-4 * time.Second)
	os.Chtimes(path, old, old)
	if _, _, err = readLiveFrame(root, time.Now()); err == nil {
		t.Fatal("stale frame presented as live")
	}
	os.Remove(path)
	os.Symlink(filepath.Join(t.TempDir(), "image.jpg"), path)
	if _, _, err = readLiveFrame(root, time.Now()); err == nil {
		t.Fatal("symlink accepted")
	}
	os.Remove(path)
	os.WriteFile(path, []byte("not JPEG"), 0600)
	if _, _, err = readLiveFrame(root, time.Now()); err == nil {
		t.Fatal("invalid media accepted")
	}
}
