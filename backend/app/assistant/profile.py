from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional
from app.core.db import conn
from app.core.security import audit
from app.assistant.schemas import (
    PersonalProfile,
    ProfileItem,
    WorkingHours,
)

# Reject API keys, passwords, and sensitive credentials
SENSITIVE_KEY_PATTERNS = [
    re.compile(r"(?i)(password|passwd|api[_-]?key|apikey|secret[_-]?key|access[_-]?key|jwt[_-]?token|auth[_-]?token)"),
]

SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z-_]{28,}"),
    re.compile(r"gsk_[a-zA-Z0-9]{20,}"),
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"(?i)\b(bearer\s+[a-zA-Z0-9_\-\.]{12,})"),
    re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret)\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
]


def screen_sensitive_data(key: str, value: Any) -> None:
    """Ensure sensitive credentials and secrets are never stored in the profile."""
    for kp in SENSITIVE_KEY_PATTERNS:
        if kp.search(key):
            audit("profile.rejected_secret", f"Attempted to store secret in profile key '{key}'")
            raise ValueError(f"Security error: Profile cannot store sensitive credentials or keys (key '{key}').")

    val_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    for vp in SENSITIVE_VALUE_PATTERNS:
        if vp.search(val_str):
            audit("profile.rejected_secret", f"Attempted to store secret in profile value for key '{key}'")
            raise ValueError(f"Security error: Profile cannot store API keys, passwords, or tokens (key '{key}').")


class ProfileManager:
    """
    Manages the user's structured Personal Assistant Profile.
    Strictly distinguishes confirmed facts from inferred preferences.
    Allows user corrections and prevents storing credentials.
    """

    DEFAULT_KEYS = {
        "preferences": {},
        "communication_style": "concise",
        "goals": [],
        "projects": [],
        "frequent_apps": ["VS Code", "Terminal", "Browser"],
        "working_hours": {"start_time": "09:00", "end_time": "18:00", "work_days": [0, 1, 2, 3, 4], "timezone": "local"},
        "routines": [],
        "priorities": ["Security and stability first", "Maintain backups", "Timely reminders"],
        "important_deadlines": [],
    }

    def __init__(self):
        pass

    def get_profile(self) -> PersonalProfile:
        """Retrieve the complete structured profile, aggregating confirmed and inferred items."""
        with conn() as c:
            rows = c.execute("SELECT * FROM assistant_profile ORDER BY category, key").fetchall()

        items: List[ProfileItem] = []
        raw_map: Dict[str, Any] = {}

        for r in rows:
            try:
                parsed_val = json.loads(r["value"])
            except Exception:
                parsed_val = r["value"]

            item = ProfileItem(
                key=r["key"],
                value=parsed_val,
                category=r["category"],
                is_confirmed=bool(r["is_confirmed"]),
                confidence=float(r["confidence"]),
                source=r["source"],
                updated_at=r["updated_at"],
            )
            items.append(item)
            raw_map[r["key"]] = parsed_val

        # Fill defaults if not yet customized
        pref = dict(self.DEFAULT_KEYS["preferences"])
        if isinstance(raw_map.get("preferences"), dict):
            pref.update(raw_map["preferences"])
        for it in items:
            if it.category == "preferences":
                pref[it.key] = it.value

        comm = raw_map.get("communication_style", self.DEFAULT_KEYS["communication_style"])
        goals = raw_map.get("goals", self.DEFAULT_KEYS["goals"])
        projects = raw_map.get("projects", self.DEFAULT_KEYS["projects"])
        apps = raw_map.get("frequent_apps", self.DEFAULT_KEYS["frequent_apps"])
        wh_raw = raw_map.get("working_hours", self.DEFAULT_KEYS["working_hours"])
        routines = raw_map.get("routines", self.DEFAULT_KEYS["routines"])
        priorities = raw_map.get("priorities", self.DEFAULT_KEYS["priorities"])
        deadlines = raw_map.get("important_deadlines", self.DEFAULT_KEYS["important_deadlines"])

        wh = WorkingHours(**wh_raw) if isinstance(wh_raw, dict) else WorkingHours()

        return PersonalProfile(
            preferences=pref if isinstance(pref, dict) else {},
            communication_style=str(comm),
            goals=goals if isinstance(goals, list) else [],
            projects=projects if isinstance(projects, list) else [],
            frequent_apps=apps if isinstance(apps, list) else [],
            working_hours=wh,
            routines=routines if isinstance(routines, list) else [],
            priorities=priorities if isinstance(priorities, list) else [],
            important_deadlines=deadlines if isinstance(deadlines, list) else [],
            items=items,
        )

    def get_full_profile(self) -> PersonalProfile:
        """Alias for get_profile()."""
        return self.get_profile()

    def update_profile_item(self, req: Any) -> ProfileItem:
        """Update or create a profile item from a ProfileUpdateReq model."""
        return self.set_item(
            key=req.key,
            value=req.value,
            category=req.category,
            is_confirmed=req.is_confirmed,
            confidence=req.confidence,
            source=req.source,
        )

    def set_item(
        self,
        key: str,
        value: Any,
        category: str = "preferences",
        is_confirmed: bool = True,
        confidence: float = 1.0,
        source: str = "user_explicit",
    ) -> ProfileItem:
        """
        Store or update a profile item with explicit confirmation tracking.
        Never silently turns inferred guesses into confirmed facts without explicit flag.
        """
        clean_key = key.strip().lower()
        if not clean_key:
            raise ValueError("Profile key cannot be empty.")

        screen_sensitive_data(clean_key, value)
        val_json = json.dumps(value) if isinstance(value, (dict, list)) else str(value)

        with conn() as c:
            c.execute(
                """
                INSERT INTO assistant_profile(key, value, category, is_confirmed, confidence, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    is_confirmed = excluded.is_confirmed,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (clean_key, val_json, category, 1 if is_confirmed else 0, max(0.0, min(confidence, 1.0)), source),
            )

        audit("profile.update", f"Updated profile key '{clean_key}' (confirmed={is_confirmed}, src={source})")

        return ProfileItem(
            key=clean_key,
            value=value,
            category=category,
            is_confirmed=is_confirmed,
            confidence=confidence,
            source=source,
        )

    def correct_inferred_item(self, key: str, corrected_value: Any, confirm: bool = True) -> ProfileItem:
        """
        Allows user to correct an inferred preference, turning it into a confirmed fact.
        """
        return self.set_item(
            key=key,
            value=corrected_value,
            is_confirmed=confirm,
            confidence=1.0,
            source="user_correction",
        )

    def delete_item(self, key: str) -> bool:
        """Delete a profile item, respecting privacy controls."""
        clean_key = key.strip().lower()
        with conn() as c:
            cur = c.execute("DELETE FROM assistant_profile WHERE key = ?", (clean_key,))
            deleted = cur.rowcount > 0
        if deleted:
            audit("profile.delete", f"Deleted profile key '{clean_key}'")
        return deleted

    def clear_inferred_preferences(self) -> int:
        """Delete all unconfirmed inferred items, keeping only user-confirmed facts."""
        with conn() as c:
            cur = c.execute("DELETE FROM assistant_profile WHERE is_confirmed = 0")
            count = cur.rowcount
        audit("profile.clear_inferred", f"Cleared {count} unconfirmed inferred profile items")
        return count


profile_manager = ProfileManager()
