package sdk

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os/exec"
	"strings"
	"sync"
)

// ExternalPlugin implements the Plugin interface by proxying calls to
// a subprocess over stdio using the JSON-line protocol.
type ExternalPlugin struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout *bufio.Scanner

	mu   sync.Mutex // serializes requests
	next int        // next request ID

	info PluginInfo // cached after first Info() call
}

// StartExternalPlugin spawns the plugin subprocess and returns an adapter
// that implements the Plugin interface.
func StartExternalPlugin(command []string) (*ExternalPlugin, error) {
	if len(command) == 0 {
		return nil, fmt.Errorf("empty command")
	}
	cmd := exec.Command(command[0], command[1:]...)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("stdin pipe: %w", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("stdout pipe: %w", err)
	}
	// Forward plugin stderr to host stderr for debugging.
	cmd.Stderr = nil // inherits parent stderr by default when nil... actually no.
	// Let's explicitly pipe stderr through.
	cmd.Stderr = writerFunc(func(p []byte) (int, error) {
		// Could log or prefix, but for now just pass through.
		return len(p), nil // discard plugin stderr to avoid noise
	})
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("starting plugin: %w", err)
	}
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 1024*1024), 10*1024*1024)
	return &ExternalPlugin{
		cmd:    cmd,
		stdin:  stdin,
		stdout: scanner,
		next:   1,
	}, nil
}

type writerFunc func([]byte) (int, error)

func (f writerFunc) Write(p []byte) (int, error) { return f(p) }

// call sends a request and reads the response. Must be called with mu held.
func (e *ExternalPlugin) call(method string, params interface{}) (*Response, error) {
	id := e.next
	e.next++

	req := Request{ID: id, Method: method}
	if params != nil {
		data, err := json.Marshal(params)
		if err != nil {
			return nil, fmt.Errorf("marshaling params: %w", err)
		}
		req.Params = data
	}

	line, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshaling request: %w", err)
	}
	line = append(line, '\n')
	if _, err := e.stdin.Write(line); err != nil {
		return nil, fmt.Errorf("writing to plugin stdin: %w", err)
	}

	if !e.stdout.Scan() {
		if err := e.stdout.Err(); err != nil {
			return nil, fmt.Errorf("reading plugin stdout: %w", err)
		}
		return nil, fmt.Errorf("plugin closed stdout unexpectedly")
	}

	var resp Response
	if err := json.Unmarshal(e.stdout.Bytes(), &resp); err != nil {
		return nil, fmt.Errorf("unmarshaling response: %w", err)
	}
	if resp.Error != "" {
		return nil, fmt.Errorf("plugin error: %s", resp.Error)
	}
	return &resp, nil
}

// Info implements Plugin.
func (e *ExternalPlugin) Info() PluginInfo {
	return e.info
}

// Configure implements Plugin.
func (e *ExternalPlugin) Configure(env map[string]string) error {
	e.mu.Lock()
	defer e.mu.Unlock()

	// First, call info to cache plugin metadata.
	resp, err := e.call("info", nil)
	if err != nil {
		return fmt.Errorf("getting plugin info: %w", err)
	}
	if err := json.Unmarshal(resp.Result, &e.info); err != nil {
		return fmt.Errorf("unmarshaling plugin info: %w", err)
	}

	// Then configure.
	_, err = e.call("configure", ConfigureParams{Env: env})
	return err
}

// ServeHTTP implements Plugin (http.Handler).
func (e *ExternalPlugin) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	e.mu.Lock()
	defer e.mu.Unlock()

	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, fmt.Sprintf("reading body: %v", err), http.StatusInternalServerError)
		return
	}

	params := HTTPRequestParams{
		Method: r.Method,
		Path:   r.URL.Path,
		Body:   string(body),
	}
	if r.URL.RawQuery != "" {
		params.Path = r.URL.Path + "?" + r.URL.RawQuery
	}
	params.Headers = make(map[string]string)
	for k := range r.Header {
		params.Headers[k] = r.Header.Get(k)
	}

	resp, err := e.call("http", params)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	var result HTTPResult
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		http.Error(w, fmt.Sprintf("unmarshaling http result: %v", err), http.StatusBadGateway)
		return
	}

	for k, v := range result.Headers {
		w.Header().Set(k, v)
	}
	w.WriteHeader(result.Status)
	if result.Body != "" {
		io.Copy(w, strings.NewReader(result.Body))
	}
}

// Reset implements Plugin.
func (e *ExternalPlugin) Reset() error {
	e.mu.Lock()
	defer e.mu.Unlock()
	_, err := e.call("reset", nil)
	return err
}

// Stop terminates the plugin subprocess.
func (e *ExternalPlugin) Stop() error {
	e.stdin.Close()
	return e.cmd.Wait()
}
