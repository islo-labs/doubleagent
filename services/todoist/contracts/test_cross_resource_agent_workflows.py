"""
Contract tests for Cross-Resource Agent Workflows scenario.

Tests end-to-end workflows that AI agents commonly perform, combining
multiple resource types (projects, sections, tasks, labels, comments)
in realistic sequences.
"""

import time
from datetime import date

import pytest
from todoist_api_python.api import TodoistAPI


def _collect_all_pages(paginator) -> list:
    """Iterate a ResultsPaginator and collect all items across pages."""
    items = []
    for page in paginator:
        items.extend(page)
    return items


class TestFullProjectSetupWorkflow:
    """AI agent sets up a complete project with sections, tasks, labels, and comments."""

    def test_full_project_setup(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        # ---------------------------------------------------------------
        # Step 1: Create the project
        # ---------------------------------------------------------------
        project = todoist_client.add_project(
            name="Q1 Launch",
            color="blue",
            view_style="board",
        )
        resource_tracker.project(project.id)

        assert project.id is not None
        assert project.name == "Q1 Launch"
        assert project.color == "blue"
        assert project.view_style == "board"

        # Round-trip verification: read project back
        fetched_project = todoist_client.get_project(project.id)
        assert fetched_project.name == "Q1 Launch"
        assert fetched_project.view_style == "board"

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 2: Create three sections in the project
        # ---------------------------------------------------------------
        planning_section = todoist_client.add_section("Planning", project.id)
        resource_tracker.section(planning_section.id)
        assert planning_section.name == "Planning"
        assert planning_section.project_id == project.id

        if grounding_mode:
            time.sleep(0.3)

        dev_section = todoist_client.add_section("Development", project.id)
        resource_tracker.section(dev_section.id)
        assert dev_section.name == "Development"
        assert dev_section.project_id == project.id

        if grounding_mode:
            time.sleep(0.3)

        review_section = todoist_client.add_section("Review", project.id)
        resource_tracker.section(review_section.id)
        assert review_section.name == "Review"
        assert review_section.project_id == project.id

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: verify all sections appear in list
        all_sections = _collect_all_pages(todoist_client.get_sections(project.id))
        section_names = {s.name for s in all_sections}
        assert "Planning" in section_names
        assert "Development" in section_names
        assert "Review" in section_names

        section_ids = {s.id for s in all_sections}
        assert planning_section.id in section_ids
        assert dev_section.id in section_ids
        assert review_section.id in section_ids

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 3: Create tasks in different sections with labels
        # ---------------------------------------------------------------
        requirements_task = todoist_client.add_task(
            content="Define requirements",
            project_id=project.id,
            section_id=planning_section.id,
            priority=4,
            due_date=date(2026, 3, 1),
            labels=["planning"],
        )
        resource_tracker.task(requirements_task.id)

        assert requirements_task.content == "Define requirements"
        assert requirements_task.project_id == project.id
        assert requirements_task.section_id == planning_section.id
        assert requirements_task.priority == 4
        assert "planning" in requirements_task.labels
        assert requirements_task.due is not None
        assert requirements_task.due.date == date(2026, 3, 1)

        if grounding_mode:
            time.sleep(0.3)

        feature_task = todoist_client.add_task(
            content="Implement feature X",
            project_id=project.id,
            section_id=dev_section.id,
            priority=3,
            labels=["development"],
        )
        resource_tracker.task(feature_task.id)

        assert feature_task.content == "Implement feature X"
        assert feature_task.project_id == project.id
        assert feature_task.section_id == dev_section.id
        assert feature_task.priority == 3
        assert "development" in feature_task.labels

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read each task back individually
        fetched_req = todoist_client.get_task(requirements_task.id)
        assert fetched_req.content == "Define requirements"
        assert fetched_req.section_id == planning_section.id
        assert fetched_req.priority == 4
        assert "planning" in fetched_req.labels

        if grounding_mode:
            time.sleep(0.3)

        fetched_feat = todoist_client.get_task(feature_task.id)
        assert fetched_feat.content == "Implement feature X"
        assert fetched_feat.section_id == dev_section.id
        assert fetched_feat.priority == 3
        assert "development" in fetched_feat.labels

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 4: Add a comment to the requirements task
        # ---------------------------------------------------------------
        comment = todoist_client.add_comment(
            content="See PRD doc: https://docs.example.com/prd",
            task_id=requirements_task.id,
        )
        resource_tracker.comment(comment.id)

        assert comment.id is not None
        assert comment.content == "See PRD doc: https://docs.example.com/prd"
        assert comment.task_id == requirements_task.id

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read comment back
        fetched_comment = todoist_client.get_comment(comment.id)
        assert fetched_comment.content == "See PRD doc: https://docs.example.com/prd"
        assert fetched_comment.task_id == requirements_task.id

        if grounding_mode:
            time.sleep(0.3)

        # Verify comment appears in task's comments list
        task_comments = _collect_all_pages(
            todoist_client.get_comments(task_id=requirements_task.id)
        )
        comment_ids = [c.id for c in task_comments]
        assert comment.id in comment_ids

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 5: List all tasks in the project and verify everything
        # ---------------------------------------------------------------
        all_tasks = _collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        task_ids = [t.id for t in all_tasks]

        # Containment check: both tasks appear in the project
        assert requirements_task.id in task_ids
        assert feature_task.id in task_ids

        # Verify tasks have correct attributes when listed
        for t in all_tasks:
            if t.id == requirements_task.id:
                assert t.section_id == planning_section.id
                assert t.priority == 4
                assert "planning" in t.labels
            elif t.id == feature_task.id:
                assert t.section_id == dev_section.id
                assert t.priority == 3
                assert "development" in t.labels


class TestTaskTriageWorkflow:
    """AI agent triages tasks: close completed, update priorities, add comments."""

    def test_task_triage(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        # ---------------------------------------------------------------
        # Step 1: Create project and populate with tasks
        # ---------------------------------------------------------------
        project = todoist_client.add_project(name="Triage Project")
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        done_task = todoist_client.add_task(
            content="Done task",
            project_id=project.id,
            priority=1,
        )
        resource_tracker.task(done_task.id)

        if grounding_mode:
            time.sleep(0.3)

        escalation_task = todoist_client.add_task(
            content="Needs escalation",
            project_id=project.id,
            priority=1,
        )
        resource_tracker.task(escalation_task.id)

        if grounding_mode:
            time.sleep(0.3)

        context_task = todoist_client.add_task(
            content="Needs context",
            project_id=project.id,
            priority=2,
        )
        resource_tracker.task(context_task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Verify all three tasks exist in the project
        all_tasks_before = _collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        task_ids_before = [t.id for t in all_tasks_before]
        assert done_task.id in task_ids_before
        assert escalation_task.id in task_ids_before
        assert context_task.id in task_ids_before

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 2: Close the "Done task"
        # ---------------------------------------------------------------
        result = todoist_client.complete_task(done_task.id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: verify the completed task is excluded from active list
        active_tasks_after_close = _collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        active_ids_after_close = [t.id for t in active_tasks_after_close]
        assert done_task.id not in active_ids_after_close

        # The other two tasks should still be active
        assert escalation_task.id in active_ids_after_close
        assert context_task.id in active_ids_after_close

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 3: Escalate "Needs escalation" — update priority + add label
        # ---------------------------------------------------------------
        updated_escalation = todoist_client.update_task(
            escalation_task.id,
            priority=4,
            labels=["escalated"],
        )
        assert updated_escalation.priority == 4
        assert "escalated" in updated_escalation.labels

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read the escalated task back
        fetched_escalation = todoist_client.get_task(escalation_task.id)
        assert fetched_escalation.priority == 4
        assert "escalated" in fetched_escalation.labels
        assert fetched_escalation.content == "Needs escalation"

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 4: Add comment to "Needs context"
        # ---------------------------------------------------------------
        triage_comment = todoist_client.add_comment(
            content="Added by triage bot: requires stakeholder input before proceeding",
            task_id=context_task.id,
        )
        resource_tracker.comment(triage_comment.id)

        assert triage_comment.content == "Added by triage bot: requires stakeholder input before proceeding"
        assert triage_comment.task_id == context_task.id

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: verify comment exists on the task
        context_comments = _collect_all_pages(
            todoist_client.get_comments(task_id=context_task.id)
        )
        comment_ids = [c.id for c in context_comments]
        assert triage_comment.id in comment_ids

        if grounding_mode:
            time.sleep(0.3)

        # ---------------------------------------------------------------
        # Step 5: Final verification — list project tasks
        # ---------------------------------------------------------------
        final_tasks = _collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        final_task_ids = [t.id for t in final_tasks]

        # "Done task" should NOT appear (completed)
        assert done_task.id not in final_task_ids

        # "Needs escalation" should appear with updated attributes
        assert escalation_task.id in final_task_ids

        # "Needs context" should still appear
        assert context_task.id in final_task_ids

        # Verify escalated task attributes in the list result
        for t in final_tasks:
            if t.id == escalation_task.id:
                assert t.priority == 4
                assert "escalated" in t.labels
            elif t.id == context_task.id:
                # Task content unchanged
                assert t.content == "Needs context"
