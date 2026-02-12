package main

import (
	"fmt"
	"sync"
	"time"
)

// Todo represents a todo item.
type Todo struct {
	ID        int       `json:"id"`
	Title     string    `json:"title"`
	Completed bool      `json:"completed"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// Store holds in-memory state for the todo plugin.
type Store struct {
	mu     sync.RWMutex
	todos  map[int]*Todo
	nextID int
}

// NewStore creates an empty Store.
func NewStore() *Store {
	return &Store{
		todos:  make(map[int]*Todo),
		nextID: 1,
	}
}

// Reset clears all state.
func (s *Store) Reset() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.todos = make(map[int]*Todo)
	s.nextID = 1
}

// Create adds a new todo.
func (s *Store) Create(title string) *Todo {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UTC()
	t := &Todo{
		ID:        s.nextID,
		Title:     title,
		Completed: false,
		CreatedAt: now,
		UpdatedAt: now,
	}
	s.todos[t.ID] = t
	s.nextID++
	return t
}

// Get returns a todo by ID.
func (s *Store) Get(id int) (*Todo, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.todos[id]
	return t, ok
}

// List returns all todos ordered by ID.
func (s *Store) List() []*Todo {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]*Todo, 0, len(s.todos))
	for i := 1; i < s.nextID; i++ {
		if t, ok := s.todos[i]; ok {
			result = append(result, t)
		}
	}
	return result
}

// Update modifies a todo. Only non-nil fields are updated.
func (s *Store) Update(id int, title *string, completed *bool) (*Todo, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	t, ok := s.todos[id]
	if !ok {
		return nil, fmt.Errorf("todo %d not found", id)
	}
	if title != nil {
		t.Title = *title
	}
	if completed != nil {
		t.Completed = *completed
	}
	t.UpdatedAt = time.Now().UTC()
	return t, nil
}

// Delete removes a todo by ID.
func (s *Store) Delete(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.todos[id]; !ok {
		return fmt.Errorf("todo %d not found", id)
	}
	delete(s.todos, id)
	return nil
}
