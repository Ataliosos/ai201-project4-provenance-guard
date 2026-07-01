"""
audit_log.py — Structured audit log for Provenance Guard.

Every submission and appeal is recorded as a JSON entry in audit_log.json.
The log is append-only; status updates happen in-place on the matching entry.
"""

import json
import os
import logging
from datetime import datetime, timezone
from threading import Lock

logger = logging.getLogger(__name__)

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_log.json")
_lock = Lock()  # protects concurrent read-modify-write of the log file


def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _read_log() -> list[dict]:
    """Read the full log from disk. Returns [] if the file doesn't exist yet."""
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to read audit log: {e}")
        return []


def _write_log(entries: list[dict]) -> None:
    """Write the full log back to disk."""
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def log_submission(
    content_id: str,
    creator_id: str,
    text_preview: str,
    attribution: str,
    confidence: float,
    confidence_label: str,
    llm_score: float,
    llm_reasoning: str,
    stylometric_score: float | None = None,
    stylometric_details: dict | None = None,
    label_text: str = "",
    short_text_warning: bool = False,
) -> dict:
    """
    Append a structured submission entry to the audit log.

    Returns the entry that was written.
    """
    entry = {
        "entry_type": "submission",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": _now_iso(),
        "text_preview": text_preview[:120],
        "attribution": attribution,
        "confidence": round(confidence, 4),
        "confidence_label": confidence_label,
        "llm_score": round(llm_score, 4),
        "llm_reasoning": llm_reasoning,
        "stylometric_score": round(stylometric_score, 4) if stylometric_score is not None else None,
        "stylometric_details": stylometric_details,
        "label_text": label_text,
        "short_text_warning": short_text_warning,
        "status": "classified",
    }

    with _lock:
        entries = _read_log()
        entries.append(entry)
        _write_log(entries)

    return entry


def log_appeal(content_id: str, creator_reasoning: str) -> dict | None:
    """
    Append an appeal entry and update the matching submission's status
    to "under_review".

    Returns the appeal entry, or None if content_id was not found.
    """
    with _lock:
        entries = _read_log()

        # Find the original submission
        original = None
        for entry in entries:
            if entry.get("content_id") == content_id and entry.get("entry_type") == "submission":
                original = entry
                break

        if original is None:
            return None

        # Update the original's status in place
        original["status"] = "under_review"

        appeal_entry = {
            "entry_type": "appeal",
            "content_id": content_id,
            "timestamp": _now_iso(),
            "creator_reasoning": creator_reasoning,
            "original_attribution": original.get("attribution"),
            "original_confidence": original.get("confidence"),
            "status": "under_review",
        }
        entries.append(appeal_entry)
        _write_log(entries)

    return appeal_entry


def get_entries(limit: int | None = None, content_id: str | None = None) -> list[dict]:
    """
    Retrieve audit log entries, most recent first.

    Args:
        limit (int | None): max number of entries to return. None = all.
        content_id (str | None): filter to entries matching this content_id.

    Returns:
        list[dict]: log entries.
    """
    entries = _read_log()
    if content_id:
        entries = [e for e in entries if e.get("content_id") == content_id]
    entries = list(reversed(entries))  # most recent first
    if limit:
        entries = entries[:limit]
    return entries


def find_submission(content_id: str) -> dict | None:
    """Find the original submission entry for a given content_id."""
    entries = _read_log()
    for entry in entries:
        if entry.get("content_id") == content_id and entry.get("entry_type") == "submission":
            return entry
    return None