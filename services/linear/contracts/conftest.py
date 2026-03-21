"""
pytest fixtures for Linear contract tests.

Uses httpx to call the fake directly via GraphQL, verifying the fake
behaves like the real Linear API.
The service is started by the CLI before tests run.
"""

import os
from typing import Any, Optional

import httpx
import pytest

SERVICE_URL = os.environ["DOUBLEAGENT_LINEAR_URL"]


class LinearClient:
    """
    Minimal Linear GraphQL client backed by httpx.

    Mirrors the calling conventions of the official Linear SDK so that
    contract tests read naturally and can be ported to the real SDK later.
    """

    def __init__(self, base_url: str, token: str = "fake-token") -> None:
        self._url = base_url.rstrip("/") + "/graphql"
        self._token = token

    def _post(self, query: str, variables: Optional[dict] = None) -> dict[str, Any]:
        resp = httpx.post(
            self._url,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(body["errors"][0]["message"])
        return body["data"]

    # ------------------------------------------------------------------
    # Viewer
    # ------------------------------------------------------------------

    def viewer(self) -> dict:
        data = self._post("{ viewer { id name displayName email } }")
        return data["viewer"]

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    def teams(self) -> list[dict]:
        data = self._post("{ teams { nodes { id name key description } } }")
        return data["teams"]["nodes"]

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def issues(
        self,
        filter: Optional[dict] = None,
        first: int = 50,
    ) -> list[dict]:
        query = """
        query Issues($filter: IssueFilter, $first: Int) {
          issues(filter: $filter, first: $first) {
            nodes {
              id title description priority
              state { id name type }
              team { id name key }
              assignee { id name }
              createdAt updatedAt
            }
          }
        }
        """
        data = self._post(query, {"filter": filter, "first": first})
        return data["issues"]["nodes"]

    def issue(self, issue_id: str) -> dict:
        query = """
        query Issue($id: String!) {
          issue(id: $id) {
            id title description priority
            state { id name type }
            team { id name key }
            assignee { id name }
            createdAt updatedAt
          }
        }
        """
        data = self._post(query, {"id": issue_id})
        return data["issue"]

    def create_issue(self, title: str, **kwargs) -> dict:
        query = """
        mutation IssueCreate($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue {
              id title description priority
              state { id name type }
              team { id name key }
              assignee { id name }
              createdAt updatedAt
            }
          }
        }
        """
        data = self._post(query, {"input": {"title": title, **kwargs}})
        return data["issueCreate"]

    def update_issue(self, issue_id: str, **kwargs) -> dict:
        query = """
        mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
          issueUpdate(id: $id, input: $input) {
            success
            issue {
              id title description priority
              state { id name type }
              team { id name key }
              assignee { id name }
              createdAt updatedAt
            }
          }
        }
        """
        data = self._post(query, {"id": issue_id, "input": kwargs})
        return data["issueUpdate"]

    def delete_issue(self, issue_id: str) -> dict:
        query = """
        mutation IssueDelete($id: String!) {
          issueDelete(id: $id) {
            success
          }
        }
        """
        data = self._post(query, {"id": issue_id})
        return data["issueDelete"]

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def projects(self, first: int = 50) -> list[dict]:
        query = """
        query Projects($first: Int) {
          projects(first: $first) {
            nodes {
              id name description state createdAt updatedAt
            }
          }
        }
        """
        data = self._post(query, {"first": first})
        return data["projects"]["nodes"]

    def project(self, project_id: str) -> dict:
        query = """
        query Project($id: String!) {
          project(id: $id) {
            id name description state createdAt updatedAt
          }
        }
        """
        data = self._post(query, {"id": project_id})
        return data["project"]

    def create_project(self, name: str, **kwargs) -> dict:
        query = """
        mutation ProjectCreate($input: ProjectCreateInput!) {
          projectCreate(input: $input) {
            success
            project {
              id name description state createdAt updatedAt
            }
          }
        }
        """
        data = self._post(query, {"input": {"name": name, **kwargs}})
        return data["projectCreate"]

    def update_project(self, project_id: str, **kwargs) -> dict:
        query = """
        mutation ProjectUpdate($id: String!, $input: ProjectUpdateInput!) {
          projectUpdate(id: $id, input: $input) {
            success
            project {
              id name description state createdAt updatedAt
            }
          }
        }
        """
        data = self._post(query, {"id": project_id, "input": kwargs})
        return data["projectUpdate"]


@pytest.fixture
def linear_client() -> LinearClient:
    """Provides a LinearClient configured to talk to the fake."""
    return LinearClient(base_url=SERVICE_URL)


@pytest.fixture(autouse=True)
def reset_fake():
    """Reset fake state before each test."""
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset")
    yield
