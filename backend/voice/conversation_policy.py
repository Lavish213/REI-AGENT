from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


@dataclass(frozen=True)
class TurnPlan:
    goal: str
    guidance: str
    question_limit: int = 1

    def render(self) -> str:
        return f"RESPONSE PRIORITY: {self.goal}\n{self.guidance}\nAsk at most {self.question_limit} question(s). Zero questions is often appropriate."


def plan_turn(ctx, text: str) -> TurnPlan:
    lower = text.lower().replace("’", "'").strip()
    if getattr(ctx, "stop_requested", False) or re.search(r"\b(stop calling|do not call|don't call|remove me|no me llames)\b", lower):
        return TurnPlan("stop", "Honor the stop request with the tool, acknowledge briefly, and end. No sales questions.", 0)
    if re.search(r"\b(wrong number|wrong person|no one (?:here )?(?:by|with) that name|you have the wrong)\b", lower):
        return TurnPlan("wrong_person", "Apologize briefly and end. Do not ask for the correct number or pitch this person.", 0)
    if re.search(r"\b(speak to (?:a human|a real person)|talk to (?:a person|someone|a human|a real person)|transfer me)\b", lower):
        return TurnPlan("human", "Attempt the permitted transfer now. Explain a failed transfer honestly; offer a human callback without restarting discovery.", 0)
    if re.search(r"\b(are you (?:an? )?(?:ai|robot|bot|human|real)|is this (?:automated|a recording)|eres (?:una? )?(?:ia|robot))\b", lower):
        return TurnPlan("identity", "Say directly that Sophia is an AI assistant for San Joaquin House Buyers. Do not give a biography or dodge the question.", 0)
    if re.search(r"\b(hold on|hang on|one (?:second|sec|moment)|give me a (?:second|minute)|let me finish|don't interrupt|espera|un momento)\b", lower):
        return TurnPlan("wait", "Acknowledge briefly, then let the caller continue. Do not ask a question, offer a time, or advance a sales stage.", 0)
    conditional_sale = bool(re.search(r"\bnot selling\s+(?:until|before|unless|yet)\b", lower))
    if not conditional_sale and re.search(r"\b(not interested|not selling|don't want to sell|never selling|no quiero vender|no me interesa)\b", lower):
        return TurnPlan("decline", "Respect the decision and close briefly. Do not treat it as an objection to overcome or ask for referrals.", 0)
    if re.search(r"\b(can't talk|cannot talk|at work|i'm driving|busy right now|call me (?:back|later)|not a good time|no puedo hablar)\b", lower):
        return TurnPlan("callback", "Respect their time. Ask only for a specific callback date/time if they want another call. Do not continue qualification or pretend a callback was saved.")
    if re.search(r"\b(goodbye|gotta go|have to go|bye|take care|adios|adi[oó]s)\b", lower):
        return TurnPlan("goodbye", "Respect the goodbye. End warmly without another question or an invented next step.", 0)
    if re.search(r"\b(slow down|say that again|repeat that|didn't (?:hear|catch)|what did you say|no te escuch)\b", lower):
        return TurnPlan("repair", "Repeat or simplify only the last relevant answer, using shorter words. Do not introduce a new topic or ask another discovery question.", 0)
    if re.search(r"\b(actually|correction|i meant|not .{0,25}but|that's (?:not right|wrong)|no,? (?:it's|i said)|en realidad)\b", lower):
        return TurnPlan("correction", "Acknowledge the correction once. Use the latest stated value, not old memory. Clarify only if the replacement is ambiguous; do not confirm a changed appointment before a successful tool result.")
    if "?" in text or re.search(r"^(?:wait[, ]+)?(?:why|how|what|who|where|can you|do you|are you|is there|is this|will you|would you|cu[aá]nto|c[oó]mo|por qu[eé])\b", lower):
        return TurnPlan("answer", "Answer the caller's actual question first using verified facts. No invented price, timeline, company history, or data-source explanation. If unknown, say so. Do not append an unrelated discovery or booking question.", 0)
    if conditional_sale:
        return TurnPlan("space", "Respect the seller's timing or condition. Do not treat conditional willingness as a permanent refusal or an agreed visit. Ask at most one relevant clarification.")
    if re.search(r"\b(i (?:just )?need (?:time|to think)|think about it|talk to my (?:wife|husband|spouse|partner)|check with (?:family|my)|not ready|no rush)\b", lower):
        return TurnPlan("space", "Respect the need for time or another decision-maker. Do not lean in, manufacture urgency, or suggest they agreed. Offer an optional next step rather than demanding one.", 0)
    if getattr(ctx, "_walkthrough_asked", False) and re.search(r"\b(maybe|not sure|possibly|depends|if|but)\b", lower):
        return TurnPlan("space", "They have not accepted the walkthrough. Respect uncertainty, answer any concern, and do not start scheduling or repeat the same pitch.", 0)
    if getattr(ctx, "emotional_state", "NEUTRAL") in {"GRIEVING", "DISTRESSED", "OVERWHELMED"}:
        return TurnPlan("empathy", "Acknowledge what they actually shared in one grounded sentence. Do not claim shared personal experience, force optimism, or pivot immediately into condition/price questions.", 0)
    if getattr(ctx, "appointment_set", False) or getattr(ctx, "callback_set", False):
        return TurnPlan("saved_next_step", "Read back only the next step the tool actually saved. Answer any remaining question; do not restart discovery.", 0)
    if getattr(ctx, "pre_close_done", False):
        return TurnPlan("schedule", "They accepted discussing a walkthrough. Ask for one missing scheduling detail. Read back date, Pacific time and address, obtain confirmation, then use the reservation tool.")
    if not getattr(ctx, "owner_confirmed", False) and not getattr(ctx, "address_known", False):
        return TurnPlan("contact", "Confirm the intended person or property with one simple question. A yes answers the last question only; never infer unrelated ownership or scheduling consent.")
    if not getattr(ctx, "intent_locked", False) and not getattr(ctx, "motivation_signals", []):
        return TurnPlan("interest", "Ask whether discussing the property would be useful. Do not assume they want to sell or already agreed to a visit.")
    if not getattr(ctx, "motivation_signals", []):
        return TurnPlan("motivation", "React to their last answer, then ask what is prompting them to consider selling. Do not ask about motivation twice after they explain it.")
    if not getattr(ctx, "timeline_mentioned", None):
        return TurnPlan("timeline", "Use what they already shared. Ask one simple question about their preferred timing; no pressure or invented deadline.")
    if not getattr(ctx, "condition_known", False) and not getattr(ctx, "property_issues", []):
        return TurnPlan("condition", "Ask one broad question about the property's condition. A house in good condition is a valid answer; do not insist on finding defects.")
    return TurnPlan("walkthrough", "Briefly connect the next step to what the seller told you. Ask whether a no-obligation walkthrough would be useful. Do not claim a visit is agreed or booked.")


class ConversationTurnReset(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TranscriptionFrame) and frame.text.strip():
            self._ctx.runtime_instruction = None
            self._ctx.response_guidance = ""
        await self.push_frame(frame, direction)


class ConversationPolicyProcessor(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TranscriptionFrame) and frame.text.strip():
            plan = plan_turn(self._ctx, frame.text)
            self._ctx.response_goal = plan.goal
            self._ctx.response_guidance = plan.render()
            facts = {"motivation": self._ctx.motivation_signals, "timeline": self._ctx.timeline_mentioned, "condition_answered": self._ctx.condition_known, "issues": self._ctx.property_issues, "seller_asking_price_cents": self._ctx.last_price_mentioned}
            self._ctx.response_guidance += "\nAlready collected; do not ask again: " + json.dumps(facts, ensure_ascii=False)
        await self.push_frame(frame, direction)


def remember_assistant_turn(ctx, text: str) -> None:
    questions = re.findall(r"([^.!?]+\?)", text)
    if not questions:
        return
    question = questions[-1].lower()
    ctx._walkthrough_asked = False
    ctx.last_question_topic = "other"
    ctx.awaiting_owner_confirmation = bool(re.search(r"speaking with|property owner|own (?:this|the) (?:house|property)", question))
    if ctx.awaiting_owner_confirmation:
        ctx.last_question_topic = "owner"
    elif re.search(r"asking|price|number in mind|want for|looking to get", question):
        ctx.last_question_topic = "price"
    elif re.search(r"mortgage|owe|loan", question):
        ctx.last_question_topic = "mortgage"
    elif re.search(r"walkthrough|come (?:take|have) a look|come (?:by|over)|come out", question):
        ctx.last_question_topic = "walkthrough"
        ctx._walkthrough_asked = True
    elif re.search(r"condition|repairs|shape", question):
        ctx.last_question_topic = "condition"
    elif re.search(r"timing|timeline|how soon|when.*sell", question):
        ctx.last_question_topic = "timeline"
