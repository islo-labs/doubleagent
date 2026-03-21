"""
Contract tests for Linear project endpoints.

Verifies that the fake correctly implements the Linear GraphQL API
for project CRUD operations.
"""

import pytest

from conftest import LinearClient


class TestListProjects:
    """Tests for listing projects."""

    def test_list_projects_empty(self, linear_client: LinearClient):
        """Returns an empty list when no projects exist."""
        projects = linear_client.projects()
        assert projects == []

    def test_list_projects_returns_created_projects(
        self, linear_client: LinearClient
    ):
        """Projects created via the API appear in the list."""
        linear_client.create_project(name="Project Alpha")
        linear_client.create_project(name="Project Beta")

        projects = linear_client.projects()

        names = [p["name"] for p in projects]
        assert "Project Alpha" in names
        assert "Project Beta" in names

    def test_list_projects_respects_first_limit(self, linear_client: LinearClient):
        """The `first` argument limits the number of returned projects."""
        for i in range(5):
            linear_client.create_project(name=f"Project {i}")

        projects = linear_client.projects(first=2)
        assert len(projects) == 2


class TestCreateProject:
    """Tests for creating projects."""

    def test_create_project_minimal(self, linear_client: LinearClient):
        """Create a project with only a name."""
        result = linear_client.create_project(name="Minimal Project")

        assert result["success"] is True
        project = result["project"]
        assert project["name"] == "Minimal Project"
        assert project["id"] is not None
        assert project["state"] == "planned"

    def test_create_project_with_description(self, linear_client: LinearClient):
        """Create a project with a description."""
        result = linear_client.create_project(
            name="Described Project",
            description="A detailed project description.",
        )

        assert result["success"] is True
        assert result["project"]["description"] == "A detailed project description."

    def test_create_project_with_state(self, linear_client: LinearClient):
        """Create a project in a specific state."""
        result = linear_client.create_project(
            name="Active Project",
            state="started",
        )

        assert result["success"] is True
        assert result["project"]["state"] == "started"

    def test_create_project_has_timestamps(self, linear_client: LinearClient):
        """A created project includes createdAt and updatedAt timestamps."""
        result = linear_client.create_project(name="Timestamped Project")

        project = result["project"]
        assert project["createdAt"] is not None
        assert project["updatedAt"] is not None

    def test_create_project_missing_name_returns_error(
        self, linear_client: LinearClient
    ):
        """Creating a project without a name raises an error."""
        with pytest.raises(RuntimeError, match="name is required"):
            linear_client.create_project(name="")


class TestGetProject:
    """Tests for fetching a single project."""

    def test_get_project_by_id(self, linear_client: LinearClient):
        """Fetching a project by ID returns the correct project."""
        created = linear_client.create_project(name="Fetchable Project")
        project_id = created["project"]["id"]

        fetched = linear_client.project(project_id)

        assert fetched["id"] == project_id
        assert fetched["name"] == "Fetchable Project"

    def test_get_nonexistent_project_raises_error(
        self, linear_client: LinearClient
    ):
        """Fetching a project that doesn't exist raises an error."""
        with pytest.raises(RuntimeError, match="not found"):
            linear_client.project("nonexistent-id")


class TestUpdateProject:
    """Tests for updating projects."""

    def test_update_project_name(self, linear_client: LinearClient):
        """Updating a project name persists the change."""
        created = linear_client.create_project(name="Old Name")
        project_id = created["project"]["id"]

        result = linear_client.update_project(project_id, name="New Name")

        assert result["success"] is True
        assert result["project"]["name"] == "New Name"

    def test_update_project_description(self, linear_client: LinearClient):
        """Updating a description persists the change."""
        created = linear_client.create_project(name="My Project")
        project_id = created["project"]["id"]

        result = linear_client.update_project(
            project_id, description="Updated description"
        )

        assert result["project"]["description"] == "Updated description"

    def test_update_project_state(self, linear_client: LinearClient):
        """Updating project state persists the change."""
        created = linear_client.create_project(name="Planned Project")
        project_id = created["project"]["id"]
        assert created["project"]["state"] == "planned"

        result = linear_client.update_project(project_id, state="completed")

        assert result["project"]["state"] == "completed"

    def test_updated_project_visible_in_list(self, linear_client: LinearClient):
        """An updated project is reflected when listing projects."""
        created = linear_client.create_project(name="Before Update")
        project_id = created["project"]["id"]
        linear_client.update_project(project_id, name="After Update")

        projects = linear_client.projects()
        names = [p["name"] for p in projects]

        assert "After Update" in names
        assert "Before Update" not in names

    def test_update_nonexistent_project_raises_error(
        self, linear_client: LinearClient
    ):
        """Updating a project that doesn't exist raises an error."""
        with pytest.raises(RuntimeError, match="not found"):
            linear_client.update_project("nonexistent-id", name="Ghost")
