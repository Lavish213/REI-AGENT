# Expanded adversarial and stress campaign

This campaign expanded beyond the previous repair regression suite to adversarial protocols, actual dashboard HTTP behavior, real local Redis concurrency, database reservations/leases, malformed permissions, financial data, identity questions, and corrected conversation state. Newly found defects were repaired in the same review branch. It does not certify production telephone naturalness or sustained production infrastructure capacity.

## Verified results

| Area | Test execution | Result |
|---|---|---|
| Python | Full suite with original regressions and 631 added matrix cases | 983 passed; 5 pinned-dependency/API deprecation warnings |
| Real Redis | Isolated Redis 6.2 process; 30 rounds, 256 competing requests, 64 threads | 7,680 attempts; exactly 3 admissions per round; duplicate and expired slots handled |
| Redis-compatible engine | 20 rounds, 128 competing requests, 32 threads | 2,560 attempts; exactly 3 admissions per round |
| Lease ownership | Old status callback, old generation release, unauthenticated release, delayed provider bind, DB failure after accepted call | New call retains its slot; accepted call stays counted when persistence fails |
| Interrupted speech | 10,000 interruption/reset/new-response cycles, plus earlier 1,000-cycle regression | No stale sentence text emitted |
| Large response frame | Individual 1,201/5,000/10,000/100,000-character chunks | Pending buffer stays at or below 1,200 characters; content conservation checked |
| Calendar | 179 daily roundtrips over the booking horizon plus DST and invalid time tests | Pacific/UTC roundtrips and rejection behavior pass |
| Database | Both committed tenant/suppression and scheduling migrations in PGlite | Overlaps, approved availability, rebooking, adjacent slots, anonymous denial and append-only evidence checks pass |
| Database stress | 100 repeated reservation requests and 100 competing callback-claim requests | Same confirmed reservation ID; no duplicate callback claims |
| Identity binding | 1,000 randomized poisoned identity/destination sets | Model input cannot replace server-resolved seller/lead/address/email |
| Permissions | Missing/malformed packets, unsafe flags, invalid levels, corrupt entries, expired/malformed expiry, wrong action, disabled outreach, kill switch | Deny behavior passes; read-only availability can remain readable while outbound actions are disabled |
| Provider failures | HTTP 400/401/429/500/503, socket failure, stalled backend, real locally generated ECDSA signatures and mutations | Failures do not become delivery acknowledgments; invalid signatures deny |
| Actual backend | Real FastAPI application's OpenAPI route inventory, no operator credentials | 71 administrative method/path combinations denied; liveness remains available |
| Dashboard HTTP | Built Next.js server with isolated local backend | 30 checks passed, including 100 concurrent proxy requests, binary/multipart uploads, authentication, status preservation and 15-second backend timeout |
| Dashboard static checks | Production build, TypeScript, ESLint | Passed; zero lint errors/warnings |
| Python static checks | Compile, undefined-name/local-variable/unused-import checks, dependency consistency, patch whitespace | Passed |

PGlite serializes work within its embedded PostgreSQL instance. Its 100-request batches are useful correctness/load checks, but do not prove independent PostgreSQL backend-process locking under real multi-process contention. Redis tests do exercise a real server and concurrent client connections. Neither replaces a production soak test.

## Coverage

Coverage.py measured the full backend, including unexecuted modules: **28.4% statement coverage, 19.1% branch coverage, 26.3% combined**. The report includes 145 backend files. This is deliberately measured against the whole repository, not a selected subset that would inflate the percentage.

| Module | Combined statement/branch coverage |
|---|---|
| Media session validation | 87.9% |
| API authentication/signatures | 88.0% |
| Voice tools | 50.1% |
| Voice pipeline/agent | 43.5% |
| CSV parser | 56.3% |
| Comps calculator | 55.1% |

These percentages describe execution, not behavioral correctness. Uncovered code is not considered verified. [Coverage detail](test-evidence/backend-coverage.json) records missing lines and branches for every module.

## New defects and repairs

The failing-case names from the initial runs are preserved in [reproduced-failing-cases.json](test-evidence/reproduced-failing-cases.json). Repeated failing parametrizations represent the same root cause; their count is not a count of separate defects. Two initial assertions were corrected: read-only availability does not need to be blocked by an outbound disable switch, and a local appointment three hours past the exact 180-day cutoff should be rejected.

| Finding | Evidence and change |
|---|---|
| A large single LLM chunk left an unbounded speech buffer | Multi-size test failed; split loop now drains all excess, not just one segment |
| Decimal split across chunks became two spoken numbers | `$150.` followed by `50` failed content preservation; numeric trailing periods wait for clarification/response end |
| Malformed media JSON shapes crashed with attribute/type errors | Null/list/scalar/start-shape tests failed; object, ID and parameter shape checks now reject them |
| Invalid codec shapes and Boolean channel count were accepted/crashed | Media format mutation tests failed; mono PCMU 8 kHz requires correctly typed numeric fields |
| Non-ASCII provider signatures caused a server exception | Signature garbage tests failed; validation now rejects non-ASCII input |
| Non-ASCII bearer credentials caused a server exception | Actual middleware request failed; malformed credential input now returns 401 |
| Malformed permission maps crashed | Packet matrix failed across tools; shape validation denies malformed maps and entries |
| Unknown permission strings allowed disposition/voicemail actions | `admin`, `allowed`, and arbitrary levels passed; registry and exact-action checks now deny them |
| A string `false` marked a packet safe | Safe flag mutation failed; safety must be literal Boolean true |
| An empty malformed expiry acted like no expiry | Expiry object tests failed; explicit corrupt/empty/naive timestamps deny |
| Human-review kill switch did not govern tool execution | Five side-effect tests failed; preflight now blocks side effects pending review |
| Price extraction lost decimals and confused debt with asking price | Six price scenarios exposed incorrect state; exact decimal arithmetic and local debt/asking context now separate the values |
| Negative equity statements asserted free-and-clear ownership | Three negation cases failed; negated phrases retain mortgage state |
| Later mortgage corrections did not replace the initial value | Paid-off correction failed; later explicit evidence updates state |
| Supported-language AI identity questions were missed | Five English/Spanish phrasings failed; identity detection expanded |
| CSV currency conversion lost cents and accepted nonfinite values | `1.15`, half-cent rounding, NaN/infinity failed; Decimal rounding and finite-number rejection replace float truncation |
| Invalid comparable sales produced invalid authority or crashed | Negative/nonfinite/nonnumeric price/area tests failed; invalid comps are excluded and cannot create ARV/MAO |
| MAO/ARV money calculations drifted through floating-point truncation | Tiny-cent valuation test failed; final ARV rounds cents explicitly and MAO uses integer arithmetic |
| Offer quotation displayed cents as dollars and exceeded MAO | Quote test failed; verified dollars are formatted once and high range is capped at MAO/operator max |
| A model could choose an arbitrary written offer amount | Poisoned-price send test failed; summaries derive the range server-side and require medium/high-confidence authority |
| Approval threshold and prompt display used inconsistent units | Added contract tests verify cents-to-cents comparison and dollar display; thresholds no longer multiply already-cent amounts by 100 |
| Cancelled booking prevented rebooking the same slot | Actual SQL produced a unique-constraint error; confirmed-only uniqueness permits cancellation/rebooking while preserving overlap protection |
| Idempotency was checked before the slot lock only | Reservation lookup is repeated after acquiring the availability lock to handle waiting same-lead attempts |
| Valid empty HTTP responses became backend failures | Actual dashboard returned 502 for 204/304; proxy now uses null bodies for 204/205/304 |
| Backend fetch had no application deadline | Added 15-second deadline; actual stalled-backend request returns 502 within the test's 18-second bound |
| Old callbacks could free a newer call slot | Added owned generation/provider-ID leases and atomic release/bind checks; stale messages cannot release a newer attempt |
| Persistence failure after provider acceptance freed live capacity | Accepted-call DB-failure test now retains the bound slot and reports the provider acceptance |
| Test suite itself performed unintended stub DB reads | Workflow read fixtures now isolate persistence; this avoids network delay and removes two Supabase warnings |
| Unused imports obscured static verification | 21 unused imports removed; critical and unused-import checks pass |

Permission failures do not automatically grant the model broader authority. Written offer ranges now require verified server values and may refuse offers previously generated from arbitrary input or weak comps. Existing environments must provide the correct packet/action permissions and cents-based pricing data.

## Evidence and reproduction

- [Full Python run](test-evidence/max-pytest.txt)
- [Dashboard HTTP results](test-evidence/dashboard-http.json)
- [Initially failing case ledger](test-evidence/reproduced-failing-cases.json)
- [Original 129-finding ledger](VOICE-AUDIT-LEDGER.md)

```sh
uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m coverage run --branch --source=backend -m pytest -q
.venv/bin/python -m coverage report
npm ci --prefix tests
npm run test:database --prefix tests
npm run build --prefix dashboard
npm run lint --prefix dashboard
npm run test:dashboard --prefix tests
```

The real Redis test starts a private local process, disables persistent saves, uses a temporary directory, and terminates it afterward. `redislite` is a test-only source of the Redis binary. The dashboard test starts its own local Next.js server/backend, uses fake credentials and contacts, and terminates both afterward. Configure the nonproduction Supabase build values described in VOICE-REPAIR.md before building.

## Remaining limits and gaps

Passing many parametrized cases is not equivalent to complete code or behavior coverage. Large parts of acquisition, cash-buyer integrations, actual provider delivery, durable post-call work, calendar synchronization, human operator workflows, reminder/attendance truth, and production database bootstrap remain outside this verified execution path. See the original ledger and release requirements.

The Redis namespace now uses shared cluster hash tags and owned leases. Drain existing active calls before switching versions because old capacity keys are not migrated.

The lease now rejects stale releases, but it still lacks heartbeat/maximum-call-duration enforcement and durable reconciliation if provider callbacks arrive before binding, Redis fails after dialing, or a worker dies. Provider status updates also need durable event idempotency and current-call filtering so old events cannot overwrite newer database outcomes.

The conversation tests exercise actual processors and tools with controlled inputs; they do not include an actual speaking language model, external STT/TTS streaming, remote audible playback marks, echo cancellation, real barge-in recovery, noise/accent accuracy, or a 50-call recorded acceptance campaign. No real sellers were called or messaged, no production data was changed, and no deployment was performed. Those measurements remain essential before claiming A-grade telephone behavior.
