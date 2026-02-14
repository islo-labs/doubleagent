"""
Contract tests for GitHub issue endpoints.

Uses official PyGithub SDK to verify the fake works correctly.
"""

import uuid
import pytest
from github import Github


class TestIssues:
    """Tests for issue CRUD operations."""
    
    @pytest.fixture(autouse=True)
    def setup_repo(self, github_client: Github):
        """Create a test repository for issue tests."""
        user = github_client.get_user()
        self.repo = user.create_repo(
            name=f"issue-test-{uuid.uuid4().hex[:8]}",
            auto_init=True,  # Need at least one commit for issues
        )
        yield
    
    def test_create_issue(self, github_client: Github):
        """Test creating an issue."""
        issue = self.repo.create_issue(
            title="Test Issue",
            body="This is a test issue body",
        )
        
        assert issue.title == "Test Issue"
        assert issue.body == "This is a test issue body"
        assert issue.state == "open"
        assert issue.number >= 1
    
    def test_get_issue(self, github_client: Github):
        """Test getting an issue by number."""
        created = self.repo.create_issue(title="Get Test")
        
        fetched = self.repo.get_issue(created.number)
        
        assert fetched.id == created.id
        assert fetched.title == "Get Test"
    
    def test_update_issue(self, github_client: Github):
        """Test updating an issue."""
        issue = self.repo.create_issue(title="Original Title")
        
        issue.edit(
            title="Updated Title",
            body="Updated body",
        )
        
        # Fetch fresh
        updated = self.repo.get_issue(issue.number)
        assert updated.title == "Updated Title"
        assert updated.body == "Updated body"
    
    def test_close_issue(self, github_client: Github):
        """Test closing an issue."""
        issue = self.repo.create_issue(title="To Close")
        assert issue.state == "open"
        
        issue.edit(state="closed")
        
        # Fetch fresh
        closed = self.repo.get_issue(issue.number)
        assert closed.state == "closed"
    
    def test_reopen_issue(self, github_client: Github):
        """Test reopening a closed issue."""
        issue = self.repo.create_issue(title="To Reopen")
        issue.edit(state="closed")
        
        # Reopen
        issue.edit(state="open")
        
        reopened = self.repo.get_issue(issue.number)
        assert reopened.state == "open"
    
    def test_list_issues_filters_by_state(self, github_client: Github):
        """Test listing issues with state filter."""
        # Create open and closed issues
        open_issue = self.repo.create_issue(title="Open Issue")
        closed_issue = self.repo.create_issue(title="Closed Issue")
        closed_issue.edit(state="closed")
        
        # List open issues
        open_issues = list(self.repo.get_issues(state="open"))
        open_titles = [i.title for i in open_issues]
        assert "Open Issue" in open_titles
        assert "Closed Issue" not in open_titles
        
        # List closed issues
        closed_issues = list(self.repo.get_issues(state="closed"))
        closed_titles = [i.title for i in closed_issues]
        assert "Closed Issue" in closed_titles
        assert "Open Issue" not in closed_titles
        
        # List all issues
        all_issues = list(self.repo.get_issues(state="all"))
        all_titles = [i.title for i in all_issues]
        assert "Open Issue" in all_titles
        assert "Closed Issue" in all_titles
