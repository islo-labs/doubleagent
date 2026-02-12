package main

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/islo-labs/double-agent/pkg/sdk"
)

// TodoPlugin is a fake todo API service.
type TodoPlugin struct {
	store  *Store
	router *http.ServeMux
}

// NewTodoPlugin creates a new TodoPlugin.
func NewTodoPlugin() *TodoPlugin {
	p := &TodoPlugin{store: NewStore()}
	p.setupRoutes()
	return p
}

func (p *TodoPlugin) Info() sdk.PluginInfo {
	return sdk.PluginInfo{Name: "todo", Version: "v1"}
}

func (p *TodoPlugin) Configure(env map[string]string) error {
	return nil
}

func (p *TodoPlugin) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p.router.ServeHTTP(w, r)
}

func (p *TodoPlugin) Reset() error {
	p.store.Reset()
	return nil
}

func (p *TodoPlugin) setupRoutes() {
	p.router = http.NewServeMux()
	p.router.HandleFunc("POST /todos", p.createTodo)
	p.router.HandleFunc("GET /todos", p.listTodos)
	p.router.HandleFunc("GET /todos/{id}", p.getTodo)
	p.router.HandleFunc("PATCH /todos/{id}", p.updateTodo)
	p.router.HandleFunc("DELETE /todos/{id}", p.deleteTodo)
}

type createTodoRequest struct {
	Title string `json:"title"`
}

func (p *TodoPlugin) createTodo(w http.ResponseWriter, r *http.Request) {
	var req createTodoRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		jsonError(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	if req.Title == "" {
		jsonError(w, "title is required", http.StatusUnprocessableEntity)
		return
	}
	todo := p.store.Create(req.Title)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(todo)
}

func (p *TodoPlugin) listTodos(w http.ResponseWriter, r *http.Request) {
	todos := p.store.List()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(todos)
}

func (p *TodoPlugin) getTodo(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		jsonError(w, "invalid id", http.StatusBadRequest)
		return
	}
	todo, ok := p.store.Get(id)
	if !ok {
		jsonError(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(todo)
}

type updateTodoRequest struct {
	Title     *string `json:"title,omitempty"`
	Completed *bool   `json:"completed,omitempty"`
}

func (p *TodoPlugin) updateTodo(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		jsonError(w, "invalid id", http.StatusBadRequest)
		return
	}
	var req updateTodoRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		jsonError(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	todo, err := p.store.Update(id, req.Title, req.Completed)
	if err != nil {
		jsonError(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(todo)
}

func (p *TodoPlugin) deleteTodo(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		jsonError(w, "invalid id", http.StatusBadRequest)
		return
	}
	if err := p.store.Delete(id); err != nil {
		jsonError(w, "not found", http.StatusNotFound)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func jsonError(w http.ResponseWriter, msg string, code int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
