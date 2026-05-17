import asyncio
import logging
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition
from .web_tools import execute_tool
from ..schemas.request import TravelSearchRequest

logger = logging.getLogger(__name__)

_NATIONALITY_CURRENCY = {
    "american": ("USD", "US Dollar", "$"),
    "british": ("GBP", "British Pound", "£"),
    "canadian": ("CAD", "Canadian Dollar", "C$"),
    "australian": ("AUD", "Australian Dollar", "A$"),
    "indian": ("INR", "Indian Rupee", "₹"),
    "german": ("EUR", "Euro", "€"),
    "french": ("EUR", "Euro", "€"),
    "italian": ("EUR", "Euro", "€"),
    "spanish": ("EUR", "Euro", "€"),
    "dutch": ("EUR", "Euro", "€"),
    "belgian": ("EUR", "Euro", "€"),
    "irish": ("EUR", "Euro", "€"),
    "portuguese": ("EUR", "Euro", "€"),
    "austrian": ("EUR", "Euro", "€"),
    "finnish": ("EUR", "Euro", "€"),
    "greek": ("EUR", "Euro", "€"),
    "japanese": ("JPY", "Japanese Yen", "¥"),
    "chinese": ("CNY", "Chinese Yuan", "¥"),
    "korean": ("KRW", "South Korean Won", "₩"),
    "south korean": ("KRW", "South Korean Won", "₩"),
    "brazilian": ("BRL", "Brazilian Real", "R$"),
    "mexican": ("MXN", "Mexican Peso", "$"),
    "thai": ("THB", "Thai Baht", "฿"),
    "indonesian": ("IDR", "Indonesian Rupiah", "Rp"),
    "malaysian": ("MYR", "Malaysian Ringgit", "RM"),
    "singaporean": ("SGD", "Singapore Dollar", "S$"),
    "emirati": ("AED", "UAE Dirham", "د.إ"),
    "saudi": ("SAR", "Saudi Riyal", "﷼"),
    "turkish": ("TRY", "Turkish Lira", "₺"),
    "russian": ("RUB", "Russian Ruble", "₽"),
    "swiss": ("CHF", "Swiss Franc", "CHF"),
    "swedish": ("SEK", "Swedish Krona", "kr"),
    "norwegian": ("NOK", "Norwegian Krone", "kr"),
    "danish": ("DKK", "Danish Krone", "kr"),
    "polish": ("PLN", "Polish Zloty", "zł"),
    "czech": ("CZK", "Czech Koruna", "Kč"),
    "hungarian": ("HUF", "Hungarian Forint", "Ft"),
    "south african": ("ZAR", "South African Rand", "R"),
    "new zealander": ("NZD", "New Zealand Dollar", "NZ$"),
    "filipino": ("PHP", "Philippine Peso", "₱"),
    "vietnamese": ("VND", "Vietnamese Dong", "₫"),
    "pakistani": ("PKR", "Pakistani Rupee", "₨"),
    "bangladeshi": ("BDT", "Bangladeshi Taka", "৳"),
    "sri lankan": ("LKR", "Sri Lankan Rupee", "₨"),
    "nepali": ("NPR", "Nepalese Rupee", "₨"),
    "egyptian": ("EGP", "Egyptian Pound", "E£"),
    "nigerian": ("NGN", "Nigerian Naira", "₦"),
    "kenyan": ("KES", "Kenyan Shilling", "KSh"),
    "colombian": ("COP", "Colombian Peso", "$"),
    "argentinian": ("ARS", "Argentine Peso", "$"),
    "chilean": ("CLP", "Chilean Peso", "$"),
    "peruvian": ("PEN", "Peruvian Sol", "S/."),
    "israeli": ("ILS", "Israeli Shekel", "₪"),
}

_DESTINATION_CURRENCY = {
    "japan": ("JPY", "Japanese Yen", "¥"),
    "thailand": ("THB", "Thai Baht", "฿"),
    "india": ("INR", "Indian Rupee", "₹"),
    "usa": ("USD", "US Dollar", "$"),
    "uk": ("GBP", "British Pound", "£"),
    "australia": ("AUD", "Australian Dollar", "A$"),
    "singapore": ("SGD", "Singapore Dollar", "S$"),
    "france": ("EUR", "Euro", "€"),
    "germany": ("EUR", "Euro", "€"),
    "italy": ("EUR", "Euro", "€"),
    "spain": ("EUR", "Euro", "€"),
    "netherlands": ("EUR", "Euro", "€"),
    "uae": ("AED", "UAE Dirham", "د.إ"),
    "indonesia": ("IDR", "Indonesian Rupiah", "Rp"),
    "malaysia": ("MYR", "Malaysian Ringgit", "RM"),
    "china": ("CNY", "Chinese Yuan", "¥"),
    "south korea": ("KRW", "South Korean Won", "₩"),
    "mexico": ("MXN", "Mexican Peso", "$"),
    "brazil": ("BRL", "Brazilian Real", "R$"),
    "turkey": ("TRY", "Turkish Lira", "₺"),
    "switzerland": ("CHF", "Swiss Franc", "CHF"),
    "canada": ("CAD", "Canadian Dollar", "C$"),
    "new zealand": ("NZD", "New Zealand Dollar", "NZ$"),
    "egypt": ("EGP", "Egyptian Pound", "E£"),
    "south africa": ("ZAR", "South African Rand", "R"),
    "philippines": ("PHP", "Philippine Peso", "₱"),
    "vietnam": ("VND", "Vietnamese Dong", "₫"),
    "nepal": ("NPR", "Nepalese Rupee", "₨"),
    "maldives": ("MVR", "Maldivian Rufiyaa", "Rf"),
    "sri lanka": ("LKR", "Sri Lankan Rupee", "₨"),
    "czech republic": ("CZK", "Czech Koruna", "Kč"),
    "hungary": ("HUF", "Hungarian Forint", "Ft"),
    "poland": ("PLN", "Polish Zloty", "zł"),
    "sweden": ("SEK", "Swedish Krona", "kr"),
    "norway": ("NOK", "Norwegian Krone", "kr"),
    "denmark": ("DKK", "Danish Krone", "kr"),
    "russia": ("RUB", "Russian Ruble", "₽"),
    "argentina": ("ARS", "Argentine Peso", "$"),
    "colombia": ("COP", "Colombian Peso", "$"),
    "peru": ("PEN", "Peruvian Sol", "S/."),
    "chile": ("CLP", "Chilean Peso", "$"),
    "kenya": ("KES", "Kenyan Shilling", "KSh"),
    "morocco": ("MAD", "Moroccan Dirham", "MAD"),
    "israel": ("ILS", "Israeli Shekel", "₪"),
    "jordan": ("JOD", "Jordanian Dinar", "JD"),
    "greece": ("EUR", "Euro", "€"),
    "portugal": ("EUR", "Euro", "€"),
    "austria": ("EUR", "Euro", "€"),
    "ireland": ("EUR", "Euro", "€"),
    "belgium": ("EUR", "Euro", "€"),
    "finland": ("EUR", "Euro", "€"),
    "croatia": ("EUR", "Euro", "€"),
}

_CITY_TO_COUNTRY = {
    "tokyo": "japan", "osaka": "japan", "kyoto": "japan",
    "bangkok": "thailand", "phuket": "thailand", "chiang mai": "thailand",
    "mumbai": "india", "delhi": "india", "goa": "india", "jaipur": "india",
    "new york": "usa", "nyc": "usa", "los angeles": "usa", "san francisco": "usa",
    "miami": "usa", "chicago": "usa", "las vegas": "usa", "hawaii": "usa",
    "london": "uk", "manchester": "uk", "edinburgh": "uk",
    "sydney": "australia", "melbourne": "australia",
    "paris": "france", "lyon": "france", "nice": "france",
    "berlin": "germany", "munich": "germany", "frankfurt": "germany",
    "rome": "italy", "milan": "italy", "venice": "italy", "florence": "italy",
    "barcelona": "spain", "madrid": "spain",
    "amsterdam": "netherlands",
    "dubai": "uae", "abu dhabi": "uae",
    "bali": "indonesia", "jakarta": "indonesia",
    "kuala lumpur": "malaysia", "penang": "malaysia",
    "beijing": "china", "shanghai": "china",
    "seoul": "south korea", "busan": "south korea",
    "mexico city": "mexico", "cancun": "mexico",
    "istanbul": "turkey", "antalya": "turkey", "ankara": "turkey",
    "zurich": "switzerland", "geneva": "switzerland",
    "toronto": "canada", "vancouver": "canada",
    "cairo": "egypt", "cape town": "south africa", "johannesburg": "south africa",
    "manila": "philippines", "ho chi minh city": "vietnam", "hanoi": "vietnam",
    "kathmandu": "nepal", "male": "maldives", "colombo": "sri lanka",
    "prague": "czech republic", "budapest": "hungary", "warsaw": "poland",
    "stockholm": "sweden", "oslo": "norway", "copenhagen": "denmark",
    "moscow": "russia", "buenos aires": "argentina", "bogota": "colombia",
    "lima": "peru", "santiago": "chile", "nairobi": "kenya",
    "marrakech": "morocco", "tel aviv": "israel", "jerusalem": "israel",
    "amman": "jordan", "athens": "greece", "lisbon": "portugal",
    "vienna": "austria", "dublin": "ireland", "brussels": "belgium",
    "helsinki": "finland", "zagreb": "croatia", "dubrovnik": "croatia",
    "singapore": "singapore",
}


def _get_home_currency(nationality: str) -> tuple[str, str, str] | None:
    nat = nationality.lower().strip()
    if nat in _NATIONALITY_CURRENCY:
        return _NATIONALITY_CURRENCY[nat]
    for key, val in _NATIONALITY_CURRENCY.items():
        if key in nat or nat in key:
            return val
    return None


def _resolve_destination_currency(destination: str) -> tuple[str, str, str] | None:
    dest = destination.lower().strip()
    country = _CITY_TO_COUNTRY.get(dest, dest)
    if country in _DESTINATION_CURRENCY:
        return _DESTINATION_CURRENCY[country]
    for key, val in _DESTINATION_CURRENCY.items():
        if key in dest or dest in key:
            return val
    return None


class ForexAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "forex"))

    async def run(self, request: TravelSearchRequest) -> dict:
        self._destination = request.destination
        home = _get_home_currency(request.nationality)
        local = _resolve_destination_currency(request.destination)

        local_code = local[0] if local else "local currency"
        dest_name = request.destination

        # Phase 1: Run real web searches in parallel for live data
        searches = {
            "usd_rate": execute_tool("web_search", {"query": f"1 USD to {local_code} exchange rate today"}),
            "eur_rate": execute_tool("web_search", {"query": f"1 EUR to {local_code} exchange rate today"}),
            "exchange_places": execute_tool("web_search", {"query": f"best place to exchange money in {dest_name} tourists 2025 2026"}),
            "atm_cards": execute_tool("web_search", {"query": f"ATM fees credit card acceptance {dest_name} tourists"}),
        }

        if home and home[0] not in ("USD", "EUR") and home[0] != local_code:
            searches["home_rate"] = execute_tool("web_search", {"query": f"1 {home[0]} to {local_code} exchange rate today"})

        keys = list(searches.keys())
        raw_results = await asyncio.gather(*searches.values(), return_exceptions=True)
        search_data = {}
        for key, result in zip(keys, raw_results):
            if isinstance(result, Exception):
                logger.warning(f"Forex search '{key}' failed: {result}")
                search_data[key] = f"Search failed: {result}"
            else:
                search_data[key] = result

        logger.info(f"Forex agent completed {len(search_data)} web searches for {dest_name}")

        # Phase 2: Feed real search results to LLM for structured JSON extraction
        home_section = ""
        if home:
            code, name, symbol = home
            home_section = (
                f"\nThe traveler's home currency is {name} ({code}, {symbol}).\n"
                f"You MUST include the exchange rate from {code} to {local_code} as a third entry in exchange_rates.\n"
            )
            if "home_rate" in search_data:
                home_section += f"\n=== WEB SEARCH: {code} to {local_code} rate ===\n{search_data['home_rate']}\n"

        local_section = ""
        if local:
            local_section = f"The local currency is {local[1]} ({local[0]}, {local[2]}).\n"

        prompt = (
            f"You are extracting REAL forex data from web search results for {dest_name}.\n"
            f"{local_section}"
            f"Traveler nationality: {request.nationality}\n"
            f"Travel dates: {request.departure_date} to {request.return_date or 'N/A'}\n"
            f"{home_section}\n"
            f"=== WEB SEARCH: USD to {local_code} exchange rate ===\n"
            f"{search_data.get('usd_rate', 'No results')}\n\n"
            f"=== WEB SEARCH: EUR to {local_code} exchange rate ===\n"
            f"{search_data.get('eur_rate', 'No results')}\n\n"
            f"=== WEB SEARCH: Best places to exchange money ===\n"
            f"{search_data.get('exchange_places', 'No results')}\n\n"
            f"=== WEB SEARCH: ATM and card info ===\n"
            f"{search_data.get('atm_cards', 'No results')}\n\n"
            f"CRITICAL: Extract the ACTUAL exchange rates from the web search results above. "
            f"These are REAL, CURRENT rates from the internet. Use the exact numbers from the search snippets. "
            f"Do NOT make up rates or use old/estimated rates.\n"
            f"If a search returned no results, use your best knowledge but mark it clearly.\n"
            f"Provide comprehensive advice on exchange locations, card acceptance, cash advice, ATMs, "
            f"tipping customs, and money tips specific to {dest_name}."
        )

        return await self.execute(prompt)

    async def _enrich_urls(self, data: dict) -> dict:
        source_urls = data.get("source_urls", [])
        if source_urls and all(self._is_clean_url(u) for u in source_urls):
            return data

        dest_country = self._destination.split(",")[-1].strip() if "," in self._destination else self._destination
        queries = [
            f"{dest_country} currency exchange rate tips travelers",
            f"{dest_country} ATM card payment guide tourists",
        ]

        urls = []
        for query in queries:
            url = await self._search_url(query)
            if url:
                urls.append(url)

        if urls:
            data["source_urls"] = urls
            logger.info(f"Forex URLs: {dest_country} -> {urls}")

        return data
