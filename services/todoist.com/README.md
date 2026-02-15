# todoist.com — DoubleAgent Service

Todoist is a popular task management and productivity application used by millions of individuals and teams to organize work and personal tasks across web, mobile, and desktop platforms. The service provides a REST API (v2) that enables developers to programmatically interact with projects, tasks, sections, comments, and labels. The API supports natural language processing for task creation (e.g., "tomorrow at 4pm", "every Monday"), priority levels (P1-P4), recurring tasks, task assignments, due dates, and collaborative features like comments and project sharing.

This fake would cover the core REST API v2 endpoints for CRUD operations on all major resource types (projects, sections, tasks, comments, labels), along with task-specific operations like closing/reopening tasks, archiving projects, and managing shared labels. It would also include the Sync API v9's webhook functionality for real-time event notifications (item:added, item:updated, item:deleted, project:added). The fake is particularly valuable for testing AI agent integrations, which commonly use Todoist for automated task creation, intelligent prioritization, natural language task management, and workflow automation across multiple platforms.

The implementation would focus on the most common AI agent use cases: creating tasks with natural language due dates, filtering and searching tasks by labels/priority/projects, updating task status and priorities, managing project hierarchies with sections, and delivering webhook events for real-time task synchronization. This covers the essential API surface that automation tools, productivity integrations, and AI assistants rely on when integrating with Todoist.

## Recommended SDK

| Field | Value |
|-------|-------|
| **SDK** | todoist-api-python |
| **Language** | python |
| **Package** | `todoist-api-python` |
| **Install** | `pip install todoist-api-python` |
| **GitHub** | https://github.com/Doist/todoist-api-python |
| **Docs** | https://doist.github.io/todoist-api-python/ |

### Why this SDK?

Official SDK by Doist with 221 GitHub stars and ~96K monthly PyPI downloads. 2.4x more popular than the TypeScript alternative. Actively maintained (v3.2.0 released Jan 2026), comprehensive documentation, supports both sync and async clients. Python 3.9+ required. Most widely used for Todoist API integrations and automation tasks.
