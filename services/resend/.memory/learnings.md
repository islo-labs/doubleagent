# Resend API — Surprising Findings & Learnings

## 1. Invalid API key returns 400, not 401 or 403
**Surprise**: An invalid API key (e.g., `re_invalid_key_12345`) returns:
- HTTP **400** with `name: "validation_error"` and `message: "API key is invalid"`

This is unexpected because:
- Missing API key → 401 (expected)
- Invalid API key → 400 (NOT 401/403 as one might expect)
- The SDK maps `InvalidApiKeyError` to status 403, but the real API never seems to return 403 for this

## 2. All successful operations return HTTP 200
**Surprise**: Resend does NOT follow REST conventions for status codes:
- Create → 200 (not 201)
- Delete → 200 (not 204)
- Update → 200 (not 204)
- All actions (cancel, verify, publish, duplicate) → 200

This simplifies the fake server since every success is 200.

## 3. POST /emails response has NO `object` field
**Surprise**: While most create responses include `"object": "resource_type"`, the send email response is just:
```json
{"id": "uuid"}
```
No `object` field. Same for batch send — just `{"data": [{"id": "..."}, ...]}`.

Similarly, `POST /api-keys` returns `{"id": "...", "token": "re_..."}` without an `object` field.

## 4. Rate limit is exactly 2 requests per second per team
**Verified**: Sending 3 requests simultaneously, exactly 2 succeed and 1 gets 429. Rate limit headers:
- `ratelimit-limit: 2`
- `ratelimit-policy: 2;w=1`
- `ratelimit-remaining: 0|1`
- `ratelimit-reset: 1`
- `retry-after: 1` (only on 429)

Additional quota headers on successful sends:
- `x-resend-daily-quota: N`
- `x-resend-monthly-quota: N`

## 5. Contact delete response uses `contact` field instead of `id`
**Surprise**: While domain, template, and webhook delete responses use `"id"` for the resource identifier:
```json
{"object": "domain", "id": "...", "deleted": true}
```
Contact delete uses a different field name:
```json
{"object": "contact", "contact": "520784e2-...", "deleted": true}
```

## 6. ApiKeys delete returns empty body
**Surprise**: `DELETE /api-keys/{id}` returns an empty response body (HTTP 200 with no content), unlike all other delete endpoints which return JSON with `deleted: true`. The SDK's `ApiKeys.remove()` returns `None`.

## 7. Validation order for email sending
**Surprise**: When sending an email with missing fields, Resend validates in this order:
1. Auth → missing/invalid key
2. Permissions → restricted key
3. JSON parsing → invalid JSON body
4. `to` field first → "Missing `to` field"
5. `html` or `text` → "Missing `html` or `text` field" (before subject!)
6. Then `subject`, `from`, etc.

This means sending `{"from": "x@y.com", "to": "a@b.com"}` returns "Missing `html` or `text` field" (422), NOT "Missing `subject`".

## 8. SDK injects response headers into response dict
**Gotcha**: The SDK adds `response["headers"] = dict(http_response_headers)` to every dict response. This means the fake server does NOT need to include `headers` in its JSON response — the SDK adds it client-side. But it also means the `headers` key in the response dict collides with email custom headers.

## 9. SDK statusCode field check
**Critical**: The SDK checks if the JSON response body contains a `statusCode` field. If it's present and not None and not 200, the SDK raises an error. The fake server MUST NOT include `statusCode` in successful (200) responses, or it will break the SDK.

## 10. resend.dev is a shared test domain
- `*@resend.dev` is available to all accounts as a test sender domain
- Test emails can only be sent TO `delivered@resend.dev`
- This means the grounding token (which is sending-only) can only send to this address

## 11. Idempotency works correctly
**Verified**: Sending the same email twice with the same `Idempotency-Key` header returns the same UUID both times, confirming deduplication works at the API level.

## 12. Template 404 is accessible even with sending-only key
**Surprise**: `POST /emails` with `template.id` pointing to a nonexistent template returns a proper 404:
```json
{"statusCode": 404, "name": "not_found", "message": "Template not found"}
```
This works even with a sending-only API key, unlike `GET /templates/{id}` which returns 401 for restricted keys.

## 13. Missing required fields return 422 with `missing_required_field`
**Noted**: The error name for missing fields is `missing_required_field` (singular), not `missing_required_fields` (plural). The SDK has a `MissingRequiredFieldsError` mapped to 422 / `missing_required_fields` (plural), which may not match exactly.

## 14. Cloudflare is the CDN/proxy
All responses include `server: cloudflare` and `cf-ray` headers, indicating Resend uses Cloudflare as their edge proxy.

## 15. Validation error for invalid email format is 422
```json
{
  "statusCode": 422,
  "name": "validation_error",
  "message": "Invalid `to` field. The email address needs to follow the `email@example.com` or `Name <email@example.com>` format."
}
```
Note: Both `missing_required_field` and `validation_error` can use HTTP 422.
