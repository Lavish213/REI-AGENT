import os
import json
import hashlib
from loguru import logger


_cache: dict = {}


def _cache_key(address: str, city: str, state: str) -> str:
    raw = f"{address.lower().strip()}{city.lower().strip()}{state.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def get_cached_comps(address: str, city: str, state: str) -> list[dict] | None:
    key = _cache_key(address, city, state)
    result = _cache.get(key)
    if result:
        logger.debug("cache hit for address={}", address)
        return result
    logger.debug("cache miss for address={}", address)
    return None


def set_cached_comps(address: str, city: str, state: str, comps: list[dict]) -> None:
    key = _cache_key(address, city, state)
    _cache[key] = comps
    logger.debug("cache set for address={} comps={}", address, len(comps))


def clear_cache() -> None:
    _cache.clear()
    logger.info("comps cache cleared")
