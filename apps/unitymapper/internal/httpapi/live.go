package httpapi

import (
	"fmt"
	"net/http"
	"time"
)

// A single authenticated multipart connection carries actual Unity camera frames.
func (s *Server) live(w http.ResponseWriter, r *http.Request) {
	data, stamp, err := s.Service.LiveFrame(r.Context(), r.PathValue("action"))
	if err != nil {
		failure(w, 404, "live_unavailable")
		return
	}
	w.Header().Set("Content-Type", "multipart/x-mixed-replace; boundary=unityframe")
	w.Header().Set("Cache-Control", "no-store, private")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	controller := http.NewResponseController(w)
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	var last time.Time
	for {
		if !stamp.Equal(last) {
			if err = controller.SetWriteDeadline(time.Now().Add(5 * time.Second)); err != nil {
				return
			}
			if _, err = fmt.Fprintf(w, "--unityframe\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n", len(data)); err != nil {
				return
			}
			if _, err = w.Write(data); err != nil {
				return
			}
			if _, err = w.Write([]byte("\r\n")); err != nil {
				return
			}
			if err = controller.Flush(); err != nil {
				return
			}
			last = stamp
		}
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
		}
		data, stamp, err = s.Service.LiveFrame(r.Context(), r.PathValue("action"))
		if err != nil {
			return
		}
	}
}
