// Package config confines the local application and its backend to the workspace.
package config

import (
	"errors"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

type Config struct{ Workspace, Listen, Backend, TokenFile, State string }

func Load(workspace, listen, backend string) (Config, error) {
	var c Config
	if workspace == "" {
		return c, errors.New("workspace is required")
	}
	root, err := filepath.Abs(workspace)
	if err != nil {
		return c, err
	}
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		return c, err
	}
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return c, errors.New("workspace must be a directory")
	}
	host, port, err := net.SplitHostPort(listen)
	if err != nil || host != "127.0.0.1" || port == "0" || port == "" {
		return c, errors.New("listen must be 127.0.0.1 with an explicit port")
	}
	u, err := url.Parse(backend)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Port() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return c, errors.New("backend must be a loopback HTTP origin")
	}
	return Config{root, listen, strings.TrimRight(backend, "/"), filepath.Join(root, ".hdrp-agent", "local-token"), filepath.Join(root, ".hdrp-agent", "chat")}, nil
}

// ProjectRoot resolves symlinks before checking containment; lexical prefixes are insufficient.
func (c Config) ProjectRoot(path string) (string, error) {
	if !filepath.IsAbs(path) {
		path = filepath.Join(c.Workspace, path)
	}
	root, err := filepath.EvalSymlinks(path)
	if err != nil {
		return "", err
	}
	rel, err := filepath.Rel(c.Workspace, root)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", errors.New("project outside workspace")
	}
	for _, p := range []string{"Assets", "ProjectSettings", "Packages"} {
		info, e := os.Stat(filepath.Join(root, p))
		if e != nil || !info.IsDir() {
			return "", errors.New("not a Unity project")
		}
	}
	return root, nil
}
