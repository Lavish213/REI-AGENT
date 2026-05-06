# REI Agent Compliance Documentation

## TCPA Requirements
- AI voice calls require prior written consent for automated calls to cell phones
- FCC February 2024 ruling: AI-generated voices = "artificial voice" under TCPA
- Must honor opt-out requests immediately
- Cannot call numbers on National DNC Registry without existing business relationship
- Calling hours: 8am-9pm in called party's local time zone
- Must identify: name of caller, phone number, business name at call start

## California-Specific Laws
- CCPA: Sellers have right to know what data collected and request deletion
- SB 1001 (Bot Disclosure): Must disclose AI identity when sincerely asked
- Cannot claim to be human when directly asked in good faith
- Consumer Legal Remedies Act applies to real estate transactions

## SMS Compliance
- 10DLC registration required for business SMS at scale
- Must include opt-out instructions (STOP to opt out)
- SMS hours: 8am-9pm recipient local time
- Must honor STOP within 10 business days (immediate is best practice)
- P2P vs A2P: Our system is A2P, must be registered

## AI Identity Disclosure (SB 1001)
When caller sincerely asks if Sophia is a bot/AI/robot/human:
MUST say: "I'm Sophia — an automated assistant for San Joaquin House Buyers.
Would you like to speak with someone directly?"
NEVER claim to be human when directly asked.

## National DNC Registry
- Check leads against DNC before calling: donotcall.gov
- Established Business Relationship (EBR) exception: if they inquired within 18 months
- DNC registration is permanent until caller removes themselves
- Internal DNC list: maintain opted_out=true in leads table

## Record Keeping
- Call recordings: 5 years minimum (California 2-party consent state)
- Two-party consent: Must inform callers recording may occur
- Opt-out records: permanent
- Compliance log: minimum 5 years

## Fair Housing
- Cannot steer based on race, color, religion, national origin, sex, disability, familial status
- Cannot reference school quality in demographic terms
- Cannot reference neighborhood in demographic terms
- Applies to: buyer selection, pricing, terms, conditions

## San Joaquin County Specific
- Transfer tax: Seller pays $1.10 per $1,000 of sale price
- On $200k sale: ~$220 in transfer tax
- Seller closing costs total: ~$3,000-4,000

## Opt-Out Handling
Trigger words: STOP, UNSUBSCRIBE, CANCEL, QUIT, END, REMOVE
Immediate actions on opt-out:
1. Set opted_out=true on lead record
2. Record opted_out_at timestamp
3. Cancel all scheduled outreach
4. Never contact again without explicit reinstatement

## Solar Panel Disclosure (AB 723 Adjacent)
Leased solar panels create potential encumbrances.
Must disclose and check assumability before close.
