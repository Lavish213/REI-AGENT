# Call States

## Lead Pipeline Stages

These are the canonical `stage` values on the `leads` table:

| Stage | Meaning |
|---|---|
| `new` | Lead created, not yet contacted |
| `contacted` | At least one contact attempt made |
| `offer_made` | Verbal offer discussed on call |
| `walkthrough_booked` | Appointment scheduled, confirmation SMS sent |
| `under_contract` | Purchase agreement signed |
| `closed` | Deal closed |
| `dead` | Unresponsive, hostile, wrong number, or DNC |

Stage transitions are set by:
- `update_lead_stage()` directly (manual or tool call)
- `update_lead_for_disposition()` — HOT sets `priority_callback`, DEAD sets `opted_out=True`
- `_end_call()` tool — maps reason to stage: `appointment_booked→walkthrough_booked`, `not_interested→dead`, `callback_scheduled→contacted`, `wrong_number→dead`

## Conversation States (In-Call)

Managed by `ConversationFlow` in `backend/voice/flows.py`. These govern Sophia's behavior within a single call.

| State | Turns Budget | Goal |
|---|---|---|
| `warm_open` | 2 | Greet, confirm they have a minute |
| `discovery` | 6 | Learn situation, motivation, timeline, condition |
| `price_discussion` | 4 | Deliver verbal range, anchor above MAO |
| `objection_handling` | 4 | Handle pushback with empathy |
| `close` | 4 | Book walkthrough directly |
| `end_call` | 2 | Wrap up, confirm next step |

### Valid Transitions

```
warm_open → [discovery, end_call]
discovery → [price_discussion, close, end_call]
price_discussion → [objection_handling, close, end_call]
objection_handling → [price_discussion, close, end_call]
close → [end_call, objection_handling]
end_call → []
```

State transitions are detected via:
1. Turn budget expiry → auto-advance to first valid next state
2. Signal detection in Sophia/seller speech (`detect_state_from_response`)
3. Tool call (`book_appointment` → end_call, `end_call` tool)

**Note:** `ConversationFlow` exists in `flows.py` but is NOT actively injected into the Pipecat pipeline. State context is currently managed via `ContextTrackerProcessor` + system prompt injection rather than explicit flow gating.

## Call Dispositions (Sophia's Assessment)

Set by `set_disposition` tool during the call. Stored in `calls.call_disposition` and used to update lead record.

| Disposition | Meaning | Lead Action |
|---|---|---|
| `HOT` | Timeline mentioned, price discussed, or appointment agreed | Sets `priority_callback=True` |
| `WARM` | Engaged but not ready, open to callback | No change |
| `COLD` | Not interested now, may reconsider | Advances drip to day 30 |
| `DEAD` | Hostile, wrong number, explicit no, or DNC request | Sets `opted_out=True`, pauses drip |

## Outbound Eligibility Requirements

Lead must pass ALL of the following to be dialed:
1. `opted_out = False`
2. `callable = True` (set by BatchData enrichment)
3. `dnc_blocked = False`
4. `last_called_at` is NULL or > 72 hours ago
5. `distress_score >= 50` (on linked property)
6. `estimated_arv IS NOT NULL` (on linked property)
7. `callable_phones IS NOT NULL` (on linked property)
8. Calling hours: 8am–9pm PT
9. Score >= 50 (ComplianceEngine secondary check)

Leads that fail enrichment (no BatchData result) will have `callable=NULL` and never reach the queue. Use `PATCH /api/leads/{lead_id}/activate` to manually override for testing.
