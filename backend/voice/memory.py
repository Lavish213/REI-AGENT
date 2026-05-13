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
        has_data = any([
            self.call_summaries, self.hot_topics, self.objections_raised,
            self.price_floor, self.timeline_mentioned, self.motivation_level,
            self.best_callback_time, self.next_best_action, self.competitor_mentions,
            self.spouse_name,
        ])
        if not has_data:
            return ""

        call_count = len(self.call_summaries)
        parts = [f"SELLER MEMORY ({call_count} prior call{'s' if call_count != 1 else ''}):"]

        # Multi-call arc — most recent first, max 3
        if self.call_summaries:
            recent = self.call_summaries[-3:]
            if len(recent) == 1:
                parts.append(f"Last call: {recent[-1]}")
            else:
                parts.append(f"Most recent: {recent[-1]}")
                parts.append(f"Previous: {recent[-2]}")

        # Price floor — critical negotiation context
        if self.price_floor:
            dollar = self.price_floor // 100
            parts.append(f"Price floor they mentioned: ${dollar:,} — don't go below this without Alanzo")

        # Objections — Sophia should anticipate these
        if self.objections_raised:
            recent_obj = self.objections_raised[-4:]
            parts.append(f"Objections they've raised: {'; '.join(recent_obj)}")

        # Competitor mentions
        if self.competitor_mentions:
            parts.append(f"Other buyers they've talked to: {', '.join(self.competitor_mentions[-3:])}")

        # Timeline
        if self.timeline_mentioned:
            parts.append(f"Their timeline: {self.timeline_mentioned}")

        # Motivation
        if self.motivation_level:
            parts.append(f"Motivation level: {self.motivation_level}/10")

        # Hot topics — things they care about
        if self.hot_topics:
            parts.append(f"Topics they care about: {', '.join(self.hot_topics[-5:])}")

        # Personal details — rapport building
        if self.spouse_name:
            parts.append(f"Spouse/partner: {self.spouse_name} — reference naturally if relevant")

        # Callback preference
        if self.best_callback_time:
            parts.append(f"Best time to reach them: {self.best_callback_time}")

        # Next action
        if self.next_best_action:
            parts.append(f"Operator note: {self.next_best_action}")

        parts.append(
            "\nUse this memory naturally. Sound like you remember them personally. "
            "Never say 'according to my records' or 'our last call notes.' "
            "Reference it like: 'Wasn't repairs the main thing you were worried about?' "
            "or 'You mentioned your timeline was pretty soon, right?'"
        )
        return "\n".join(parts)

    def update_from_intel(self, intel: dict) -> None:
        """
        Merge structured transcript intel into memory fields.
        Called after each call's transcript analysis completes.
        """
        if intel.get("objections"):
            for obj in intel["objections"]:
                if obj and obj not in self.objections_raised:
                    self.objections_raised.append(obj)
            if len(self.objections_raised) > 15:
                self.objections_raised = self.objections_raised[-15:]

        if intel.get("hot_topics"):
            for topic in intel["hot_topics"]:
                if topic and topic not in self.hot_topics:
                    self.hot_topics.append(topic)
            if len(self.hot_topics) > 15:
                self.hot_topics = self.hot_topics[-15:]

        if intel.get("competitor_mentions"):
            for comp in intel["competitor_mentions"]:
                if comp and comp not in self.competitor_mentions:
                    self.competitor_mentions.append(comp)

        if intel.get("timeline_mentioned") and not self.timeline_mentioned:
            self.timeline_mentioned = intel["timeline_mentioned"]

        if intel.get("motivation_level") and intel["motivation_level"] > 0:
            self.motivation_level = intel["motivation_level"]

        if intel.get("price_floor") and (
            self.price_floor is None or intel["price_floor"] < self.price_floor
        ):
            self.price_floor = intel["price_floor"]
