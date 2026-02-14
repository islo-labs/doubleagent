"""
Contract tests for GitHub repository endpoints.

Uses official PyGithub SDK to verify the fake works correctly.
"""

import uuid
import pytest
from github import Github


class TestRepositories:
    """Tests for repository CRUD operations."""
    
    def test_create_repo(self, github_client: Github):
        """Test creating a repository."""
        user = github_client.get_user()
        repo_name = f"test-repo-{uuid.uuid4().hex[:8]}"
        
        repo = user.create_repo(
            name=repo_name,
            description="Test repository",
            private=True,
        )
        
        assert repo.name == repo_name
        assert repo.description == "Test repository"
        assert repo.private == True
    
    def test_get_repo(self, github_client: Github):
        """Test getting a repository by full name."""
        user = github_client.get_user()
        repo_name = f"test-repo-{uuid.uuid4().hex[:8]}"
        
        # Create repo first
        created = user.create_repo(name=repo_name, private=True)
        
        # Get repo by full name
        fetched = github_client.get_repo(created.full_name)
        
        assert fetched.id == created.id
        assert fetched.name == repo_name
    
    def test_update_repo(self, github_client: Github):
        """Test updating repository properties."""
        user = github_client.get_user()
        repo_name = f"test-repo-{uuid.uuid4().hex[:8]}"
        
        repo = user.create_repo(name=repo_name, description="Original")
        
        # Update description
        repo.edit(description="Updated description")
        
        # Fetch fresh and verify
        updated = github_client.get_repo(repo.full_name)
        assert updated.description == "Updated description"
    
    def test_delete_repo(self, github_client: Github):
        """Test deleting a repository."""
        user = github_client.get_user()
        repo_name = f"test-repo-{uuid.uuid4().hex[:8]}"
        
        repo = user.create_repo(name=repo_name)
        full_name = repo.full_name
        
        # Delete
        repo.delete()
        
        # Verify deleted (should raise 404)
        with pytest.raises(Exception):  # GithubException
            github_client.get_repo(full_name)
    
    def test_list_user_repos(self, github_client: Github):
        """Test listing repositories for authenticated user."""
        user = github_client.get_user()
        run_id = uuid.uuid4().hex[:8]
        
        # Create a few repos
        repo_names = [f"list-test-{i}-{run_id}" for i in range(3)]
        
        for name in repo_names:
            user.create_repo(name=name)
        
        # List repos
        repos = list(user.get_repos())
        
        # Verify our repos are in the list
        found_names = {r.name for r in repos}
        for name in repo_names:
            assert name in found_names
