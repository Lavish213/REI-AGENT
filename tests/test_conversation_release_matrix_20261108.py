import pytest

from backend.voice.conversation_policy import plan_turn
from backend.voice.processors.context_tracker import CallContext


CASES = [
    ("stop", ["Stop calling me", "Do not call again", "Remove me", "No me llames"], {}),
    ("identity", ["Are you an AI?", "Are you a robot?", "Is this automated?", "Eres una IA?"], {}),
    ("wrong_person", ["Wrong number", "You have the wrong person", "No one here by that name", "This is a wrong number"], {}),
    ("human", ["Let me speak to a human", "Transfer me", "I want a real person", "Can I talk to someone?"], {}),
    ("wait", ["Hold on", "Give me one second", "Let me finish", "Un momento"], {}),
    ("alternative", ["I am not interested in a walkthrough", "No visit", "I do not want an appointment", "Not interested in the walkthrough"], {}),
    ("decline", ["Not interested", "I am not selling", "I do not want to sell", "No me interesa"], {}),
    ("callback", ["I am busy right now", "Call me tomorrow", "I cannot talk", "I am driving"], {}),
    ("goodbye", ["Goodbye", "I have to go", "Take care", "Adios"], {}),
    ("repair", ["Say that again", "I cannot hear you", "Bad connection", "Mas despacio"], {}),
    ("correction", ["Actually I said two hundred", "That is wrong", "No, I said next month", "I meant Friday"], {}),
    ("answer", ["What happens next?", "How does this work?", "Tell me about the process", "Why do you need that?"], {}),
    ("space", ["I need time to think", "I need to talk to my wife", "I am not ready", "There is no rush"], {}),
    ("contact", ["I am the tenant", "My brother owns it", "I do not own the house", "The owner is not here"], {"ownership_denied": True}),
    ("empathy", ["My husband passed away", "This is overwhelming", "I am grieving", "I am really distressed"], {"emotional_state": "GRIEVING"}),
    ("saved_next_step", ["Okay", "Sounds good", "That works", "Fine"], {"appointment_set": True}),
    ("contact", ["Hello", "This is me", "Speaking", "Yes this is the owner"], {}),
    ("interest", ["Maybe", "I am listening", "Go ahead", "You have a minute"], {"owner_confirmed": True}),
    ("motivation", ["Yes", "I might sell", "Possibly", "I am open to it"], {"owner_confirmed": True, "intent_locked": True}),
    ("timeline", ["The roof leaks", "It needs work", "The kitchen is old", "It is vacant"], {"owner_confirmed": True, "intent_locked": True, "motivation_known": True}),
    ("condition", ["Within a month", "Next week", "This month", "This summer"], {"owner_confirmed": True, "intent_locked": True, "motivation_known": True, "timeline_mentioned": "next month"}),
    ("walkthrough", ["The roof needs work", "It is in good shape", "The kitchen is dated", "It needs cosmetic repairs"], {"owner_confirmed": True, "intent_locked": True, "motivation_known": True, "timeline_mentioned": "next month", "condition_known": True}),
    ("space", ["Maybe", "It depends", "I am not sure", "Possibly"], {"_walkthrough_asked": True}),
    ("schedule", ["A walkthrough is fine", "You can come by", "Let us schedule it", "That visit works"], {"owner_confirmed": True, "intent_locked": True, "motivation_known": True, "timeline_mentioned": "next month", "condition_known": True, "pre_close_done": True}),
    ("saved_next_step", ["Okay", "I have it", "That callback works", "We are set"], {"callback_set": True}),
]


MATRIX = [
    pytest.param(text, expected, state, id=f"{expected}-{index}-{variant}")
    for index, (expected, texts, state) in enumerate(CASES)
    for variant, text in enumerate(texts)
]


@pytest.mark.parametrize("text,expected,state", MATRIX)
def test_release_conversation_matrix(text, expected, state):
    ctx = CallContext(**state)
    assert plan_turn(ctx, text).goal == expected
