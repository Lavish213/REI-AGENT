from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytz


PACIFIC = pytz.timezone("America/Los_Angeles")


def local_slot(date: str, time: str, now: datetime | None = None) -> datetime:
    naive = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    aware = PACIFIC.localize(naive, is_dst=None)
    current = now or datetime.now(timezone.utc)
    if aware <= current:
        raise ValueError("Please choose a future date and time")
    if aware > current + timedelta(days=180):
        raise ValueError("Please choose a time within the next 180 days")
    return aware


def callback_slot(inp: dict, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if inp.get("date") and inp.get("time"):
        return local_slot(inp["date"], inp["time"], current)
    if inp.get("day_of_week"):
        raise ValueError("Please confirm a specific calendar date and local time")
    delay = float(inp.get("delay_hours", 0))
    if not 0 < delay <= 24 * 180:
        raise ValueError("Please confirm an exact time or a positive delay")
    return (current + timedelta(hours=delay)).astimezone(PACIFIC)
