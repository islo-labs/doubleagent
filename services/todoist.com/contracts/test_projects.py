"""
Contract tests for Todoist projects CRUD operations.

Tests the complete flow: create, read, update, delete, archive, unarchive,
and retrieve project collaborators using the official todoist-api-python SDK.
"""

import pytest
from todoist_api_python.api import TodoistAPI


def test_create_project(todoist_client: TodoistAPI):
    """Test creating a new project"""
    project = todoist_client.add_project(name="Test Project")

    assert project is not None
    assert project.id is not None
    assert project.name == "Test Project"
    assert project.color is not None
    assert project.is_archived is False

    # Read back to verify persistence
    retrieved_project = todoist_client.get_project(project_id=project.id)
    assert retrieved_project.id == project.id
    assert retrieved_project.name == "Test Project"
    assert retrieved_project.is_archived is False


def test_get_project(todoist_client: TodoistAPI):
    """Test retrieving a specific project by ID"""
    # Create a project first
    created_project = todoist_client.add_project(name="Project to Get")

    # Retrieve it
    retrieved_project = todoist_client.get_project(project_id=created_project.id)

    assert retrieved_project is not None
    assert retrieved_project.id == created_project.id
    assert retrieved_project.name == "Project to Get"


def test_get_all_projects(todoist_client: TodoistAPI):
    """Test retrieving all projects"""
    # Create multiple projects
    todoist_client.add_project(name="Project 1")
    todoist_client.add_project(name="Project 2")
    todoist_client.add_project(name="Project 3")

    # Get all projects - the SDK returns an iterator of pages (lists)
    # We need to iterate through pages and collect all projects
    all_projects = []
    for page in todoist_client.get_projects():
        all_projects.extend(page)

    assert len(all_projects) >= 3
    project_names = [p.name for p in all_projects]
    assert "Project 1" in project_names
    assert "Project 2" in project_names
    assert "Project 3" in project_names


def test_update_project(todoist_client: TodoistAPI):
    """Test updating a project's properties"""
    # Create a project
    project = todoist_client.add_project(name="Original Name", is_favorite=False)

    # Update the project
    updated_project = todoist_client.update_project(
        project_id=project.id, name="Updated Name", is_favorite=True
    )

    assert updated_project.id == project.id
    assert updated_project.name == "Updated Name"
    assert updated_project.is_favorite is True

    # Read back to verify persistence
    retrieved_project = todoist_client.get_project(project_id=project.id)
    assert retrieved_project.id == project.id
    assert retrieved_project.name == "Updated Name"
    assert retrieved_project.is_favorite is True


def test_archive_project(todoist_client: TodoistAPI):
    """Test archiving a project"""
    # Create a project
    project = todoist_client.add_project(name="Project to Archive")

    # Archive it
    archived_project = todoist_client.archive_project(project_id=project.id)

    assert archived_project.id == project.id
    assert archived_project.is_archived is True

    # Read back to verify persistence
    retrieved_project = todoist_client.get_project(project_id=project.id)
    assert retrieved_project.id == project.id
    assert retrieved_project.is_archived is True

    # Verify it doesn't appear in active projects list
    all_projects = []
    for page in todoist_client.get_projects():
        all_projects.extend(page)

    active_project_ids = [p.id for p in all_projects]
    assert project.id not in active_project_ids


def test_unarchive_project(todoist_client: TodoistAPI):
    """Test unarchiving a previously archived project"""
    # Create and archive a project
    project = todoist_client.add_project(name="Project to Unarchive")
    todoist_client.archive_project(project_id=project.id)

    # Unarchive it
    unarchived_project = todoist_client.unarchive_project(project_id=project.id)

    assert unarchived_project.id == project.id
    assert unarchived_project.is_archived is False

    # Read back to verify persistence
    retrieved_project = todoist_client.get_project(project_id=project.id)
    assert retrieved_project.id == project.id
    assert retrieved_project.is_archived is False

    # Verify it appears in active projects list again
    all_projects = []
    for page in todoist_client.get_projects():
        all_projects.extend(page)

    active_project_ids = [p.id for p in all_projects]
    assert project.id in active_project_ids


def test_delete_project(todoist_client: TodoistAPI):
    """Test deleting a project"""
    # Create a project
    project = todoist_client.add_project(name="Project to Delete")
    project_id = project.id

    # Delete it
    result = todoist_client.delete_project(project_id=project_id)

    assert result is True

    # Verify it's gone - attempting to get it should fail
    with pytest.raises(Exception):
        todoist_client.get_project(project_id=project_id)


def test_get_project_collaborators(todoist_client: TodoistAPI):
    """Test retrieving collaborators for a project"""
    # Create a project
    project = todoist_client.add_project(name="Shared Project")

    # Get collaborators (should be empty for a fresh project)
    all_collaborators = []
    for page in todoist_client.get_collaborators(project_id=project.id):
        all_collaborators.extend(page)

    assert isinstance(all_collaborators, list)
    # For a fake service, it should return an empty list initially
    assert len(all_collaborators) == 0


def test_complete_project_lifecycle(todoist_client: TodoistAPI):
    """Test the complete CRUD lifecycle of a project"""
    # Create
    project = todoist_client.add_project(name="Lifecycle Test", is_favorite=False)
    assert project.name == "Lifecycle Test"
    assert project.is_favorite is False

    # Read
    retrieved = todoist_client.get_project(project_id=project.id)
    assert retrieved.id == project.id

    # Update
    updated = todoist_client.update_project(
        project_id=project.id, name="Updated Lifecycle", is_favorite=True
    )
    assert updated.name == "Updated Lifecycle"
    assert updated.is_favorite is True

    # Read back to verify update persistence
    retrieved_after_update = todoist_client.get_project(project_id=project.id)
    assert retrieved_after_update.name == "Updated Lifecycle"
    assert retrieved_after_update.is_favorite is True

    # Archive
    archived = todoist_client.archive_project(project_id=project.id)
    assert archived.is_archived is True

    # Unarchive
    unarchived = todoist_client.unarchive_project(project_id=project.id)
    assert unarchived.is_archived is False

    # Delete
    result = todoist_client.delete_project(project_id=project.id)
    assert result is True


def test_create_nested_project(todoist_client: TodoistAPI):
    """Test creating a project with a parent project"""
    # Create parent project
    parent = todoist_client.add_project(name="Parent Project")

    # Create child project
    child = todoist_client.add_project(name="Child Project", parent_id=parent.id)

    assert child.parent_id == parent.id
    assert child.name == "Child Project"

    # Read back to verify persistence
    retrieved_child = todoist_client.get_project(project_id=child.id)
    assert retrieved_child.parent_id == parent.id
    assert retrieved_child.name == "Child Project"


def test_update_project_color(todoist_client: TodoistAPI):
    """Test updating a project's color"""
    project = todoist_client.add_project(name="Color Test")

    # Update color
    updated = todoist_client.update_project(project_id=project.id, color="red")

    assert updated.color == "red"

    # Read back to verify persistence
    retrieved_project = todoist_client.get_project(project_id=project.id)
    assert retrieved_project.color == "red"


def test_update_project_view_style(todoist_client: TodoistAPI):
    """Test updating a project's view style"""
    project = todoist_client.add_project(name="View Style Test")

    # Update view style
    updated = todoist_client.update_project(project_id=project.id, view_style="board")

    assert updated.view_style == "board"

    # Read back to verify persistence
    retrieved_project = todoist_client.get_project(project_id=project.id)
    assert retrieved_project.view_style == "board"
