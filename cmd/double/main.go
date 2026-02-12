// Command double is the DoubleAgent CLI.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"

	"github.com/islo-labs/double-agent/internal/config"
	"github.com/islo-labs/double-agent/internal/engine"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	configFile := flag.String("config", "double.hcl", "path to config file")
	flag.Parse()

	args := flag.Args()
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "usage: double run [-config double.hcl]")
		os.Exit(1)
	}
	cmd := args[0]
	if cmd != "run" {
		return fmt.Errorf("unknown command: %q (expected 'run')", cmd)
	}

	cfg, err := config.Load(*configFile)
	if err != nil {
		return fmt.Errorf("loading config: %w", err)
	}
	if len(cfg.Services) == 0 {
		return fmt.Errorf("no services defined in %s", *configFile)
	}

	eng, err := engine.New(cfg)
	if err != nil {
		return err
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()

	log.Printf("DoubleAgent starting with %d service(s)", len(cfg.Services))
	return eng.Run(ctx)
}
