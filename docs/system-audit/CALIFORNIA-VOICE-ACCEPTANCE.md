# California voice and integration acceptance

This change consumes canonical, same-lead California and San Joaquin context from the exact Bob producer commit ea02f3c8513be859e87c2b22870798b1ce620ac0. It strips source notes, clears rejected/stale brief context, and grants no quote/contact authority. The dashboard renders a current same-lead reviewed valuation as research, separately from offers and reservations; invalid or expired evidence is visibly unavailable.

## Corrections

- MLS intake requires explicit California/San Joaquin geography and residential sale type. Neighboring Modesto/Turlock, leases and unknown geography are excluded. Asking price no longer becomes estimated value; price change requires an actual reduction. The existing CRMLS runner returns candidates only and does not persist them; its endpoint/credentials are not live-verified.
- Homeharvest no longer treats long time on market as expired or a missing agent as proof of FSBO. Listing IDs/URLs are not parcel IDs. Verified APN/county is required before persistence, money uses integer cents, and an unreviewed listing is not an approved viable deal. Existing canonical property valuation/approval fields are preserved. Feeds without APN/county need licensed enrichment before persistence.
- Tax queries reject malformed/mismatched/duplicate parcels; partial assessments stay unknown.
- Prompt examples disclose AI, verify identity before sensitive property detail, respect declines, avoid fabricated contact provenance and unverified closing promises. Runtime already covers interruptions, uncertain transcription, one-question turns, seller corrections, exact Pacific scheduling, authoritative tool results, durable suppression and side-effect permission checks.

## Comparison to primary voice framework guidance

Reviewed LiveKit turns, tuning and testing docs, and Pipecat evaluation/turn-start reference. https://docs.livekit.io/agents/logic/turns/ ; https://docs.livekit.io/testing/ ; https://reference-server.pipecat.ai/en/latest/api/pipecat.evals.script.html

The useful targets are semantic turn completion plus VAD, true interruption versus backchannel handling, cancelable/timeout-bounded tools, tool-result truthfulness, traces, and separate policy/unit, simulated conversation and real audio evaluations. Sophia currently has Silero/SmartTurn construction, synthetic streaming tests, deterministic conversational policy replay, tool containment and provider recovery tests. Framework marketing or passing fixture replies cannot establish natural generated conversation quality. Do not replace the working Pipecat/SignalWire transport merely to adopt another framework.

## Evidence and unverified operations

2,538 Python tests pass locally; final hosted results are recorded in CI. 12 actual Python producer/consumer/embedded PostgreSQL roundtrip checks pass, including county/state context, retracted ownership, suppression and cent-correct advisory prices. SQL scheduling tests validate reservation collisions/idempotency, generation-owned callbacks and provider event handling. Eleven dashboard evidence checks reject wrong-lead, stale, malformed and authorized-as-research input. Dashboard production build passes.

No seller call, text, email, calendar reservation, paid data access or live migration was performed. Provider credentials, current contact/quote permissions, email acceptance/delivery, audio latency/interruption quality, live calendar conflicts and hosted dashboard persistence remain production acceptance requirements. The 1,000 extra MLS tests establish that asking prices never become valuation; they are not 1,000 generated conversations or proof of all-site lead coverage. No 10/10 live grade is warranted.
