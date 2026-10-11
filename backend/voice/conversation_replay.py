from __future__ import annotations

import json

from backend.voice.conversation_policy import plan_turn, remember_assistant_turn
from backend.voice.emotional_state_engine import EmotionalStateEngine
from backend.voice.objective_engine import ObjectiveEngine
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.resistance_tracker import ResistanceTracker


SCENARIOS = {
    "relocation": [
        (5, "Am I speaking with Alex?", "I own the house and want to sell because I'm relocating", "timeline"),
        (15, "What timing works for you?", "Next week ideally", "condition"),
        (25, "How is the house's condition?", "Good condition, no repairs needed", "walkthrough"),
        (35, "Would a walkthrough be useful?", "Are there any fees?", "answer"),
        (45, "The team can explain any terms before you decide.", "Yeah, a walkthrough sounds good", "schedule"),
        (55, "Which date would work?", "Tuesday, but which times do you have?", "answer"),
    ],
    "busy": [
        (5, "Am I speaking with Alex?", "I'm at work", "callback"),
        (15, "Would another time work better?", "Call me back tomorrow", "callback"),
        (25, "What Pacific time tomorrow works?", "Hold on one second", "wait"),
        (35, "Take your time.", "Actually make that Thursday at three", "correction"),
        (45, "Which Thursday do you mean?", "Why do you need the exact date?", "answer"),
        (55, "So the callback can be saved for the right day.", "Okay, I have to go now", "goodbye"),
    ],
    "grief": [
        (5, "What prompted your call?", "My dad passed away", "empathy"),
        (15, "I'm sorry about your dad.", "I need time to think", "space"),
        (25, "You can take your time.", "Can I talk to a real person?", "human"),
        (35, "I can try connecting you with the team.", "Wait, are you AI?", "identity"),
        (45, "Yes, I'm an AI assistant for San Joaquin House Buyers.", "Let me finish before you ask anything", "wait"),
        (55, "Go ahead.", "I don't want to sell", "decline"),
    ],
    "corrections": [
        (5, "What price are you asking?", "I want $220k", "contact"),
        (15, "Is it your house?", "It's my house and I need to sell because I'm moving", "timeline"),
        (25, "What timing works?", "Next week, but actually I'm asking $210k now", "correction"),
        (35, "Got it, your asking price is $210,000.", "The roof leaks", "walkthrough"),
        (45, "Would a walkthrough be useful?", "Actually the roof is fine now", "correction"),
        (55, "Thanks for correcting that.", "Can you offer $210k?", "answer"),
    ],
    "identity_repeat": [
        (5, "Am I speaking with Alex?", "Are you a robot?", "identity"),
        (15, "Yes, I'm an AI assistant.", "How did you get my number?", "answer"),
        (25, "I don't have the verified source available.", "Are you AI though?", "identity"),
        (35, "Yes, I'm an AI assistant for San Joaquin House Buyers.", "Can I speak to a human?", "human"),
        (45, "I can try connecting you.", "Hold on", "wait"),
        (55, "Take your time.", "Not interested", "decline"),
    ],
    "short_answers": [
        (5, "What prompted you to consider selling?", "Moving", "contact"),
        (15, "Is it your house?", "My house", "timeline"),
        (25, "What timing works?", "Next week", "condition"),
        (35, "How is the house's condition?", "Good condition", "walkthrough"),
        (45, "Would a walkthrough help?", "Yes", "schedule"),
        (55, "Which date works?", "What times are available?", "answer"),
    ],
    "spanish": [
        (5, "Hola, soy Sophia, asistente automatizada.", "Eres una IA?", "identity"),
        (15, "Sí, soy una asistente automatizada.", "No puedo hablar", "callback"),
        (25, "Podemos acordar otro momento.", "Un momento", "wait"),
        (35, "Claro.", "En realidad prefiero otro día", "correction"),
        (45, "Podemos aclarar qué día te viene bien.", "No quiero vender", "decline"),
        (55, "Gracias por decírmelo.", "No me llames", "stop"),
    ],
    "conditional_interest": [
        (5, "Am I speaking with Alex?", "I own the house and am moving", "timeline"),
        (15, "What timing works for you?", "I'm not selling until next month", "space"),
        (25, "We can respect that timing.", "The house is in good condition", "walkthrough"),
        (35, "Would a walkthrough help?", "Maybe, I'm not sure", "space"),
        (45, "You can take your time.", "Yes but only if you pay my asking price", "space"),
        (55, "The team would need to review before any offer.", "Are you an AI?", "identity"),
    ],
    "question_scope": [
        (5, "Would a walkthrough help?", "How does that work?", "answer"),
        (15, "The team can explain the visit. Is this a good time?", "Yes", "contact"),
        (25, "Am I speaking with Alex?", "Are you a real person?", "identity"),
        (35, "I'm an AI assistant for San Joaquin House Buyers.", "Can I talk to a real person?", "human"),
        (45, "I can try connecting you with the team.", "Hold on a moment", "wait"),
        (55, "Go ahead.", "Have to go now", "goodbye"),
    ],
    "wrong_person": [
        (5, "Am I speaking with Alex?", "You have the wrong number", "wrong_person"),
    ],
    "audio_repair": [
        (5, "Am I speaking with Alex?", "Say that again", "repair"),
        (15, "I'm Sophia, an AI assistant with San Joaquin House Buyers.", "What did you say?", "repair"),
        (25, "Sophia, an AI assistant.", "Slow down", "repair"),
        (35, "Sure.", "Why are you calling?", "answer"),
        (45, "To see whether discussing the property would be useful.", "I need to talk to my wife", "space"),
        (55, "Take your time to discuss it.", "Not selling", "decline"),
    ],
}


def replay_scenario(name: str, variant: str = "original") -> dict:
    ctx = CallContext(is_outbound=True)
    tracker = ContextTrackerProcessor(ctx)
    emotions = EmotionalStateEngine(ctx)
    resistance = ResistanceTracker(ctx)
    turns = []
    for second, assistant, seller, expected in SCENARIOS[name]:
        if variant == "uppercase":
            seller = seller.upper()
        elif variant == "curly_apostrophes":
            seller = seller.replace("'", "’")
        ctx.runtime_instruction = None
        remember_assistant_turn(ctx, assistant)
        normalized = seller.replace("’", "'")
        ctx.turn_count += 1
        emotions._update_emotional_state(normalized)
        resistance._update_resistance(normalized)
        tracker._analyze(normalized)
        ctx.objective = ObjectiveEngine().decide(ctx)
        plan = plan_turn(ctx, seller)
        turns.append({"virtual_second": second, "assistant_fixture": assistant, "seller": seller, "response_goal": plan.goal, "expected_goal": expected, "question_limit": plan.question_limit, "guidance": plan.guidance, "objective": ctx.objective, "passed": plan.goal == expected})
        if plan.goal in {"stop", "decline", "wrong_person", "goodbye"}:
            break
    return {"scenario": name, "variant": variant, "window_seconds": 60, "mode": "deterministic_policy_replay_without_llm_or_audio", "turns": turns, "passed": all(turn["passed"] for turn in turns), "final_asking_price_cents": ctx.last_price_mentioned, "final_property_issues": ctx.property_issues, "appointment_booked": ctx.appointment_set}


def run_replays() -> dict:
    runs = [replay_scenario(name, variant) for name in SCENARIOS for variant in ("original", "uppercase", "curly_apostrophes")]
    return {"runs": len(runs), "passed": sum(run["passed"] for run in runs), "failed": sum(not run["passed"] for run in runs), "model_generated_conversations": 0, "results": runs}


if __name__ == "__main__":
    import sys
    result = run_replays()
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    raise SystemExit(1 if result["failed"] else 0)
