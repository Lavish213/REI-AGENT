import math
import httpx
from loguru import logger


OSM_HEADERS = {
    "User-Agent": "SanJoaquinHouseBuyers/1.0 (sanjoaquinhousebuyers.com)",
    "Accept": "application/json",
}

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
OVERPASS_BASE = "https://overpass-api.de/api/interpreter"
FEMA_FLOOD_URL = (
    "https://hazards.fema.gov/gis/nfhl/rest/services/FIRMette/NFHL/MapServer/28/query"
)

ACE_STATIONS = [
    {"name": "Stockton", "lat": 37.9577, "lng": -121.2908},
    {"name": "Lodi", "lat": 38.1302, "lng": -121.2722},
]

_SCHOOL_DISTRICT_RULES = [
    ("Tracy Unified",    lambda city, lat, lng: city.lower() == "tracy"),
    ("Lodi Unified",     lambda city, lat, lng: city.lower() == "lodi"),
    ("Manteca Unified",  lambda city, lat, lng: city.lower() == "manteca"),
    ("Lincoln Unified",  lambda city, lat, lng: city.lower() == "stockton" and lat >= 37.985),
    ("Stockton Unified", lambda city, lat, lng: city.lower() == "stockton" and lat < 37.985),
]

_DISTRICT_PERFORMANCE = {
    "Lincoln Unified": "higher performing — 10-15% price premium",
    "Stockton Unified": "lower performing — most distressed sellers",
    "Lodi Unified": "mid-range performing — stable values",
    "Tracy Unified": "higher performing — Bay Area transplant buyers",
    "Manteca Unified": "mid-range performing — growing market",
}

_NEIGHBORHOOD_PROFILES = [
    {
        "label": "South Stockton",
        "city": "stockton",
        "lat_max": 37.940,
        "arv_min": 80_000,
        "arv_max": 180_000,
        "buy_box": "yes",
        "notes": "highest distress, best wholesale market",
    },
    {
        "label": "Central Stockton",
        "city": "stockton",
        "lat_min": 37.940,
        "lat_max": 37.970,
        "arv_min": 120_000,
        "arv_max": 220_000,
        "buy_box": "yes",
        "notes": "mixed, good flip area",
    },
    {
        "label": "North Stockton",
        "city": "stockton",
        "lat_min": 37.970,
        "lat_max": 37.990,
        "arv_min": 200_000,
        "arv_max": 350_000,
        "buy_box": "marginal",
        "notes": "lower distress, Lincoln Unified premium",
    },
    {
        "label": "Weston Ranch",
        "city": "stockton",
        "lat_min": 37.900,
        "lat_max": 37.930,
        "lng_max": -121.310,
        "arv_min": 250_000,
        "arv_max": 380_000,
        "buy_box": "marginal",
        "notes": "newer construction, ACE train access",
    },
    {
        "label": "Morada / Northeast Stockton",
        "city": "stockton",
        "lat_min": 37.990,
        "arv_min": 300_000,
        "arv_max": 500_000,
        "buy_box": "no",
        "notes": "semi-rural, acreage, different buyer pool",
    },
    {
        "label": "Brookside",
        "city": "stockton",
        "lat_min": 37.985,
        "lng_max": -121.330,
        "arv_min": 400_000,
        "arv_max": 600_000,
        "buy_box": "no",
        "notes": "upscale, out of buy box",
    },
    {
        "label": "Lodi",
        "city": "lodi",
        "arv_min": 200_000,
        "arv_max": 350_000,
        "buy_box": "yes",
        "notes": "wine country adjacent, tighter inventory",
    },
    {
        "label": "Tracy",
        "city": "tracy",
        "arv_min": 350_000,
        "arv_max": 500_000,
        "buy_box": "marginal",
        "notes": "Bay Area spillover, fastest growing in county",
    },
    {
        "label": "Manteca",
        "city": "manteca",
        "arv_min": 300_000,
        "arv_max": 450_000,
        "buy_box": "yes",
        "notes": "growing fast, good buy and hold",
    },
]


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return _haversine_meters(lat1, lng1, lat2, lng2) / 1609.344


def geocode_address(address: str, city: str, state: str) -> dict:
    query = f"{address}, {city}, {state}"
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 1}
    try:
        with httpx.Client(headers=OSM_HEADERS, timeout=10) as client:
            response = client.get(f"{NOMINATIM_BASE}/search", params=params)
            response.raise_for_status()
            results = response.json()
            if not results:
                logger.warning("geocode_address no results address={}", query)
                return {}
            result = results[0]
            addr = result.get("address", {})
            return {
                "lat": float(result["lat"]),
                "lng": float(result["lon"]),
                "neighborhood": addr.get("neighbourhood") or addr.get("suburb") or "",
                "district": addr.get("city_district") or addr.get("county") or "",
                "display_name": result.get("display_name", ""),
            }
    except Exception as e:
        logger.error("geocode_address failed address={} error={}", query, str(e))
        return {}


def get_nearby_landmarks(lat: float, lng: float, radius_meters: int = 500) -> list[dict]:
    query = f"""
[out:json][timeout:10];
(
  node["amenity"~"school|park|hospital|library|community_centre"](around:{radius_meters},{lat},{lng});
  node["leisure"~"park|nature_reserve"](around:{radius_meters},{lat},{lng});
  node["natural"~"water|lake|river"](around:{radius_meters},{lat},{lng});
  way["leisure"~"park|nature_reserve"](around:{radius_meters},{lat},{lng});
  way["natural"~"water|lake|river"](around:{radius_meters},{lat},{lng});
);
out center 10;
""".strip()
    try:
        with httpx.Client(headers=OSM_HEADERS, timeout=15) as client:
            response = client.post(OVERPASS_BASE, data={"data": query})
            response.raise_for_status()
            elements = response.json().get("elements", [])
            landmarks = []
            for el in elements:
                name = el.get("tags", {}).get("name", "").strip()
                if not name:
                    continue
                el_lat = el.get("lat") or el.get("center", {}).get("lat")
                el_lng = el.get("lon") or el.get("center", {}).get("lon")
                if el_lat is None or el_lng is None:
                    continue
                distance = int(_haversine_meters(lat, lng, float(el_lat), float(el_lng)))
                tags = el.get("tags", {})
                poi_type = (
                    tags.get("amenity") or tags.get("leisure") or tags.get("natural") or "place"
                )
                landmarks.append({"name": name, "type": poi_type, "distance": distance})
            landmarks.sort(key=lambda x: x["distance"])
            return landmarks[:8]
    except Exception as e:
        logger.error("get_nearby_landmarks failed lat={} lng={} error={}", lat, lng, str(e))
        return []


def get_cross_streets(lat: float, lng: float, radius_meters: int = 200) -> list[str]:
    query = f"""
[out:json][timeout:10];
(
  way["highway"~"primary|secondary|tertiary|residential"]["name"](around:{radius_meters},{lat},{lng});
);
out tags;
""".strip()
    try:
        with httpx.Client(headers=OSM_HEADERS, timeout=12) as client:
            response = client.post(OVERPASS_BASE, data={"data": query})
            response.raise_for_status()
            elements = response.json().get("elements", [])
            seen: set[str] = set()
            priority_order = ["primary", "secondary", "tertiary", "residential"]
            by_priority: dict[str, list[str]] = {k: [] for k in priority_order}
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name", "").strip()
                hw = tags.get("highway", "residential")
                if name and name not in seen:
                    seen.add(name)
                    bucket = hw if hw in priority_order else "residential"
                    by_priority[bucket].append(name)
            ordered: list[str] = []
            for bucket in priority_order:
                ordered.extend(by_priority[bucket])
            return ordered[:3]
    except Exception as e:
        logger.warning("get_cross_streets failed lat={} lng={} error={}", lat, lng, str(e))
        return []


def get_flood_zone(lat: float, lng: float) -> dict:
    params = {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(FEMA_FLOOD_URL, params=params)
            response.raise_for_status()
            data = response.json()
            features = data.get("features", [])
            if not features:
                return {"zone": "X", "risk": "minimal", "sfha": False}
            attrs = features[0].get("attributes", {})
            zone = (attrs.get("FLD_ZONE") or "X").strip()
            sfha = str(attrs.get("SFHA_TF", "F")).upper() == "T"
            if zone.startswith("A") or zone.startswith("V"):
                risk = "high — flood insurance required"
            elif zone == "X":
                risk = "minimal"
            else:
                risk = "moderate"
            return {"zone": zone, "risk": risk, "sfha": sfha}
    except Exception as e:
        logger.warning("get_flood_zone failed lat={} lng={} error={}", lat, lng, str(e))
        return {"zone": "unknown", "risk": "unknown", "sfha": False}


def get_ace_distance(lat: float, lng: float) -> dict | None:
    closest = None
    closest_miles = float("inf")
    for station in ACE_STATIONS:
        miles = _haversine_miles(lat, lng, station["lat"], station["lng"])
        if miles < closest_miles:
            closest_miles = miles
            closest = station
    if closest is None:
        return None
    return {
        "station": closest["name"],
        "miles": round(closest_miles, 1),
        "accessible": closest_miles <= 3.0,
    }


def get_school_district(city: str, lat: float, lng: float) -> dict:
    for name, rule in _SCHOOL_DISTRICT_RULES:
        try:
            if rule(city, lat, lng):
                return {
                    "district": name,
                    "description": _DISTRICT_PERFORMANCE.get(name, ""),
                }
        except Exception:
            continue
    return {"district": "unknown", "description": ""}


def get_neighborhood_profile(city: str, lat: float, lng: float) -> dict | None:
    city_lower = city.lower()
    candidates = [p for p in _NEIGHBORHOOD_PROFILES if p.get("city", "") == city_lower]
    for profile in candidates:
        if city_lower not in ("stockton",):
            return profile
        lat_min = profile.get("lat_min", -90)
        lat_max = profile.get("lat_max", 90)
        lng_max = profile.get("lng_max", 180)
        if lat_min <= lat <= lat_max and lng <= lng_max:
            return profile
    if candidates:
        return candidates[-1]
    return None


def enrich_property_full(address: str, city: str, state: str) -> dict:
    logger.info("enrich_property_full address={} {}, {}", address, city, state)
    result: dict = {
        "neighborhood": "",
        "cross_streets": [],
        "school_district": "",
        "school_district_description": "",
        "arv_min": None,
        "arv_max": None,
        "buy_box": "unknown",
        "neighborhood_notes": "",
        "flood_zone": "unknown",
        "flood_risk": "unknown",
        "ace_station": None,
        "ace_miles": None,
        "ace_accessible": False,
        "landmarks": [],
        "lat": None,
        "lng": None,
    }

    geo = geocode_address(address, city, state)
    if not geo:
        return result

    lat, lng = geo["lat"], geo["lng"]
    result["lat"] = lat
    result["lng"] = lng
    result["neighborhood"] = geo.get("neighborhood") or ""

    cross = get_cross_streets(lat, lng)
    result["cross_streets"] = cross

    district_info = get_school_district(city, lat, lng)
    result["school_district"] = district_info["district"]
    result["school_district_description"] = district_info["description"]

    profile = get_neighborhood_profile(city, lat, lng)
    if profile:
        if not result["neighborhood"]:
            result["neighborhood"] = profile["label"]
        result["arv_min"] = profile.get("arv_min")
        result["arv_max"] = profile.get("arv_max")
        result["buy_box"] = profile.get("buy_box", "unknown")
        result["neighborhood_notes"] = profile.get("notes", "")

    flood = get_flood_zone(lat, lng)
    result["flood_zone"] = flood["zone"]
    result["flood_risk"] = flood["risk"]

    ace = get_ace_distance(lat, lng)
    if ace:
        result["ace_station"] = ace["station"]
        result["ace_miles"] = ace["miles"]
        result["ace_accessible"] = ace["accessible"]

    landmarks = get_nearby_landmarks(lat, lng, radius_meters=800)
    result["landmarks"] = [lm["name"] for lm in landmarks[:4]]

    logger.info(
        "enrich_property_full done neighborhood={} district={} flood={} ace={}mi",
        result["neighborhood"],
        result["school_district"],
        result["flood_zone"],
        result["ace_miles"],
    )
    return result


def enrich_property_context(address: str, city: str, state: str) -> str:
    data = enrich_property_full(address, city, state)
    parts = []
    if data["neighborhood"]:
        parts.append(f"in the {data['neighborhood']} area")
    if data["cross_streets"]:
        if len(data["cross_streets"]) >= 2:
            parts.append(f"near {data['cross_streets'][0]} and {data['cross_streets'][1]}")
        else:
            parts.append(f"near {data['cross_streets'][0]}")
    if data["landmarks"]:
        names = data["landmarks"][:2]
        parts.append(f"nearby: {', '.join(names)}")
    if not parts:
        return ""
    result = f"Property is {', '.join(parts)}."
    logger.info("enrich_property_context result={}", result)
    return result
