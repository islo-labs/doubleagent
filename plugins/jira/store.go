package jira

import (
	"fmt"
	"sync"
	"time"
)

// Project represents a Jira project.
type Project struct {
	ID   int    `json:"id"`
	Key  string `json:"key"`
	Name string `json:"name"`
}

// Issue represents a Jira issue.
type Issue struct {
	ID         int       `json:"id"`
	Key        string    `json:"key"`
	ProjectKey string    `json:"project_key"`
	Summary    string    `json:"summary"`
	Description string   `json:"description"`
	Status     string    `json:"status"`
	IssueType  string    `json:"issue_type"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

// Store holds in-memory state for a Jira plugin instance.
type Store struct {
	mu       sync.RWMutex
	projects map[string]*Project // key: project key
	issues   map[string][]*Issue // key: project key
	nextID   int
	issueCtr map[string]int // per-project issue counter
}

// NewStore creates an empty Store.
func NewStore() *Store {
	return &Store{
		projects: make(map[string]*Project),
		issues:   make(map[string][]*Issue),
		issueCtr: make(map[string]int),
		nextID:   1,
	}
}

// Reset clears all state.
func (s *Store) Reset() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.projects = make(map[string]*Project)
	s.issues = make(map[string][]*Issue)
	s.issueCtr = make(map[string]int)
	s.nextID = 1
}

func (s *Store) allocID() int {
	id := s.nextID
	s.nextID++
	return id
}

// CreateProject creates a new project.
func (s *Store) CreateProject(key, name string) (*Project, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.projects[key]; exists {
		return nil, fmt.Errorf("project %s already exists", key)
	}
	p := &Project{
		ID:   s.allocID(),
		Key:  key,
		Name: name,
	}
	s.projects[key] = p
	return p, nil
}

// GetProject returns a project by key.
func (s *Store) GetProject(key string) (*Project, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.projects[key]
	return p, ok
}

// ListProjects returns all projects.
func (s *Store) ListProjects() []*Project {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]*Project, 0, len(s.projects))
	for _, p := range s.projects {
		out = append(out, p)
	}
	return out
}

// CreateIssue creates a new issue in a project.
func (s *Store) CreateIssue(projectKey, summary, description, issueType string) (*Issue, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.projects[projectKey]; !ok {
		return nil, fmt.Errorf("project %s not found", projectKey)
	}
	s.issueCtr[projectKey]++
	issueKey := fmt.Sprintf("%s-%d", projectKey, s.issueCtr[projectKey])
	now := time.Now().UTC()
	issue := &Issue{
		ID:          s.allocID(),
		Key:         issueKey,
		ProjectKey:  projectKey,
		Summary:     summary,
		Description: description,
		Status:      "To Do",
		IssueType:   issueType,
		CreatedAt:   now,
		UpdatedAt:   now,
	}
	s.issues[projectKey] = append(s.issues[projectKey], issue)
	return issue, nil
}

// GetIssue returns an issue by key.
func (s *Store) GetIssue(issueKey string) (*Issue, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, issues := range s.issues {
		for _, issue := range issues {
			if issue.Key == issueKey {
				return issue, true
			}
		}
	}
	return nil, false
}

// ListIssues returns all issues for a project.
func (s *Store) ListIssues(projectKey string) []*Issue {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.issues[projectKey]
}
