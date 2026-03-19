# Resend Research

**Description**: Email sending and management API for developers, supporting transactional emails, batch sending, domain management, contacts, templates, and webhooks.
**Docs**: https://resend.com/docs/api-reference/introduction

Resend is a developer-focused email API service that enables applications to send transactional and marketing emails via a REST API. It provides a clean, modern alternative to legacy email providers like SendGrid and Mailgun, with first-class support for React Email components. The API is organized around core resources: Emails (send, batch send, schedule, cancel, retrieve), Domains (register, verify via DNS, configure tracking), Contacts (manage subscriber lists with properties and segments), Templates (create, publish, and send with variable substitution), API Keys (manage access with granular permissions), Broadcasts (bulk marketing emails to audiences), and Webhooks (subscribe to delivery events like sent, delivered, bounced, opened, clicked).

This fake covers the primary API surface that AI agents would use: sending individual and batch emails, managing email lifecycle (scheduling, canceling, retrieving status), domain registration and verification, contact CRUD with subscription management, template creation and publishing, API key management, and webhook configuration. The API uses Bearer token authentication, enforces HTTPS, has a 2 req/sec rate limit per team, and supports cursor-based pagination on list endpoints. All responses follow a consistent pattern with an 'object' field indicating the resource type.

## Scenarios

- **email-sending-lifecycle**: Email Sending Lifecycle — Covers sending individual emails, retrieving their status, and verifying delivery tracking fields.
- **scheduled-email-management**: Scheduled Email Management — Covers scheduling emails for future delivery, updating the scheduled time, and canceling scheduled emails.
- **batch-email-sending**: Batch Email Sending — Covers sending multiple emails in a single API call, verifying individual email tracking, and testing batch limits.
- **domain-management**: Domain Management — Covers the full lifecycle of domain registration, configuration, verification, listing, updating, and deletion.
- **contact-management**: Contact Management — Covers creating, retrieving, updating, listing, and deleting contacts including subscription management and lookup by email.
- **template-lifecycle**: Template Lifecycle — Covers creating, retrieving, listing, publishing, duplicating, updating, and deleting email templates, plus sending emails using templates.
- **api-key-management**: API Key Management — Covers creating API keys with different permission levels, listing keys, and deleting keys.
- **webhook-configuration**: Webhook Configuration — Covers creating webhooks with event subscriptions, listing, retrieving, updating, and deleting webhooks.
- **error-handling**: Error Handling and Edge Cases — Covers authentication failures, validation errors, not-found errors, and other edge cases that AI agents must handle gracefully.
- **template-email-integration**: Template and Email Integration — Covers sending emails using templates with variable substitution, testing template alias lookups, and verifying template defaults are applied.
