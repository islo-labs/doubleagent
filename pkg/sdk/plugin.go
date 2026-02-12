// Package sdk defines the public plugin interface for DoubleAgent.
package sdk

import "net/http"

// PluginInfo holds metadata about a plugin.
type PluginInfo struct {
	Name    string `json:"name"`    // "github", "jira", etc.
	Version string `json:"version"`
}

// Plugin is the interface every DoubleAgent service fake must implement.
// Plugins implement http.Handler directly so they can use any Go HTTP router internally.
type Plugin interface {
	// Info returns plugin metadata.
	Info() PluginInfo

	// Configure passes environment config to the plugin.
	Configure(env map[string]string) error

	// ServeHTTP handles HTTP requests (standard http.Handler).
	http.Handler

	// Reset clears all in-memory state.
	Reset() error
}
