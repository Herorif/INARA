"""
Contextual greeting detection for INARA.

Matches transcribed user speech against greeting patterns and returns
context to inject into the Gemini session so INARA responds naturally.

Greeting patterns also specify optional routine triggers that tie into
the SchedulerAgent's routine system (Phase 5).
"""

from typing import Optional


# ---------------------------------------------------------------------------
# Greeting Patterns
# ---------------------------------------------------------------------------

GREETING_PATTERNS = {
    "good_morning": {
        "patterns": ["good morning", "morning inara"],
        "context": (
            "The user is greeting you with a good morning. Respond warmly, "
            "mention the time of day, and offer to brief them on their day "
            "(weather, schedule, reminders)."
        ),
        "routines": ["morning"],
    },
    "im_home": {
        "patterns": ["i'm home", "im home", "i am home"],
        "context": (
            "The user just arrived home. Welcome them warmly and offer to "
            "set up the house (lights on, comfortable temperature, etc.)."
        ),
        "routines": ["arrival"],
    },
    "goodnight": {
        "patterns": ["good night", "goodnight", "night inara"],
        "context": (
            "The user is going to bed. Wish them goodnight, offer to turn off "
            "lights, set night mode, and mention any reminders for tomorrow."
        ),
        "routines": ["bedtime"],
    },
    "leaving": {
        "patterns": ["i'm leaving", "im leaving", "heading out", "i'm going out"],
        "context": (
            "The user is leaving the house. Wish them well, offer to turn off "
            "lights and lock up. Mention anything they might need (weather, keys)."
        ),
        "routines": ["departure"],
    },
}


# ---------------------------------------------------------------------------
# Greeting Detector
# ---------------------------------------------------------------------------

class GreetingDetector:
    """
    Matches transcribed speech against greeting patterns.

    Usage:
        detector = GreetingDetector()
        result = detector.detect("Good morning INARA")
        if result:
            print(result["context"])     # Inject into Gemini session
            print(result["routines"])    # Trigger these routines
    """

    def __init__(self, patterns: Optional[dict] = None):
        self._patterns = patterns or GREETING_PATTERNS

    def detect(self, text: str) -> Optional[dict]:
        """
        Check if the transcribed text matches a greeting pattern.

        Returns a dict with 'name', 'context', and 'routines' if matched,
        or None if no greeting was detected.
        """
        lower = text.lower().strip()

        for name, entry in self._patterns.items():
            for pattern in entry["patterns"]:
                if pattern in lower:
                    return {
                        "name": name,
                        "context": entry["context"],
                        "routines": entry.get("routines", []),
                    }

        return None
