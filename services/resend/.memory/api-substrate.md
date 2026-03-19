# Resend API Substrate Documentation

## Overview

Resend is a developer-focused email API for sending transactional and marketing emails. The API covers: Emails, Domains, Contacts, Templates, API Keys, and Webhooks.

---

## Base URL & Versioning

- **Base URL**: `https://api.resend.com`
- **Versioning**: No versioning system exists. All endpoints are unversioned (e.g., `/emails`, `/domains`). Calendar-based header versioning is planned for the future.
- **Protocol**: HTTPS only. HTTP is not supported.
- **Path convention**: `/{resource}` (e.g., `/emails`, `/domains`, `/contacts`, `/templates`, `/api-keys`, `/webhooks`)

---

## Authentication

- **Mechanism**: Bearer token in the `Authorization` header
- **Header format**: `Authorization: Bearer re_xxxxxxxxx`
- **API key format**: Keys start with `re_` prefix (e.g., `re_c1tpEyD8_NKFusih9vKVQknRAQfmFcWCv`)
- **Permission levels**: `full_access` (all operations) or `sending_access` (email sending only, optionally scoped to a specific domain)
- **Required headers**:
  - `Authorization: Bearer <api_key>` (required for all requests)
  - `Content-Type: application/json` (required for POST/PATCH requests with body)
  - `User-Agent` is recommended; omitting it may result in errors

### Auth Error Responses (verified by probing)

**Missing API key** (no Authorization header):
```
HTTP 401
{
  "statusCode": 401,
  "name": "missing_api_key",
  "message": "Missing API Key"
}
```
Response includes `www-authenticate: realm=""` header.

**Invalid API key** (malformed or revoked key):
```
HTTP 400
{
  "statusCode": 400,
  "name": "validation_error",
  "message": "API key is invalid"
}
```
Note: Invalid key returns **400** (not 401/403). This is a quirk.

**Restricted API key** (sending-only key accessing non-email endpoints):
```
HTTP 401
{
  "statusCode": 401,
  "name": "restricted_api_key",
  "message": "This API key is restricted to only send emails"
}
```

---

## ID Format

- **All resource IDs are UUIDs** (e.g., `49a3999c-0ce1-4ea6-ab68-afcd6dc2e794`)
- **API key tokens** start with `re_` prefix (e.g., `re_c1tpEyD8_NKFusih9vKVQknRAQfmFcWCv`)

---

## Response Envelope & Common Patterns

### Single resource responses
Individual resources include an `"object"` field identifying the resource type:
```json
{
  "object": "email",
  "id": "49a3999c-...",
  ...fields...
}
```

### List responses
All list endpoints return a consistent envelope:
```json
{
  "object": "list",
  "has_more": true,
  "data": [ ...resources... ]
}
```

### Create responses
Most create endpoints return a minimal response:
```json
{
  "id": "49a3999c-...",
  "object": "resource_type"
}
```
Exception: `POST /emails` returns only `{"id": "..."}` (no `object` field). Verified by probing.

Exception: `POST /api-keys` returns `{"id": "...", "token": "re_..."}` (no `object` field).

Exception: `POST /webhooks` returns `{"object": "webhook", "id": "...", "signing_secret": "..."}`.

Exception: `POST /domains` returns a full domain object with `records` array.

### Delete responses
Most delete endpoints return:
```json
{
  "object": "resource_type",
  "id": "...",
  "deleted": true
}
```
Exception: `DELETE /api-keys/{id}` returns empty body (no content). The SDK returns `None`.

Exception: `DELETE /contacts/{id}` uses `"contact"` field instead of `"id"`:
```json
{
  "object": "contact",
  "contact": "520784e2-...",
  "deleted": true
}
```

---

## Pagination

- **Style**: Cursor-based using resource IDs
- **Parameters** (query string):
  - `limit` (number): Items to return. Default: 20, Min: 1, Max: 100
  - `after` (string): ID after which to retrieve more items (forward pagination)
  - `before` (string): ID before which to retrieve more items (backward pagination)
  - `after` and `before` are mutually exclusive
- **Response**:
  - `has_more` (boolean): `true` if more items exist beyond current page
  - `data` (array): Array of resource objects
- **Detecting last page**: `has_more === false`

---

## Rate Limiting (verified by probing)

- **Default limit**: 2 requests per second per team (across all API keys)
- **Headers** (present on ALL responses, including errors):
  - `ratelimit-limit: 2` — Maximum requests per window
  - `ratelimit-policy: 2;w=1` — Policy (2 requests per 1 second window)
  - `ratelimit-remaining: 1` — Remaining requests in current window
  - `ratelimit-reset: 1` — Seconds until window resets
  - `retry-after: 1` — (only on 429 responses) Seconds to wait before retrying
- **Quota headers** (on successful send responses only):
  - `x-resend-daily-quota: N` — Number of emails sent today
  - `x-resend-monthly-quota: N` — Number of emails sent this month

### Rate limit error (verified by probing):
```
HTTP 429
{
  "statusCode": 429,
  "name": "rate_limit_exceeded",
  "message": "Too many requests. You can only make 2 requests per second. See rate limit response headers for more information. Or contact support to increase rate limit."
}
```

---

## Error Format (verified by probing)

All errors follow this exact JSON shape:
```json
{
  "statusCode": <number>,
  "name": "<error_type_string>",
  "message": "<human_readable_message>"
}
```

### Observed error codes and names:

| HTTP Status | `name` | Example `message` |
|---|---|---|
| 400 | `validation_error` | "API key is invalid", "Request body must be valid JSON." |
| 401 | `missing_api_key` | "Missing API Key" |
| 401 | `restricted_api_key` | "This API key is restricted to only send emails" |
| 404 | `not_found` | "Template not found" |
| 422 | `missing_required_field` | "Missing \`to\` field." |
| 422 | `validation_error` | "Invalid \`to\` field. The email address needs to follow the \`email@example.com\` or \`Name <email@example.com>\` format.", "Missing \`html\` or \`text\` field." |
| 429 | `rate_limit_exceeded` | "Too many requests..." |

### Validation order (verified by probing):
1. Authentication check (missing/invalid key → 400/401)
2. Permission check (restricted key → 401)
3. JSON parsing (invalid JSON → 400)
4. Required field validation: `to` is checked before `from`, and `html`/`text` before `subject`

---

## Soft Delete Behavior

Resend does **NOT** soft-delete. Deleted resources return 404 on subsequent GET requests (documented in API docs for domains, templates, webhooks, contacts). Delete responses include `"deleted": true` as confirmation.

---

## Resource: Emails

### POST /emails — Send an email
**Request body**:
| Field | Type | Required | Notes |
|---|---|---|---|
| `from` | string | Yes | `"Name <email@domain.com>"` format |
| `to` | string \| string[] | Yes | Max 50 recipients |
| `subject` | string | Yes | Email subject |
| `html` | string | No* | HTML body (*one of `html` or `text` required) |
| `text` | string | No* | Plain text body |
| `cc` | string \| string[] | No | CC recipients |
| `bcc` | string \| string[] | No | BCC recipients |
| `reply_to` | string \| string[] | No | Reply-to address(es) |
| `tags` | array | No | `[{name: string, value: string}]`, max 256 chars each |
| `headers` | object | No | Custom email headers |
| `attachments` | array | No | File attachments |
| `scheduled_at` | string | No | ISO 8601 future timestamp |
| `template` | object | No | `{id: string, variables: object}` |
| `topic_id` | string | No | Topic ID for subscription filtering |

**Request headers**:
- `Idempotency-Key` (optional): Unique per request, expires after 24 hours, max 256 chars

**Response** (200):
```json
{
  "id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"
}
```
Verified: Returns only `id` field (no `object` field).

### GET /emails/{id} — Retrieve an email
**Response** (200):
```json
{
  "object": "email",
  "id": "49a3999c-...",
  "to": ["recipient@example.com"],
  "from": "sender@example.com",
  "created_at": "2024-01-01T00:00:00.000Z",
  "subject": "Hello",
  "html": "<p>Hello</p>",
  "text": null,
  "bcc": null,
  "cc": null,
  "reply_to": null,
  "last_event": "delivered",
  "scheduled_at": null,
  "tags": [{"name": "key", "value": "val"}]
}
```

Key fields:
- `to`, `cc`, `bcc`, `reply_to` are arrays (or null)
- `last_event` values include: `sent`, `delivered`, `scheduled`, `canceled`, `bounced`, `opened`, `clicked`, etc.
- `scheduled_at` is null for non-scheduled emails

### GET /emails — List emails
**Query parameters**: `limit`, `after`, `before` (standard pagination)

**Response** (200):
```json
{
  "object": "list",
  "has_more": false,
  "data": [
    {
      "id": "...",
      "to": ["..."],
      "from": "...",
      "created_at": "...",
      "subject": "...",
      "bcc": null,
      "cc": null,
      "reply_to": null,
      "last_event": "delivered",
      "scheduled_at": null
    }
  ]
}
```
Note: List items do NOT include `html`, `text`, or `tags` fields. Only summary fields.

### PATCH /emails/{id} — Update (reschedule) an email
**Request body**:
```json
{
  "scheduled_at": "2024-08-05T11:52:01.858Z"
}
```

**Response** (200):
```json
{
  "object": "email",
  "id": "49a3999c-..."
}
```

### POST /emails/{id}/cancel — Cancel a scheduled email
**Request body**: None (empty)

**Response** (200):
```json
{
  "object": "email",
  "id": "49a3999c-..."
}
```

### POST /emails/batch — Send batch emails
**Request body**: Array of email objects (same fields as single send), max 100 emails.
- Attachments and `scheduled_at` are NOT supported in batch.

**Response** (200):
```json
{
  "data": [
    {"id": "uuid-1"},
    {"id": "uuid-2"}
  ]
}
```
Verified: Each item in `data` has only an `id` field. No `object` field on the wrapper or items.

**Request headers**:
- `Idempotency-Key` (optional)
- `x-batch-validation` (optional): `"strict"` or `"permissive"` — controls batch validation mode

---

## Resource: Domains

### POST /domains — Create a domain
**Request body**:
| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | Yes | — | Domain name |
| `region` | string | No | `us-east-1` | Options: `us-east-1`, `eu-west-1`, `sa-east-1`, `ap-northeast-1` |
| `customReturnPath` | string | No | `send` | Return-Path subdomain |
| `openTracking` | boolean | No | — | Enable open tracking |
| `clickTracking` | boolean | No | — | Enable click tracking |
| `tls` | string | No | `opportunistic` | `opportunistic` or `enforced` |
| `capabilities` | object | No | — | `{sending: "enabled"/"disabled", receiving: "enabled"/"disabled"}` |

**Response** (200):
```json
{
  "id": "uuid",
  "name": "example.com",
  "created_at": "2024-...",
  "status": "not_started",
  "region": "us-east-1",
  "capabilities": {"sending": "enabled", "receiving": "disabled"},
  "records": [
    {
      "record": "SPF",
      "name": "send.example.com",
      "type": "MX",
      "value": "feedback-smtp.us-east-1.amazonses.com",
      "ttl": "Auto",
      "status": "not_started",
      "priority": 10
    },
    {
      "record": "DKIM",
      "name": "resend._domainkey.example.com",
      "type": "CNAME",
      "value": "...",
      "ttl": "Auto",
      "status": "not_started"
    }
  ]
}
```
Note: Create response returns the full domain object including records. No `object` field in docs.

### GET /domains/{domain_id} — Retrieve a domain
**Response** (200):
```json
{
  "object": "domain",
  "id": "...",
  "name": "...",
  "status": "not_started|pending|verified",
  "created_at": "...",
  "region": "us-east-1",
  "capabilities": {"sending": "enabled", "receiving": "disabled"},
  "records": [...]
}
```

### GET /domains — List domains
**Query parameters**: `limit`, `after`, `before` (standard pagination)

**Response** (200):
```json
{
  "object": "list",
  "has_more": false,
  "data": [
    {
      "id": "...",
      "name": "...",
      "status": "...",
      "created_at": "...",
      "region": "...",
      "capabilities": {"sending": "enabled", "receiving": "disabled"}
    }
  ]
}
```
Note: List items do NOT include `records` array.

### PATCH /domains/{domain_id} — Update a domain
**Request body** (all optional):
```json
{
  "click_tracking": true,
  "open_tracking": true,
  "tls": "enforced",
  "capabilities": {"sending": "enabled", "receiving": "enabled"}
}
```

**Response** (200):
```json
{
  "object": "domain",
  "id": "..."
}
```

### POST /domains/{domain_id}/verify — Verify a domain
**Request body**: None

**Response** (200):
```json
{
  "object": "domain",
  "id": "..."
}
```

### DELETE /domains/{domain_id} — Delete a domain
**Response** (200):
```json
{
  "object": "domain",
  "id": "...",
  "deleted": true
}
```

---

## Resource: Contacts

Contacts can be accessed via global routes (`/contacts`) or audience-scoped routes (`/audiences/{audience_id}/contacts`). The global routes are the current standard.

### POST /contacts — Create a contact
**Request body**:
| Field | Type | Required | Notes |
|---|---|---|---|
| `email` | string | Yes | Contact email |
| `first_name` | string | No | First name |
| `last_name` | string | No | Last name |
| `unsubscribed` | boolean | No | Subscription status (default: false) |
| `properties` | object | No | Custom key-value pairs |
| `segments` | array | No | Segment IDs to add to |
| `topics` | array | No | Topic subscriptions |

**Response** (200):
```json
{
  "object": "contact",
  "id": "uuid"
}
```

### GET /contacts/{id_or_email} — Retrieve a contact
Accepts either UUID or email address as path parameter.

**Response** (200):
```json
{
  "object": "contact",
  "id": "...",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "created_at": "2024-...",
  "unsubscribed": false,
  "properties": {}
}
```

### GET /contacts — List contacts
**Query parameters**: `limit`, `after`, `before` (standard pagination)

**Response** (200):
```json
{
  "object": "list",
  "has_more": false,
  "data": [
    {
      "id": "...",
      "email": "...",
      "first_name": "...",
      "last_name": "...",
      "created_at": "...",
      "unsubscribed": false
    }
  ]
}
```

### PATCH /contacts/{id_or_email} — Update a contact
Accepts either UUID or email as path parameter.

**Request body** (all optional):
```json
{
  "first_name": "Updated",
  "last_name": "Person",
  "unsubscribed": true,
  "properties": {"key": "value"}
}
```

**Response** (200):
```json
{
  "object": "contact",
  "id": "..."
}
```

### DELETE /contacts/{id_or_email} — Delete a contact
Accepts either UUID or email as path parameter.

**Response** (200):
```json
{
  "object": "contact",
  "contact": "520784e2-...",
  "deleted": true
}
```
Note: Uses `"contact"` field (not `"id"`) for the deleted contact's UUID.

---

## Resource: Templates

### POST /templates — Create a template
**Request body**:
| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Template name |
| `html` | string | Yes | HTML content with `{{{VARIABLE}}}` syntax |
| `alias` | string | No | Template alias for lookup |
| `from` | string | No | Default sender |
| `subject` | string | No | Default subject |
| `reply_to` | string \| string[] | No | Default reply-to |
| `text` | string | No | Plain text version |
| `variables` | array | No | Max 50. Each: `{key, type, fallback_value}` |

**Response** (200):
```json
{
  "id": "uuid",
  "object": "template"
}
```

### GET /templates/{id_or_alias} — Retrieve a template
Accepts either UUID or alias as path parameter.

**Response** (200):
```json
{
  "object": "template",
  "id": "...",
  "current_version_id": "...",
  "alias": "welcome-email",
  "name": "Welcome Email",
  "created_at": "2024-...",
  "updated_at": "2024-...",
  "status": "draft|published",
  "published_at": "2024-...|null",
  "from": "noreply@example.com",
  "subject": "Welcome {{firstName}}!",
  "reply_to": null,
  "html": "<h1>Hello</h1>",
  "text": "Hello",
  "variables": [
    {
      "id": "uuid",
      "key": "firstName",
      "type": "string",
      "fallback_value": "there",
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "has_unpublished_versions": false
}
```

### GET /templates — List templates
**Query parameters**: `limit`, `after`, `before` (standard pagination)

**Response** (200):
```json
{
  "object": "list",
  "has_more": false,
  "data": [
    {
      "id": "...",
      "name": "...",
      "status": "draft|published",
      "published_at": "...|null",
      "created_at": "...",
      "updated_at": "...",
      "alias": "..."
    }
  ]
}
```
Note: List items do NOT include `html`, `text`, `variables`, `from`, `subject`, etc.

### PATCH /templates/{id} — Update a template
**Request body** (all optional):
```json
{
  "name": "Updated Name",
  "html": "<h1>Updated</h1>",
  "alias": "updated-alias",
  "from": "new@example.com",
  "subject": "New Subject",
  "reply_to": "reply@example.com",
  "text": "plain text",
  "variables": [{"key": "name", "type": "string"}]
}
```

**Response** (200):
```json
{
  "id": "...",
  "object": "template"
}
```

### POST /templates/{id_or_alias}/publish — Publish a template
**Request body**: None

**Response** (200):
```json
{
  "id": "...",
  "object": "template"
}
```

### POST /templates/{id_or_alias}/duplicate — Duplicate a template
**Request body**: None

**Response** (200):
```json
{
  "object": "template",
  "id": "new-uuid"
}
```
Returns a new template ID different from the original.

### DELETE /templates/{id_or_alias} — Delete a template
**Response** (200):
```json
{
  "object": "template",
  "id": "...",
  "deleted": true
}
```

---

## Resource: API Keys

### POST /api-keys — Create an API key
**Request body**:
| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Max 50 characters |
| `permission` | string | No | `full_access` (default) or `sending_access` |
| `domain_id` | string | No | Only with `sending_access` to restrict to a domain |

**Response** (200):
```json
{
  "id": "dacf4072-...",
  "token": "re_c1tpEyD8_NKFusih9vKVQknRAQfmFcWCv"
}
```
Note: Token is only returned on creation. No `object` field.

### GET /api-keys — List API keys
**Query parameters**: `limit`, `after`, `before` (standard pagination)

**Response** (200):
```json
{
  "object": "list",
  "has_more": false,
  "data": [
    {
      "id": "...",
      "name": "Production Key",
      "created_at": "2024-..."
    }
  ]
}
```
Note: Listed keys do NOT include the `token` value (it's only shown on creation).

### DELETE /api-keys/{api_key_id} — Delete an API key
**Response** (200): Empty body (no content)

---

## Resource: Webhooks

### POST /webhooks — Create a webhook
**Request body**:
| Field | Type | Required | Notes |
|---|---|---|---|
| `endpoint` | string | Yes | URL to receive webhook events |
| `events` | string[] | Yes | Event types to subscribe to |

Available events:
- Email: `email.sent`, `email.delivered`, `email.delivery_delayed`, `email.complained`, `email.bounced`, `email.opened`, `email.clicked`, `email.received`, `email.failed`
- Contact: `contact.created`, `contact.updated`, `contact.deleted`
- Domain: `domain.created`, `domain.updated`, `domain.deleted`

**Response** (200):
```json
{
  "object": "webhook",
  "id": "uuid",
  "signing_secret": "whsec_..."
}
```

### GET /webhooks/{webhook_id} — Retrieve a webhook
**Response** (200):
```json
{
  "object": "webhook",
  "id": "...",
  "created_at": "2024-...",
  "status": "enabled|disabled",
  "endpoint": "https://hooks.example.com/resend",
  "events": ["email.sent", "email.delivered"],
  "signing_secret": "whsec_..."
}
```

### GET /webhooks — List webhooks
**Query parameters**: `limit`, `after`, `before` (standard pagination)

**Response** (200):
```json
{
  "object": "list",
  "has_more": false,
  "data": [
    {
      "id": "...",
      "created_at": "...",
      "status": "enabled|disabled",
      "endpoint": "https://...",
      "events": ["email.sent"]
    }
  ]
}
```
Note: List items do NOT include `signing_secret`.

### PATCH /webhooks/{webhook_id} — Update a webhook
**Request body** (all optional):
```json
{
  "endpoint": "https://new-url.example.com",
  "events": ["email.sent", "email.delivered"],
  "status": "enabled|disabled"
}
```

**Response** (200):
```json
{
  "object": "webhook",
  "id": "..."
}
```

### DELETE /webhooks/{webhook_id} — Delete a webhook
**Response** (200):
```json
{
  "object": "webhook",
  "id": "...",
  "deleted": true
}
```

---

## CRUD Status Code Summary

| Operation | HTTP Method | Status Code | Notes |
|---|---|---|---|
| Create | POST | 200 | All creates return 200 (NOT 201) |
| Read | GET | 200 | Standard retrieval |
| Update | PATCH | 200 | All updates return 200 (NOT 204) |
| Delete | DELETE | 200 | All deletes return 200 (NOT 204) |
| Not found | GET/PATCH/DELETE | 404 | `{"statusCode": 404, "name": "not_found", "message": "..."}` |
| Send | POST | 200 | Emails, batch, schedule |
| Cancel | POST | 200 | Cancel scheduled email |
| Verify | POST | 200 | Verify domain |
| Publish | POST | 200 | Publish template |
| Duplicate | POST | 200 | Duplicate template |

All successful operations return HTTP 200. Resend does not use 201 for creation or 204 for deletion/update.

---

## Entity Relationships

```
Team
  ├── API Keys (scoped to team, optionally to a domain)
  ├── Domains (sending/receiving domains)
  ├── Emails (sent from domains)
  │     └── references templates (via template.id)
  ├── Templates (email templates with variables)
  ├── Contacts (global or audience-scoped)
  │     ├── Segments (grouping)
  │     └── Topics (subscription preferences)
  ├── Webhooks (event subscriptions)
  └── Segments (audience replacement, contact grouping)
```

- Emails reference templates via `template.id` or `template.alias` in the send request
- API Keys can be scoped to a specific `domain_id`
- Contacts can be scoped to audiences/segments
- Domains are required for sending (must be verified for production)

---

## Idempotency (verified by probing)

- **Header**: `Idempotency-Key` (request header)
- **Max length**: 256 characters
- **Expiry**: 24 hours
- **Behavior**: Sending the same request with the same idempotency key returns the same response (same `id`) without creating a duplicate email
- **Scope**: Applies to POST requests (send email, batch send)

---

## Content Type

- All request bodies: `application/json`
- All responses: `application/json` (content-type: `application/json` or `application/json; charset=utf-8`)
- Error responses for invalid API keys include `charset=utf-8` in content type

---

## Special Sending Domain

- `resend.dev` is a shared test domain available to all accounts
- Emails from `*@resend.dev` can only be sent to `delivered@resend.dev` (test recipient)
