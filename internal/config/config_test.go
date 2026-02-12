package config

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func writeHCL(t *testing.T, content string) string {
	t.Helper()
	dir := t.TempDir()
	p := filepath.Join(dir, "test.hcl")
	require.NoError(t, os.WriteFile(p, []byte(content), 0644))
	return p
}

func TestLoad_ValidConfig(t *testing.T) {
	path := writeHCL(t, `
service "github" "my-gh" {
  port    = 8080
  version = "v1"
  env = {
    DEFAULT_ORG = "acme"
  }
}
`)
	cfg, err := Load(path)
	require.NoError(t, err)
	require.Len(t, cfg.Services, 1)
	svc := cfg.Services[0]
	assert.Equal(t, "github", svc.Type)
	assert.Equal(t, "my-gh", svc.Name)
	assert.Equal(t, 8080, svc.Port)
	assert.Equal(t, "v1", svc.Version)
	assert.Equal(t, map[string]string{"DEFAULT_ORG": "acme"}, svc.Env)
}

func TestLoad_MultipleServices(t *testing.T) {
	path := writeHCL(t, `
service "github" "gh1" {
  port = 8080
}
service "jira" "jr1" {
  port = 8081
}
`)
	cfg, err := Load(path)
	require.NoError(t, err)
	require.Len(t, cfg.Services, 2)

	// Collect types into a set for order-independent comparison.
	types := map[string]bool{}
	for _, svc := range cfg.Services {
		types[svc.Type] = true
	}
	assert.True(t, types["github"])
	assert.True(t, types["jira"])
}

func TestLoad_OptionalFields(t *testing.T) {
	path := writeHCL(t, `
service "github" "gh" {
  port = 9090
}
`)
	cfg, err := Load(path)
	require.NoError(t, err)
	require.Len(t, cfg.Services, 1)
	assert.Equal(t, "", cfg.Services[0].Version)
	assert.Nil(t, cfg.Services[0].Env)
}

func TestLoad_FileNotFound(t *testing.T) {
	_, err := Load("/nonexistent/path.hcl")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "reading config")
}

func TestLoad_InvalidHCLSyntax(t *testing.T) {
	path := writeHCL(t, `this is not valid HCL {{{{`)
	_, err := Load(path)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "parsing config")
}

func TestLoad_InvalidHCLSchema(t *testing.T) {
	path := writeHCL(t, `
service "github" "gh" {
  port       = 8080
  bogusfield = "nope"
}
`)
	_, err := Load(path)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "decoding config")
}

func TestLoad_EmptyConfig(t *testing.T) {
	path := writeHCL(t, ``)
	cfg, err := Load(path)
	require.NoError(t, err)
	assert.Empty(t, cfg.Services)
}
