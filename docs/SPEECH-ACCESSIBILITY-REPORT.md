# Speech understanding, hearing accessibility and acoustic stress

The local repair addresses the six wording/state failures from the long-conversation grade and adds handling for hearing difficulty and uncertain transcription. **1,282 backend tests pass**, including **152 new speech/accessibility tests**. The fifteen long-window state replays now pass **195/195 harder probes**, up from 105/195. These results do not establish human-level speech recognition or natural voice quality.

## Tested areas and actual scope

| Area | Local evidence |
|---|---|
| Hearing and understanding requests | Hard of hearing, hearing aid, louder, slower, muffled, quiet, repeat, pardon, connection loss and Spanish repair requests; 39 distinct phrases with original, uppercase and curly-apostrophe variants |
| Uncertain transcription | Low overall confidence, one low-confidence word, missing confidence, invalid/nonfinite/Boolean confidence, unclear markers, provider object/dict shapes, interim frames and upstream frames |
| Consequential actions | Uncertain speech blocks booking, callback, messages, offer range and transfer; stop handling remains available |
| Frame ordering | Actual Pipecat worker executes an uncertain price followed immediately by a clear correction; facts and priorities stay associated with their turns |
| Repeated failures | After three hearing/clarification failures, guidance offers a human connection or an authorized, wanted text alternative; it does not assume the caller can read text |
| Caller pause | Explicit wait gets 60 seconds; requested 30 seconds or two minutes is honored within a 15–120-second bound before the silence prompt |
| Corrections | Written-number timing, retracted ownership/motivation, partial refusal and callback wording from the prior audit; denied ownership blocks booking and offer actions even with a bound address |
| PCM acoustic stress | 69 cases execute the installed Silero VAD with the actual live confidence/start/stop/volume settings |
| Earlier replays | All 33 scripted one-minute-window policy replays still pass |

The acoustic cases synthesize the same sentence in five FFmpeg/flite voices and apply twelve changes plus a clean baseline: rectangular telephone band limit, actual 8-kHz PCMU encode/decode/resample, muffling at 800 Hz, −26 dB volume, severe clipping, 200 ms echo, 20% dropouts, 60 Hz hum and white noise at +20/+10/0/−5 dB SNR. Three noise-only controls and one silence control complete the 69 cases. These are reproducible signal tests, not representative human accents, real street/TV/café recordings, overlapping human conversations or hearing-aid hardware tests.

## Acoustic finding remains open

Speech was detected in **60 of 65 synthetic speech cases**. All five clean samples and all five PCMU codec-converted samples were detected. All five sharply band-limited samples failed to enter SPEAKING. Their maximum VAD confidence ranged from 0.552 to 0.773; some briefly exceeded the 0.7 threshold without sustaining the start requirement. All four noise/silence controls stayed quiet.

This exposes a calibration risk, not a measured 92.3% recognition rate. VAD detects activity; it does not recognize words. The existing aggregator also has transcript-based start detection, but no provider transcript was produced for these distorted samples, so fallback success is unknown. VAD settings were retained instead of tuned to this small synthetic corpus. Representative human telephone samples are required to select thresholds without increasing unwanted background interruptions.

Evidence: [all acoustic results](test-evidence/acoustic-stress.json). Reproduce with `python -m backend.voice.acoustic_stress` in an environment with the pinned Python dependencies and FFmpeg/flite. The tested FFmpeg version and signal settings are included in the evidence.

## Repairs and boundaries

Provider results now supply transcript and word confidence to a dedicated input processor. Overall confidence below 0.55, any word confidence below 0.35, malformed supplied confidence or explicit unclear markers trigger clarification. Missing confidence alone does not establish low confidence. These initial thresholds are conservative engineering choices, not calibrated probabilities or proven accent fairness.

Uncertain turns do not overwrite seller facts or feed emotional/trust/heat scoring. Consequential tool actions are denied until the unclear detail is resolved. Explicit opt-outs and truthful identity disclosure retain priority. The entire input analysis cluster uses Pipecat direct processing so one frame is analyzed before the next mutates its shared call state; the worker regression reproduces the original race and verifies the repair. More complex live interruption and provider timing still require testing.

Hearing responses prioritize short, clear explanation or repetition rather than another sales question. Instructions prohibit shouting, blaming an accent or claiming a volume change. This improves response guidance; it does not implement verified adaptive TTS speed or gain, and no audible output was measured. Language repair phrases are covered in text, but automatic bilingual STT/TTS switching and pronunciation remain unverified.

The twelve new findings are logged as REI-161–172. Eleven have local repairs; REI-172 remains open for real-phone VAD calibration. The earlier gaps and production blockers remain in the full ledger.

## Remaining acceptance work

Use consented human recordings spanning regional and non-native accents, age-related voice differences, soft/fast/stuttered speech and supported languages. Include real traffic, café, TV, speakerphone echo, crosstalk, packet loss and codec paths. Measure word error rate plus exact recognition of prices, names, dates, stop requests and consent. Evaluate false/missed interruptions, turn timing, repetition recovery and completed real reservations/callbacks. Have listeners score naturalness and clarity, including callers with hearing difficulty. Compare alternate TTS voices and pacing using actual recordings.

No live STT, model or TTS provider credentials are available here. Human accents tested: **zero**. Provider recognition tests: **zero**. Phone calls: **zero**. No production records were modified, nothing was deployed and no seller was contacted.

Whole-backend coverage: **33.4% statements, 25.5% branches, 31.6% combined**. [Full regression output](test-evidence/speech-pytest.txt), [coverage summary](test-evidence/speech-coverage.json), [one-minute replay results](test-evidence/speech-conversation-replays.json). Compilation, critical/unused-import lint, dependency compatibility and whitespace checks pass. The prior hosted conversation run 38155931620 passed on f346cc7; later speech changes need their own hosted result.

## References checked

[Deepgram confidence documentation](https://developers.deepgram.com/docs/confidence) distinguishes whole-transcript and word confidence. [Deepgram audio preprocessing guidance](https://developers.deepgram.com/guides/deep-dives/audio-preprocessing-barge-in) explains why blanket noise suppression can damage short utterances. [Pipecat turn strategies](https://reference-server.pipecat.ai/en/latest/api/pipecat.turns.user_turn_strategies.html) describes voice/transcript start strategies. The pinned installed implementation was inspected and exercised locally; current web documentation alone is not treated as proof of this application's behavior.
