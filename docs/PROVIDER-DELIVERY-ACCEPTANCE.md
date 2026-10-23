# Provider delivery receipts and recovery

The SMS and SendGrid routes acknowledge only durably staged, authenticated events. SQLite at the existing private `COMMUNICATION_JOURNAL_PATH` retains callbacks across process restarts; a five-second recovery loop mirrors them through `apply_delivery_event`. This loop never sends messages and runs independently of outbound campaigns. Apply `supabase/migrations/20261020_provider_delivery_receipts.sql` after existing migrations before enabling this projection. A missing migration leaves events pending and dashboard evidence unavailable.

SMS events bind to an exact accepted message receipt and tenant. New email sends include a non-contact `communication_intent` custom argument bound to the original recipient before submission. SendGrid's API response header is not assumed identical to its webhook message ID. Legacy events without an exact binding stay pending for provider reconciliation. Caller-supplied lead IDs and address lookups cannot redirect events to an arbitrary lead.

Provider events are append-only and deduplicated. Database application and message projection share one transaction; lost acknowledgements replay the same event. Delayed queued/sent/deferred events cannot reverse terminal evidence. Conflicting success/failure receipts remain `conflicting_receipts`. Opens and clicks are separate observations, never delivery evidence, engagement bonuses, or proof of a human reading. Failure codes no longer automatically declare a phone permanently invalid.

Unsubscribe, group-unsubscribe, spam, dropped, and bounce events durably block the email address locally before acknowledgement, including during database outages. Unsubscribe and spam complaints also block calls and texts to leads with that address before database sync, preserving the existing broad opt-out policy. Bounces block email without inventing a cross-channel opt-out. Resubscribe events never grant authority. The remote projection pauses email only when tenant, lead and current address agree. No contact permission, quote authority, offer acceptance, external booking, or outbound action is created.

`GET /api/operations/delivery` uses the existing source-command secret and returns the latest 100 messages with projected receipts plus pending journal counts. The dashboard validates tenant and schema, strips recipients and raw payloads, and shows conflicts, pending recovery, empty results and unavailable evidence.

Verification covers invalid batches and conflicting IDs, batch rollback, database outage, lost ACK, real process exit, concurrent duplicate staging, 1,000 duplicate receipts, and PostgreSQL replay/ordering/tenant/permission contracts. These synthetic tests do not establish carrier or email delivery.

Remaining production acceptance: persistent storage and replica topology, additive migration against a backed-up baseline, signed provider callback configuration, missing-callback reconciliation against provider records, and authorized test-contact delivery. SignalWire callbacks are best effort; no callback means delivery remains unconfirmed. The read model contains received callbacks, not all accepted sends. Rollback must preserve SQLite and SQL receipts and must not resend messages.

Provider references checked October 16, 2026:
- https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/event
- https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/twilio-sendgrid-event-webhook-overview
- https://www.twilio.com/docs/sendgrid/glossary/message-id
- https://signalwire.com/docs/compatibility-api/guides/webhooks

## Accepted-message inventory follow-up — October 22, 2026

Provider acceptance and its inventory entry now commit together in the private communication journal. Recovery stages deterministic `accepted` evidence for SMS/email even if no provider callback arrives, then applies the existing SQL projection. Such messages remain pending/unconfirmed; a subsequent callback can establish delivery without a late acceptance event reversing it. Identical acknowledgement replay is idempotent, conflicting receipt replay is rejected, and another tenant cannot accept an intent it does not own.

Legacy accepted journal entries are backfilled with unknown acceptance time; no timestamp is invented. Uncertain submission intents remain explicitly counted and cannot be automatically resent. Staging and callback recovery are failure-isolated. The authenticated read model reports accepted, uncertain and pending-staging counts; the dashboard shows incomplete/older-source inventory honestly. The latest 100 projected messages are a window, not the entire history.

Scope remains journaled SMS/email. Calls, messages sent outside these adapters, unjournaled historical sends, automatic provider status polling and production migration/volume/provider acceptance are not established by this change. No new SQL migration is needed beyond the existing provider-receipt migration. The fixture integration test uses an HTTP acceptance provider and RPC bridge with real SQLite/PostgreSQL execution and the authenticated source API; it never contacts a live messaging provider.
