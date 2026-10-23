# Scout persistence and contact-authority repair

The CSV scout now confirms a saved property ID before creating a lead or initiating an alert/follow-up. A failed record does not stop later records. Existing leads do not repeat initial lead actions. Imported phone/email fields are stored through the database wrapper without setting `callable`, clearing suppression or granting contact permission. Failed contact persistence is reported independently of saved-lead count. Owner-alert counters distinguish accepted submissions from failed attempts and do not assert delivery.

The returned report distinguishes unconfigured CSV input, an empty parsed batch, success and partial failures. It reports confirmed property writes, confirmed lead creation, accepted/failed alerts, record failures and contact failures. This is the CSV path only; other source adapters still need structured runtime coverage/health acceptance. No private export or production datastore was used in the fixture tests.

Acceptance tests exercise failed property writes, an isolated poison record followed by a valid one, duplicate existing leads, failed alerts, absent CSV input and imported contacts without authority mutation. Coordinated public-source review is in Bob's `docs/SOURCE-COVERAGE-20261022.md`.
