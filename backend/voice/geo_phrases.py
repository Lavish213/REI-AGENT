"""
Converts structured OSM/geo enrichment data into natural Sophia speech phrases.
These phrases are injected into the property context so Sophia sounds locally familiar.
"""
from __future__ import annotations


_NEIGHBORHOOD_INTROS = {
    "South Stockton": [
        "That's down in South Stockton, right?",
        "South Stock — yeah I know that area well.",
        "That whole south side corridor.",
    ],
    "Central Stockton": [
        "That's central Stockton area.",
        "Yeah Central Stockton — we've been active there.",
    ],
    "North Stockton": [
        "Up in North Stockton — that's Lincoln Unified territory.",
        "North Stockton, nicer area.",
    ],
    "Weston Ranch": [
        "Weston Ranch — newer construction out there.",
        "Oh Weston Ranch, ACE train's right there.",
    ],
    "Morada / Northeast Stockton": [
        "Out in the Morada area — more rural out there.",
        "Northeast side, more acreage properties.",
    ],
    "Brookside": [
        "Brookside — that's one of the nicer areas.",
        "Brookside neighborhood, yeah.",
    ],
    "Lodi": [
        "Lodi area — wine country adjacent.",
        "Lodi's a tight market right now.",
    ],
    "Tracy": [
        "Tracy — that's been growing fast, lot of Bay Area folks moving out there.",
        "Tracy market's been pretty active.",
    ],
    "Manteca": [
        "Manteca's been moving fast lately.",
        "Manteca — good market out there.",
    ],
}

_STREET_CONNECTORS = [
    "near {street}",
    "right off {street}",
    "over by {street}",
    "just off {street}",
]

_LANDMARK_CONNECTORS = [
    "right near {landmark}",
    "close to {landmark}",
    "by {landmark}",
]

_BUY_BOX_NOTES = {
    "yes": "That area fits what we look for.",
    "marginal": "We look at deals case by case out there.",
    "no": "That area's a bit outside our usual buy box, but we still look.",
}

_FLOOD_PHRASES = {
    "high — flood insurance required": "One thing — that area's in a flood zone so there'd be flood insurance.",
    "moderate": "That area has some flood zone consideration.",
}

_ACE_PHRASES = [
    "You've got the ACE train close — that's a big deal for commuters.",
    "ACE train's nearby, Bay Area people love that.",
]

_SCHOOL_PHRASES = {
    "Lincoln Unified": "Lincoln Unified over there — that's a premium district.",
    "Stockton Unified": "Stockton Unified area — we see a lot of motivated sellers there.",
    "Tracy Unified": "Tracy Unified — solid district, Bay Area transplants like it.",
    "Lodi Unified": "Lodi Unified, steady market.",
    "Manteca Unified": "Manteca Unified, growing area.",
}


def get_geo_phrases(osm_data: dict, city: str = "") -> list[str]:
    """
    Returns up to 3 natural conversational phrases Sophia can reference during the call.
    Each phrase sounds like something a local acquisitions person would naturally say.
    """
    phrases: list[str] = []

    neighborhood = osm_data.get("neighborhood", "")
    cross_streets = osm_data.get("cross_streets", [])
    landmarks = osm_data.get("landmarks", [])
    school_district = osm_data.get("school_district", "")
    flood_risk = osm_data.get("flood_risk", "")
    ace_accessible = osm_data.get("ace_accessible", False)
    buy_box = osm_data.get("buy_box", "unknown")

    # Neighborhood intro
    nbhd_options = _NEIGHBORHOOD_INTROS.get(neighborhood, [])
    if nbhd_options:
        phrases.append(nbhd_options[0])
    elif neighborhood:
        phrases.append(f"That's over in the {neighborhood} area.")

    # Cross street reference
    if cross_streets:
        import random
        connector = random.choice(_STREET_CONNECTORS)
        phrases.append(connector.format(street=cross_streets[0]))
    elif landmarks:
        import random
        connector = random.choice(_LANDMARK_CONNECTORS)
        phrases.append(connector.format(landmark=landmarks[0]))

    # School district
    school_phrase = _SCHOOL_PHRASES.get(school_district)
    if school_phrase and len(phrases) < 3:
        phrases.append(school_phrase)

    # Flood zone (only if high/moderate — material info)
    flood_phrase = _FLOOD_PHRASES.get(flood_risk)
    if flood_phrase and len(phrases) < 3:
        phrases.append(flood_phrase)

    # ACE train
    if ace_accessible and len(phrases) < 3:
        phrases.append(_ACE_PHRASES[0])

    # Buy box note
    buy_box_note = _BUY_BOX_NOTES.get(buy_box)
    if buy_box_note and len(phrases) < 3 and not any("area" in p.lower() for p in phrases):
        phrases.append(buy_box_note)

    return phrases[:3]


# ── Local slang + regional shorthand (G21) ────────────────────────────────────

# City/area nicknames and local shorthand
_LOCAL_SLANG: dict[str, list[str]] = {
    "stockton": [
        "Stockton" , "the 209", "Stock-town", "S-Town",
        "downtown Stockton", "South Stock",
    ],
    "south stockton": ["South Stock", "the south side"],
    "tracy":    ["Tracy", "out toward Tracy", "Tracy side"],
    "lodi":     ["Lodi", "wine country"],
    "manteca":  ["Manteca", "out in Manteca"],
    "modesto":  ["Modesto", "Mo-Town"],
    "sacramento": ["Sac", "South Sac", "downtown Sac"],
    "san jose": ["South Bay", "the Bay Area", "SJ"],
    "san francisco": ["SF", "the city", "The Bay"],
    "fresno":   ["Fresno", "the Central Valley"],
    "the bay area": ["the Bay", "Bay Area folks"],
}

# Commute reference phrases
_COMMUTE_PHRASES = [
    "lot of Bay Area people looking out this way",
    "good spot for Bay Area commuters",
    "ACE train area — attracts Bay Area buyers",
    "people are moving out from the Bay",
]

# Investor shorthand
_INVESTOR_SHORTHAND = [
    "in our buy box",
    "good wholesale area",
    "flip-friendly neighborhood",
    "solid buy-and-hold market",
    "distressed seller inventory is high there",
]


def get_local_slang(city: str, neighborhood: str = "") -> list[str]:
    """
    Returns local nicknames and shorthand for a city/neighborhood.
    These can be dropped into Sophia's speech naturally.
    """
    city_lower = city.lower().strip()
    nbhd_lower = neighborhood.lower().strip()

    results: list[str] = []

    # Check neighborhood first (more specific)
    for key, terms in _LOCAL_SLANG.items():
        if nbhd_lower and key in nbhd_lower:
            results.extend(terms[:2])
            break

    # City nicknames
    city_terms = _LOCAL_SLANG.get(city_lower, [])
    if city_terms and not results:
        results.extend(city_terms[:2])

    return results[:3]


def format_geo_phrases_for_prompt(phrases: list[str], slang: list[str] | None = None) -> str:
    """
    Formats geo phrases (and optional slang terms) for injection into the system prompt.
    """
    if not phrases and not slang:
        return ""
    lines = [
        "SOPHIA LOCAL GEOGRAPHIC FAMILIARITY",
        "Reference these naturally during conversation (don't recite all at once):",
    ]
    for p in phrases:
        lines.append(f'- "{p}"')
    if slang:
        lines.append(f'Local nicknames you can drop in: {", ".join(slang)}')
    return "\n".join(lines)
