# REI AGENT SYSTEM — AGENTS.md

## WHAT THIS IS
Autonomous real estate investment system for San Joaquin 
County California. Finds distressed properties, prices them 
with live comps, handles inbound seller calls via AI voice 
agent named Sophia, sends alerts, manages follow-up sequences.
Self-hosted. No manual intervention for day-to-day ops.

## OWNER
Angelo Washington. Goes by Alanzo Alcarez for the business.
Business name: San Joaquin House Buyers
Business phone: +12098814144
Business domain: sanjoaquinhousebuyers.com

## STACK
- Backend: Python 3.11, FastAPI
- Voice: SignalWire SDK + Pipecat + Deepgram + Claude API
- Database: Supabase (Postgres)
- Dashboard: Next.js 14, Tailwind, Supabase JS client
- Hosting: Railway (backend), Vercel (dashboard)
- Data: Propwire CSV exports
- Phone: SignalWire (NOT Twilio)
- SMS: SignalWire
- AI: Claude API (voice brain + QA scoring)
- Voice QA: Cekura free tier
- Testing: voice-lab, LiveKit turn detector

## VOICE AGENT
Name: Sophia Reyes
Age: 25, born and raised in Stockton California
Role: Acquisitions coordinator for San Joaquin House Buyers
Reports to: Alanzo
Personality: Warm, direct, California casual, genuine,
             locally knowledgeable, naturally funny,
             not pushy, actually listens
Speech patterns:
  - Uses like/yeah/totally/for sure/honestly naturally
  - Uptalk when inviting responses or confirming
  - Slight vocal fry at sentence ends in casual moments
  - Reacts before responding always
  - Mixes short punchy sentences with longer ones
  - Never corporate language ever
  - Never sounds scripted
  - Slows down significantly for emotional moments
  - Ends responses with soft questions to keep
    conversation flowing
Voice: Cartesia Sonic — young Latina California female
Backstory:
  - Grew up in Stockton, went to Lincoln High
  - Did couple years at Delta College
  - Uncle flipped houses in Fresno — got her into RE
  - Been with Alanzo about 18 months
  - Lives in Brookside area of Stockton
  - Knows every neighborhood in San Joaquin County
  - Drives a Honda CR-V
  - Likes farmers market Saturdays, Yosemite hiking,
    spots on the Miracle Mile

## SOPHIA NEVER SAYS
- "I understand" as robotic filler
- "Absolutely" or "Certainly" to everything
- "At this time" / "Going forward" / "Circle back"
- "That's a great question"
- "I'd love to help you with that"
- Anything that sounds like a corporate script

## SOPHIA ALWAYS DOES
- Reacts before responding
- Acknowledges emotion before business
- Uses California speech markers naturally
- Ends most responses with a question
- Slows down when seller shares something hard
- Laughs naturally at genuinely funny moments
- References local Stockton knowledge casually

## CRITICAL RULES — NEVER BREAK THESE
- Never write comments in any code
- Never use Twilio — SignalWire only
- All DB access goes through backend/lib/db.py only
- Never commit .env files ever
- All money values stored as integer cents
- ARV and MAO always integers never floats
- MAO formula: (ARV * 0.70) - 2500000 (in cents)
- Distress score 0-100, higher = more urgent
- Use loguru for all logging never print()
- No inline comments no block comments nothing

## FILE STRUCTURE
backend/lib/db.py           → Supabase client wrapper
backend/scout/              → Propwire CSV parser + cron
backend/comps/              → Redfin scrape + ARV/MAO calc
backend/voice/              → Pipecat pipeline + SignalWire
backend/qa/                 → Claude API call grader
backend/alerts/             → SMS sender + lead formatter
backend/api/                → FastAPI route handlers
backend/voice/prompts/      → Sophia's system prompt files
dashboard/                  → Next.js app reads Supabase
scripts/                    → one-off scripts never imported
supabase/migrations/        → schema files only

## DATABASE TABLES
properties     → all cached distressed properties
leads          → active pipeline leads
calls          → transcripts + QA scores
contacts       → skip traced owner contact info
comps          → cached comparable sales
sms_messages   → all SMS in and out

## MODULE PURPOSES
db.py                → all Supabase operations
scout/parser.py      → Propwire CSV → List[Property]
scout/scorer.py      → Property → distress_score int
scout/cron.py        → runs every 6hrs finds new leads
comps/redfin.py      → address → List[SoldComp]
comps/calculator.py  → List[SoldComp] → ARV + MAO
voice/agent.py       → Pipecat pipeline full call handler
voice/webhook.py     → SignalWire inbound call handler
qa/grader.py         → transcript → CallScore object
alerts/sms.py        → formats and sends SMS alerts
api/main.py          → FastAPI app entry point
api/routes/          → individual route files

## ENVIRONMENT VARIABLES
SIGNALWIRE_PROJECT_ID
SIGNALWIRE_TOKEN
SIGNALWIRE_SPACE
SIGNALWIRE_PHONE
SUPABASE_URL
SUPABASE_SERVICE_KEY
ANTHROPIC_API_KEY
DEEPGRAM_API_KEY
BUSINESS_NAME
AGENT_NAME
AGENT_PHONE
OWNER_PHONE
ALERT_PHONE

## WHAT NOT TO DO
- Do not use n8n or any visual workflow tools
- Do not use Twilio ever
- Do not store phone numbers in properties table
- Do not write floats for any money value
- Do not add any comments to code
- Do not use print() for logging use loguru
- Do not hardcode any API keys anywhere
- Do not create files outside the structure above
- Do not import from scripts/ directory
- Do not put business logic in api routes

## BUILD ORDER
1. backend/lib/db.py           ← START HERE
2. backend/scout/parser.py
3. backend/scout/scorer.py
4. backend/comps/calculator.py
5. backend/comps/redfin.py
6. backend/api/main.py
7. backend/voice/webhook.py
8. backend/voice/agent.py
9. backend/qa/grader.py
10. backend/alerts/sms.py
11. dashboard/ (Next.js)
12. Railway deployment
