"""
labels.py — Transparency label generation for Provenance Guard.

Implements the three label variants defined in planning.md Section 3.
The label text is what would be shown to a reader on the platform.

Label variants:
  - likely_ai    (confidence >= 0.80): "AI-generated content detected"
  - uncertain    (confidence 0.31–0.79): "Origin unclear"
  - likely_human (confidence < 0.31): "Appears human-written"

A short_text_warning forces the uncertain label regardless of the score,
because we cannot be confident about texts under 100 words.
"""


# ── Label text variants ───────────────────────────────────────────────────────
# Written out exactly as shown in planning.md Section 3.
# These are the strings returned in the API response and stored in the audit log.

LABEL_LIKELY_AI = (
    "⚠️ AI-generated content detected\n\n"
    "Our analysis strongly suggests this content was created with AI assistance. "
    "This does not prevent it from being shared, but it will be labeled for readers.\n\n"
    "If you wrote this yourself, you can submit an appeal and we will review it. "
    "Appeals are reviewed by a human within 48 hours."
)

LABEL_UNCERTAIN = (
    "ℹ️ Origin unclear\n\n"
    "Our analysis couldn't confidently determine whether this content was "
    "written by a person or created with AI assistance.\n\n"
    "It will be shared with this notice attached. If you are the human author, "
    "you can submit an appeal to have your work reviewed and the label updated."
)

LABEL_LIKELY_HUMAN = (
    "✅ Appears human-written\n\n"
    "Our analysis suggests this content was written by a person. "
    "No label will be shown to readers.\n\n"
    "Note: This is an automated assessment and may not be fully accurate."
)

# Short-text variant — same uncertain messaging but with an additional note
LABEL_SHORT_TEXT = (
    "ℹ️ Origin unclear\n\n"
    "Our analysis couldn't confidently determine whether this content was "
    "written by a person or created with AI assistance.\n\n"
    "Note: This content is quite short, which limits the accuracy of our analysis. "
    "It will be shared with this notice attached. If you are the human author, "
    "you can submit an appeal to have your work reviewed and the label updated."
)


def get_label(confidence: float, attribution: str, short_text_warning: bool = False) -> str:
    """
    Return the transparency label text for a given confidence score and
    attribution category.

    Args:
        confidence (float): The combined confidence score, 0.0-1.0.
        attribution (str): "likely_human" | "uncertain" | "likely_ai"
        short_text_warning (bool): True if text was under 100 words.

    Returns:
        str: The exact label text to show the user.

    Logic (mirrors planning.md Section 2 thresholds):
        - short_text_warning=True  → always returns LABEL_SHORT_TEXT
        - attribution == "likely_ai"   (score >= 0.80) → LABEL_LIKELY_AI
        - attribution == "uncertain"   (0.31-0.79)     → LABEL_UNCERTAIN
        - attribution == "likely_human" (score < 0.31) → LABEL_LIKELY_HUMAN
    """
    if short_text_warning:
        return LABEL_SHORT_TEXT

    if attribution == "likely_ai":
        return LABEL_LIKELY_AI
    elif attribution == "uncertain":
        return LABEL_UNCERTAIN
    else:
        return LABEL_LIKELY_HUMAN


def get_label_summary(attribution: str, short_text_warning: bool = False) -> str:
    """
    Return a short single-line summary of the label for logging/display.
    Used in the audit log label_text field (truncated version).
    """
    if short_text_warning:
        return "ℹ️ Origin unclear (short text — limited analysis)"
    labels = {
        "likely_ai":    "⚠️ AI-generated content detected",
        "uncertain":    "ℹ️ Origin unclear",
        "likely_human": "✅ Appears human-written",
    }
    return labels.get(attribution, "ℹ️ Origin unclear")