// Package builtin provides the built-in plugin registry.
package builtin

import (
	"github.com/islo-labs/double-agent/pkg/sdk"
	"github.com/islo-labs/double-agent/plugins/github"
	"github.com/islo-labs/double-agent/plugins/jira"
)

// Registry maps plugin type names to their constructor functions.
var Registry = map[string]func() sdk.Plugin{
	"github": github.New,
	"jira":   jira.New,
}
