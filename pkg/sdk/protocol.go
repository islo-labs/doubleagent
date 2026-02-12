package sdk

import "encoding/json"

// Request is a JSON-line message sent from the host to a plugin over stdin.
type Request struct {
	ID     int             `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params,omitempty"`
}

// Response is a JSON-line message sent from a plugin to the host over stdout.
type Response struct {
	ID     int             `json:"id"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  string          `json:"error,omitempty"`
}

// ConfigureParams are the parameters for the "configure" method.
type ConfigureParams struct {
	Env map[string]string `json:"env"`
}

// HTTPRequestParams are the parameters for the "http" method.
type HTTPRequestParams struct {
	Method  string            `json:"method"`
	Path    string            `json:"path"`
	Headers map[string]string `json:"headers,omitempty"`
	Body    string            `json:"body,omitempty"`
}

// HTTPResult is the result of the "http" method.
type HTTPResult struct {
	Status  int               `json:"status"`
	Headers map[string]string `json:"headers,omitempty"`
	Body    string            `json:"body"`
}
