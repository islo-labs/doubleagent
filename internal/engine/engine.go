// Package engine manages the lifecycle of plugin instances.
package engine

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"sync"

	"github.com/islo-labs/double-agent/internal/builtin"
	"github.com/islo-labs/double-agent/internal/config"
	"github.com/islo-labs/double-agent/pkg/sdk"
)

// Instance is a running plugin instance.
type Instance struct {
	Config   config.Service
	Plugin   sdk.Plugin
	Server   *http.Server
	external *sdk.ExternalPlugin // non-nil for external plugins
}

// Engine manages plugin instances.
type Engine struct {
	instances []*Instance
}

// New creates an Engine from the given config.
func New(cfg *config.Config) (*Engine, error) {
	e := &Engine{}
	for _, svc := range cfg.Services {
		var (
			p   sdk.Plugin
			ext *sdk.ExternalPlugin
		)
		if len(svc.Command) > 0 {
			// External plugin: spawn subprocess.
			var err error
			ext, err = sdk.StartExternalPlugin(svc.Command)
			if err != nil {
				return nil, fmt.Errorf("starting external plugin %s/%s: %w", svc.Type, svc.Name, err)
			}
			p = ext
		} else {
			// Built-in plugin: look up registry.
			newFn, ok := builtin.Registry[svc.Type]
			if !ok {
				return nil, fmt.Errorf("unknown plugin type: %q", svc.Type)
			}
			p = newFn()
		}
		if err := p.Configure(svc.Env); err != nil {
			return nil, fmt.Errorf("configuring %s/%s: %w", svc.Type, svc.Name, err)
		}
		mux := http.NewServeMux()
		mux.HandleFunc("POST /_/reset", func(w http.ResponseWriter, r *http.Request) {
			if err := p.Reset(); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			w.WriteHeader(http.StatusOK)
			fmt.Fprintln(w, `{"status":"ok"}`)
		})
		mux.Handle("/", p)
		inst := &Instance{
			Config:   svc,
			Plugin:   p,
			external: ext,
			Server: &http.Server{
				Addr:    fmt.Sprintf(":%d", svc.Port),
				Handler: mux,
			},
		}
		e.instances = append(e.instances, inst)
	}
	return e, nil
}

// Run starts all HTTP servers and blocks until the context is cancelled.
func (e *Engine) Run(ctx context.Context) error {
	var wg sync.WaitGroup
	errCh := make(chan error, len(e.instances))

	for _, inst := range e.instances {
		info := inst.Plugin.Info()
		addr := inst.Server.Addr
		log.Printf("starting %s/%s (%s) on %s", inst.Config.Type, inst.Config.Name, info.Version, addr)

		ln, err := net.Listen("tcp", addr)
		if err != nil {
			return fmt.Errorf("listen %s: %w", addr, err)
		}

		wg.Add(1)
		go func(srv *http.Server, ln net.Listener) {
			defer wg.Done()
			if err := srv.Serve(ln); err != nil && err != http.ErrServerClosed {
				errCh <- err
			}
		}(inst.Server, ln)
	}

	// Wait for context cancellation.
	<-ctx.Done()
	log.Println("shutting down...")

	// Shutdown all servers, then stop external plugins.
	for _, inst := range e.instances {
		if err := inst.Server.Shutdown(context.Background()); err != nil {
			log.Printf("error shutting down %s/%s: %v", inst.Config.Type, inst.Config.Name, err)
		}
		if inst.external != nil {
			if err := inst.external.Stop(); err != nil {
				log.Printf("error stopping external plugin %s/%s: %v", inst.Config.Type, inst.Config.Name, err)
			}
		}
	}
	wg.Wait()

	select {
	case err := <-errCh:
		return err
	default:
		return nil
	}
}
