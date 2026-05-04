import math
import httpx
from loguru import logger


OSM_HEADERS = {
    "User-Agent": "SanJoaquinHouseBuyers/1.0 (sanjoaquinhousebuyers.com)",
    "Accept": "application/json",
}

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
OVERPASS_BASE = "https://overpass-api.de/api/interpreter"


def geocode_address(address: str, city: str, state: str) -> dict:
    query = f"{address}, {city}, {state}"
    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "limit": 1,
    }
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
                    tags.get("amenity")
                    or tags.get("leisure")
                    or tags.get("natural")
                    or "place"
                )
                landmarks.append({"name": name, "type": poi_type, "distance": distance})
            landmarks.sort(key=lambda x: x["distance"])
            return landmarks[:8]
    except Exception as e:
        logger.error("get_nearby_landmarks failed lat={} lng={} error={}", lat, lng, str(e))
        return []


def enrich_property_context(address: str, city: str, state: str) -> str:
    logger.info("enrich_property_context address={} {}, {}", address, city, state)
    geo = geocode_address(address, city, state)
    if not geo:
        return ""

    lat = geo["lat"]
    lng = geo["lng"]
    neighborhood = geo.get("neighborhood", "")
    district = geo.get("district", "")

    landmarks = get_nearby_landmarks(lat, lng)

    parts = []

    location_parts = []
    if neighborhood:
        location_parts.append(neighborhood)
    if district and district != neighborhood:
        location_parts.append(district)
    if location_parts:
        parts.append(f"in the {', '.join(location_parts)} area")

    if landmarks:
        names = [lm["name"] for lm in landmarks[:3]]
        if len(names) == 1:
            parts.append(f"near {names[0]}")
        elif len(names) == 2:
            parts.append(f"near {names[0]} and {names[1]}")
        else:
            parts.append(f"near {names[0]}, {names[1]}, and {names[2]}")

    if not parts:
        return ""

    result = f"Property is {', '.join(parts)}."
    logger.info("enrich_property_context result={}", result)
    return result


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
