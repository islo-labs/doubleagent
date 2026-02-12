package builtin

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRegistry_ContainsExpectedPlugins(t *testing.T) {
	assert.Len(t, Registry, 2)
	assert.Contains(t, Registry, "github")
	assert.Contains(t, Registry, "jira")
}

func TestRegistry_GitHubConstructor(t *testing.T) {
	newFn, ok := Registry["github"]
	require.True(t, ok)
	p := newFn()
	require.NotNil(t, p)
	assert.Equal(t, "github", p.Info().Name)
}

func TestRegistry_JiraConstructor(t *testing.T) {
	newFn, ok := Registry["jira"]
	require.True(t, ok)
	p := newFn()
	require.NotNil(t, p)
	assert.Equal(t, "jira", p.Info().Name)
}

func TestRegistry_UnknownType(t *testing.T) {
	_, ok := Registry["unknown"]
	assert.False(t, ok)
}
