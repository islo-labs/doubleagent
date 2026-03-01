# Resend Python SDK Analysis

## Package Info

- **Package name**: `resend`
- **Version**: 2.23.0
- **Install**: `pip install resend`
- **Language**: Python
- **Location**: `/Users/rotem.tamir/Library/Python/3.9/lib/python/site-packages/resend/`

---

## Base URL Override

The SDK uses a **module-level singleton pattern** (no client class). Configuration is done via module-level variables:

```python
import resend

# Method 1: Direct assignment (recommended for fake server)
resend.api_key = "re_your_api_key"
resend.api_url = "http://localhost:8080"

# Method 2: Environment variables (checked at import time)
# RESEND_API_KEY → resend.api_key
# RESEND_API_URL → resend.api_url (defaults to "https://api.resend.com")
```

**Default base URL**: `https://api.resend.com`
**Override env var**: `RESEND_API_URL`
**Override at runtime**: `resend.api_url = "http://your-fake:port"`

URLs are constructed as: `f"{resend.api_url}{path}"` (e.g., `http://localhost:8080/emails`)

**Important**: The base URL should NOT have a trailing slash.

---

## HTTP Layer

### HTTP Client
- Uses the **`requests`** library (NOT httpx, NOT urllib3)
- Default timeout: **30 seconds**
- Client: `resend.http_client_requests.RequestsClient`
- Abstract interface: `resend.http_client.HTTPClient`
- Can be replaced: `resend.default_http_client = CustomClient()`

### Request Construction
The SDK calls:
```python
requests.request(method=method, url=url, headers=headers, json=body, timeout=30)
```
- `json=` parameter auto-sets `Content-Type: application/json`
- Content-Type is NOT explicitly set in headers

### Request Headers
Every request includes:
```python
{
    "Accept": "application/json",
    "Authorization": f"Bearer {resend.api_key}",
    "User-Agent": "resend-python:2.23.0",
}
```

Conditional headers:
- `Idempotency-Key: <value>` — Added for POST requests when `options["idempotency_key"]` is provided
- `x-batch-validation: <value>` — Added for `Batch.send()` when `options["batch_validation"]` is provided

---

## Response Handling

### ResponseDict
All dict API responses are returned as `ResponseDict` — a `dict` subclass with attribute-style access:

```python
response = resend.Emails.send({...})
response["id"]  # dict access
response.id     # attribute access (same thing)
```

The `ResponseDict` is NOT a model/dataclass — it's a plain dict enhanced with `__getattr__`. TypedDict annotations exist for type-checking only but have no runtime effect.

### Response Processing Pipeline
1. HTTP response received as `(content_bytes, status_code, headers)`
2. Content-Type must be `application/json` (otherwise error)
3. Body is JSON-parsed
4. **Response headers are injected**: `parsed_data["headers"] = dict(response_headers)` — this means every response dict contains an extra `headers` key with HTTP response headers
5. If `statusCode` field is present and not 200, an exception is raised
6. Dict responses are wrapped in `ResponseDict`
7. List responses (arrays) are returned as plain lists

### perform() vs perform_with_content()
- `perform()` → `Union[T, None]` — may return None (used for delete operations that return empty body)
- `perform_with_content()` → `T` — raises `NoContentError` if body is empty

---

## Error Handling

### Exception Hierarchy
```
Exception
  └── ResendError (base)
      ├── MissingApiKeyError      (401 / missing_api_key)
      ├── InvalidApiKeyError      (403 / invalid_api_key)
      ├── ValidationError         (400, 422 / validation_error)
      ├── MissingRequiredFieldsError (422 / missing_required_fields)
      ├── ApplicationError        (500 / application_error)
      └── RateLimitError          (429 / rate_limit_exceeded, daily_quota_exceeded, monthly_quota_exceeded)
  └── NoContentError              (empty response body)
```

### Error Resolution
The SDK matches on `(statusCode, name)` from the API response JSON:
1. Look up HTTP status code → get dict of error_type → exception_class
2. Look up `name` (error type) in that dict
3. Raise the specific exception, or generic `ResendError` for unknown combinations

### HTTP Client Errors
If `requests` throws any exception, it's caught and re-raised as:
```python
ResendError(code=500, message=str(e), error_type="HttpClientError")
```

### Client-side Validation (raises ValueError, not ResendError)
- `Contacts.update()`: "id or email must be provided"
- `Contacts.get()`: "id or email must be provided"
- `Contacts.remove()`: "id or email must be provided"

**Note on error name mapping quirk**: The SDK maps error name `"invalid_api_key"` to status 403, but the real API returns status 400 with name `"validation_error"` for invalid API keys. This mismatch means the SDK's `InvalidApiKeyError` (403) may never actually be raised for the invalid key scenario — instead, a `ValidationError` (400) would be raised.

---

## Method Inventory

### Emails (`resend.Emails`)

| Method | HTTP | Path | Returns |
|---|---|---|---|
| `send(params, options=None)` | POST | `/emails` | `{"id": "uuid"}` |
| `get(email_id)` | GET | `/emails/{email_id}` | Full email object |
| `list(params=None)` | GET | `/emails` + query | List envelope |
| `update(params)` | PATCH | `/emails/{params['id']}` | `{"object": "email", "id": "..."}` |
| `cancel(email_id)` | POST | `/emails/{email_id}/cancel` | `{"object": "email", "id": "..."}` |

**SendParams** fields: `from`, `to`, `subject`, `bcc`, `cc`, `reply_to`, `html`, `text`, `headers`, `attachments`, `tags`, `scheduled_at`, `template`
**SendOptions**: `idempotency_key`

### Batch (`resend.Batch`)

| Method | HTTP | Path | Returns |
|---|---|---|---|
| `send(params, options=None)` | POST | `/emails/batch` | `{"data": [{"id": "..."}]}` |

**SendOptions**: `idempotency_key`, `batch_validation` (Literal["strict", "permissive"])

### Domains (`resend.Domains`)

| Method | HTTP | Path | Returns |
|---|---|---|---|
| `create(params)` | POST | `/domains` | Full domain with records |
| `get(domain_id)` | GET | `/domains/{domain_id}` | Full domain with records |
| `list(params=None)` | GET | `/domains` + query | List envelope |
| `update(params)` | PATCH | `/domains/{params['id']}` | `{"object": "domain", "id": "..."}` |
| `remove(domain_id)` | DELETE | `/domains/{domain_id}` | `{"object": "domain", "id": "...", "deleted": true}` |
| `verify(domain_id)` | POST | `/domains/{domain_id}/verify` | `{"object": "domain", "id": "..."}` |

### Contacts (`resend.Contacts`)

| Method | HTTP | Path | Returns |
|---|---|---|---|
| `create(params)` | POST | `/audiences/{audience_id}/contacts` OR `/contacts` | `{"object": "contact", "id": "..."}` |
| `get(audience_id=None, id=None, email=None)` | GET | `/contacts/{id_or_email}` | Full contact object |
| `list(audience_id=None, params=None)` | GET | `/contacts` + query | List envelope |
| `update(params)` | PATCH | `/contacts/{id_or_email}` | `{"object": "contact", "id": "..."}` |
| `remove(audience_id=None, id=None, email=None)` | DELETE | `/contacts/{id_or_email}` | `{"object": "contact", "contact": "...", "deleted": true}` |

**Dual routing**: If `audience_id` is provided, routes to `/audiences/{audience_id}/contacts/...`. Otherwise uses `/contacts/...`.
**Email precedence**: When both `id` and `email` are provided, **email takes precedence over id** (matching Node.js SDK behavior).

### Templates (`resend.Templates`)

| Method | HTTP | Path | Returns |
|---|---|---|---|
| `create(params)` | POST | `/templates` | `{"id": "...", "object": "template"}` |
| `get(template_id)` | GET | `/templates/{template_id}` | Full template object |
| `list(params=None)` | GET | `/templates` + query | List envelope |
| `update(params)` | PATCH | `/templates/{params['id']}` | `{"id": "...", "object": "template"}` |
| `publish(template_id)` | POST | `/templates/{template_id}/publish` | `{"id": "...", "object": "template"}` |
| `duplicate(template_id)` | POST | `/templates/{template_id}/duplicate` | `{"object": "template", "id": "new-uuid"}` |
| `remove(template_id)` | DELETE | `/templates/{template_id}` | `{"object": "template", "id": "...", "deleted": true}` |

**Update quirk**: The SDK explicitly strips `id` from the request body before sending:
```python
update_params = {k: v for k, v in params.items() if k != "id"}
```

### API Keys (`resend.ApiKeys`)

| Method | HTTP | Path | Returns |
|---|---|---|---|
| `create(params)` | POST | `/api-keys` | `{"id": "...", "token": "re_..."}` |
| `list(params=None)` | GET | `/api-keys` + query | List envelope |
| `remove(api_key_id)` | DELETE | `/api-keys/{api_key_id}` | `None` (empty body) |

**Delete quirk**: `remove()` uses `perform()` (not `perform_with_content()`), so it returns `None`. This is the ONLY delete method that returns `None`.

### Webhooks (`resend.Webhooks`)

| Method | HTTP | Path | Returns |
|---|---|---|---|
| `create(params)` | POST | `/webhooks` | `{"object": "webhook", "id": "...", "signing_secret": "..."}` |
| `get(webhook_id)` | GET | `/webhooks/{webhook_id}` | Full webhook object |
| `list(params=None)` | GET | `/webhooks` + query | List envelope |
| `update(params)` | PATCH | `/webhooks/{params['webhook_id']}` | `{"object": "webhook", "id": "..."}` |
| `remove(webhook_id)` | DELETE | `/webhooks/{webhook_id}` | `{"object": "webhook", "id": "...", "deleted": true}` |

**Update quirk**: `webhook_id` is extracted from params for the URL, but the full params dict (including `webhook_id`) is sent in the request body.

### Audiences (`resend.Audiences`) — DEPRECATED

All methods emit `DeprecationWarning` and delegate to `Segments`:

| Method | Delegates to |
|---|---|
| `create(params)` | `Segments.create()` |
| `list(params=None)` | `Segments.list()` |
| `get(id)` | `Segments.get()` |
| `remove(id)` | `Segments.remove()` |

### Segments (`resend.Segments`)

| Method | HTTP | Path |
|---|---|---|
| `create(params)` | POST | `/segments` |
| `list(params=None)` | GET | `/segments` |
| `get(id)` | GET | `/segments/{id}` |
| `remove(id)` | DELETE | `/segments/{id}` |

---

## Quirks and Gotchas

### 1. `from` keyword workaround
Python's `from` is a reserved keyword. The SDK uses "functional TypedDict" syntax:
```python
_SendParamsFrom = TypedDict("_SendParamsFrom", {"from": str})
```
Users pass `from` as a dict key: `{"from": "sender@example.com"}`, which works because dict keys are strings.

### 2. Response headers injected into every response
Every API response dict gets `response["headers"] = dict(http_response_headers)` injected. This collides with the `headers` field name used in email custom headers. The SDK handles this with `BaseResponse` declaring `headers: NotRequired[Dict[str, str]]`.

When working with the fake server, every JSON response should work without this injection — it's done client-side by the SDK.

### 3. All methods are `@classmethod`
No instance state. The SDK is entirely stateless per-resource-class. All configuration is in module-level variables (`resend.api_key`, `resend.api_url`, `resend.default_http_client`).

### 4. ID parameter naming inconsistency
Different resources use different parameter names for the same concept:
- `ApiKeys.remove(api_key_id)`
- `Domains.remove(domain_id)`
- `Webhooks.remove(webhook_id)`
- `Templates.remove(template_id)`
- `Emails.get(email_id)`

### 5. ID stripping from body varies by resource
- `Templates.update()`: Explicitly strips `id` from body
- `ContactProperties.update()`: Builds new payload without `id`
- `Domains.update()`, `Emails.update()`: Send full params including `id` in body
- `Webhooks.update()`: Sends full params including `webhook_id` in body

### 6. Contacts email precedence
When both `id` and `email` are provided to `Contacts.get()`, `update()`, or `remove()`, **email takes precedence**. This matches the Node.js SDK behavior per SDK comments.

### 7. Contacts.Topics.update() sends raw array
The `update()` method for contact topics sends the `topics` array directly as the request body (a raw list), not wrapped in a dict. This is the only PATCH method that sends a list as the top-level JSON body.

### 8. Error name mismatch for invalid API keys
- SDK maps: 403 → `invalid_api_key` → `InvalidApiKeyError`
- Real API returns: 400 → `validation_error` for invalid keys
- The SDK's `InvalidApiKeyError` may never be raised for the actual invalid key scenario

### 9. Pagination parameter passing
All `list()` methods accept `ListParams` (dict with `limit`, `after`, `before`) and use `PaginationHelper.build_paginated_path()` to append query parameters to the URL. Parameters go in URL query string, NOT request body.

### 10. ApiKeys.remove() returns None
Unlike all other delete methods which return a response dict with `deleted: true`, `ApiKeys.remove()` returns `None` because the API returns an empty body for API key deletion.

### 11. Content-Type validation
The SDK validates that the response `Content-Type` is `application/json`. If the fake server returns a different content type, the SDK will raise an error. Always set `Content-Type: application/json` on responses.

### 12. statusCode field check
The SDK checks if the JSON response contains a `statusCode` field. If present and not `None` and not `200`, it treats it as an error and calls `raise_for_code_and_type()`. This means the fake server should NOT include `statusCode` in successful responses.
