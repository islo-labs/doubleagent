// Package config parses DoubleAgent HCL configuration files.
package config

import (
	"fmt"
	"os"

	"github.com/hashicorp/hcl/v2"
	"github.com/hashicorp/hcl/v2/gohcl"
	"github.com/hashicorp/hcl/v2/hclsyntax"
)

// Config is the top-level configuration.
type Config struct {
	Services []Service `hcl:"service,block"`
}

// Service represents a single service block in the config.
type Service struct {
	Type    string            `hcl:"type,label"`
	Name    string            `hcl:"name,label"`
	Port    int               `hcl:"port"`
	Version string            `hcl:"version,optional"`
	Command []string          `hcl:"command,optional"`
	Env     map[string]string `hcl:"env,optional"`
}

// Load parses an HCL config file and returns the Config.
func Load(path string) (*Config, error) {
	src, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading config: %w", err)
	}
	file, diags := hclsyntax.ParseConfig(src, path, hcl.Pos{Line: 1, Column: 1})
	if diags.HasErrors() {
		return nil, fmt.Errorf("parsing config: %s", diags.Error())
	}
	var cfg Config
	diags = gohcl.DecodeBody(file.Body, nil, &cfg)
	if diags.HasErrors() {
		return nil, fmt.Errorf("decoding config: %s", diags.Error())
	}
	return &cfg, nil
}
