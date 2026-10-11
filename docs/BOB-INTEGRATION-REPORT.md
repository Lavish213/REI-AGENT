# Bob ↔ Sophia integration repair

Bob's original worker read different memory/intelligence tables from this repository and accepted prior calls or generic hot topics as confirmed facts. Its event tasks ran on no active loop, and most brief fields never reached the voice guidance.

The coordinated repair uses shared `leads`, `properties` and `intel_packets`; a V2 brief bound to the lead with expiry and bounded typed fields; useful pre-call advisory guidance; and `bob_record_call_facts` for fresh, call-bound checklist evidence. Clear frames can produce evidence; uncertain frames cannot. Explicit denials replace confirmations. Preloaded addresses alone are not caller confirmation. Bob's guidance cannot alter action permissions or initial call stages, and early focus disappears after live dialogue begins.

A full assembly regression also caught a money boundary error: `_detect_conflicts` expected cents but `assemble_intel_packet` passed dollar ARV and seller floor against cents-based Bob max offer. The actual assembly path and profile values now retain integer cents, declare `USD_cents`, and reject invalid money before comparison. Existing untagged/cached packets need reviewed refresh in staging; do not blindly rescale values without establishing their provenance and units.

Validation: **1,354 tests passed**, including **51 new Bob integration/fact/payload/money cases**; four dependency deprecation warnings. Backend/new-test critical and unused-import lint, compilation and whitespace pass. This is local contract evidence, not live voice/provider certification.

Bob's companion repair supplies database-owned generations, source fingerprints, transactional brief/decision/outbox saves, retries/quarantine/dead letters, bounded I/O, graceful shutdown, dependency locking and CI. Its tests pass **206 Python cases** and **33 actual SQL contracts**. A 256-attempt queued lease test grants one generation; embedded PostgreSQL serializes requests and does not establish independent-backend concurrency.

Apply `supabase/migrations/20261011_bob_durable_briefs.sql` from the Bob repository once after confirming the shared REI baseline and tenant columns. It owns the new fields/tables/RPCs; do not run a duplicate through another migration system. Deploy the matching consumer and worker together in staging with outbound disabled. Older unversioned, expired or malformed briefs are ignored by the normal conversation policy.

Remaining blockers include the incomplete shared schema baseline, actual Supabase concurrency/recovery, receiver route/authentication/deduplication, operational alerts/retention, and durable REI post-call handoff. The fact hook is awaited and failure-contained; process death before that RPC still requires durable post-call recovery. The earlier real-phone, acoustic, cancellation/rescheduling and operator approval delivery gaps remain.

Detailed 38-finding audit and rollout instructions: [Bob repair branch](https://github.com/Lavish213/Bob-Intelligence-/tree/repair/bob-integration), `docs/BOB-AUDIT.md`, `docs/BOB-FINDINGS.json`, and `README.md`. No migration was applied to production, nothing deployed and no real recipients contacted.
