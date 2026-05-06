from loguru import logger
from backend.lib.db import get_supabase


class SellerMemory:
    def __init__(self, lead_id: str):
        self.lead_id = lead_id
        self.call_summaries: list[str] = []
        self.price_floor: int | None = None
        self.hot_topics: list[str] = []
        self.rapport_openers: list[str] = []
        self.objections_raised: list[str] = []
        self.competitor_mentions: list[str] = []
        self.timeline_mentioned: str | None = None
        self.motivation_level: int | None = None
        self.best_callback_time: str | None = None
        self.next_best_action: str | None = None
        self.spouse_name: str | None = None
        self.spouse_phone: str | None = None
        self.birthday: str | None = None
        self.wedding_anniversary: str | None = None

    @classmethod
    def load(cls, lead_id: str) -> "SellerMemory":
        memory = cls(lead_id)
        try:
            sb = get_supabase()
            result = sb.table("leads").select(
                "call_summaries,price_floor,hot_topics,rapport_openers,"
                "objections_raised,competitor_mentions,timeline_mentioned,"
                "motivation_level,best_callback_time,next_best_action,"
                "spouse_name,spouse_phone,birthday,wedding_anniversary"
            ).eq("id", lead_id).single().execute()

            if result.data:
                data = result.data
                memory.call_summaries = data.get("call_summaries") or []
                memory.price_floor = data.get("price_floor")
                memory.hot_topics = data.get("hot_topics") or []
                memory.rapport_openers = data.get("rapport_openers") or []
                memory.objections_raised = data.get("objections_raised") or []
                memory.competitor_mentions = data.get("competitor_mentions") or []
                memory.timeline_mentioned = data.get("timeline_mentioned")
                memory.motivation_level = data.get("motivation_level")
                memory.best_callback_time = data.get("best_callback_time")
                memory.next_best_action = data.get("next_best_action")
                memory.spouse_name = data.get("spouse_name")
                memory.spouse_phone = data.get("spouse_phone")
                memory.birthday = data.get("birthday")
                memory.wedding_anniversary = data.get("wedding_anniversary")
                logger.info("seller_memory loaded lead_id={}", lead_id)
        except Exception as e:
            logger.error("seller_memory load failed lead_id={} error={}", lead_id, str(e))
        return memory

    def save(self) -> None:
        try:
            sb = get_supabase()
            payload = {
                "call_summaries": self.call_summaries,
                "hot_topics": self.hot_topics,
                "rapport_openers": self.rapport_openers,
                "objections_raised": self.objections_raised,
                "competitor_mentions": self.competitor_mentions,
                "timeline_mentioned": self.timeline_mentioned,
                "motivation_level": self.motivation_level,
                "best_callback_time": self.best_callback_time,
                "next_best_action": self.next_best_action,
                "spouse_name": self.spouse_name,
                "spouse_phone": self.spouse_phone,
            }
            if self.price_floor is not None:
                payload["price_floor"] = self.price_floor
            if self.birthday is not None:
                payload["birthday"] = self.birthday
            if self.wedding_anniversary is not None:
                payload["wedding_anniversary"] = self.wedding_anniversary
            sb.table("leads").update(payload).eq("id", self.lead_id).execute()
            logger.info("seller_memory saved lead_id={}", self.lead_id)
        except Exception as e:
            logger.error("seller_memory save failed lead_id={} error={}", self.lead_id, str(e))

    def add_call_summary(self, summary: str) -> None:
        self.call_summaries.append(summary)
        if len(self.call_summaries) > 10:
            self.call_summaries = self.call_summaries[-10:]

    def to_prompt_context(self) -> str:
        if not self.call_summaries and not self.hot_topics:
            return ""

        parts = ["PREVIOUS CALL CONTEXT:"]
        if self.call_summaries:
            parts.append(f"Last call summary: {self.call_summaries[-1]}")
        if self.price_floor:
            dollar = self.price_floor // 100
            parts.append(f"Price floor: ${dollar:,}")
        if self.hot_topics:
            parts.append(f"Hot topics: {', '.join(self.hot_topics[-5:])}")
        if self.timeline_mentioned:
            parts.append(f"Their timeline: {self.timeline_mentioned}")
        if self.motivation_level:
            parts.append(f"Motivation: {self.motivation_level}/10")
        if self.best_callback_time:
            parts.append(f"Best time to call: {self.best_callback_time}")
        if self.next_best_action:
            parts.append(f"Notes: {self.next_best_action}")
        parts.append("Reference this naturally. Never say 'according to my notes.' Just remember like a real person would.")
        return "\n".join(parts)
