// Command todo is an external DoubleAgent plugin that provides a fake todo API.
// It communicates with the host over stdio using the JSON-line protocol.
package main

import "github.com/islo-labs/double-agent/pkg/sdk"

func main() {
	sdk.Serve(NewTodoPlugin())
}
