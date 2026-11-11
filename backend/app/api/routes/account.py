"""Account profile, settings, onboarding and sign-in identities."""

import unicodedata

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...core.session_payload import user_payload
from ...db import user_settings_db as sdb
from ...db import users_db
from ...db.database import get_connection
from ...game import hooks, trip_hooks

router = APIRouter()


def _display_name(raw: str) -> str:
    name = unicodedata.normalize("NFC", raw or "").strip()
    if not 1 <= len(name) <= 50 or any(
        unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp") for c in name
    ):
        raise ApiError(422, "display_name_invalid", "Display name is not valid.")
    return name


def _identities(user_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT provider, email, created_at FROM user_identities
               WHERE user_id = ? ORDER BY created_at, id""",
            (user_id,),
        ).fetchall()
    return [
        {"provider": r["provider"], "email": r["email"], "linked_at": r["created_at"]}
        for r in rows
    ]


@router.get("/account")
def get_account(user: dict = Depends(get_current_user)):
    return {
        "user": user_payload(user),
        "identities": _identities(user["id"]),
        "settings": sdb.get_settings(user["id"]),
        "onboarding": sdb.get_onboarding(user["id"]),
    }


class ProfilePatch(BaseModel):
    display_name: str


@router.patch("/account", dependencies=[Depends(rate_limit("account"))])
def patch_account(body: ProfilePatch, user: dict = Depends(get_current_user)):
    users_db.set_display_name(user["id"], _display_name(body.display_name))
    return {"user": user_payload(users_db.get_user_by_id(user["id"]))}


@router.get("/account/settings")
def get_account_settings(user: dict = Depends(get_current_user)):
    return sdb.get_settings(user["id"])


@router.patch("/account/settings", dependencies=[Depends(rate_limit("account"))])
def patch_account_settings(
    body: sdb.SettingsPatch, user: dict = Depends(get_current_user)
):
    return sdb.patch_settings(user["id"], body.model_dump(exclude_unset=True))


class OnboardingBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step: int = Field(ge=0, le=5)
    done: bool
    skipped: bool = False
    traveller_type: str | None = Field(default=None, pattern=r"^[a-z_]{1,32}$")


@router.put("/account/onboarding", dependencies=[Depends(rate_limit("account"))])
def put_account_onboarding(
    body: OnboardingBody, user: dict = Depends(get_current_user)
):
    onboarding, award = sdb.put_onboarding(
        user["id"], body.step, body.done, body.skipped, body.traveller_type
    )
    game = hooks.on_onboarding_complete(user["id"]) if award else None
    if body.traveller_type is not None:
        game = trip_hooks.merge_deltas(
            game, trip_hooks.on_traveller_type(user["id"], body.traveller_type)
        )
    return {"onboarding": onboarding, "game": game}


@router.delete(
    "/account/identities/{provider}",
    status_code=204,
    dependencies=[Depends(rate_limit("account"))],
)
def unlink_identity(provider: str, user: dict = Depends(get_current_user)):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, provider FROM user_identities WHERE user_id = ?", (user["id"],)
        ).fetchall()
        mine = [r["id"] for r in rows if r["provider"] == provider]
        if not mine:
            raise ApiError(
                404, "identity_not_found", "That sign-in method is not linked."
            )
        has_password = user.get("password_hash") != "!"
        if not has_password and len(rows) - len(mine) == 0:
            raise ApiError(
                409,
                "last_sign_in_method",
                "You can't remove your only way to sign in. Set a password first.",
            )
        conn.execute(
            "DELETE FROM user_identities WHERE user_id = ? AND provider = ?",
            (user["id"], provider),
        )
    return Response(status_code=204)
