# Conversation repair and one-minute replay report

Sophia's conversation guidance now follows the caller's current request before advancing a sales stage. **1,130 backend tests pass**, including **84 new conversation tests**. **33 scripted policy replays pass** across eleven scenarios and three wording variants. This establishes local regression behavior, not perfect conversation or A-grade phone performance.

## What changed

- Questions receive a direct answer before another discovery or booking question. Pause, repeat, human-transfer, busy, goodbye, wrong-person and refusal requests get their own response priority.
- Old instructions reset before each new transcript. Current guidance enters the assembled live pipeline after analysis and before the model sees the updated call state.
- Stage advancement requires collected facts. Turn counts, Bob phase labels and short-answer fatigue cannot manufacture discovery or end a useful conversation.
- Good condition is a valid answer. Known motivation, timeline and condition are supplied explicitly so the model is instructed not to ask again.
- Latest explicit price corrections replace old prices. Clearly repaired defects are removed. Bare numeric price answers are interpreted only after an asking-price question; mortgage answers do not overwrite asking price.
- A yes applies to the last actual spoken question. Another question cancels pending walkthrough acceptance. Maybe, yes-if and yes-but do not start scheduling.
- “Not selling until next month” preserves conditional interest. Common timing answers such as next month, within two weeks and no rush are retained.
- Identity disclosure instructions repeat whenever asked. Asking whether Sophia is a person is distinguished from requesting a human transfer.
- The opener queues once at connection. Initial caller speech can no longer suppress the delayed disclosure.
- Spoken question memory handles provider text delivered in one-word, two-word or sentence chunks. Partial questions reset when caller speech begins, and the buffer is bounded.
- Duplicate resistance scoring was removed. A single rejection no longer receives six copies of the same penalty.
- Conversation guidance removes pressure to lean in after uncertainty, invented scheduling choices, forced slang, laughter, repeated names and automatic questions after every answer.

These are guidance and state fixes. The model can still fail to follow guidance; generated replies and actual call behavior must be measured separately. A pause instruction alone does not prove silence timing or interruption handling.

## Simulation changes

The API-driven text simulator now uses asynchronous requests, the live model default, disclosure opener, production prompt and per-turn conversation policy. It has an explicit estimated 60-second speech budget with a turn cap and a 30-second deadline per model request. Estimated duration uses 150 words per minute plus turn gaps; a completed exchange can exceed the budget. It is not a recording or an actual timed phone call.

The simulator no longer counts “appointment,” “confirmed” or “see you” as a booking. Without tool execution it always reports no appointment booked. Grading cannot save production call grades or send owner alerts, including when an older caller passes `save_to_db=True`.

No actual model-generated simulation ran in this environment: the Anthropic key is absent. Test clients supplied fixed responses to verify simulator behavior. No fallback silently substitutes fixtures for a live model. Production tools, authorization, transport and output filters are not exercised by the text simulator.

## Results

| Check | Evidence |
|---|---|
| Entire backend | 1,130 passed, four dependency deprecation warnings, 25.60 seconds |
| New conversation tests | 84 passed; request priority, fact gates, corrections, consent, repeated disclosure, word chunks, simulator limits and grading isolation |
| Scripted replays | 33 passed, zero failed; 11 scenarios × original, uppercase and curly-apostrophe wording |
| Replay time | Each script uses a virtual 60-second window; explicit refusal/goodbye/wrong-person ends early |
| Generated conversations | Zero; no Anthropic credential available |
| Whole-backend coverage | 33.0% statements, 24.6% branches, 31.0% combined; includes unimported files |
| Static checks | Backend compilation, critical/unused-import checks, unused-local checks for changed files, dependency compatibility and patch whitespace pass |
| Broader unused-local lint | Eleven pre-existing unused-local findings outside changed files remain; no automatic broad rewrite applied |
| Previous hosted checkpoint | GitHub Actions run 38152958585 passed on commit 5a5ef41; this does not verify the later conversation commit |

Scenarios: relocation, busy callback, grief, price/condition corrections, repeated identity questions, short answers, Spanish requests, conditional interest, question scope, wrong person and audio-repair requests. “Audio repair” here tests a request to repeat; no audio was generated or measured. Replays use authored assistant fixtures and actual context, emotion, resistance, objective and policy code; they do not measure response quality from a live language model.

Evidence: [full Python run](test-evidence/conversation-pytest.txt), [all replay turns and priorities](test-evidence/conversation-replays.json), [coverage summary](test-evidence/conversation-coverage.json), [finding ledger](VOICE-AUDIT-LEDGER.md). Sixteen newly identified conversation findings are logged as REI-145 through REI-160.

## Remaining conversation acceptance gates

Run API-generated transcripts with independent human review for question relevance, concise reactions, corrections, uncertainty, repeated concerns, interruptions, emotional context and truthful next steps. Run recorded one-minute phone calls against actual STT, LLM and TTS providers; measure first audible response, end-of-turn delay, double-talk, pause handling, acoustic naturalness and pronunciation. Then test longer calls, language switching, multi-property discussions and real reservation/callback failures. Prompt instructions and deterministic pass counts cannot establish these outcomes.

A production grade also still depends on the infrastructure and unresolved workflows in [RECOVERY-TEST-REPORT.md](RECOVERY-TEST-REPORT.md). Nothing was deployed, and no seller was contacted.
