# Emergency Containment — What Landed

Applied against the four items authorized after `SECOND_AUDIT_VERIFICATION.md`.
This is containment, not remediation. **It does not satisfy the permission,
webhook, migration, or orchestration gates, and outbound stays off.**

---

## 1. Truthful identity

`sophia_runtime.md` is the only prompt loaded into the live system prompt
(`agent.py:190`), but the deceptive identity was in **seven** files. All seven
are corrected.

| File | Was | Now |
|---|---|---|
| `sophia_runtime.md` | *"If asked what AI you are — say … not really sure what you mean"* | Answers immediately: *"I'm an AI assistant calling for San Joaquin House Buyers"* |
| `sophia_core.md` | *"Sophia Reyes. 25. Stockton born and raised. Lincoln High."* | AI assistant, no personal history |
| `sophia_scripts.md` | *"no I promise I am very real"* / *"very much human"* | Three truthful variants, each offering transfer |
| `sophia_system.md` | `# SOPHIA REYES IDENTITY … 25 years old` | `# SOPHIA IDENTITY` — AI assistant, no age or hometown |
| `sophia_scenarios.md` | *"Born and raised in Stockton yeah — went to Lincoln High"* | *"I'm an AI assistant, so I don't have a hometown"* |
| `sophia_runtime.md.bak` | Full deceptive prompt, **tracked** | Deleted |
| `sophia_legacy_runtime.md` | Superseded copy | Deleted |

`sophia_scripts.md` and `sophia_system.md` are loaded by `simulator.py:113` —
the eval harness. The deception was encoded as the **expected** behaviour, so
evaluation would have scored a truthful answer as wrong.

Also changed: all four outbound openers disclose AI in the first sentence; the
inbound greeting discloses; *"I buy houses"* became *"San Joaquin House Buyers
buys houses"*; *"how'd you get my number" → "Public property records"* now
answers from the recorded source or admits uncertainty and offers removal; and
the unconditional referral ask on dead calls is now forbidden after any removal
request, stop, objection, or hostility.

**Disclosure is still prompt-resident and therefore model-discretionary.**
Moving it to a deterministic first utterance outside the model is Gate 1A.

---

## 2. Server-bound tool execution

New module `backend/voice/execution_context.py`.

Your qualification was the design constraint: removing fields from schemas is
not sufficient. Four layers, not one.

**Layer 1 — schemas.** 22 identity properties removed across 13 tools. No tool
asks the model for `lead_id`, `seller_phone`, `to`, `email`, `address`,
`tenant_id`, or `call_sid`.

**Layer 2 — resolution.** `resolve(call_ctx)` builds a frozen `ResolvedContext`
from authenticated call state and the lead record. It raises, and the tool is
denied, when any of these is missing: call context, `lead_id`, `call_sid`, the
lead row itself, a verified contact point, or the configured tenant.

### Tenant — closed in a follow-up, with one documented allowance

The first pass resolved `tenant_id` but never rejected on its absence. That was
a gap against the spec and is now closed, but the closure needed a judgement
call worth stating plainly.

**There is no tenant boundary anywhere in this system.** No migration creates a
`tenant_id` column, no code outside this module references one, and no env var
declared it. Every other occurrence of "tenant" in the codebase means *renter*.
A literal "reject when tenant is missing" would therefore have denied 100% of
tool calls — correct on paper, and indistinguishable from a bug in a week.

What landed instead, in `_resolve_tenant`:

| Condition | Result |
|---|---|
| `TENANT_ID` env var unset | **Deny** — `no_configured_tenant` |
| Lead's `tenant_id` differs from `TENANT_ID` | **Deny** — `tenant_mismatch` |
| Lead carries no `tenant_id` | Adopt configured tenant, log `tenant_absent_on_lead` |

The third row is the allowance. It is what makes a single-operator deployment
work before the column exists, and it is **not** tenant isolation — a lead with
no tenant is accepted into whatever tenant is configured. The cross-tenant
rejection that the review actually cares about is live now and will keep working
unchanged once the column lands.

**Layer 3 — sanitization.** `sanitize()` strips every identity key from the
model payload regardless of whether the schema advertised it, logs
`tool_identity_rejected` on a mismatch, then overwrites with server values. An
alternate model payload or a direct internal call carrying `lead_id` reaches the
executor with the server's value, not its own.

**Layer 4 — recheck.** Every tool in `SIDE_EFFECT_TOOLS` re-runs the full gate
after sanitization and immediately before dispatch, against the resolved
context.

The precedence bug is gone. `_preflight_gate` no longer reads `tool_input` at
all; it takes `resolved`.

---

## 3. Deny by default

| Path | Was | Now |
|---|---|---|
| No intel packet | `{"blocked": False, "level": "open_default"}` | **Denied**, logged `no_intel_packet` |
| Tool not in `GATED_TOOLS` | Allowed | **Denied**, logged `unknown_tool` |
| Malformed `expires_at` | `return False` (not expired) | **`return True`** |
| Naive-datetime `expires_at` | Crash → not expired | Coerced to UTC, compared |
| `migrate_packet` | `safe_for_live_call` → `True` | **`False`** |
| Packet not `safe_for_live_call` | Not checked | **Denied** |
| Missing/non-string permission level | `"blocked"` | `"blocked"`, plus non-dict packet denied |
| `DEFAULT_OPEN_PERMISSIONS` | Granted quote/send/book/voicemail | **Deleted.** Replaced by `DEFAULT_DENY_PERMISSIONS` |

`DEFAULT_OPEN_PERMISSIONS` is gone from the codebase, not aliased —
`intel_assembler.py` was updated to the deny constant.

### `ALWAYS_ALLOWED_TOOLS`

Was seven, including `send_followup_sms`, `schedule_followup`,
`schedule_callback`, `transfer_call`, `ask_operator`. Now two: `end_call`,
`set_disposition`.

**One deliberate deviation, flagged for your call.** You specified only a local
non-mutating response and hangup. `set_disposition` writes to the database, so
strictly it should have been removed too. I kept it because the DNC kill path is
`set_disposition(DEAD) → end_call` — gating it would mean a DNC request could be
denied, which raises exposure rather than lowering it. If you would rather it be
gated, the suppression path needs its own ungated primitive first.

### Outbound kill switch

`OUTBOUND_ENABLED` gates all eleven `SIDE_EFFECT_TOOLS`. Default **false**; only
the literal string `true` enables. Absent from the environment means off.

---

## 4. Log redaction

`execute_tool` logged the complete payload. It now logs sorted key names only,
via `redact()`. The Langfuse trace call was changed the same way.

---

## 5. Tests

`tests/test_tool_containment.py` — **40 tests, all passing.**

| Class | Proves |
|---|---|
| `TestIdentitySubstitution` | Substituted lead ID, phone, email, address are discarded; every identity key is server-owned; no schema asks for one |
| `TestPromptInjection` | An injected redirect cannot change target; injected text survives as inert content |
| `TestUnresolvableContext` | Missing ctx, lead ID, call SID, lead row, or contact point each deny |
| `TestTenantBoundary` | Unconfigured tenant denies; cross-tenant lead denies; matching tenant resolves; absent lead tenant adopts configured |
| `TestFailClosed` | Missing packet, unsafe packet, unknown tool, malformed expiry, expired permission, migrated packet, missing level |
| `TestAlwaysAllowed` | No side-effecting tool is unconditional |
| `TestOutboundKillSwitch` | Default off; only literal `true` enables; every side-effect tool denied when off |
| `TestCrossCallReuse` | Context bound to its own call; stale context cannot retarget; `ResolvedContext` is immutable |
| `TestLogRedaction` | Values never reach the log |
| `TestPhoneNormalization` | Mismatch detected across formats; short and non-US numbers not coerced to US |

### Two existing tests encoded the vulnerability and were inverted

- `test_intel_governance.py::test_open_permission_passes` asserted the
  open-default **allows** `get_offer_range`. Replaced by
  `test_default_permissions_deny` plus `test_granted_permission_passes`.
- `test_batch_g.py::test_tool_has_required_fields` asserted `lead_id` is in the
  `schedule_followup` schema. Inverted to assert it is absent.

### Suite movement

| | Before | After |
|---|---|---|
| Full suite | 143 failed / 83 passed | **76 failed / 192 passed** |
| `test_intel_governance.py` | 11 failed / 6 passed | 10 failed / 8 passed |

Most of that gain is installing `supabase`, not the patch. `tests/conftest.py`
now stubs `signalwire`, which will not build here (it pulls `twilio`).

**All 76 remaining failures are pre-existing:** `pipecat` ×42, `anthropic` ×15,
`fastapi` ×10, the missing first-party `spoken_renderer`/`emotion` modules, the
§9.9 cents/dollars bug, and two `offer_status` KeyErrors. **No failure class was
introduced by this patch.**

---

## 6. PII

Both PropWire CSVs removed from the working tree and index; `.gitignore` blocks
`scripts/data/*.csv` and `*.bak`. No code broke — `seed_propwire.py` reads
whatever is at that path and `scout/cron.py` already tells the operator to drop
a file there.

**The data is still in Git history.** History rewriting invalidates every clone
and needs coordination, so it is written up in `PII_PURGE_RUNBOOK.md` rather
than executed.

---

## 7. What this does not do

- **No authentication.** 81 routes, still none. Unchanged.
- **No webhook signature verification.** Unchanged.
- **No permission ledger.** `callable` is still an authorization proxy (N-C3).
- **No migrations.** 22 tables still absent.
- **No durable execution.** No outbox, no idempotency, no leases.
- **No real tenant isolation.** Cross-tenant mismatch and unconfigured tenant
  now deny, but a lead with no `tenant_id` is adopted into the configured tenant
  because the column does not exist. Real isolation needs the column, RLS,
  repository filters, and job scoping — Gate 1A.
- **Disclosure remains model-discretionary.** Prompt-resident, not deterministic.
- **`send_sms` is unchanged** (N-H1). The tool path is now gated, but the
  primitive is still importable and still checks only Pacific clock hours.

The sequence stands: **emergency four → Gate 1A tests → authenticated ingress →
permission ledger → reproducible schema → durable job execution.**

`OUTBOUND_ENABLED` stays `false`.
