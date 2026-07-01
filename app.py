"""
app.py — Provenance Guard Flask API (complete — all milestones)

Endpoints:
  POST /submit    — content attribution analysis (rate limited)
  POST /appeal    — creator appeal submission
  GET  /log       — structured audit log viewer
  GET  /dashboard — analytics dashboard (stretch)
  GET  /          — health check
"""

import uuid
import logging
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from signals import get_llm_score, get_stylometric_score, combine_scores, _split_words
from labels import get_label
import audit_log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Rate limiter ──────────────────────────────────────────────────────────────
# 10 per minute protects against flooding scripts.
# 100 per day prevents overnight API exhaustion.
# See planning.md ## Rate Limiting for full reasoning.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        "error": "rate_limit_exceeded",
        "message": (
            "You have exceeded the submission rate limit. "
            "Limit: 10 requests per minute, 100 per day. "
            "Please wait before submitting again."
        ),
        "retry_after": "60 seconds",
    }), 429


# ── POST /submit ──────────────────────────────────────────────────────────────

@app.route("/submit", methods=["POST"])
@limiter.limit("100 per day")
@limiter.limit("10 per minute")
def submit():
    """
    Accept text content for attribution analysis.

    Request JSON:
        {
            "text":       str  (required) — the content to analyze
            "creator_id": str  (optional) — identifier for the creator
        }

    Response JSON:
        {
            "content_id":         str,
            "attribution":        str,   # "likely_human" | "uncertain" | "likely_ai"
            "confidence":         float, # 0.0–1.0 combined confidence score
            "confidence_label":   str,   # "high" | "medium" | "low"
            "llm_score":          float, # Signal 1 raw output
            "llm_reasoning":      str,   # one-sentence LLM explanation
            "stylometric_score":  float, # Signal 2 raw output
            "short_text_warning": bool,  # true if text < 100 words
            "label":              str,   # transparency label shown to users
        }
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    creator_id = data.get("creator_id", "anonymous")

    if not text:
        return jsonify({
            "error": "validation_error",
            "message": "text field is required and cannot be empty.",
        }), 400

    content_id = str(uuid.uuid4())

    # ── Signal 1: LLM semantic analysis ──────────────────────────────────────
    llm_result = get_llm_score(text)
    llm_score = llm_result["score"]
    llm_reasoning = llm_result["reasoning"]

    # ── Signal 2: Stylometric heuristics ─────────────────────────────────────
    style_result = get_stylometric_score(text)
    stylometric_score = style_result["score"]
    stylometric_details = style_result["details"]

    # ── Combine signals into confidence score + category ──────────────────────
    word_count = len(_split_words(text))
    combined = combine_scores(llm_score, stylometric_score, word_count)
    confidence = combined["confidence"]
    attribution = combined["attribution"]
    confidence_label = combined["confidence_label"]
    short_text_warning = combined["short_text_warning"]

    # ── Transparency label ────────────────────────────────────────────────────
    label_text = get_label(confidence, attribution, short_text_warning)

    # ── Audit log ─────────────────────────────────────────────────────────────
    audit_log.log_submission(
        content_id=content_id,
        creator_id=creator_id,
        text_preview=text,
        attribution=attribution,
        confidence=confidence,
        confidence_label=confidence_label,
        llm_score=llm_score,
        llm_reasoning=llm_reasoning,
        stylometric_score=stylometric_score,
        stylometric_details=stylometric_details,
        label_text=label_text,
        short_text_warning=short_text_warning,
    )

    logger.info(
        f"[SUBMIT] content_id={content_id} creator={creator_id} "
        f"attribution={attribution} confidence={confidence}"
    )

    return jsonify({
        "content_id":         content_id,
        "attribution":        attribution,
        "confidence":         confidence,
        "confidence_label":   confidence_label,
        "llm_score":          round(llm_score, 4),
        "llm_reasoning":      llm_reasoning,
        "stylometric_score":  stylometric_score,
        "short_text_warning": short_text_warning,
        "label":              label_text,
    })


# ── POST /appeal ──────────────────────────────────────────────────────────────

@app.route("/appeal", methods=["POST"])
def appeal():
    """
    Submit a creator appeal contesting an attribution result.

    Request JSON:
        {
            "content_id":        str  (required) — from a prior /submit response
            "creator_reasoning": str  (required) — why the creator believes
                                                   the classification is wrong
        }

    Response JSON:
        {
            "status":     "appeal_received",
            "content_id": str,
            "message":    str
        }
    """
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id", "").strip()
    creator_reasoning = data.get("creator_reasoning", "").strip()

    if not content_id:
        return jsonify({
            "error": "validation_error",
            "message": "content_id is required.",
        }), 400

    if not creator_reasoning:
        return jsonify({
            "error": "validation_error",
            "message": "creator_reasoning is required. Please explain why you believe this classification is incorrect.",
        }), 400

    # Verify the content_id exists
    original = audit_log.find_submission(content_id)
    if original is None:
        return jsonify({
            "error": "not_found",
            "message": f"No submission found with content_id '{content_id}'. "
                       "Check the ID from your original /submit response.",
        }), 404

    # Log the appeal + update status to "under_review"
    appeal_entry = audit_log.log_appeal(content_id, creator_reasoning)

    logger.info(f"[APPEAL] content_id={content_id} status=under_review")

    return jsonify({
        "status":     "appeal_received",
        "content_id": content_id,
        "message": (
            "Your appeal has been received and logged. A human reviewer will examine "
            "your content, the original signal scores, and your reasoning within 48 hours. "
            "You can check the status using GET /log?content_id=" + content_id
        ),
    })


# ── GET /log ──────────────────────────────────────────────────────────────────

@app.route("/log", methods=["GET"])
def get_log():
    """
    Return structured audit log entries, most recent first.

    Query params:
        limit      (int, optional): max entries to return. Default 50.
        content_id (str, optional): filter to a specific content_id.
    """
    limit = request.args.get("limit", default=50, type=int)
    content_id = request.args.get("content_id", default=None, type=str)

    entries = audit_log.get_entries(limit=limit, content_id=content_id)
    return jsonify({"entries": entries, "count": len(entries)})


# ── GET /dashboard ────────────────────────────────────────────────────────────

@app.route("/dashboard", methods=["GET"])
def dashboard():
    """
    Analytics dashboard (stretch feature).

    Returns:
        {
            "total_submissions":     int,
            "attribution_breakdown": {"likely_ai": int, "uncertain": int, "likely_human": int},
            "ai_ratio":              float,
            "total_appeals":         int,
            "appeal_rate":           float,   # appeals / submissions
            "avg_confidence":        float,
            "short_text_submissions": int,
        }
    """
    all_entries = audit_log.get_entries()

    submissions = [e for e in all_entries if e.get("entry_type") == "submission"]
    appeals     = [e for e in all_entries if e.get("entry_type") == "appeal"]

    total_submissions = len(submissions)
    total_appeals     = len(appeals)

    breakdown = {"likely_ai": 0, "uncertain": 0, "likely_human": 0}
    confidences = []
    short_text_count = 0

    for s in submissions:
        attr = s.get("attribution", "uncertain")
        if attr in breakdown:
            breakdown[attr] += 1
        if s.get("confidence") is not None:
            confidences.append(s["confidence"])
        if s.get("short_text_warning"):
            short_text_count += 1

    ai_ratio    = round(breakdown["likely_ai"] / total_submissions, 4) if total_submissions else 0
    appeal_rate = round(total_appeals / total_submissions, 4) if total_submissions else 0
    avg_conf    = round(sum(confidences) / len(confidences), 4) if confidences else 0

    return jsonify({
        "total_submissions":      total_submissions,
        "attribution_breakdown":  breakdown,
        "ai_ratio":               ai_ratio,
        "total_appeals":          total_appeals,
        "appeal_rate":            appeal_rate,
        "avg_confidence":         avg_conf,
        "short_text_submissions": short_text_count,
    })


# ── GET / ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service":   "Provenance Guard",
        "version":   "1.0.0",
        "status":    "running",
        "endpoints": {
            "POST /submit":    "Submit content for attribution analysis",
            "POST /appeal":    "Appeal a classification result",
            "GET  /log":       "View structured audit log",
            "GET  /dashboard": "View analytics dashboard (stretch)",
        },
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)