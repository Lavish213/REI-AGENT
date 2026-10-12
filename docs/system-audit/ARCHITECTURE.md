# Four-repository architecture

REI-AGENT is the primary voice runtime and shared Supabase domain. SignalWire delivers audio; Pipecat connects transcription, context, model, tools and speech. Tools must bind tenant/lead/contact identity and permission server-side. Durable receipts and live-fact recovery support Bob, whose worker is advisory and cannot authorize outreach.

Bob-Intelligence- reads shared facts and writes bounded call briefs. Its durable event receiver/brief/feedback migrations and existing 51-finding ledger remain the baseline. Market enrichment and production operational verification remain open.

Sophia-Agent is a separate fallback runtime with its own schema and Bob planner. Its IDs, memory evidence and policy assumptions are not interchangeable with REI's shared tenant contract. Do not silently run both voice agents against the same live leads.

The-Dashboard/Karpathys has its own PostgreSQL workflow, governance, approvals, call/session, transcript and event authority. Its frontend reads backend truth. A Call UUID is not a SophiaSession UUID. REI-to-Karpathys ingestion requires explicit entity mapping and versioned authenticated event receipts; a shared webhook secret alone does not complete that wiring.

The initial static inventory covered 1,598 tracked files before repairs. The regenerated map reflects recovered commits. Neither count proves every file/path has been manually reviewed. Research preceded UI changes; the existing tokens/components and workflows remain the foundation. No screenshot-backed visual redesign is claimed: the managed browser timed out and the workspace reset, requiring recovery of uncommitted edits. Recovered changes are committed and rerun checks are distinguished from earlier lost evidence.
