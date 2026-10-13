# Long-conversation grade

**Provisional conversation-readiness grade: C−.** Basic request handling improved, but ordinary seller wording still exposes consequential state and routing errors. Audible naturalness remains ungraded.

## Length

`backend/voice/agent.py` defaults `VOICE_MAX_CALL_SECONDS` to 1,200 seconds (20 minutes). It accepts 60 through 3,000 seconds (50 minutes). This is a configured worker lifetime, including setup; it is not a measured successful conversation duration. No live model conversation or phone call has been tested in this environment.

The earlier eleven scenarios had virtual one-minute windows, with early endings for refusals and wrong numbers. This follow-up stresses state over virtual 3-, 5-, 10-, 20- and 50-minute windows at six exchanges per minute. No real elapsed call, generated assistant dialogue or audio occurred.

## Evidence

Fifteen runs cover five windows and original/uppercase/curly-apostrophe wording. Each seeds ownership, motivation, next-week timing, a leaking roof and a $220,000 asking price; repeats direct process questions; then applies thirteen harder probes. Across runs, 105 of 195 probe checks pass (53.8%). Six distinct failures recur in every window and variant. They are wording/state errors, not evidence that memory gets worse as minutes pass. The 1,584 repeated direct-question checks pass but use one repeated question; they do not establish broad dialogue quality.

| Failed behavior | Reproduction and observed result |
|---|---|
| Question without punctuation | “Tell me what fees you charge” routes toward a walkthrough instead of answering. Spoken STT text does not always contain question marks. |
| Callback phrasing | “Call me tomorrow at three” routes toward a walkthrough because the callback detector expects particular wording such as “call me back.” |
| Refusing only one option | “Not interested in a walkthrough, but I do want an offer” becomes a whole-call refusal. |
| Corrected timeline | “Actually six months instead of next week” retains next week. Written-number timing is missed, and the superseded timing still matches. |
| Corrected ownership | “I don't own that house; my brother does” leaves `owner_confirmed=True`. |
| Retracted motivation | “I'm no longer moving; I'm keeping the rental” leaves relocation in motivation memory. |

Passing probes cover latest explicit price, corrected roof condition, retention of seeded price/timing through repeated questions, pause request, AI identity, human request and stop-request policy. These are state/policy checks; they do not execute a transfer, booking, callback or suppression tool.

Source review also finds `_maybe_compress_context` and `_trim_history` defined but not called in the voice path. The conversation history therefore lacks an established active compaction strategy. This presents an unmeasured long-call latency/cost/context-growth risk; this test does not establish a provider context-limit failure.

## Grade rationale

A respectful opening and several correct priorities earn credit. Missing common spoken questions and callback requests, treating a partial refusal as total refusal, and retaining retracted facts prevent a B or A. An A requires generated and recorded conversations that handle these cases accurately, correctly save next steps, and demonstrate timing, naturalness, interruption recovery and long-call retention.

The grade is a qualitative engineering judgment, not 53.8% converted to a school grade. The 1,130 passing backend regressions do not cancel these newly exposed failures.

Evidence: [complete synthetic results](test-evidence/long-conversation-grade.json). No application fixes were made during this grading pass, nothing was deployed, and no seller was contacted.


## Later speech/accessibility repair

The subsequent repair fixes the six failed probe types. The same synthetic suite now passes 195/195 probe checks across its fifteen virtual-window runs; see [retest evidence](test-evidence/long-conversation-retest.json) and [SPEECH-ACCESSIBILITY-REPORT.md](SPEECH-ACCESSIBILITY-REPORT.md). The baseline C− above records the earlier audit state, not a new post-repair grade. A live conversation grade remains unestablished.
