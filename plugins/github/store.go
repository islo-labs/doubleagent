package github

import (
	"fmt"
	"sync"
	"time"
)

// Repo represents a GitHub repository.
type Repo struct {
	ID        int       `json:"id"`
	Owner     string    `json:"owner"`
	Name      string    `json:"name"`
	FullName  string    `json:"full_name"`
	Private   bool      `json:"private"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// Issue represents a GitHub issue.
type Issue struct {
	ID        int       `json:"id"`
	Number    int       `json:"number"`
	Title     string    `json:"title"`
	Body      string    `json:"body"`
	State     string    `json:"state"`
	Owner     string    `json:"owner"`
	Repo      string    `json:"repo"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// PullRequest represents a GitHub pull request.
type PullRequest struct {
	ID        int       `json:"id"`
	Number    int       `json:"number"`
	Title     string    `json:"title"`
	Body      string    `json:"body"`
	State     string    `json:"state"`
	Head      string    `json:"head"`
	Base      string    `json:"base"`
	Owner     string    `json:"owner"`
	Repo      string    `json:"repo"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// Store holds in-memory state for a GitHub plugin instance.
type Store struct {
	mu     sync.RWMutex
	repos  map[string]*Repo          // key: "owner/name"
	issues map[string][]*Issue       // key: "owner/repo"
	prs    map[string][]*PullRequest // key: "owner/repo"
	nextID int
}

// NewStore creates an empty Store.
func NewStore() *Store {
	return &Store{
		repos:  make(map[string]*Repo),
		issues: make(map[string][]*Issue),
		prs:    make(map[string][]*PullRequest),
		nextID: 1,
	}
}

// Reset clears all state.
func (s *Store) Reset() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.repos = make(map[string]*Repo)
	s.issues = make(map[string][]*Issue)
	s.prs = make(map[string][]*PullRequest)
	s.nextID = 1
}

func (s *Store) allocID() int {
	id := s.nextID
	s.nextID++
	return id
}

// CreateRepo creates a new repository.
func (s *Store) CreateRepo(owner, name string, private bool) (*Repo, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := repoKey(owner, name)
	if _, exists := s.repos[key]; exists {
		return nil, fmt.Errorf("repository %s already exists", key)
	}
	now := time.Now().UTC()
	r := &Repo{
		ID:        s.allocID(),
		Owner:     owner,
		Name:      name,
		FullName:  key,
		Private:   private,
		CreatedAt: now,
		UpdatedAt: now,
	}
	s.repos[key] = r
	return r, nil
}

// GetRepo returns a repository by owner and name.
func (s *Store) GetRepo(owner, name string) (*Repo, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	r, ok := s.repos[repoKey(owner, name)]
	return r, ok
}

// CreateIssue creates a new issue on a repository.
func (s *Store) CreateIssue(owner, repo, title, body string) (*Issue, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := repoKey(owner, repo)
	if _, ok := s.repos[key]; !ok {
		return nil, fmt.Errorf("repository %s not found", key)
	}
	now := time.Now().UTC()
	number := len(s.issues[key]) + len(s.prs[key]) + 1
	issue := &Issue{
		ID:        s.allocID(),
		Number:    number,
		Title:     title,
		Body:      body,
		State:     "open",
		Owner:     owner,
		Repo:      repo,
		CreatedAt: now,
		UpdatedAt: now,
	}
	s.issues[key] = append(s.issues[key], issue)
	return issue, nil
}

// GetIssues returns all issues for a repository.
func (s *Store) GetIssues(owner, repo string) []*Issue {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.issues[repoKey(owner, repo)]
}

// CreatePullRequest creates a new pull request on a repository.
func (s *Store) CreatePullRequest(owner, repo, title, body, head, base string) (*PullRequest, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := repoKey(owner, repo)
	if _, ok := s.repos[key]; !ok {
		return nil, fmt.Errorf("repository %s not found", key)
	}
	now := time.Now().UTC()
	number := len(s.issues[key]) + len(s.prs[key]) + 1
	pr := &PullRequest{
		ID:        s.allocID(),
		Number:    number,
		Title:     title,
		Body:      body,
		State:     "open",
		Head:      head,
		Base:      base,
		Owner:     owner,
		Repo:      repo,
		CreatedAt: now,
		UpdatedAt: now,
	}
	s.prs[key] = append(s.prs[key], pr)
	return pr, nil
}

// GetPullRequest returns a pull request by number.
func (s *Store) GetPullRequest(owner, repo string, number int) (*PullRequest, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, pr := range s.prs[repoKey(owner, repo)] {
		if pr.Number == number {
			return pr, true
		}
	}
	return nil, false
}

func repoKey(owner, name string) string {
	return owner + "/" + name
}
