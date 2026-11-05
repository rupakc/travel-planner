"""A fake ``test`` price source for the price-watch tests (never registered
outside tests). Prices are queued per check; no network."""

from app.services.price_watch import (
    CreatedWatch,
    InvalidSpec,
    NoLivePrice,
    PriceObservation,
)


class QuotaError(Exception):
    quota_exceeded = True


class FakeSource:
    """Hotel-like subject: spec {name, price?, expires_on?, no_match?}."""

    kind = "test"

    def __init__(self):
        self.queue: list = []  # PriceObservation | Exception per check
        self.cost = 1  # estimate_calls
        self.create_calls = 1
        self.created: list[dict] = []
        self.checked: list[int] = []

    def match_key(self, spec: dict) -> str:
        name = (spec.get("name") or "").strip()
        if not name:
            raise InvalidSpec("Tell us which thing to watch.")
        return name.lower()

    async def create(self, spec: dict, user: dict, api_key: str):
        self.match_key(spec)
        self.created.append({"spec": spec, "user": user["id"], "key": api_key})
        if spec.get("no_match"):
            return NoLivePrice(
                message="We couldn't find live prices for this thing.",
                suggestions=[{"name": "Other thing", "price": 90.0}],
                estimate={"price": 120.0, "source": "ai_estimate"},
                calls=self.create_calls,
            )
        return CreatedWatch(
            subject={"name": spec["name"], "token": "tok-1"},
            baseline=PriceObservation(
                price=float(spec.get("price", 400.0)),
                unit_price=100.0,
                source="fake_live",
                link="https://example.test/thing",
                observed={"rating": 4.5},
                calls=self.create_calls,
            ),
            title=spec["name"],
            subtitle="Testville · 1–5 Feb",
            expires_on=spec.get("expires_on", "2027-02-01"),
            plan_id=spec.get("plan_id"),
        )

    async def check(self, watch: dict, api_key: str) -> PriceObservation:
        self.checked.append(watch["id"])
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def estimate_calls(self, watch: dict) -> int:
        return self.cost

    def compose(self, kind: str, watch: dict, obs: PriceObservation, ref: float):
        verb = "is under your target" if kind.endswith("_target") else "dropped"
        return {
            "kind": kind,
            "title": f"{watch['title']} {verb}: ${obs.price:.0f}",
            "body": f"Was ${ref:.0f}.",
            "data": {"custom": "yes"},
        }


def ok(price: float, **kw) -> PriceObservation:
    return PriceObservation(price=price, source="fake_live", calls=1, **kw)


def gone() -> PriceObservation:
    return PriceObservation(
        price=None, status="unavailable", source="fake_live", calls=1
    )
