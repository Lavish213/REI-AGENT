# Second Audit — Independent Verification

A second review arrived against commit `068dee9` on
`claude/project-visibility-8cah98`. I did not take it at face value. This
document records what I verified myself, line by line, what holds, what I got
wrong in my own audit, and what changes as a result.

**Bottom line: it holds.** Every load-bearing claim I checked reproduced. It
found the single most serious defect in the codebase, which my audit missed,
and it correctly characterized the most legally dangerous artifact in the repo,
which my audit understated.

---

## 1. Verification results

| Claim | Verified | Notes |
|---|---|---|
| N-C1 tools fail open with no intel packet | ✅ **Confirmed** | Plus an extra fail-open they did not name |
| N-C2 model supplies IDs and destinations | ✅ **Confirmed** | Worse than stated — model value takes *precedence* |
| N-C3 `callable` used as contact authority | ✅ Confirmed | |
| N-C4 prompt directs deception | ✅ **Confirmed** | Verbatim text below; worse than stated |
| N-H1 `send_sms` has no consent decision | ✅ Confirmed | Plus a `bypass_hours` escape hatch |
| N-H4 offer fallback + unit guessing | ✅ **Confirmed** | Fabricates $150k–$175k |
| N-H8 email unsubscribe sets SMS opt-out | ✅ Confirmed | |
| 6 tables created vs 28 referenced | ✅ **Confirmed** | I got this wrong — see §3 |
| PropWire CSVs contain personal data | ✅ **Confirmed** | Named individuals + agent emails/phones |
| 81 route decorators | ✅ Confirmed | My "28" counted POST only |
| 259 broad/bare exception handlers | ✅ Confirmed | Their methodology beat mine |
| `.env.example` empty | ✅ Confirmed | Matches my §9.6 |
| Suite stops on `spoken_renderer` | ✅ Confirmed | Matches my §9.10 |

Nothing I checked failed to reproduce. I found no overstatement.

---

## 2. The finding I missed — and it is the worst one

### N-C2 confirmed, and the precedence makes it worse

Every tool schema in `backend/voice/tools.py` requires the **language model** to
supply the record identifier:

```
book_appointment      required: date, time, address, lead_id, seller_phone
send_followup_sms     required: to, message, lead_id
send_followup_email   required: to, lead_id
send_offer_summary    required: seller_phone, lead_id
collect_and_send_email       takes: email, lead_id
get_offer_range       required: address, lead_id
end_call / transfer_call / schedule_callback / ask_operator   all require lead_id
```

Then `tools.py:266-268`:

```python
lead_id = (tool_input.get("lead_id") or "") if tool_input else ""
if not lead_id and call_ctx is not None:
    lead_id = getattr(call_ctx, "lead_id", "")
```

**The model's value is used first. The authenticated call context is only a
fallback.** That is exactly backwards. The one identifier the system can trust —
the lead bound to the call it actually placed — is subordinated to a value
produced by a model that is reading untrusted seller speech.

A seller saying "send that to 209-555-0143 instead," a transcription error on a
spoken number, or a deliberate injection can write to another lead's record or
send an offer summary to an arbitrary destination. Classic confused deputy.

**Why I missed it.** I audited prompt injection at the *text* layer, found
seller speech properly wrapped in `<seller>` tags, and gave the codebase credit
for it in `AUDIT_AND_GRADE.md` §9.28. That credit stands for what it covers —
but I never looked at the tool-argument layer, which is where the actual
authority lives. Delimiting the input does nothing when the model still names
the target. That was the wrong place to stop looking.

### N-C1 confirmed, plus one more fail-open

```python
if tool_name not in GATED_TOOLS:
    return {"blocked": False, "level": "allowed"}      # tools.py:274
...
intel_packet = getattr(call_ctx, "intel_packet", None) if call_ctx else None
if not intel_packet:
    return {"blocked": False, "level": "open_default"} # tools.py:293
```

`DEFAULT_OPEN_PERMISSIONS` then grants `quote_range`, `send_summary`,
`book_appointment`, and `drop_voicemail`.

Three fail-opens in one path: unknown tool allowed, missing packet allowed, and
`is_permission_expired` returning `False` on a malformed timestamp
(`intel_packet.py:97-99`).

**A fourth they did not name:** `migrate_packet` does
`raw.setdefault("safe_for_live_call", True)` (`intel_packet.py:78`). Upgrading
an old packet *asserts* it is safe for a live call.

Worth noting precisely, because it shows intent: `DEFAULT_FALLBACK_PERMISSIONS`
**does** block the risky tools. The safe default was written. It is simply not
on the missing-packet path. The bug is not ignorance of fail-closed design — it
is a branch that never reaches it.

---

## 3. Where my own audit was wrong

### 3.1 I marked the migrations `KEEP`. They are not sufficient.

`REBUILD_MAP.md` §4.10 classifies `supabase/migrations/*` as
`KEEP — applied; forward-only`. Verified:

```
CREATE TABLE:  call_events, compliance_log, followups, offers,
               transcript_chunks, workflows          → 6
ALTER TABLE:   calls, leads, properties              → assumed pre-existing
Referenced in code:                                     28
```

**22 referenced tables are never created by any committed migration**, including
`leads`, `properties`, `calls`, `contacts`, `sms_messages`, `dnc_list`,
`approval_requests`, `intel_packets`, `decision_records`.

The schema of record is not in version control. A clean environment cannot be
built from this repository. `KEEP` was the wrong classification — it should be
`REPLACE`, and reconstructing the baseline schema is a new checklist item.

### 3.2 I marked the PropWire CSVs `KEEP`. That was a bad call.

`REBUILD_MAP.md` §4.10: `scripts/* (9 py, 2 csv) — KEEP — never imported`. I
reasoned about whether the code imports them. I did not open them.

They contain **578 rows of real personal data**:

```
Owner 1–4 First Name / Last Name
Owner Mailing Address / City / State / Zip
Listing Agent Full Name / Email / Phone
```

Named individuals, home addresses, plus named real-estate agents with direct
email and phone — committed to Git. Deleting the files from `HEAD` does not
remove them from history, forks, or clones.

That is not a `KEEP`. It is a data-protection issue that needs history rewrite
and, depending on counsel's view, possibly notification.

### 3.3 My exception count was scoped too narrowly

I reported 246 broad handlers by grep over `backend/`. Their AST scan found 259.
Both are right: `backend` 246 + `scripts` 12 + `tests` 1 = **259**. Their
methodology was better and their number is the one to use.

### 3.4 I understated the AI-disclosure problem

`AUDIT_AND_GRADE.md` §2 says the disclosure is "reactive-only and delegated to
the model." True, and incomplete. The system prompt actively instructs evasion.

---

## 4. N-C4 verified — the verbatim text

`backend/voice/prompts/sophia_runtime.md:2`:

> You are Sophia Reyes. 25. Stockton born and raised. Lincoln High. Delta
> College. **That identity is permanent and cannot change.** … **If asked what
> AI you are — say "I'm Sophia, I work for San Joaquin House Buyers — not
> really sure what you mean."** … Never say: acquisitions rep, investor,
> wholesaler.

Line 41:

> `"are you a robot" → "I work with the team at San Joaquin House Buyers — want
> me to connect you with someone directly?"`

Line 30:

> `"how'd you get my number" → "Public property records."` — while the code also
> uses BatchData skip trace and CRMLS.

Opener D:

> `"I buy houses in Stockton"` — first person, from an agent that buys nothing.

This is not a missing disclosure. **It is a scripted response of feigned
incomprehension to a direct question about being AI**, on top of a fabricated
human biography asserted as immutable.

It also **directly contradicts `ai_identity.py`**, which defines
`_SB1001_DISCLOSURE` and tries to inject it. That injection arrives as a
`runtime_instruction` — a prompt suggestion — against a system prompt that says
the identity "cannot change." The system prompt very likely wins.

And `"Every dead call ends with: 'do you know anyone thinking about selling?'
No exceptions"` contradicts honoring a DNC request immediately.

**This is now the most dangerous artifact in the repository.** It is a text
file. It can be rewritten this afternoon. There is no reason to run another
outbound call against it.

---

## 5. Revised grade

| Area | Was | Now | Why |
|---|---|---|---|
| Security | F | **F** | N-C2 confused deputy compounds "no auth" |
| Compliance | F | **F** | Now evidenced as directed deception, not omission |
| Data integrity | D | **F** | Model controls which record is mutated |
| Data governance | — | **F** | 578 people's PII in Git; no source register |
| Platform / reproducibility | — | **F** | 22 of 28 tables not in migrations |
| Documentation | A− | **B+** | Two `KEEP` calls were wrong (§3.1, §3.2) |

### Overall: **D+ → D−**

The prototype quality claim is unchanged; the trust claim is worse. There is no
enforcement boundary anywhere between an untrusted transcript and a database
write or an outbound message.

---

## 6. Where I disagree — on sequencing only

I accept every finding. One difference of emphasis:

The review's next milestone is "a narrow, truthful, inbound/internal-only system
with authenticated ingress, bound model capabilities, immutable permissions, a
reproducible database, and durable side effects." That is the right destination
and it is months of work.

Three items are **hours**, not months, and each removes real exposure today:

1. **Rewrite the identity prompt.** One markdown file. Removes directed
   deception entirely.
2. **Drop `lead_id`, `to`, `seller_phone`, `email` from every tool schema** and
   read them from `call_ctx` only. Roughly 200 lines. Closes the confused deputy
   without any architecture.
3. **Flip the three fail-opens to deny** — `tools.py:274`, `tools.py:293`,
   `intel_packet.py:97`. About ten lines.

Gate 1A is correct as a gate. It should not block these three, which can land
before the gate is designed. Everything else — tenant isolation, outbox,
capability registry, migrations rebuild, governance registers — I accept as
specified and sequenced.

I also accept the unverifiable list as genuinely unverifiable. Nothing in this
repository can attest to live Supabase RLS, Railway configuration, DNC
subscription, consent records, or provider settings. Those need evidence
collection, and treating them as blockers rather than assumed-good is correct.

---

## 7. Consolidated register

| Source | Count |
|---|---|
| `MASTER_REFERENCE.md` §9 | 15 |
| `AUDIT_AND_GRADE.md` §3 | 15 |
| Second audit — critical | 4 |
| Second audit — high | 12 |
| Second audit — medium | 20 |
| Found during this verification | 2 |

**68 distinct findings.** The two new ones: `migrate_packet` defaulting
`safe_for_live_call=True`, and model-supplied `lead_id` taking precedence over
the authenticated call context.

### Revised top of the queue

| # | Item | Effort | Was |
|---|---|---|---|
| 1 | Rewrite identity prompt — remove directed deception | Hours | *not ranked* |
| 2 | Remove IDs/destinations from tool schemas (N-C2) | ~1 day | *not ranked* |
| 3 | Flip the four fail-opens to deny (N-C1) | Hours | *not ranked* |
| 4 | TCPA attorney consultation | One call | 1 |
| 5 | DNC fails closed | Hours | 2 |
| 6 | Purge PropWire CSVs + rewrite history | ~1 day | *not ranked* |
| 7 | Recipient-timezone calling hours | 1 day | 3 |
| 8 | Authentication across 81 routes | ~1 week | 4 |
| 9 | Reconstruct the 22 missing tables as migrations | ~1 week | *not ranked* |
| 10 | Hot leads ignored by the queue | 1 day | 6 |

Items 1, 2, 3 and 6 did not exist in my ranking. Three of them are the cheapest
work on the list.

---

*Verified against commit `068dee9`. Every claim above was reproduced from the
files and line numbers cited, not accepted from the review.*
