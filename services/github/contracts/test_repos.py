"""
Contract tests for GitHub repository endpoints.

Uses official PyGithub SDK to validate DoubleAgent fake matches real API.
"""

import pytest
from github import Github
from doubleagent_contracts import contract_test, Target


@contract_test
class TestRepositories:
    """Tests for repository CRUD operations."""
    
    def test_create_repo(self, github_client: Github, target: Target):
        """Test creating a repository."""
        user = github_client.get_user()
        repo_name = f"test-repo-{target.run_id}"
        
        repo = user.create_repo(
            name=repo_name,
            description="Test repository",
            private=True,
        )
        
        assert repo.name == repo_name
        assert repo.description == "Test repository"
        assert repo.private == True
        
        # Cleanup for real API
        if target.is_real:
            repo.delete()
    
    def test_get_repo(self, github_client: Github, target: Target):
        """Test getting a repository by full name."""
        user = github_client.get_user()
        repo_name = f"test-repo-{target.run_id}"
        
        # Create repo first
        created = user.create_repo(name=repo_name, private=True)
        
        # Get repo by full name
        fetched = github_client.get_repo(created.full_name)
        
        assert fetched.id == created.id
        assert fetched.name == repo_name
        
        # Cleanup
        if target.is_real:
            created.delete()
    
    def test_update_repo(self, github_client: Github, target: Target):
        """Test updating repository properties."""
        user = github_client.get_user()
        repo_name = f"test-repo-{target.run_id}"
        
        repo = user.create_repo(name=repo_name, description="Original")
        
        # Update description
        repo.edit(description="Updated description")
        
        # Fetch fresh and verify
        updated = github_client.get_repo(repo.full_name)
        assert updated.description == "Updated description"
        
        # Cleanup
        if target.is_real:
            repo.delete()
    
    def test_delete_repo(self, github_client: Github, target: Target):
        """Test deleting a repository."""
        user = github_client.get_user()
        repo_name = f"test-repo-{target.run_id}"
        
        repo = user.create_repo(name=repo_name)
        full_name = repo.full_name
        
        # Delete
        repo.delete()
        
        # Verify deleted (should raise 404)
        with pytest.raises(Exception):  # GithubException for real, various for fake
            github_client.get_repo(full_name)
    
    def test_list_user_repos(self, github_client: Github, target: Target):
        """Test listing repositories for authenticated user."""
        user = github_client.get_user()
        
        # Create a few repos
        repo_names = [f"list-test-{i}-{target.run_id}" for i in range(3)]
        created_repos = []
        
        for name in repo_names:
            repo = user.create_repo(name=name)
            created_repos.append(repo)
        
        # List repos
        repos = list(user.get_repos())
        
        # Verify our repos are in the list
        found_names = {r.name for r in repos}
        for name in repo_names:
            assert name in found_names
        
        # Cleanup
        if target.is_real:
            for repo in created_repos:
                repo.delete()
