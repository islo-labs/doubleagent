"""
Contract tests for Linear issue endpoints.

Verifies that the fake correctly implements the Linear GraphQL API
for issue CRUD operations.
"""

import pytest

from conftest import LinearClient


class TestListIssues:
    """Tests for listing issues."""

    def test_list_issues_empty(self, linear_client: LinearClient):
        """Returns an empty list when no issues exist."""
        issues = linear_client.issues()
        assert issues == []

    def test_list_issues_returns_created_issues(self, linear_client: LinearClient):
        """Issues created via the API appear in the list."""
        linear_client.create_issue(title="Issue One")
        linear_client.create_issue(title="Issue Two")

        issues = linear_client.issues()

        titles = [i["title"] for i in issues]
        assert "Issue One" in titles
        assert "Issue Two" in titles

    def test_list_issues_filter_by_state(self, linear_client: LinearClient):
        """Issues can be filtered by state name."""
        linear_client.create_issue(title="Open Issue")
        result = linear_client.create_issue(title="Done Issue")
        issue_id = result["issue"]["id"]
        linear_client.update_issue(issue_id, stateId="state-done")

        todo_issues = linear_client.issues(
            filter={"state": {"name": {"eq": "Todo"}}}
        )
        done_issues = linear_client.issues(
            filter={"state": {"name": {"eq": "Done"}}}
        )

        todo_titles = [i["title"] for i in todo_issues]
        done_titles = [i["title"] for i in done_issues]

        assert "Open Issue" in todo_titles
        assert "Done Issue" not in todo_titles
        assert "Done Issue" in done_titles
        assert "Open Issue" not in done_titles

    def test_list_issues_respects_first_limit(self, linear_client: LinearClient):
        """The `first` argument limits the number of returned issues."""
        for i in range(5):
            linear_client.create_issue(title=f"Issue {i}")

        issues = linear_client.issues(first=3)
        assert len(issues) == 3


class TestCreateIssue:
    """Tests for creating issues."""

    def test_create_issue_minimal(self, linear_client: LinearClient):
        """Create an issue with only a title."""
        result = linear_client.create_issue(title="Minimal Issue")

        assert result["success"] is True
        issue = result["issue"]
        assert issue["title"] == "Minimal Issue"
        assert issue["id"] is not None
        assert issue["state"]["name"] == "Todo"

    def test_create_issue_with_description(self, linear_client: LinearClient):
        """Create an issue with a description."""
        result = linear_client.create_issue(
            title="Described Issue",
            description="A detailed description.",
        )

        assert result["success"] is True
        assert result["issue"]["description"] == "A detailed description."

    def test_create_issue_with_priority(self, linear_client: LinearClient):
        """Create an issue with a priority."""
        result = linear_client.create_issue(title="Urgent Issue", priority=1)

        assert result["success"] is True
        assert result["issue"]["priority"] == 1

    def test_create_issue_with_state(self, linear_client: LinearClient):
        """Create an issue in a specific workflow state."""
        result = linear_client.create_issue(
            title="In-Progress Issue",
            stateId="state-inprogress",
        )

        assert result["success"] is True
        assert result["issue"]["state"]["name"] == "In Progress"

    def test_create_issue_has_team(self, linear_client: LinearClient):
        """A created issue is associated with a team."""
        result = linear_client.create_issue(title="Teamwork Issue")

        issue = result["issue"]
        assert issue["team"] is not None
        assert issue["team"]["id"] is not None

    def test_create_issue_missing_title_returns_error(
        self, linear_client: LinearClient
    ):
        """Creating an issue without a title raises an error."""
        with pytest.raises(RuntimeError, match="title is required"):
            linear_client.create_issue(title="")


class TestGetIssue:
    """Tests for fetching a single issue."""

    def test_get_issue_by_id(self, linear_client: LinearClient):
        """Fetching an issue by ID returns the correct issue."""
        created = linear_client.create_issue(title="Fetchable Issue")
        issue_id = created["issue"]["id"]

        fetched = linear_client.issue(issue_id)

        assert fetched["id"] == issue_id
        assert fetched["title"] == "Fetchable Issue"

    def test_get_nonexistent_issue_raises_error(self, linear_client: LinearClient):
        """Fetching an issue that doesn't exist raises an error."""
        with pytest.raises(RuntimeError, match="not found"):
            linear_client.issue("nonexistent-id")


class TestUpdateIssue:
    """Tests for updating issues."""

    def test_update_issue_title(self, linear_client: LinearClient):
        """Updating an issue title persists the change."""
        created = linear_client.create_issue(title="Original Title")
        issue_id = created["issue"]["id"]

        result = linear_client.update_issue(issue_id, title="Updated Title")

        assert result["success"] is True
        assert result["issue"]["title"] == "Updated Title"

    def test_update_issue_description(self, linear_client: LinearClient):
        """Updating a description persists the change."""
        created = linear_client.create_issue(title="Issue")
        issue_id = created["issue"]["id"]

        result = linear_client.update_issue(issue_id, description="New description")

        assert result["issue"]["description"] == "New description"

    def test_update_issue_state(self, linear_client: LinearClient):
        """Updating the state changes the workflow state."""
        created = linear_client.create_issue(title="To Complete")
        issue_id = created["issue"]["id"]
        assert created["issue"]["state"]["name"] == "Todo"

        result = linear_client.update_issue(issue_id, stateId="state-done")

        assert result["issue"]["state"]["name"] == "Done"

    def test_update_issue_priority(self, linear_client: LinearClient):
        """Updating priority persists the change."""
        created = linear_client.create_issue(title="Low Pri")
        issue_id = created["issue"]["id"]

        result = linear_client.update_issue(issue_id, priority=2)

        assert result["issue"]["priority"] == 2

    def test_updated_issue_visible_in_list(self, linear_client: LinearClient):
        """An updated issue is reflected when listing issues."""
        created = linear_client.create_issue(title="Before Update")
        issue_id = created["issue"]["id"]
        linear_client.update_issue(issue_id, title="After Update")

        issues = linear_client.issues()
        titles = [i["title"] for i in issues]

        assert "After Update" in titles
        assert "Before Update" not in titles

    def test_update_nonexistent_issue_raises_error(
        self, linear_client: LinearClient
    ):
        """Updating an issue that doesn't exist raises an error."""
        with pytest.raises(RuntimeError, match="not found"):
            linear_client.update_issue("nonexistent-id", title="Ghost")
