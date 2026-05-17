ACK_BANK = [
    "Okay.",
    "Gotcha.",
    "Alright.",
    "Makes sense.",
    "Yeah.",
    "Right.",
    "Okay, yeah.",
    "Got it.",
]

PIVOT_BANK: dict[str, list[str]] = {
    "GET_ADDRESS": [
        "What's the address?",
        "What's the property address?",
        "Where's the place at?",
        "Which property?",
    ],
    "GET_MOTIVATION": [
        "What's got you thinking about selling?",
        "What's going on with the place?",
        "Why sell now?",
        "What happened?",
    ],
    "GET_OCCUPANCY": [
        "Vacant right now?",
        "Anyone living there?",
        "Tenant occupied?",
        "You staying there now?",
    ],
    "GET_CONDITION": [
        "Need much work?",
        "How's the condition?",
        "Anything major going on with it?",
        "Updated at all?",
    ],
    "GET_TIMELINE": [
        "How soon you trying to move?",
        "Trying to sell pretty quick?",
        "What's the timeline look like?",
        "Sooner or later?",
    ],
    "TEST_PRICE": [
        "What do you need to walk away with?",
        "What's your number?",
        "What would make this work for you?",
    ],
    "BOOK_APPOINTMENT": [
        "Want us to come take a look?",
        "You around tomorrow?",
        "When can somebody stop by?",
        "Best time to see it?",
    ],
}

REDIRECT_BANK: list[str] = [
    "Got it. And the property?",
    "Makes sense. What's the situation with the house?",
    "Okay. How soon are you looking to move?",
    "Sure. What's the address on that?",
]

PUSHBACK_BANK: dict[str, list[str]] = {
    "price_too_high": [
        "Why not list it?",
        "At that price you'd probably list it.",
        "That's retail.",
        "We might not be the right fit then.",
    ],
    "price_demand": [
        "How'd you come up with that number?",
        "How'd you land on that number?",
        "Where'd you get that number from?",
        "Okay… where's that coming from?",
    ],
    "just_browsing": [
        "Okay. Are you serious about selling, or just seeing what's out there?",
        "Gotcha. So you're not really in a hurry?",
    ],
    "needs_info_first": [
        "Usually helps if I understand the property first.",
        "I can try, but I'd need to know the condition first.",
        "Gotcha. I'd just need a couple quick questions about it.",
    ],
    "not_interested": [
        "Totally. Before I let you go — never sell, or just not unless the number was strong?",
        "No problem. Would you ever consider it, or no?",
    ],
}
