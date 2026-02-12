// Package github provides a fake GitHub API plugin.
package github

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/islo-labs/double-agent/pkg/sdk"
)

// GitHubPlugin is a fake GitHub API service.
type GitHubPlugin struct {
	store      *Store
	router     *http.ServeMux
	defaultOrg string
}

// New creates a new GitHubPlugin.
func New() sdk.Plugin {
	p := &GitHubPlugin{store: NewStore()}
	p.setupRoutes()
	return p
}

func (p *GitHubPlugin) Info() sdk.PluginInfo {
	return sdk.PluginInfo{Name: "github", Version: "v1"}
}

func (p *GitHubPlugin) Configure(env map[string]string) error {
	if org, ok := env["DEFAULT_ORG"]; ok {
		p.defaultOrg = org
	}
	return nil
}

func (p *GitHubPlugin) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p.router.ServeHTTP(w, r)
}

func (p *GitHubPlugin) Reset() error {
	p.store.Reset()
	return nil
}

func (p *GitHubPlugin) setupRoutes() {
	p.router = http.NewServeMux()
	p.router.HandleFunc("POST /repos", p.createRepo)
	p.router.HandleFunc("GET /repos/{owner}/{repo}", p.getRepo)
	p.router.HandleFunc("POST /repos/{owner}/{repo}/issues", p.createIssue)
	p.router.HandleFunc("GET /repos/{owner}/{repo}/issues", p.listIssues)
	p.router.HandleFunc("POST /repos/{owner}/{repo}/pulls", p.createPR)
	p.router.HandleFunc("GET /repos/{owner}/{repo}/pulls/{number}", p.getPR)
}

type createRepoRequest struct {
	Owner   string `json:"owner"`
	Name    string `json:"name"`
	Private bool   `json:"private"`
}

func (p *GitHubPlugin) createRepo(w http.ResponseWriter, r *http.Request) {
	var req createRepoRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"message":"invalid JSON"}`, http.StatusBadRequest)
		return
	}
	if req.Owner == "" {
		req.Owner = p.defaultOrg
	}
	if req.Owner == "" || req.Name == "" {
		http.Error(w, `{"message":"owner and name are required"}`, http.StatusUnprocessableEntity)
		return
	}
	repo, err := p.store.CreateRepo(req.Owner, req.Name, req.Private)
	if err != nil {
		http.Error(w, `{"message":"`+err.Error()+`"}`, http.StatusConflict)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(repo)
}

func (p *GitHubPlugin) getRepo(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	rep, ok := p.store.GetRepo(owner, repo)
	if !ok {
		http.Error(w, `{"message":"Not Found"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(rep)
}

type createIssueRequest struct {
	Title string `json:"title"`
	Body  string `json:"body"`
}

func (p *GitHubPlugin) createIssue(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	var req createIssueRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"message":"invalid JSON"}`, http.StatusBadRequest)
		return
	}
	issue, err := p.store.CreateIssue(owner, repo, req.Title, req.Body)
	if err != nil {
		http.Error(w, `{"message":"`+err.Error()+`"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(issue)
}

func (p *GitHubPlugin) listIssues(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	issues := p.store.GetIssues(owner, repo)
	if issues == nil {
		issues = []*Issue{}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(issues)
}

type createPRRequest struct {
	Title string `json:"title"`
	Body  string `json:"body"`
	Head  string `json:"head"`
	Base  string `json:"base"`
}

func (p *GitHubPlugin) createPR(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	var req createPRRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"message":"invalid JSON"}`, http.StatusBadRequest)
		return
	}
	pr, err := p.store.CreatePullRequest(owner, repo, req.Title, req.Body, req.Head, req.Base)
	if err != nil {
		http.Error(w, `{"message":"`+err.Error()+`"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(pr)
}

func (p *GitHubPlugin) getPR(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	numberStr := r.PathValue("number")
	number, err := strconv.Atoi(numberStr)
	if err != nil {
		http.Error(w, `{"message":"invalid PR number"}`, http.StatusBadRequest)
		return
	}
	pr, ok := p.store.GetPullRequest(owner, repo, number)
	if !ok {
		http.Error(w, `{"message":"Not Found"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(pr)
}
