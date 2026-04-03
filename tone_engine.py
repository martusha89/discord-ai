import re

# Weighted patterns — each entry is (compiled_regex, tone, weight)
# Higher weight = stronger signal. Word boundaries prevent false matches.
_PATTERNS = []

_RULES = {
    "spiral": [
        (r"\bburnout\b", 3),
        (r"\boverwhelmed\b", 3),
        (r"\bworthless\b", 4),
        (r"\bshut\s*down\b", 3),
        (r"\bcan'?t\s+cope\b", 4),
        (r"\bfalling\s+apart\b", 4),
        (r"\bgive\s*up\b", 3),
        (r"\btoo\s+much\b", 2),
        (r"\bdone\b", 1),  # low weight — ambiguous
        (r"\bfuck\s+it\b", 2),
        (r"\btired\b", 1),
    ],
    "sad": [
        (r"\bsad\b", 3),
        (r"\bdepressed\b", 4),
        (r"\bhopeless\b", 4),
        (r"\bempty\b", 2),
        (r"\blonely\b", 3),
        (r"\bmissing\s+(you|them|her|him)\b", 3),
        (r"\bcrying\b", 3),
        (r"\blost\b", 1),  # low weight — ambiguous
    ],
    "play": [
        (r"\blol\b", 2),
        (r"\blmao\b", 2),
        (r"\bhaha\b", 2),
        (r"\bflirt\b", 3),
        (r"\bkiss\b", 3),
        (r"\bwink\b", 2),
        (r"\btease\b", 2),
        (r"\b;[\)\)]\b", 2),
        (r"[😏😘🥵😈]", 3),
    ],
    "fire": [
        (r"\bfuck\s+you\b", 4),
        (r"\bliar\b", 3),
        (r"\bmanipulat", 3),
        (r"\bgaslight", 4),
        (r"\brage\b", 3),
        (r"\bbullshit\b", 3),
        (r"\bpissed\b", 3),
        (r"\bangry\b", 2),
        (r"\bhate\s+(this|you|it)\b", 3),
    ],
    "support": [
        (r"\bconfused\b", 2),
        (r"\banxious\b", 3),
        (r"\bpanic\b", 3),
        (r"\bwhat\s+if\b", 2),
        (r"\bscared\b", 3),
        (r"\bdon'?t\s+know\s+what\b", 3),
        (r"\bstruggling\b", 2),
        (r"\bworried\b", 2),
    ],
}

# Compile all patterns once at import time
for tone, rules in _RULES.items():
    for pattern, weight in rules:
        _PATTERNS.append((re.compile(pattern, re.IGNORECASE), tone, weight))


def detect_tone(text):
    """Score text against tone patterns. Returns the highest-scoring tone, or 'neutral'."""
    scores = {}
    for regex, tone, weight in _PATTERNS:
        if regex.search(text):
            scores[tone] = scores.get(tone, 0) + weight

    if not scores:
        return "neutral"

    # Highest score wins. Ties go to the more intense tone.
    priority = ["spiral", "fire", "sad", "support", "play"]
    max_score = max(scores.values())
    for tone in priority:
        if scores.get(tone, 0) == max_score:
            return tone

    return max(scores, key=scores.get)
