// Package jira provides a fake Jira API plugin.
package jira

import (
	"encoding/json"
	"net/http"

	"github.com/islo-labs/double-agent/pkg/sdk"
)

// JiraPlugin is a fake Jira API service.
type JiraPlugin struct {
	store      *Store
	router     *http.ServeMux
	projectKey string
}

// New creates a new JiraPlugin.
func New() sdk.Plugin {
	p := &JiraPlugin{store: NewStore()}
	p.setupRoutes()
	return p
}

func (p *JiraPlugin) Info() sdk.PluginInfo {
	return sdk.PluginInfo{Name: "jira", Version: "v1"}
}

func (p *JiraPlugin) Configure(env map[string]string) error {
	if key, ok := env["PROJECT_KEY"]; ok {
		p.projectKey = key
		// Pre-create the default project.
		p.store.CreateProject(key, key)
	}
	return nil
}

func (p *JiraPlugin) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p.router.ServeHTTP(w, r)
}

func (p *JiraPlugin) Reset() error {
	p.store.Reset()
	// Re-create default project after reset if configured.
	if p.projectKey != "" {
		p.store.CreateProject(p.projectKey, p.projectKey)
	}
	return nil
}

func (p *JiraPlugin) setupRoutes() {
	p.router = http.NewServeMux()
	p.router.HandleFunc("POST /rest/api/2/project", p.createProject)
	p.router.HandleFunc("GET /rest/api/2/project", p.listProjects)
	p.router.HandleFunc("GET /rest/api/2/project/{key}", p.getProject)
	p.router.HandleFunc("POST /rest/api/2/issue", p.createIssue)
	p.router.HandleFunc("GET /rest/api/2/issue/{key}", p.getIssue)
	p.router.HandleFunc("GET /rest/api/2/search", p.searchIssues)
}

type createProjectRequest struct {
	Key  string `json:"key"`
	Name string `json:"name"`
}

func (p *JiraPlugin) createProject(w http.ResponseWriter, r *http.Request) {
	var req createProjectRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"errorMessages":["invalid JSON"]}`, http.StatusBadRequest)
		return
	}
	if req.Key == "" || req.Name == "" {
		http.Error(w, `{"errorMessages":["key and name are required"]}`, http.StatusBadRequest)
		return
	}
	proj, err := p.store.CreateProject(req.Key, req.Name)
	if err != nil {
		http.Error(w, `{"errorMessages":["`+err.Error()+`"]}`, http.StatusConflict)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(proj)
}

func (p *JiraPlugin) listProjects(w http.ResponseWriter, r *http.Request) {
	projects := p.store.ListProjects()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(projects)
}

func (p *JiraPlugin) getProject(w http.ResponseWriter, r *http.Request) {
	key := r.PathValue("key")
	proj, ok := p.store.GetProject(key)
	if !ok {
		http.Error(w, `{"errorMessages":["Project not found"]}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(proj)
}

type createIssueRequest struct {
	Fields struct {
		Project struct {
			Key string `json:"key"`
		} `json:"project"`
		Summary     string `json:"summary"`
		Description string `json:"description"`
		IssueType   struct {
			Name string `json:"name"`
		} `json:"issuetype"`
	} `json:"fields"`
}

func (p *JiraPlugin) createIssue(w http.ResponseWriter, r *http.Request) {
	var req createIssueRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"errorMessages":["invalid JSON"]}`, http.StatusBadRequest)
		return
	}
	projectKey := req.Fields.Project.Key
	if projectKey == "" {
		projectKey = p.projectKey
	}
	if projectKey == "" {
		http.Error(w, `{"errorMessages":["project key is required"]}`, http.StatusBadRequest)
		return
	}
	issueType := req.Fields.IssueType.Name
	if issueType == "" {
		issueType = "Task"
	}
	issue, err := p.store.CreateIssue(projectKey, req.Fields.Summary, req.Fields.Description, issueType)
	if err != nil {
		http.Error(w, `{"errorMessages":["`+err.Error()+`"]}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(issue)
}

func (p *JiraPlugin) getIssue(w http.ResponseWriter, r *http.Request) {
	key := r.PathValue("key")
	issue, ok := p.store.GetIssue(key)
	if !ok {
		http.Error(w, `{"errorMessages":["Issue not found"]}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(issue)
}

func (p *JiraPlugin) searchIssues(w http.ResponseWriter, r *http.Request) {
	// Simple search: return all issues for the default project.
	projectKey := r.URL.Query().Get("jql")
	if projectKey == "" {
		projectKey = p.projectKey
	}
	var allIssues []*Issue
	if projectKey != "" {
		allIssues = p.store.ListIssues(projectKey)
	}
	if allIssues == nil {
		allIssues = []*Issue{}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"issues":     allIssues,
		"total":      len(allIssues),
		"maxResults": len(allIssues),
		"startAt":    0,
	})
}
