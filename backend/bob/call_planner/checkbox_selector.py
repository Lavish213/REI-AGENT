from __future__ import annotations
from loguru import logger

_BOX_PRIORITY = [
    "identity",
    "occupancy",
    "motivation",
    "condition",
    "timeline",
    "next_step",
]

_LEAD_FIELD_MAP = {
    "identity": "owner_confirmed",
    "occupancy": "occupancy_known",
    "motivation": "motivation_known",
    "condition": "condition_known",
    "timeline": "timeline_known",
    "next_step": "next_step_known",
}

def select_missing_box(lead: dict, call_number: int = 1) -> str:
    props = lead.get("properties") or lead
    prior_boxes: dict = props.get("prior_boxes") or {}

    if call_number == 1:
        priority = ["identity", "motivation", "condition", "timeline", "next_step"]
    elif call_number == 2:
        priority = ["motivation", "condition", "timeline", "next_step"]
    else:
        priority = ["next_step", "timeline", "condition", "motivation"]

    for box in priority:
        field = _LEAD_FIELD_MAP.get(box)
        if field and not prior_boxes.get(field, False):
            logger.debug("checkbox_selector missing_box={} call_number={}", box, call_number)
            return box

    logger.debug("checkbox_selector all boxes checked call_number={}", call_number)
    return "none"
