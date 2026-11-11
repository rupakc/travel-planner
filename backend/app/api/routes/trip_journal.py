"""Trips API: journal entries and place ratings/visits."""

import re
import unicodedata
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, Response

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import trip_journal_db as db
from ...game import trip_hooks

router = APIRouter()

MOODS = ("great", "good", "ok", "tough")
KINDS = ("activity", "place", "food", "hotel", "event", "tour", "nearby", "other")
PLACE_KEY_RE = re.compile(r"^[a-z]+:[a-z0-9-]{1,60}$")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = "".join(c for c in text if c == "\n" or unicodedata.category(c) != "Cc")
    return text.strip()


def _body(value: Any) -> str:
    if not isinstance(value, str):
        raise ApiError(422, "journal_empty", "Write something first")
    text = _clean(value)
    if not text:
        raise ApiError(422, "journal_empty", "Write something first")
    if len(text) > 4000:
        raise ApiError(
            422, "journal_too_long", "Entries are limited to 4000 characters"
        )
    return text


def _day(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ApiError(422, "day_invalid", "day must be YYYY-MM-DD") from None


def _mood(value: Any) -> str | None:
    if value is None:
        return None
    if value not in MOODS:
        raise ApiError(422, "mood_invalid", "Unknown mood")
    return value


@router.get("/trips/{plan_id}/journal")
def list_journal(plan_id: int, user: dict = Depends(get_current_user)):
    owned_trip(plan_id, user)
    return {"entries": db.list_entries(plan_id)}


@router.post("/trips/{plan_id}/journal", status_code=201)
def add_journal(
    plan_id: int,
    response: Response,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    owned_trip(plan_id, user)
    client_id = payload.get("client_id")
    if not isinstance(client_id, str) or not 1 <= len(client_id) <= 64:
        raise ApiError(422, "client_id_invalid", "client_id is required")
    body = _body(payload.get("body"))
    day = _day(payload.get("day"))
    mood = _mood(payload.get("mood"))
    try:
        entry, created = db.add_entry(plan_id, client_id, body, day, mood)
    except db.LimitReached:
        raise ApiError(409, "journal_limit", "Journal is full (500 entries)") from None
    if not created:
        response.status_code = 200
    return entry


@router.patch("/trips/{plan_id}/journal/{entry_id}")
def patch_journal(
    plan_id: int,
    entry_id: int,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    owned_trip(plan_id, user)
    fields: dict = {}
    if "body" in payload:
        fields["body"] = _body(payload["body"])
    if "day" in payload:
        fields["day"] = _day(payload["day"])
    if "mood" in payload:
        fields["mood"] = _mood(payload["mood"])
    entry = db.update_entry(plan_id, entry_id, fields)
    if entry is None:
        raise ApiError(404, "entry_not_found", "Entry not found")
    return entry


@router.delete("/trips/{plan_id}/journal/{entry_id}", status_code=204)
def delete_journal(plan_id: int, entry_id: int, user: dict = Depends(get_current_user)):
    owned_trip(plan_id, user)
    if not db.delete_entry(plan_id, entry_id):
        raise ApiError(404, "entry_not_found", "Entry not found")
    return Response(status_code=204)


@router.get("/trips/{plan_id}/places")
def list_trip_places(plan_id: int, user: dict = Depends(get_current_user)):
    owned_trip(plan_id, user)
    return {"places": db.list_places(plan_id)}


def _coord(value: Any, limit: float, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ApiError(422, f"{name}_invalid", f"{name} must be a number")
    if not -limit <= value <= limit:
        raise ApiError(422, f"{name}_invalid", f"{name} is out of range")
    return float(value)


@router.put("/trips/{plan_id}/places/{place_key}")
def put_place(
    plan_id: int,
    place_key: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    owned_trip(plan_id, user)
    if not PLACE_KEY_RE.match(place_key):
        raise ApiError(422, "place_key_invalid", "Invalid place key")
    fields: dict = {}
    existing = db.get_place(plan_id, place_key)
    if "name" in payload or existing is None:
        name = payload.get("name")
        name = _clean(name) if isinstance(name, str) else ""
        if not 1 <= len(name) <= 120:
            raise ApiError(422, "name_invalid", "name must be 1 to 120 characters")
        fields["name"] = name
    if "kind" in payload or existing is None:
        kind = payload.get("kind")
        if kind not in KINDS:
            raise ApiError(422, "kind_invalid", "Unknown kind")
        fields["kind"] = kind
    if "visited" in payload:
        if not isinstance(payload["visited"], bool):
            raise ApiError(422, "visited_invalid", "visited must be true or false")
        fields["visited"] = payload["visited"]
    if "stars" in payload:
        stars = payload["stars"]
        if stars is not None and (
            isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5
        ):
            raise ApiError(422, "stars_invalid", "stars must be 1 to 5 or null")
        fields["stars"] = stars
    if "note" in payload:
        note = payload["note"]
        if note is not None:
            if not isinstance(note, str):
                raise ApiError(422, "note_too_long", "note must be text")
            note = _clean(note) or None
            if note and len(note) > 500:
                raise ApiError(
                    422, "note_too_long", "Notes are limited to 500 characters"
                )
        fields["note"] = note
    if "day" in payload:
        fields["day"] = _day(payload["day"])
    if "lat" in payload:
        fields["lat"] = _coord(payload["lat"], 90, "lat")
    if "lng" in payload:
        fields["lng"] = _coord(payload["lng"], 180, "lng")
    try:
        place, newly = db.upsert_place(plan_id, place_key, fields)
    except db.LimitReached:
        raise ApiError(409, "places_limit", "Too many places on this trip") from None
    game = (
        trip_hooks.on_place_visited(str(user["id"]), plan_id, place_key)
        if newly
        else None
    )
    return {"place": place, "game": game}


@router.delete("/trips/{plan_id}/places/{place_key}", status_code=204)
def delete_trip_place(
    plan_id: int, place_key: str, user: dict = Depends(get_current_user)
):
    owned_trip(plan_id, user)
    if not db.delete_place(plan_id, place_key):
        raise ApiError(404, "place_not_found", "Place not found")
    return Response(status_code=204)
