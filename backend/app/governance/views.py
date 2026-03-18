"""
Governance API Endpoints
========================
Provides REST endpoints for:
  - GET  /governance/calling_hours_status  — Current RBI calling window status
  - GET  /governance/time_slots           — Available 1-hour calling slots
  - POST /governance/update_calling_hours — Update the calling window (admin)
  - POST /governance/select_slot          — Select a specific time slot for calls
  - GET  /governance/selected_slot        — Get currently selected slot
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.auth.views import get_current_user
from app.governance.rbi_rules import (
    get_calling_hours_status,
    TIME_SLOTS,
    DEFAULT_CALLING_START_HOUR,
    DEFAULT_CALLING_END_HOUR,
    is_within_calling_hours,
    get_ist_now
)

router = APIRouter()

# ── In-memory config (can be moved to DB later) ──
_calling_config = {
    "start_hour": DEFAULT_CALLING_START_HOUR,
    "end_hour": DEFAULT_CALLING_END_HOUR,
}

# ── Selected slot per user (in-memory, keyed by user_id) ──
_selected_slots = {}  # { user_id: { "slot_id": "slot_14", "start_hour": 14, "end_hour": 15, "label": "02:00 PM - 03:00 PM" } }


class CallingHoursUpdate(BaseModel):
    start_hour: int   # 0-23
    end_hour: int      # 0-23


class SlotSelection(BaseModel):
    slot_id: str       # e.g. "slot_14"
    start_hour: int
    end_hour: int
    label: str


def get_current_calling_config():
    """Get the current calling hours config."""
    return _calling_config


def get_user_selected_slot(user_id: str) -> Optional[dict]:
    """Get the selected slot for a user, or None if no slot selected."""
    return _selected_slots.get(user_id)


def validate_slot_and_rbi(user_id: str):
    """
    Validate BOTH the RBI calling window AND the selected slot.
    Raises HTTPException(403) if:
      1. Current time is outside the RBI calling window, OR
      2. A slot is selected and current time is NOT within that slot
    """
    config = get_current_calling_config()
    now = get_ist_now()
    current_hour = now.hour

    start_label = datetime.strptime(f"{config['start_hour']}:00", "%H:%M").strftime("%I:%M %p")
    end_label = datetime.strptime(f"{config['end_hour']}:00", "%H:%M").strftime("%I:%M %p")

    # Check 1: RBI calling window
    if not is_within_calling_hours(config["start_hour"], config["end_hour"]):
        raise HTTPException(
            status_code=403,
            detail=(
                f"⛔ Calls only allowed between {start_label} – {end_label} IST. "
                f"Current time: {now.strftime('%I:%M %p')} IST."
            )
        )

    # Check 2: Selected slot enforcement
    selected = _selected_slots.get(user_id)
    if selected:
        slot_start = selected["start_hour"]
        slot_end = selected["end_hour"]
        if not (slot_start <= current_hour < slot_end):
            slot_label = selected["label"]
            raise HTTPException(
                status_code=403,
                detail=(
                    f"⛔ Your selected slot is {slot_label}. "
                    f"Current time: {now.strftime('%I:%M %p')} IST. "
                    f"Please wait or change your slot."
                )
            )


@router.get("/calling_hours_status")
async def calling_hours_status(current_user: dict = Depends(get_current_user)):
    """Get current RBI calling window status, remaining time, and slot info."""
    user_id = str(current_user["_id"])
    config = get_current_calling_config()
    status = get_calling_hours_status(config["start_hour"], config["end_hour"])

    # Include selected slot info
    selected = _selected_slots.get(user_id)
    status["selected_slot"] = selected
    return status


@router.get("/time_slots")
async def get_time_slots(current_user: dict = Depends(get_current_user)):
    """Get all available 1-hour calling time slots within the RBI window."""
    user_id = str(current_user["_id"])
    config = get_current_calling_config()
    now = get_ist_now()
    current_hour = now.hour

    selected = _selected_slots.get(user_id)
    selected_id = selected["slot_id"] if selected else None

    # Mark slots as past/current/future
    slots_with_status = []
    for slot in TIME_SLOTS:
        # Only include slots within the configured window
        if slot["start_hour"] >= config["start_hour"] and slot["end_hour"] <= config["end_hour"]:
            if slot["start_hour"] < current_hour:
                slot_status = "past"
            elif slot["start_hour"] == current_hour:
                slot_status = "current"
            else:
                slot_status = "available"
            slots_with_status.append({
                **slot,
                "status": slot_status,
                "is_selected": slot["id"] == selected_id
            })

    return {
        "slots": slots_with_status,
        "current_hour": current_hour,
        "selected_slot": selected,
        "calling_window": {
            "start_hour": config["start_hour"],
            "end_hour": config["end_hour"]
        }
    }


@router.post("/select_slot")
async def select_slot(
    selection: SlotSelection,
    current_user: dict = Depends(get_current_user)
):
    """Select a specific time slot for making calls."""
    user_id = str(current_user["_id"])
    config = get_current_calling_config()

    # Validate slot is within RBI window
    if selection.start_hour < config["start_hour"] or selection.end_hour > config["end_hour"]:
        raise HTTPException(
            status_code=400,
            detail="Selected slot is outside the RBI calling window"
        )

    _selected_slots[user_id] = {
        "slot_id": selection.slot_id,
        "start_hour": selection.start_hour,
        "end_hour": selection.end_hour,
        "label": selection.label
    }

    print(f"[GOVERNANCE] 📅 User {user_id} selected slot: {selection.label}")

    return {
        "success": True,
        "message": f"Call slot set to {selection.label}",
        "selected_slot": _selected_slots[user_id]
    }


@router.post("/clear_slot")
async def clear_slot(current_user: dict = Depends(get_current_user)):
    """Clear the selected slot — allows calling anytime within RBI window."""
    user_id = str(current_user["_id"])
    if user_id in _selected_slots:
        del _selected_slots[user_id]
    return {"success": True, "message": "Slot cleared. Calls allowed anytime within RBI window."}


@router.post("/update_calling_hours")
async def update_calling_hours(
    update: CallingHoursUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update the RBI calling window (admin only)."""
    if update.start_hour < 0 or update.start_hour > 23:
        raise HTTPException(status_code=400, detail="start_hour must be between 0 and 23")
    if update.end_hour < 0 or update.end_hour > 23:
        raise HTTPException(status_code=400, detail="end_hour must be between 0 and 23")
    if update.start_hour >= update.end_hour:
        raise HTTPException(status_code=400, detail="start_hour must be before end_hour")

    _calling_config["start_hour"] = update.start_hour
    _calling_config["end_hour"] = update.end_hour

    # Clear any selected slots that are now outside the new window
    for uid in list(_selected_slots.keys()):
        slot = _selected_slots[uid]
        if slot["start_hour"] < update.start_hour or slot["end_hour"] > update.end_hour:
            del _selected_slots[uid]

    # Regenerate status with new config
    status = get_calling_hours_status(update.start_hour, update.end_hour)

    return {
        "success": True,
        "message": f"Calling hours updated to {status['calling_window']['label']}",
        "status": status
    }
