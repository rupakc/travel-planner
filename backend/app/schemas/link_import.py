"""Plan-from-a-link: request, extraction and preview models."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PLACE_KINDS = (
    "sight",
    "food",
    "drink",
    "stay",
    "activity",
    "nature",
    "shopping",
    "nightlife",
    "event",
    "transport",
    "area",
)
MAX_PLACES = 40
MAX_TEXT_CHARS = 20_000
MAX_IMAGES = 4


def _squash(value, limit: int) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit] or None


# ── Request ───────────────────────────────────────────────────────────────


class ImportImage(BaseModel):
    media_type: str = Field("", max_length=64)
    # ~5 MB decoded is ~6.7 MB base64; the route checks the decoded size
    data_base64: str = Field(..., max_length=7_200_000)


class ImportRequest(BaseModel):
    """Exactly one source: a link, pasted text, or 1–4 screenshots."""

    url: str | None = Field(None, max_length=2048)
    text: str | None = Field(None, max_length=MAX_TEXT_CHARS)
    images: list[ImportImage] | None = Field(None, max_length=8)

    @model_validator(mode="after")
    def one_source(self) -> ImportRequest:
        given = [
            bool(self.url and self.url.strip()),
            bool(self.text and self.text.strip()),
            self.images is not None,
        ]
        if sum(given) != 1:
            raise ValueError("Send exactly one of url, text or images.")
        if self.images is not None and not self.images:
            raise ValueError("Add at least one screenshot.")
        return self

    @property
    def kind(self) -> str:
        if self.url and self.url.strip():
            return "url"
        if self.text and self.text.strip():
            return "text"
        return "images"


# ── Agent output (validated, never trusted) ──────────────────────────────


class ExtractedPlace(BaseModel):
    name: str
    kind: str = "sight"
    city: str | None = None
    country: str | None = None
    note: str | None = None
    quote: str | None = None
    day_hint: int | None = None
    confidence: float = 0.7

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        name = _squash(v, 120)
        if not name:
            raise ValueError("place without a name")
        return name

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        kind = str(v or "").strip().lower()
        return kind if kind in PLACE_KINDS else "sight"

    @field_validator("city", "country", mode="before")
    @classmethod
    def _short(cls, v):
        return _squash(v, 80)

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v):
        return _squash(v, 140)

    @field_validator("quote", mode="before")
    @classmethod
    def _quote(cls, v):
        return _squash(v, 120)

    @field_validator("day_hint", mode="before")
    @classmethod
    def _day(cls, v):
        try:
            day = int(v)
        except (TypeError, ValueError):
            return None
        return day if 1 <= day <= 60 else None

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.7


class Extraction(BaseModel):
    title: str | None = None
    summary: str | None = None
    places: list[ExtractedPlace] = Field(default_factory=list)
    destinations_mentioned: list[str] = Field(default_factory=list)
    suggested_days: int | None = None
    season_hint: str | None = None
    interests: list[str] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v):
        return _squash(v, 160)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v):
        return _squash(v, 300)

    @field_validator("season_hint", mode="before")
    @classmethod
    def _season(cls, v):
        return _squash(v, 60)

    @field_validator("places", mode="before")
    @classmethod
    def _places(cls, v):
        if not isinstance(v, list):
            return []
        kept = []
        for item in v:
            if not isinstance(item, dict):
                continue
            try:
                kept.append(ExtractedPlace.model_validate(item))
            except ValueError:
                continue
            if len(kept) == MAX_PLACES:
                break
        return kept

    @field_validator("destinations_mentioned", mode="before")
    @classmethod
    def _destinations(cls, v):
        if not isinstance(v, list):
            return []
        out = [_squash(d, 80) for d in v if isinstance(d, str)]
        return [d for d in dict.fromkeys(out) if d][:10]

    @field_validator("suggested_days", mode="before")
    @classmethod
    def _days(cls, v):
        try:
            days = int(v)
        except (TypeError, ValueError):
            return None
        return days if 1 <= days <= 30 else None

    @field_validator("interests", mode="before")
    @classmethod
    def _interests(cls, v):
        if not isinstance(v, list):
            return []
        out = [(_squash(i, 30) or "").lower() for i in v if isinstance(i, str)]
        return [i for i in dict.fromkeys(out) if i][:6]


# ── Preview (the endpoint's response) ────────────────────────────────────


class ImportSourceInfo(BaseModel):
    kind: Literal["url", "text", "images"]
    url: str | None = None
    title: str | None = None
    site_name: str | None = None
    favicon_url: str | None = None
    author: str | None = None


class PreviewDestination(BaseModel):
    name: str
    city: str
    country: str
    airports: list[str] = Field(default_factory=list)
    lat: float | None = None
    lng: float | None = None
    place_count: int
    nights: int


class PreviewPlace(BaseModel):
    id: str
    name: str
    kind: str
    city: str | None = None
    country: str | None = None
    destination: str | None = None
    lat: float | None = None
    lng: float | None = None
    approximate: bool = True
    verified: bool = False
    address: str | None = None
    rating: float | None = None
    note: str | None = None
    quote: str | None = None
    day_hint: int | None = None
    confidence: float = 0.7


class AlsoMentioned(BaseModel):
    name: str
    place_count: int


class ImportPreview(BaseModel):
    source: dict
    title: str
    summary: str | None = None
    destinations: list[PreviewDestination]
    places: list[PreviewPlace]
    unresolved: list[PreviewPlace] = Field(default_factory=list)
    also_mentioned: list[AlsoMentioned] = Field(default_factory=list)
    suggested_days: int
    season_hint: str | None = None
    interests: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
