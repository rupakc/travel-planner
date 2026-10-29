"""Airport → region codes (US state, Canadian province, Australian state,
Brazilian UF; lower-case, matching ``core.places`` region codes).

The region comes from the dataset's ``region`` column (OurAirports
``iso_region``, "US-OR" → "or"). ``REGION_OVERRIDES`` adds the regions of the
city an airport serves when that city lies in another region: IAD and DCA
(physically in Virginia) serve Washington D.C. and also carry "dc"; MCI
serves Kansas City, Missouri and Kansas, and also carries "ks".
"""

_REGIONAL_COUNTRIES = frozenset({"US", "CA", "AU", "BR"})

REGION_OVERRIDES: dict[str, frozenset[str]] = {
    "IAD": frozenset({"dc"}),
    "DCA": frozenset({"dc"}),
    "MCI": frozenset({"ks"}),
}


def airport_regions(
    iata: str, country_code: str | None, region: str | None
) -> frozenset[str]:
    """The region codes a typed "City, ST" can match this airport by; empty
    outside the US, Canada, Australia and Brazil or without a region."""
    if country_code not in _REGIONAL_COUNTRIES or not region or "-" not in region:
        return frozenset()
    return frozenset({region.split("-", 1)[1].lower()}) | REGION_OVERRIDES.get(
        iata, frozenset()
    )
