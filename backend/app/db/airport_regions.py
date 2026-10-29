"""IATA code → region code (US state, Canadian province, Australian state,
Brazilian UF; lower-case, matching ``core.places`` region codes) for every
seeded airport in the US, Canada, Australia and Brazil.

The region is that of the city the seed lists the airport under, so a typed
"City, ST" narrows correctly: IAD and DCA (physically in Virginia) serve
"Washington D.C." and carry "dc".
"""

AIRPORT_REGION: dict[str, str] = {
    # ── United States ──
    "ATL": "ga", "LAX": "ca", "ORD": "il", "DFW": "tx", "DEN": "co",
    "JFK": "ny", "SFO": "ca", "SEA": "wa", "LAS": "nv", "MCO": "fl",
    "EWR": "nj", "MIA": "fl", "CLT": "nc", "PHX": "az", "IAH": "tx",
    "BOS": "ma", "MSP": "mn", "DTW": "mi", "PHL": "pa", "LGA": "ny",
    "IAD": "dc", "DCA": "dc", "BWI": "md", "SLC": "ut", "SAN": "ca",
    "TPA": "fl", "AUS": "tx", "PDX": "or", "STL": "mo", "BNA": "tn",
    "MSY": "la", "MCI": "mo", "RDU": "nc", "SMF": "ca", "SJC": "ca",
    "OAK": "ca", "MDW": "il", "HNL": "hi", "ANC": "ak", "PIT": "pa",
    "IND": "in", "CMH": "oh", "MKE": "wi", "OMA": "ne", "BUF": "ny",
    "ALB": "ny", "BDL": "ct", "CLE": "oh", "HOU": "tx", "DAL": "tx",
    "ABQ": "nm", "OKC": "ok", "MEM": "tn", "GRR": "mi", "TUL": "ok",
    "BOI": "id", "ELP": "tx", "LIT": "ar", "JAN": "ms", "BHM": "al",
    "SDF": "ky", "LEX": "ky", "CHS": "sc", "SAV": "ga", "JAX": "fl",
    "RSW": "fl", "PBI": "fl", "PWM": "me", "ORF": "va", "RIC": "va",
    "ROC": "ny", "SYR": "ny", "TYS": "tn", "DSM": "ia", "GEG": "wa",
    "BZN": "mt", "FAI": "ak", "KOA": "hi", "OGG": "hi", "LIH": "hi",
    "BGR": "me",
    # ── Canada ──
    "YYZ": "on", "YVR": "bc", "YUL": "qc", "YYC": "ab", "YEG": "ab",
    "YOW": "on", "YHZ": "ns", "YWG": "mb", "YQB": "qc", "YXE": "sk",
    "YYJ": "bc",
    # ── Brazil ──
    "GRU": "sp", "CGH": "sp", "GIG": "rj", "SDU": "rj", "BSB": "df",
    "SSA": "ba", "FOR": "ce", "REC": "pe", "BEL": "pa", "MAO": "am",
    # ── Australia ──
    "SYD": "nsw", "MEL": "vic", "BNE": "qld", "PER": "wa", "ADL": "sa",
    "CBR": "act", "CNS": "qld", "DRW": "nt", "HBA": "tas", "OOL": "qld",
    "TSV": "qld",
}  # fmt: skip
