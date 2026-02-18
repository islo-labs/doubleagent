"""
Contract tests for Todoist sections CRUD operations.

Tests the complete flow: create, read, update, delete sections within projects,
and organizing tasks hierarchically using the official todoist-api-python SDK.
"""

import pytest
from todoist_api_python.api import TodoistAPI


def test_create_section(todoist_client: TodoistAPI):
    """Test creating a new section in a project"""
    # Create a project first
    project = todoist_client.add_project(name="Test Project")

    # Create a section
    section = todoist_client.add_section(name="Test Section", project_id=project.id)

    assert section is not None
    assert section.id is not None
    assert section.name == "Test Section"
    assert section.project_id == project.id
    assert section.order is not None

    # Verify persistence by reading back
    retrieved_section = todoist_client.get_section(section_id=section.id)
    assert retrieved_section.id == section.id
    assert retrieved_section.name == "Test Section"
    assert retrieved_section.project_id == project.id


def test_get_section(todoist_client: TodoistAPI):
    """Test retrieving a specific section by ID"""
    # Create a project and section first
    project = todoist_client.add_project(name="Test Project")
    created_section = todoist_client.add_section(
        name="Section to Get", project_id=project.id
    )

    # Retrieve the section
    retrieved_section = todoist_client.get_section(section_id=created_section.id)

    assert retrieved_section is not None
    assert retrieved_section.id == created_section.id
    assert retrieved_section.name == "Section to Get"
    assert retrieved_section.project_id == project.id


def test_get_all_sections(todoist_client: TodoistAPI):
    """Test retrieving all sections across all projects"""
    # Create multiple projects with sections
    project1 = todoist_client.add_project(name="Project 1")
    project2 = todoist_client.add_project(name="Project 2")

    todoist_client.add_section(name="Section 1A", project_id=project1.id)
    todoist_client.add_section(name="Section 1B", project_id=project1.id)
    todoist_client.add_section(name="Section 2A", project_id=project2.id)

    # Get all sections
    all_sections = []
    for page in todoist_client.get_sections():
        all_sections.extend(page)

    assert len(all_sections) >= 3
    section_names = [s.name for s in all_sections]
    assert "Section 1A" in section_names
    assert "Section 1B" in section_names
    assert "Section 2A" in section_names


def test_get_sections_by_project(todoist_client: TodoistAPI):
    """Test retrieving sections filtered by project"""
    # Create two projects with sections
    project1 = todoist_client.add_project(name="Project 1")
    project2 = todoist_client.add_project(name="Project 2")

    todoist_client.add_section(name="Section 1A", project_id=project1.id)
    todoist_client.add_section(name="Section 1B", project_id=project1.id)
    todoist_client.add_section(name="Section 2A", project_id=project2.id)

    # Get sections for project 1 only
    project1_sections = []
    for page in todoist_client.get_sections(project_id=project1.id):
        project1_sections.extend(page)

    assert len(project1_sections) == 2
    section_names = [s.name for s in project1_sections]
    assert "Section 1A" in section_names
    assert "Section 1B" in section_names
    assert "Section 2A" not in section_names

    # Verify all sections belong to project 1
    for section in project1_sections:
        assert section.project_id == project1.id


def test_update_section(todoist_client: TodoistAPI):
    """Test updating a section's name"""
    # Create a project and section
    project = todoist_client.add_project(name="Test Project")
    section = todoist_client.add_section(name="Original Name", project_id=project.id)

    # Update the section name
    updated_section = todoist_client.update_section(
        section_id=section.id, name="Updated Name"
    )

    assert updated_section.id == section.id
    assert updated_section.name == "Updated Name"
    assert updated_section.project_id == project.id

    # Verify persistence by reading back
    retrieved_section = todoist_client.get_section(section_id=section.id)
    assert retrieved_section.id == section.id
    assert retrieved_section.name == "Updated Name"
    assert retrieved_section.project_id == project.id


def test_delete_section(todoist_client: TodoistAPI):
    """Test deleting a section"""
    # Create a project and section
    project = todoist_client.add_project(name="Test Project")
    section = todoist_client.add_section(name="Section to Delete", project_id=project.id)
    section_id = section.id

    # Delete the section
    result = todoist_client.delete_section(section_id=section_id)

    assert result is True

    # Verify it's gone from the project's sections list
    sections = []
    for page in todoist_client.get_sections(project_id=project.id):
        sections.extend(page)
    assert section_id not in [s.id for s in sections]


def test_delete_section_removes_tasks(todoist_client: TodoistAPI):
    """Test that deleting a section also removes its tasks"""
    # Create a project and section
    project = todoist_client.add_project(name="Test Project")
    section = todoist_client.add_section(name="Section with Tasks", project_id=project.id)

    # Create tasks in the section
    task1 = todoist_client.add_task(
        content="Task 1", project_id=project.id, section_id=section.id
    )
    task2 = todoist_client.add_task(
        content="Task 2", project_id=project.id, section_id=section.id
    )

    # Delete the section
    todoist_client.delete_section(section_id=section.id)

    # Verify tasks are no longer in active task list
    all_tasks = []
    for page in todoist_client.get_tasks(project_id=project.id):
        all_tasks.extend(page)
    active_task_ids = [t.id for t in all_tasks]
    assert task1.id not in active_task_ids
    assert task2.id not in active_task_ids


def test_complete_section_lifecycle(todoist_client: TodoistAPI):
    """Test the complete CRUD lifecycle of a section"""
    # Create a project
    project = todoist_client.add_project(name="Lifecycle Test Project")

    # Create section
    section = todoist_client.add_section(name="Lifecycle Section", project_id=project.id)
    assert section.name == "Lifecycle Section"
    assert section.project_id == project.id

    # Read
    retrieved = todoist_client.get_section(section_id=section.id)
    assert retrieved.id == section.id
    assert retrieved.name == "Lifecycle Section"

    # Update
    updated = todoist_client.update_section(section_id=section.id, name="Updated Section")
    assert updated.name == "Updated Section"

    # Delete
    result = todoist_client.delete_section(section_id=section.id)
    assert result is True


def test_create_multiple_sections_with_order(todoist_client: TodoistAPI):
    """Test creating multiple sections with explicit order"""
    # Create a project
    project = todoist_client.add_project(name="Test Project")

    # Create sections with different orders
    section1 = todoist_client.add_section(
        name="First Section", project_id=project.id, order=1
    )
    section2 = todoist_client.add_section(
        name="Second Section", project_id=project.id, order=2
    )
    section3 = todoist_client.add_section(
        name="Third Section", project_id=project.id, order=3
    )

    assert section1.order == 1
    assert section2.order == 2
    assert section3.order == 3

    # Verify persistence by reading back each section
    retrieved_section1 = todoist_client.get_section(section_id=section1.id)
    assert retrieved_section1.order == 1
    assert retrieved_section1.name == "First Section"

    retrieved_section2 = todoist_client.get_section(section_id=section2.id)
    assert retrieved_section2.order == 2
    assert retrieved_section2.name == "Second Section"

    retrieved_section3 = todoist_client.get_section(section_id=section3.id)
    assert retrieved_section3.order == 3
    assert retrieved_section3.name == "Third Section"


def test_organize_tasks_in_sections(todoist_client: TodoistAPI):
    """Test organizing tasks hierarchically using sections"""
    # Create a project
    project = todoist_client.add_project(name="Task Organization Project")

    # Create sections for different categories
    todo_section = todoist_client.add_section(
        name="To Do", project_id=project.id, order=1
    )
    in_progress_section = todoist_client.add_section(
        name="In Progress", project_id=project.id, order=2
    )
    done_section = todoist_client.add_section(
        name="Done", project_id=project.id, order=3
    )

    # Verify section persistence by reading back
    retrieved_todo = todoist_client.get_section(section_id=todo_section.id)
    assert retrieved_todo.name == "To Do"
    assert retrieved_todo.order == 1

    retrieved_in_progress = todoist_client.get_section(section_id=in_progress_section.id)
    assert retrieved_in_progress.name == "In Progress"
    assert retrieved_in_progress.order == 2

    retrieved_done = todoist_client.get_section(section_id=done_section.id)
    assert retrieved_done.name == "Done"
    assert retrieved_done.order == 3

    # Add tasks to different sections
    task1 = todoist_client.add_task(
        content="Task in To Do", project_id=project.id, section_id=todo_section.id
    )
    task2 = todoist_client.add_task(
        content="Task in Progress",
        project_id=project.id,
        section_id=in_progress_section.id,
    )
    task3 = todoist_client.add_task(
        content="Task Done", project_id=project.id, section_id=done_section.id
    )

    # Verify tasks are in correct sections
    assert task1.section_id == todo_section.id
    assert task2.section_id == in_progress_section.id
    assert task3.section_id == done_section.id

    # Get tasks by section
    todo_tasks = []
    for page in todoist_client.get_tasks(section_id=todo_section.id):
        todo_tasks.extend(page)

    assert len(todo_tasks) == 1
    assert todo_tasks[0].content == "Task in To Do"


def test_section_in_nonexistent_project(todoist_client: TodoistAPI):
    """Test that creating a section in a non-existent project fails"""
    with pytest.raises(Exception):
        todoist_client.add_section(
            name="Orphan Section", project_id="nonexistent-project-id"
        )


def test_delete_project_removes_sections(todoist_client: TodoistAPI):
    """Test that deleting a project also removes its sections"""
    # Create a project with sections
    project = todoist_client.add_project(name="Project to Delete")
    section1 = todoist_client.add_section(name="Section 1", project_id=project.id)
    section2 = todoist_client.add_section(name="Section 2", project_id=project.id)

    section1_id = section1.id
    section2_id = section2.id

    # Delete the project
    todoist_client.delete_project(project_id=project.id)

    # Verify sections are no longer in global sections list
    all_sections = []
    for page in todoist_client.get_sections():
        all_sections.extend(page)
    section_ids = [s.id for s in all_sections]
    assert section1_id not in section_ids
    assert section2_id not in section_ids


def test_empty_sections_list_for_new_project(todoist_client: TodoistAPI):
    """Test that a new project has no sections"""
    # Create a project
    project = todoist_client.add_project(name="Empty Project")

    # Get sections for this project
    sections = []
    for page in todoist_client.get_sections(project_id=project.id):
        sections.extend(page)

    assert len(sections) == 0
