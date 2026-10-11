# Voice audit finding ledger

All 129 original findings and 15 recovery follow-up findings remain recorded below. Addressed describes tested code changes, not production certification. Original evidence is preserved in [VOICE-AUDIT-FINDINGS.json](VOICE-AUDIT-FINDINGS.json). Open and partial items remain release blockers or follow-ups.

| Finding | Severity | Repair status | Problem |
|---|---|---|---|
| REI-001 | P0 | Addressed in repair branch; production verification pending | Every call crashes before the pipeline starts |
| REI-002 | P0 | Addressed in repair branch; production verification pending | Call ID is substituted for the media stream ID |
| REI-003 | P1 | Addressed in repair branch; production verification pending | Speech chunker defeats streaming |
| REI-004 | P1 | Addressed in repair branch; production verification pending | Interrupted responses contaminate the next answer |
| REI-005 | P1 | Addressed in repair branch; production verification pending | Custom turn controller sits after the component that consumes transcripts |
| REI-006 | P1 | Addressed in repair branch; production verification pending | STT mute travels away from the STT service |
| REI-007 | P1 | Addressed in repair branch; production verification pending | Spanish recognition remains English |
| REI-008 | P1 | Addressed in repair branch; production verification pending | Pipecat settings silently disappear on the unpinned install |
| REI-009 | P2 | Addressed in repair branch; production verification pending | Declared provider selection is disconnected from the live provider |
| REI-010 | P2 | Addressed in repair branch; production verification pending | Artificial think delays accumulate per chunk |
| REI-011 | P2 | Addressed in repair branch; production verification pending | A synthetic breath is prepended on every synthesis start |
| REI-012 | P1 | Addressed in repair branch; production verification pending | Audio filtering depends on packet boundaries |
| REI-013 | P2 | Addressed in repair branch; production verification pending | Per-sample DSP blocks the async audio loop |
| REI-014 | P2 | Addressed in repair branch; production verification pending | Spoken stage directions survive cleanup |
| REI-015 | P2 | Addressed in repair branch; production verification pending | Acknowledgment splitting can change meaning |
| REI-016 | P2 | Addressed in repair branch; production verification pending | Backchannel suppression has unreachable branches |
| REI-017 | P2 | Addressed in repair branch; production verification pending | Backchannels do not use a dedicated realtime path |
| REI-018 | P2 | Addressed in repair branch; production verification pending | Interruption acknowledgment is instantiated but not wired |
| REI-019 | P1 | Addressed in repair branch; production verification pending | Pipeline safety assertion examines freshly created substitutes |
| REI-020 | P1 | Addressed in repair branch; production verification pending | First outbound seller statement is swallowed |
| REI-021 | P2 | Partial; follow-up work remains | Greeting can wait behind enrichment and competing opener triggers |
| REI-022 | P2 | Addressed in repair branch; production verification pending | Codec and sample-rate configuration needs a captured boundary test |
| REI-023 | P1 | Addressed in repair branch; production verification pending | Slotted context cannot store required conversation state |
| REI-024 | P1 | Addressed in repair branch; production verification pending | Runtime instructions are applied to the previous user message |
| REI-025 | P1 | Addressed in repair branch; production verification pending | Property context is computed and discarded |
| REI-026 | P1 | Addressed in repair branch; production verification pending | Runtime ARV and MAO lookup references nonexistent self._ctx |
| REI-027 | P1 | Addressed in repair branch; production verification pending | Seller memory is loaded but not attached to live prompt state |
| REI-028 | P1 | Addressed in repair branch; production verification pending | Transcript is reconstructed from trimmed LLM context |
| REI-029 | P1 | Addressed in repair branch; production verification pending | Transcript contains internal context instructions |
| REI-030 | P2 | Addressed in repair branch; production verification pending | History truncation can break tool-message protocol |
| REI-031 | P1 | Addressed in repair branch; production verification pending | Street numbers, years and loan balances become asking prices |
| REI-032 | P2 | Addressed in repair branch; production verification pending | Negations reverse intent and agent status |
| REI-033 | P2 | Addressed in repair branch; production verification pending | No rush is classified as rushed |
| REI-034 | P2 | Addressed in repair branch; production verification pending | Numeric-only meaningful replies can be discarded as noise |
| REI-035 | P2 | Addressed in repair branch; production verification pending | Collected address is only a Boolean |
| REI-036 | P1 | Addressed in repair branch; production verification pending | Objective progression can wrap a hot lead before booking |
| REI-037 | P1 | Addressed in repair branch; production verification pending | Bob escalation contract is dropped at load time |
| REI-038 | P2 | Partial; follow-up work remains | Orchestrator outcomes are partly decorative |
| REI-039 | P2 | Open; not established as repaired | Snapshots have no restoration path |
| REI-040 | P1 | Addressed in repair branch; production verification pending | End-call handler references an undefined task |
| REI-041 | P1 | Addressed in repair branch; production verification pending | Failed SMS sends are announced as sent |
| REI-042 | P1 | Addressed in repair branch; production verification pending | Invalid appointments advance the lead stage |
| REI-043 | P1 | Addressed in repair branch; production verification pending | Missing price becomes an invented email offer |
| REI-044 | P1 | Addressed in repair branch; production verification pending | Voicemail tool claims an action it never performs |
| REI-045 | P1 | Addressed in repair branch; production verification pending | Model-supplied lead IDs and destinations are not bound to the call |
| REI-046 | P1 | Addressed in repair branch; production verification pending | Missing intel packet opens gated tools by default |
| REI-047 | P1 | Addressed in repair branch; production verification pending | Permission levels are not strongly tied to each authorized action |
| REI-048 | P1 | Addressed in repair branch; production verification pending | Operator approval does not clear the state that keeps blocking |
| REI-049 | P2 | Open; not established as repaired | Operator queries and approval requests are separate disconnected flows |
| REI-050 | P1 | Addressed in repair branch; production verification pending | Dollar/cents mismatch creates false intel conflicts |
| REI-051 | P2 | Open; not established as repaired | Packet freshness is rewritten without proof of fresh evidence |
| REI-052 | P2 | Open; not established as repaired | Initial packet load does not enforce safe_for_live_call |
| REI-053 | P2 | Open; not established as repaired | Packet versions and approval idempotency need concurrent DB verification |
| REI-054 | P1 | Partial; follow-up work remains | Regex output checks miss speaking paths and split phrases |
| REI-055 | P1 | Addressed in repair branch; production verification pending | Identity policy contradicts itself |
| REI-056 | P1 | Addressed in repair branch; production verification pending | Direct dial permits closed/noncallable leads and future callbacks |
| REI-057 | P1 | Addressed in repair branch; production verification pending | Concurrent limit admits twelve calls against a limit of three |
| REI-058 | P1 | Addressed in repair branch; production verification pending | Same-lead protection checks only global capacity |
| REI-059 | P1 | Addressed in repair branch; production verification pending | Redis is optional, absent from requirements, and fails open |
| REI-060 | P2 | Addressed in repair branch; production verification pending | Stale call-slot expiration is doubled |
| REI-061 | P1 | Addressed in repair branch; production verification pending | Sophia loop permanently fills an in-process active set |
| REI-062 | P1 | Addressed in repair branch; production verification pending | Retry delay exists only in a log |
| REI-063 | P1 | Addressed in repair branch; production verification pending | Follow-up poller ignores task type, due time and completion |
| REI-064 | P1 | Addressed in repair branch; production verification pending | Callback poller skips answered callers and clears failed work |
| REI-065 | P1 | Addressed in repair branch; production verification pending | Campaign pause does not govern the callers |
| REI-066 | P2 | Open; not established as repaired | Redial endpoint counts leads without queuing them |
| REI-067 | P1 | Partial; follow-up work remains | Every application process starts its own schedulers |
| REI-068 | P2 | Open; not established as repaired | Speed-to-lead advances attempts before confirming delivery |
| REI-069 | P1 | Addressed in repair branch; production verification pending | Short calls are classified dead without conversation evidence |
| REI-070 | P2 | Open; not established as repaired | Voicemail retry is unreachable in the terminal-status branch |
| REI-071 | P1 | Addressed in repair branch; production verification pending | Recording callback points at the wrong handler |
| REI-072 | P2 | Addressed in repair branch; production verification pending | SMS recency uses the wrong timestamp and never refreshes it here |
| REI-073 | P2 | Addressed in repair branch; production verification pending | Missing seller name crashes personalized SMS generation |
| REI-074 | P2 | Partial; truthful reminders and confirmed-booking filtering repaired; delivery and attendance integration remain | Appointment reminders assert an attendance event that was not recorded |
| REI-075 | P2 | Partial; follow-up work remains | Calling-hour defaults differ across subsystems |
| REI-076 | P1 | Addressed in repair branch; production verification pending | CSV upload passes a stream to a path-only parser |
| REI-077 | P1 | Addressed in repair branch; production verification pending | CSV upload expects the wrong scorer return type |
| REI-078 | P1 | Addressed in repair branch; production verification pending | Property upsert does not return the ID needed for lead creation |
| REI-079 | P1 | Addressed in repair branch; production verification pending | CSV private contact keys are sent to property storage |
| REI-080 | P1 | Addressed in repair branch; production verification pending | CSV scout entry point crashes immediately |
| REI-081 | P2 | Open; not established as repaired | Deployed scout cycle runs only part of the acquisition system |
| REI-082 | P1 | Addressed in repair branch; production verification pending | ARV trigger calls its local get_comps with missing arguments |
| REI-083 | P1 | Addressed in repair branch; production verification pending | Homeharvest ARV trigger omits the repair buffer from MAO |
| REI-084 | P2 | Open; not established as repaired | Homeharvest neighborhood search is city-wide |
| REI-085 | P1 | Addressed in repair branch; production verification pending | Offer storage contract conflicts with its migration |
| REI-086 | P2 | Addressed in repair branch; production verification pending | Offer analytics select one status name and read another |
| REI-087 | P1 | Open; not established as repaired | Clean database bootstrap is incomplete |
| REI-088 | P2 | Partial; follow-up work remains | Property/lead relationship is represented inconsistently |
| REI-089 | P2 | Open; not established as repaired | Auto-enrichment imports a function that does not exist |
| REI-090 | P2 | Open; not established as repaired | Cash-buyer acquisition is disconnected at three imports |
| REI-091 | P2 | Open; not established as repaired | Residential buyer filter accepts industrial property |
| REI-092 | P2 | Open; not established as repaired | Deal-blast property schema disagrees with acquisition schema |
| REI-093 | P2 | Open; not established as repaired | Comps cache has no age or size bound |
| REI-094 | P2 | Addressed in repair branch; production verification pending | Pending followup ranking is applied after an incompatible limit |
| REI-095 | P0 | Addressed in repair branch; production verification pending | Administrative APIs have no application authentication |
| REI-096 | P0 | Addressed in repair branch; production verification pending | Telephony/SMS webhooks and media sockets are unauthenticated |
| REI-097 | P1 | Addressed in repair branch; production verification pending | Dashboard ingest endpoints accept arbitrary writes |
| REI-098 | P1 | Addressed in repair branch; production verification pending | SendGrid webhook accepts missing signatures and uses the wrong algorithm |
| REI-099 | P1 | Partial; follow-up work remains | Email opt-out link imports a nonexistent verifier |
| REI-100 | P1 | Addressed in repair branch; production verification pending | Compliance verification fails open |
| REI-101 | P1 | Partial; follow-up work remains | Database access policies are not represented in migrations |
| REI-102 | P2 | Addressed in repair branch; production verification pending | Costly endpoints lack authentication and bounded budgets |
| REI-103 | P1 | Addressed in repair branch; production verification pending | Cross-origin dashboard requests have no server CORS policy |
| REI-104 | P2 | Addressed in repair branch; production verification pending | Live-call list is based on a context map emptied at stream start |
| REI-105 | P2 | Open; not established as repaired | User-turn events use the wrong call-ID attribute |
| REI-106 | P2 | Addressed in repair branch; production verification pending | Call metrics cleanup is not exception-safe |
| REI-107 | P1 | Partial; post-call tasks now awaited; durable crash recovery remains | Post-call processing is nondurable fire-and-forget work |
| REI-108 | P1 | Partial; follow-up work remains | Unknown inbound callers have no equivalent durable call record |
| REI-109 | P2 | Partial; follow-up work remains | Health responses do not prove a working voice session |
| REI-110 | P2 | Partial; follow-up work remains | Blocking database/provider calls run in async API and call paths |
| REI-111 | P2 | Addressed in repair branch; production verification pending | Two source pages own the root route |
| REI-112 | P2 | Open; not established as repaired | Followup count queries a column absent from its schema |
| REI-113 | P2 | Addressed in repair branch; production verification pending | Settings scores and connection labels are hardcoded |
| REI-114 | P2 | Addressed in repair branch; production verification pending | New Lead action points into a detail route |
| REI-115 | P2 | Open; not established as repaired | API failures are often rendered as ordinary empty state |
| REI-116 | P1 | Addressed in repair branch; production verification pending | Manual grade endpoint returns an unawaited coroutine |
| REI-117 | P1 | Addressed in repair branch; production verification pending | Simulator crashes when grading its first conversation |
| REI-118 | P2 | Partial; follow-up work remains | Evaluations exercise different prompts and bypass the live system |
| REI-119 | P2 | Addressed in repair branch; production verification pending | Legacy eval runner imports nonexistent case helpers |
| REI-120 | P2 | Addressed in repair branch; production verification pending | QA metric names do not match the values stored |
| REI-121 | P1 | Addressed in repair branch; production verification pending | Full regression suite cannot collect |
| REI-122 | P2 | Addressed in repair branch; production verification pending | Tests fail to enforce actual assembled wiring |
| REI-123 | P2 | Addressed in repair branch; production verification pending | Live-provider latency script is included in default discovery |
| REI-124 | P2 | Partial; follow-up work remains | Backend dependencies are unpinned and setup template is empty |
| REI-125 | P2 | Addressed in repair branch; production verification pending | Dashboard lint has 55 errors and 10 warnings |
| REI-126 | P2 | Partial; follow-up work remains | Duplicate definitions and warning-only failures obscure behavior |
| REI-127 | P2 | Open; not established as repaired | Seller named Claude triggers a fresh introduction |
| REI-128 | P1 | Addressed in repair branch; production verification pending | Silence exit sets a flag without terminating the session |
| REI-129 | P2 | Addressed in repair branch; production verification pending | Speech text buffers are unbounded when completion never arrives |
| REI-130 | P1 | Addressed locally; production or hosted verification pending | Expired callback workers could clear newer claims |
| REI-131 | P1 | Addressed locally; production or hosted verification pending | One follow-up failure abandoned the remaining claimed batch |
| REI-132 | P1 | Addressed locally; production or hosted verification pending | Provider messages repeatedly inflated call attempts and rewrote newer outcomes |
| REI-133 | P1 | Addressed locally; production or hosted verification pending | Live call leases had no heartbeat or bounded media lifetime |
| REI-134 | P1 | Partial; durable reconciliation remains | Lost provider acknowledgment could free capacity and allow a duplicate dial |
| REI-135 | P2 | Addressed locally; production or hosted verification pending | Active-call lookup orphaned expired ownership hashes |
| REI-136 | P1 | Addressed locally; production or hosted verification pending | Outbound context showed cents as dollar values |
| REI-137 | P2 | Addressed locally; production or hosted verification pending | Reminder dates were inferred from broad hour windows |
| REI-138 | P1 | Addressed locally; production or hosted verification pending | Reminder follow-up fabricated a completed visit |
| REI-139 | P1 | Addressed locally; production or hosted verification pending | Cancelled and rebooked appointments had stale reminder state |
| REI-140 | P1 | Addressed locally; production or hosted verification pending | Recording persistence failures acknowledged success |
| REI-141 | P2 | Addressed locally; production or hosted verification pending | Malformed QA scores could pollute the dashboard |
| REI-142 | P1 | Addressed locally; production or hosted verification pending | Permanent speech provider failure defaulted to continuing the pipeline |
| REI-143 | P2 | Addressed locally; production or hosted verification pending | Output and post-call network operations blocked the event loop |
| REI-144 | P2 | Addressed locally; production or hosted verification pending | Regression checks had no hosted automation |
