# SOPHIA_RUNTIME_PRODUCTION.md

## CORE PROBLEM

The current runtime is overloading realtime inference.

Sophia is currently trying to do:
- live conversation
- emotional analysis
- objection analysis
- phase tracking
- seller classification
- memory injection
- workflow steering
- CRM reasoning
- negotiation logic

all during live voice generation.

This creates:
- delayed responses
- robotic pacing
- unnatural pauses
- generic responses
- weak conversational leadership
- bad interruption recovery
- slow conversational steering

The issue is NOT primarily prompt quality anymore.

The issue is realtime cognitive overload.

---

# PRODUCTION ARCHITECTURE

Realtime runtime and deep intelligence must be separated.

## REALTIME RUNTIME

Realtime runtime should ONLY handle:
- current objective
- one seller mode
- address known
- intent confirmed
- last objection
- last seller statement
- interruption handling
- realtime pacing

Nothing else.

Realtime runtime must stay extremely lightweight.

Target:
- under 2500 total prompt tokens
- ideally under 2000

---

# REMOVE FROM REALTIME INFERENCE

These should NOT be injected every turn:

- full phase history
- energy history
- rapport history
- full objection history
- deep emotional analysis
- multiple property issues
- long motivation chains
- negotiation state tracking
- CRM summaries
- extended seller memory
- large runtime explanations
- long instruction trees

These belong in:
- CRM
- async workflows
- evaluator systems
- post-call intelligence
- analytics
- QA grading

NOT live inference.

---

# LIVE CONTEXT REBUILD

## CURRENT

Current context injection is too large.

Example:

phase=...
energy=...
issues=...
motivation=...
timeline=...
situation=...
price=...
objection=...

This overloads realtime cognition.

---

# PRODUCTION CONTEXT

Realtime context should become tiny.

## FINAL FORMAT

[CTX:OBJ=GET_CONDITION|MODE=HOT|ADDR=1|INTENT=1]

Optional:

[CTX:OBJ=TEST_PRICE|MODE=SKEPTICAL|ADDR=1|INTENT=1|OBJ_LAST=PRICE]

Maximum:
- one line
- compressed state only
- no prose
- no explanations

---

# CONTEXT TRACKER REBUILD

## KEEP

Keep:
- address_known
- intent_locked
- current objective
- seller mode
- last objection
- disposition
- turn count

## REMOVE FROM REALTIME

Do not inject:
- phase_history
- energy_history
- rapport tracking
- long issue lists
- multiple motivations
- emotional summaries
- extended memory
- long situation descriptions

Store them asynchronously only.

---

# OBJECTIVE ENGINE

Realtime conversation should be objective-driven only.

Sophia should always know ONE thing:

"What missing piece do I need next?"

Not:
- full seller psychology
- full negotiation map
- deep reasoning trees

Realtime sales conversations are lightweight.

Humans are not internally simulating CRM dashboards during calls.

---

# LATENCY FIXES

## CURRENT ISSUE

Your runtime waits too long before response commitment.

This creates:
- dead air
- slow reactions
- weak steering
- fake sounding pacing

---

# FINAL REALTIME SETTINGS

## DEEPGRAM

Reduce endpointing aggressively.

FINAL:

endpointing=120

NOT:
400

---

# VAD

FINAL:

stop_secs=0.16
start_secs=0.12

NOT:
0.2 / 0.2

---

# TURN COMPLETION

Current smart-turn waiting is too conservative.

Sophia waits too long before deciding:
"the user is done speaking"

This kills momentum.

Lower turn completion thresholds.

Favor interruption responsiveness over perfect transcripts.

Realtime humans interrupt constantly.

---

# SPOKEN RENDERER REBUILD

Current renderer is too clean.

Sophia sounds:
- polished
- overly composed
- overly complete

Real acquisitions callers:
- compress thoughts
- pivot quickly
- interrupt naturally
- partially acknowledge
- speak imperfectly

---

# FINAL RENDERER RULES

## TARGET STYLE

Good:
"Okay gotcha. Is anyone living there?"

"Yeah. About how soon were you thinking?"

"Alright. Does it need much work?"

Bad:
"So what has you considering selling your property today?"

Bad:
"Thank you for explaining your situation."

Bad:
"I completely understand your concern."

---

# ACKNOWLEDGEMENT ENGINE

Sophia needs micro-reactions.

Tiny bridge phrases dramatically improve realism.

Allowed:
- okay
- gotcha
- yeah
- alright
- makes sense

Maximum:
1 short acknowledgment before next question.

Never stack them.

Bad:
"Okay gotcha yeah makes sense."

---

# INTERRUPTION PRIORITY

Realtime phone calls prioritize interruption responsiveness over transcript perfection.

If user interrupts:
- stop speaking immediately
- respond instantly
- recover naturally

Do NOT prioritize:
- clean sentence completion
- grammatical completion
- polished delivery

Realtime > perfect.

---

# MEMORY STRATEGY

Memory should be layered.

## REALTIME MEMORY
Tiny.
Only active conversational facts.

## CRM MEMORY
Long-term seller data.

## ANALYTICS MEMORY
Post-call analysis only.

Never inject all memory into live runtime.

---

# TOOL STRATEGY

Tools should not create visible thinking pauses.

Tool calls must be:
- fast
- deterministic
- background-oriented

Do not:
- wait multiple seconds before speaking
- expose internal reasoning
- stall conversational flow

If needed:
respond conversationally first
then resolve tool logic.

---

# FINAL RECOMMENDED RUNTIME FLOW

INPUT AUDIO
→ VAD
→ STT
→ Tiny Context Injection
→ Lightweight Objective Runtime
→ Fast Spoken Renderer
→ TTS
→ Interruptible Playback

NOT:

INPUT
→ Deep Seller Analysis
→ Emotion Classification
→ Negotiation Mapping
→ Long Context Injection
→ CRM Reasoning
→ Memory Expansion
→ Response Generation

---

# TARGET METRICS

## TARGET LATENCY

Seller stops speaking
→ Sophia starts response

Target:
400ms–900ms

Maximum acceptable:
1.5 seconds

Current runtime:
too slow

---

# TARGET PROMPT SIZE

Current:
~6700 tokens

Production target:
1500–2500

Ideal:
under 2000

---

# FINAL PRODUCTION PRINCIPLE

Sophia should behave like:
a busy acquisitions receptionist handling many calls daily.

NOT:
an AI assistant trying to perfectly analyze human psychology in realtime.

The runtime must prioritize:
- speed
- flow
- interruptions
- momentum
- conversational steering

over:
- deep reasoning
- perfect analysis
- perfect transcripts
- exhaustive state tracking