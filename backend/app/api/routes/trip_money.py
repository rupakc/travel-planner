"""Trips API: expense log (idempotent on client_id)."""

import re
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import trip_expenses_db, trip_snapshot_db
from ...services import trip_money as money

router = APIRouter()

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_NOTE_MAX = 140


class ExpenseIn(BaseModel):
    client_id: UUID
    amount: str
    currency: str
    category: str
    note: str | None = None
    spent_on: str


class ExpensePatch(BaseModel):
    amount: str | None = None
    currency: str | None = None
    category: str | None = None
    note: str | None = None
    spent_on: str | None = None


def _currency(value: str) -> str:
    code = (value or "").strip().upper()
    if not _CURRENCY_RE.match(code):
        raise ApiError(422, "currency_invalid", "Currency must be a 3-letter ISO code")
    return code


def _amount(value: str, currency: str) -> int:
    try:
        return money.parse_amount(value, currency)
    except ValueError as e:
        raise ApiError(422, "amount_invalid", str(e)) from e


def _category(value: str) -> str:
    if value not in money.EXPENSE_CATEGORIES:
        raise ApiError(422, "category_invalid", "Unknown category")
    return value


def _note(value: str | None) -> str | None:
    value = (value or "").strip() or None
    if value and len(value) > _NOTE_MAX:
        raise ApiError(422, "note_too_long", f"Note is at most {_NOTE_MAX} characters")
    return value


def _day(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as e:
        raise ApiError(422, "spent_on_invalid", "spent_on must be YYYY-MM-DD") from e


def _out(row: dict) -> dict:
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "amount": money.format_amount(row["amount_minor"], row["currency"]),
        "currency": row["currency"],
        "category": row["category"],
        "note": row["note"],
        "spent_on": row["spent_on"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/trips/{plan_id}/expenses")
def list_expenses(plan_id: int, user: dict = Depends(get_current_user)):
    owned_trip(plan_id, user)
    rows = trip_expenses_db.list_for(plan_id)
    rate = money.usd_rate(trip_snapshot_db.get_snapshot(plan_id))
    t = money.totals(rows, rate)
    return {
        "expenses": [_out(r) for r in rows],
        "totals": t,
        "rate": rate,
    }


@router.post("/trips/{plan_id}/expenses", status_code=201)
def add_expense(
    plan_id: int,
    req: ExpenseIn,
    response: Response,
    user: dict = Depends(get_current_user),
):
    owned_trip(plan_id, user)
    currency = _currency(req.currency)
    minor = _amount(req.amount, currency)
    category = _category(req.category)
    note = _note(req.note)
    spent_on = _day(req.spent_on)
    try:
        row, created = trip_expenses_db.add(
            plan_id, str(req.client_id), minor, currency, category, note, spent_on
        )
    except trip_expenses_db.ExpenseLimitError as e:
        raise ApiError(
            409, "expense_limit", "This trip has reached its expense limit"
        ) from e
    if not created:
        response.status_code = 200
    return _out(row)


@router.patch("/trips/{plan_id}/expenses/{expense_id}")
def patch_expense(
    plan_id: int,
    expense_id: int,
    req: ExpensePatch,
    user: dict = Depends(get_current_user),
):
    owned_trip(plan_id, user)
    current = trip_expenses_db.get(plan_id, expense_id)
    if not current:
        raise ApiError(404, "expense_not_found", "Expense not found")
    sent = req.model_fields_set
    fields: dict = {}
    currency = current["currency"]
    if "currency" in sent:
        currency = _currency(req.currency or "")
        fields["currency"] = currency
    if "amount" in sent or "currency" in sent:
        text = (
            req.amount
            if "amount" in sent
            else money.format_amount(current["amount_minor"], current["currency"])
        )
        fields["amount_minor"] = _amount(text or "", currency)
    if "category" in sent:
        fields["category"] = _category(req.category or "")
    if "note" in sent:
        fields["note"] = _note(req.note)
    if "spent_on" in sent:
        fields["spent_on"] = _day(req.spent_on or "")
    row = trip_expenses_db.update(plan_id, expense_id, fields)
    if row is None:  # deleted between the read above and the update
        raise ApiError(404, "expense_not_found", "Expense not found")
    return _out(row)


@router.delete("/trips/{plan_id}/expenses/{expense_id}", status_code=204)
def delete_expense(
    plan_id: int, expense_id: int, user: dict = Depends(get_current_user)
):
    owned_trip(plan_id, user)
    if not trip_expenses_db.delete(plan_id, expense_id):
        raise ApiError(404, "expense_not_found", "Expense not found")
    return Response(status_code=204)
