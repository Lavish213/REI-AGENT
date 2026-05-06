import httpx
from loguru import logger

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
CENSUS_ACS_URL = "https://api.census.gov/data/2022/acs/acs5"


def get_census_data(lat: float, lng: float) -> dict:
    result = {
        "median_household_income": None,
        "vacancy_rate": None,
        "owner_occupancy_rate": None,
        "census_tract": None,
        "state_fips": None,
        "county_fips": None,
    }

    try:
        params = {
            "x": str(lng),
            "y": str(lat),
            "benchmark": "Public_AR_Census2020",
            "vintage": "Census2020_Census2020",
            "layers": "Census Tracts",
            "format": "json",
        }
        with httpx.Client(timeout=15) as client:
            geo_resp = client.get(CENSUS_GEOCODER_URL, params=params)
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

            tracts = (
                geo_data.get("result", {})
                .get("geographies", {})
                .get("Census Tracts", [])
            )
            if not tracts:
                logger.warning("census: no tract found lat={} lng={}", lat, lng)
                return result

            tract_info = tracts[0]
            state_fips = tract_info.get("STATE", "")
            county_fips = tract_info.get("COUNTY", "")
            tract = tract_info.get("TRACT", "")

            result["census_tract"] = tract
            result["state_fips"] = state_fips
            result["county_fips"] = county_fips

            variables = "B19013_001E,B25002_002E,B25002_003E,B25003_002E"
            acs_params = {
                "get": variables,
                "for": f"tract:{tract}",
                "in": f"state:{state_fips} county:{county_fips}",
            }
            acs_resp = client.get(CENSUS_ACS_URL, params=acs_params)
            acs_resp.raise_for_status()
            acs_data = acs_resp.json()

            if len(acs_data) < 2:
                return result

            headers_row = acs_data[0]
            values_row = acs_data[1]
            acs = dict(zip(headers_row, values_row))

            median_income_str = acs.get("B19013_001E")
            if median_income_str and median_income_str not in ("-666666666", "-999999999"):
                result["median_household_income"] = int(median_income_str)

            total_units_str = acs.get("B25002_002E")
            vacant_str = acs.get("B25002_003E")
            owner_str = acs.get("B25003_002E")

            if total_units_str and vacant_str:
                total = int(total_units_str)
                vacant = int(vacant_str)
                if total > 0:
                    result["vacancy_rate"] = round(vacant / total, 4)

            if total_units_str and owner_str:
                total = int(total_units_str)
                owner = int(owner_str)
                if total > 0:
                    result["owner_occupancy_rate"] = round(owner / total, 4)

            logger.info(
                "census_data lat={} lng={} income={} vacancy={} owner_rate={}",
                lat, lng,
                result["median_household_income"],
                result["vacancy_rate"],
                result["owner_occupancy_rate"],
            )

    except Exception as e:
        logger.error("get_census_data failed lat={} lng={} error={}", lat, lng, str(e))

    return result


def get_census_motivation_bonus(census_data: dict) -> int:
    bonus = 0
    income = census_data.get("median_household_income")
    vacancy = census_data.get("vacancy_rate")
    owner_rate = census_data.get("owner_occupancy_rate")

    if income is not None and income < 45000:
        bonus += 5
    if vacancy is not None and vacancy > 0.15:
        bonus += 8
    if owner_rate is not None and owner_rate < 0.40:
        bonus += 5

    return bonus
