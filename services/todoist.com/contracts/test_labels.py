"""
Contract tests for Todoist labels CRUD operations.

Tests the complete flow: create, read, update, delete personal and shared labels
including creating, updating, renaming shared labels, and removing shared labels
using the official todoist-api-python SDK.
"""

import pytest
from todoist_api_python.api import TodoistAPI


def test_add_personal_label(todoist_client: TodoistAPI):
    """Test creating a personal label"""
    label = todoist_client.add_label(name="Work")

    assert label is not None
    assert label.id is not None
    assert label.name == "Work"
    assert label.color is not None
    assert label.order is not None
    assert label.is_favorite is not None


def test_add_personal_label_with_color(todoist_client: TodoistAPI):
    """Test creating a personal label with custom color"""
    label = todoist_client.add_label(name="Urgent", color="red")

    assert label is not None
    assert label.id is not None
    assert label.name == "Urgent"
    assert label.color == "red"


def test_add_personal_label_with_favorite(todoist_client: TodoistAPI):
    """Test creating a personal label marked as favorite"""
    label = todoist_client.add_label(name="Important", is_favorite=True)

    assert label is not None
    assert label.id is not None
    assert label.name == "Important"
    assert label.is_favorite is True


def test_add_personal_label_with_order(todoist_client: TodoistAPI):
    """Test creating a personal label with custom order"""
    label = todoist_client.add_label(name="Priority", item_order=5)

    assert label is not None
    assert label.id is not None
    assert label.name == "Priority"
    assert label.order == 5


def test_get_label_by_id(todoist_client: TodoistAPI):
    """Test retrieving a specific label by ID"""
    # Create a label first
    created_label = todoist_client.add_label(name="Testing")

    # Retrieve it by ID
    retrieved_label = todoist_client.get_label(label_id=created_label.id)

    assert retrieved_label is not None
    assert retrieved_label.id == created_label.id
    assert retrieved_label.name == "Testing"


def test_get_all_labels(todoist_client: TodoistAPI):
    """Test retrieving all personal labels"""
    # Create multiple labels
    todoist_client.add_label(name="Label1")
    todoist_client.add_label(name="Label2")
    todoist_client.add_label(name="Label3")

    # Get all labels - returns an iterator of lists
    labels_iterator = todoist_client.get_labels()
    all_labels = []
    for label_batch in labels_iterator:
        all_labels.extend(label_batch)

    assert len(all_labels) >= 3
    label_names = [label.name for label in all_labels]
    assert "Label1" in label_names
    assert "Label2" in label_names
    assert "Label3" in label_names


def test_update_label_name(todoist_client: TodoistAPI):
    """Test updating a label's name"""
    # Create a label
    label = todoist_client.add_label(name="OldName")

    # Update the name
    updated_label = todoist_client.update_label(label_id=label.id, name="NewName")

    assert updated_label is not None
    assert updated_label.id == label.id
    assert updated_label.name == "NewName"


def test_update_label_color(todoist_client: TodoistAPI):
    """Test updating a label's color"""
    # Create a label
    label = todoist_client.add_label(name="ColorTest", color="blue")

    # Update the color
    updated_label = todoist_client.update_label(label_id=label.id, color="green")

    assert updated_label is not None
    assert updated_label.id == label.id
    assert updated_label.color == "green"
    assert updated_label.name == "ColorTest"


def test_update_label_favorite_status(todoist_client: TodoistAPI):
    """Test toggling a label's favorite status"""
    # Create a label
    label = todoist_client.add_label(name="FavoriteTest", is_favorite=False)

    # Update to favorite
    updated_label = todoist_client.update_label(
        label_id=label.id, is_favorite=True
    )

    assert updated_label is not None
    assert updated_label.id == label.id
    assert updated_label.is_favorite is True


def test_update_label_order(todoist_client: TodoistAPI):
    """Test updating a label's order"""
    # Create a label
    label = todoist_client.add_label(name="OrderTest", item_order=1)

    # Update the order
    updated_label = todoist_client.update_label(label_id=label.id, item_order=10)

    assert updated_label is not None
    assert updated_label.id == label.id
    assert updated_label.order == 10


def test_update_label_multiple_fields(todoist_client: TodoistAPI):
    """Test updating multiple label fields at once"""
    # Create a label
    label = todoist_client.add_label(
        name="MultiUpdate", color="charcoal", is_favorite=False
    )

    # Update multiple fields
    updated_label = todoist_client.update_label(
        label_id=label.id,
        name="UpdatedName",
        color="red",
        is_favorite=True,
        item_order=5,
    )

    assert updated_label is not None
    assert updated_label.id == label.id
    assert updated_label.name == "UpdatedName"
    assert updated_label.color == "red"
    assert updated_label.is_favorite is True
    assert updated_label.order == 5


def test_delete_label(todoist_client: TodoistAPI):
    """Test deleting a personal label"""
    # Create a label
    label = todoist_client.add_label(name="ToDelete")

    # Delete it
    result = todoist_client.delete_label(label_id=label.id)

    assert result is True

    # Verify it's deleted - should raise an error or return None
    try:
        todoist_client.get_label(label_id=label.id)
        # If we get here, the label wasn't deleted
        assert False, "Label should have been deleted"
    except Exception:
        # Expected - label not found
        pass


def test_search_labels_by_name(todoist_client: TodoistAPI):
    """Test searching for labels by name"""
    # Create labels with different names
    todoist_client.add_label(name="WorkEmail")
    todoist_client.add_label(name="WorkMeeting")
    todoist_client.add_label(name="PersonalEmail")

    # Search for labels starting with "Work"
    search_results_iterator = todoist_client.search_labels(query="Work")
    search_results = []
    for result_batch in search_results_iterator:
        search_results.extend(result_batch)

    assert len(search_results) >= 2
    result_names = [label.name for label in search_results]
    assert "WorkEmail" in result_names
    assert "WorkMeeting" in result_names
    # PersonalEmail should not be in results
    assert "PersonalEmail" not in result_names


def test_get_shared_labels(todoist_client: TodoistAPI):
    """Test retrieving all shared labels"""
    # Get shared labels - returns an iterator of lists
    shared_labels_iterator = todoist_client.get_shared_labels()
    shared_labels = []
    for label_batch in shared_labels_iterator:
        shared_labels.extend(label_batch)

    # Initially should be empty or contain pre-existing shared labels
    assert isinstance(shared_labels, list)


def test_rename_shared_label(todoist_client: TodoistAPI, fake_url: str):
    """Test renaming a shared label"""
    import requests

    # Seed a shared label
    seed_data = {
        "shared_labels": {
            "shared1": {
                "id": "shared1",
                "name": "TeamLabel",
                "color": "blue",
                "order": 0,
                "is_favorite": False,
            }
        }
    }
    requests.post(f"{fake_url}/_doubleagent/seed", json=seed_data)

    # Now rename it - the SDK returns a dict, not a Label object
    renamed_label = todoist_client.rename_shared_label(
        name="TeamLabel", new_name="UpdatedTeamLabel"
    )

    assert renamed_label is not None
    assert isinstance(renamed_label, dict)
    assert renamed_label["name"] == "UpdatedTeamLabel"
    assert renamed_label["id"] == "shared1"


def test_remove_shared_label(todoist_client: TodoistAPI, fake_url: str):
    """Test removing a shared label"""
    import requests

    # Seed a shared label
    seed_data = {
        "shared_labels": {
            "shared2": {
                "id": "shared2",
                "name": "ToRemoveLabel",
                "color": "green",
                "order": 0,
                "is_favorite": False,
            }
        }
    }
    requests.post(f"{fake_url}/_doubleagent/seed", json=seed_data)

    # Now remove it
    result = todoist_client.remove_shared_label(name="ToRemoveLabel")

    assert result is True

    # Verify it's removed
    shared_labels_iterator = todoist_client.get_shared_labels()
    shared_labels = []
    for label_batch in shared_labels_iterator:
        shared_labels.extend(label_batch)

    label_names = [label.name for label in shared_labels]
    assert "ToRemoveLabel" not in label_names


def test_label_used_in_task(todoist_client: TodoistAPI):
    """Test creating a task with a label and verifying the label relationship"""
    # Create a label
    label = todoist_client.add_label(name="TaskLabel")

    # Create a task with the label
    task = todoist_client.add_task(content="Task with label", labels=[label.name])

    assert task is not None
    assert label.name in task.labels

    # Verify we can retrieve the label
    retrieved_label = todoist_client.get_label(label_id=label.id)
    assert retrieved_label.name == label.name


def test_multiple_labels_on_task(todoist_client: TodoistAPI):
    """Test using multiple labels on a single task"""
    # Create multiple labels
    label1 = todoist_client.add_label(name="Label1")
    label2 = todoist_client.add_label(name="Label2")
    label3 = todoist_client.add_label(name="Label3")

    # Create a task with multiple labels
    task = todoist_client.add_task(
        content="Task with multiple labels",
        labels=[label1.name, label2.name, label3.name],
    )

    assert task is not None
    assert len(task.labels) == 3
    assert label1.name in task.labels
    assert label2.name in task.labels
    assert label3.name in task.labels


def test_label_persistence_across_operations(todoist_client: TodoistAPI):
    """Test that labels persist correctly through create, update, and retrieval"""
    # Create a label
    label = todoist_client.add_label(
        name="PersistenceTest", color="purple", is_favorite=True, item_order=3
    )
    original_id = label.id

    # Update it
    todoist_client.update_label(label_id=label.id, color="orange")

    # Retrieve it again
    retrieved = todoist_client.get_label(label_id=label.id)

    assert retrieved.id == original_id
    assert retrieved.name == "PersistenceTest"
    assert retrieved.color == "orange"
    assert retrieved.is_favorite is True
    assert retrieved.order == 3
