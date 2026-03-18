"""
RBI Calling Hours Guardrail
============================
Implements RBI Fair Practice Code guidelines:
  - AI collection/promotional calls are ONLY allowed between 08:00 AM and 07:00 PM (IST).
  - Calling outside this window is a regulatory violation.

This module provides:
  1. `is_within_calling_hours()` — returns True if current IST time is within the allowed window
  2. `get_calling_hours_status()` — returns a dict with current status, window info, and next available slot
  3. `validate_calling_hours()` — raises HTTPException(403) if outside allowed hours
  4. Slot management utilities for scheduled calling
"""

from datetime import datetime, timedelta
import pytz

# ──────────────────────────────────────────
# RBI CALLING HOURS CONFIGURATION
# ──────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")

DEFAULT_CALLING_START_HOUR = 8   # 08:00 AM IST
DEFAULT_CALLING_END_HOUR = 19   # 07:00 PM IST (19:00)

# Available time slots (1-hour intervals within RBI window)
TIME_SLOTS = []
for h in range(DEFAULT_CALLING_START_HOUR, DEFAULT_CALLING_END_HOUR):
    start = f"{h:02d}:00"
    end = f"{h+1:02d}:00"
    label_start = datetime.strptime(start, "%H:%M").strftime("%I:%M %p")
    label_end = datetime.strptime(end, "%H:%M").strftime("%I:%M %p")
    TIME_SLOTS.append({
        "id": f"slot_{h:02d}",
        "start_hour": h,
        "end_hour": h + 1,
        "start": start,
        "end": end,
        "label": f"{label_start} - {label_end}"
    })


def get_ist_now() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def is_within_calling_hours(
    start_hour: int = DEFAULT_CALLING_START_HOUR,
    end_hour: int = DEFAULT_CALLING_END_HOUR
) -> bool:
    """
    Check if the current IST time is within the allowed RBI calling window.
    Default: 08:00 AM – 07:00 PM IST.
    """
    now = get_ist_now()
    return start_hour <= now.hour < end_hour


def get_calling_hours_status(
    start_hour: int = DEFAULT_CALLING_START_HOUR,
    end_hour: int = DEFAULT_CALLING_END_HOUR
) -> dict:
    """
    Returns complete status info about the RBI calling window.
    """
    now = get_ist_now()
    is_open = start_hour <= now.hour < end_hour

    # Calculate next available window
    if is_open:
        window_closes_at = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        remaining_minutes = int((window_closes_at - now).total_seconds() / 60)
        next_window_opens = None
    else:
        remaining_minutes = 0
        if now.hour < start_hour:
            # Before today's window
            next_window_opens = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        else:
            # After today's window → next day
            next_day = now + timedelta(days=1)
            next_window_opens = next_day.replace(hour=start_hour, minute=0, second=0, microsecond=0)

    start_label = datetime.strptime(f"{start_hour}:00", "%H:%M").strftime("%I:%M %p")
    end_label = datetime.strptime(f"{end_hour}:00", "%H:%M").strftime("%I:%M %p")

    return {
        "is_within_calling_hours": is_open,
        "current_time_ist": now.strftime("%I:%M %p"),
        "current_date_ist": now.strftime("%Y-%m-%d"),
        "calling_window": {
            "start": f"{start_hour:02d}:00",
            "end": f"{end_hour:02d}:00",
            "start_label": start_label,
            "end_label": end_label,
            "label": f"{start_label} – {end_label}"
        },
        "remaining_minutes": remaining_minutes,
        "next_window_opens": next_window_opens.strftime("%Y-%m-%d %I:%M %p") if next_window_opens else None,
        "available_slots": TIME_SLOTS
    }


def validate_calling_hours(
    start_hour: int = DEFAULT_CALLING_START_HOUR,
    end_hour: int = DEFAULT_CALLING_END_HOUR
):
    """
    Raises HTTPException(403) if current time is outside the RBI calling window.
    Call this at the top of any call-triggering endpoint.
    """
    from fastapi import HTTPException

    if not is_within_calling_hours(start_hour, end_hour):
        now = get_ist_now()
        start_label = datetime.strptime(f"{start_hour}:00", "%H:%M").strftime("%I:%M %p")
        end_label = datetime.strptime(f"{end_hour}:00", "%H:%M").strftime("%I:%M %p")

        raise HTTPException(
            status_code=403,
            detail=(
                f"Cannot initiate call: Outside allowed RBI calling window "
                f"({start_label} - {end_label} IST). "
                f"Current time: {now.strftime('%I:%M %p')} IST. "
                f"Please schedule the call within the allowed hours."
            )
        )
