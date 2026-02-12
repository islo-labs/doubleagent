package sdk

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
)

// Serve runs a Plugin as an external stdio plugin. It reads JSON requests from
// stdin, dispatches them to the plugin, and writes JSON responses to stdout.
// This function blocks until stdin is closed.
func Serve(p Plugin) {
	enc := json.NewEncoder(os.Stdout)
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 0, 1024*1024), 10*1024*1024)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var req Request
		if err := json.Unmarshal(line, &req); err != nil {
			enc.Encode(Response{Error: fmt.Sprintf("invalid request: %v", err)})
			continue
		}
		resp := dispatch(p, req)
		enc.Encode(resp)
	}
}

func dispatch(p Plugin, req Request) Response {
	switch req.Method {
	case "info":
		return handleInfo(p, req)
	case "configure":
		return handleConfigure(p, req)
	case "http":
		return handleHTTP(p, req)
	case "reset":
		return handleReset(p, req)
	default:
		return Response{ID: req.ID, Error: fmt.Sprintf("unknown method: %q", req.Method)}
	}
}

func handleInfo(p Plugin, req Request) Response {
	info := p.Info()
	data, _ := json.Marshal(info)
	return Response{ID: req.ID, Result: data}
}

func handleConfigure(p Plugin, req Request) Response {
	var params ConfigureParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return Response{ID: req.ID, Error: fmt.Sprintf("invalid configure params: %v", err)}
	}
	if err := p.Configure(params.Env); err != nil {
		return Response{ID: req.ID, Error: err.Error()}
	}
	data, _ := json.Marshal(struct{}{})
	return Response{ID: req.ID, Result: data}
}

func handleHTTP(p Plugin, req Request) Response {
	var params HTTPRequestParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return Response{ID: req.ID, Error: fmt.Sprintf("invalid http params: %v", err)}
	}
	var body io.Reader
	if params.Body != "" {
		body = strings.NewReader(params.Body)
	}
	httpReq, err := http.NewRequest(params.Method, params.Path, body)
	if err != nil {
		return Response{ID: req.ID, Error: fmt.Sprintf("creating request: %v", err)}
	}
	for k, v := range params.Headers {
		httpReq.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	p.ServeHTTP(rec, httpReq)
	result := rec.Result()
	respBody, _ := io.ReadAll(result.Body)
	headers := make(map[string]string)
	for k := range result.Header {
		headers[k] = result.Header.Get(k)
	}
	httpResult := HTTPResult{
		Status:  result.StatusCode,
		Headers: headers,
		Body:    string(respBody),
	}
	data, _ := json.Marshal(httpResult)
	return Response{ID: req.ID, Result: data}
}

func handleReset(p Plugin, req Request) Response {
	if err := p.Reset(); err != nil {
		return Response{ID: req.ID, Error: err.Error()}
	}
	data, _ := json.Marshal(struct{}{})
	return Response{ID: req.ID, Result: data}
}
