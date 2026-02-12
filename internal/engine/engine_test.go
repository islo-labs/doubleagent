package engine

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/islo-labs/double-agent/internal/builtin"
	"github.com/islo-labs/double-agent/internal/config"
	"github.com/islo-labs/double-agent/pkg/sdk"
)

// fakePlugin is a minimal sdk.Plugin for testing.
type fakePlugin struct {
	info         sdk.PluginInfo
	configureErr error
	resetErr     error
}

func (f *fakePlugin) Info() sdk.PluginInfo             { return f.info }
func (f *fakePlugin) Configure(map[string]string) error { return f.configureErr }
func (f *fakePlugin) ServeHTTP(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
}
func (f *fakePlugin) Reset() error { return f.resetErr }

// doRequest is a helper that sends an HTTP request to the given handler.
func doRequest(t *testing.T, handler http.Handler, method, path string, body string) *httptest.ResponseRecorder {
	t.Helper()
	var bodyReader io.Reader
	if body != "" {
		bodyReader = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, bodyReader)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// freePort finds an available TCP port.
func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	port := ln.Addr().(*net.TCPAddr).Port
	ln.Close()
	return port
}

// waitForServer polls the given URL until it responds or the timeout expires.
func waitForServer(t *testing.T, url string, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		resp, err := http.Get(url)
		if err == nil {
			resp.Body.Close()
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("server at %s did not become ready within %s", url, timeout)
}

func TestNew_ValidConfig(t *testing.T) {
	cfg := &config.Config{
		Services: []config.Service{
			{Type: "github", Name: "gh1", Port: 8080},
		},
	}
	eng, err := New(cfg)
	require.NoError(t, err)
	require.Len(t, eng.instances, 1)
	assert.Equal(t, "gh1", eng.instances[0].Config.Name)
}

func TestNew_MultipleServices(t *testing.T) {
	cfg := &config.Config{
		Services: []config.Service{
			{Type: "github", Name: "gh1", Port: 8080},
			{Type: "jira", Name: "jr1", Port: 8081},
		},
	}
	eng, err := New(cfg)
	require.NoError(t, err)
	require.Len(t, eng.instances, 2)
}

func TestNew_UnknownPluginType(t *testing.T) {
	cfg := &config.Config{
		Services: []config.Service{
			{Type: "unknown", Name: "x", Port: 9999},
		},
	}
	_, err := New(cfg)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unknown plugin type")
}

func TestNew_ConfigureError(t *testing.T) {
	// Temporarily inject a fake plugin into the registry.
	builtin.Registry["fakebroken"] = func() sdk.Plugin {
		return &fakePlugin{
			info:         sdk.PluginInfo{Name: "fakebroken"},
			configureErr: fmt.Errorf("boom"),
		}
	}
	defer delete(builtin.Registry, "fakebroken")

	cfg := &config.Config{
		Services: []config.Service{
			{Type: "fakebroken", Name: "fb1", Port: 9999},
		},
	}
	_, err := New(cfg)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "boom")
}

func TestNew_ResetEndpoint(t *testing.T) {
	cfg := &config.Config{
		Services: []config.Service{
			{Type: "github", Name: "gh1", Port: 8080},
		},
	}
	eng, err := New(cfg)
	require.NoError(t, err)
	require.Len(t, eng.instances, 1)

	handler := eng.instances[0].Server.Handler
	rec := doRequest(t, handler, http.MethodPost, "/_/reset", "")
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Contains(t, rec.Body.String(), `"status":"ok"`)
}

func TestEngine_Run_StartsAndStops(t *testing.T) {
	port := freePort(t)
	// Inject a fake plugin so tests don't depend on real plugin behavior.
	builtin.Registry["fakeok"] = func() sdk.Plugin {
		return &fakePlugin{info: sdk.PluginInfo{Name: "fakeok", Version: "v0"}}
	}
	defer delete(builtin.Registry, "fakeok")

	cfg := &config.Config{
		Services: []config.Service{
			{Type: "fakeok", Name: "s1", Port: port},
		},
	}
	eng, err := New(cfg)
	require.NoError(t, err)

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)
	go func() { errCh <- eng.Run(ctx) }()

	url := fmt.Sprintf("http://127.0.0.1:%d/", port)
	waitForServer(t, url, 3*time.Second)

	// Verify the server is responding.
	resp, err := http.Get(url)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	cancel()
	require.NoError(t, <-errCh)
}

func TestEngine_Run_ListenError(t *testing.T) {
	// Occupy a port on all interfaces (engine binds to ":port").
	ln, err := net.Listen("tcp", ":0")
	require.NoError(t, err)
	defer ln.Close()
	port := ln.Addr().(*net.TCPAddr).Port

	builtin.Registry["fakeok2"] = func() sdk.Plugin {
		return &fakePlugin{info: sdk.PluginInfo{Name: "fakeok2", Version: "v0"}}
	}
	defer delete(builtin.Registry, "fakeok2")

	cfg := &config.Config{
		Services: []config.Service{
			{Type: "fakeok2", Name: "s1", Port: port},
		},
	}
	eng, err := New(cfg)
	require.NoError(t, err)

	err = eng.Run(context.Background())
	require.Error(t, err)
	assert.Contains(t, err.Error(), "listen")
}
