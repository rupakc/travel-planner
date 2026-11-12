"""Notification text, served to apps (``GET /notifications/catalog``) and used
by the server senders. T1 stub: English only; T2 fills the other six languages
and keeps these signatures. Placeholders are ``{name}`` format fields."""

DEFAULT_LOCALE = "en"

TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "trip_t30": "{destination} is {days} days away. Check your visa and entry rules.",
        "trip_t7": "{days} days to {destination}. Time to pack.",
        "trip_t1": "Tomorrow you fly to {destination}. Check in and review the weather.",
        "trip_morning": "Good morning from {destination}. Open Today for your plan.",
        "trip_morning_slot": "First up: {slot}",
        "trip_morning_tip": "Tip: {tip}",
        "trip_morning_weather": "Weather: {weather}",
        "nearby_arrival": "You're near {place}: {item} is {minutes} min away",
    },
    "es": {
        "trip_t30": "Faltan {days} días para {destination}. Revisa tu visado y los requisitos de entrada.",
        "trip_t7": "Faltan {days} días para {destination}. Hora de hacer la maleta.",
        "trip_t1": "Mañana vuelas a {destination}. Haz el check-in y mira el tiempo.",
        "trip_morning": "Buenos días desde {destination}. Abre Hoy para ver tu plan.",
        "trip_morning_slot": "Primero: {slot}",
        "trip_morning_tip": "Consejo: {tip}",
        "trip_morning_weather": "Tiempo: {weather}",
        "nearby_arrival": "Estás cerca de {place}: {item} está a {minutes} min",
    },
    "de": {
        "trip_t30": "Noch {days} Tage bis {destination}. Prüf dein Visum und die Einreiseregeln.",
        "trip_t7": "Noch {days} Tage bis {destination}. Zeit zum Packen.",
        "trip_t1": "Morgen fliegst du nach {destination}. Check dich ein und schau aufs Wetter.",
        "trip_morning": "Guten Morgen aus {destination}. Öffne Heute für deinen Plan.",
        "trip_morning_slot": "Als Erstes: {slot}",
        "trip_morning_tip": "Tipp: {tip}",
        "trip_morning_weather": "Wetter: {weather}",
        "nearby_arrival": "Du bist in der Nähe von {place}: {item} ist {minutes} Min. entfernt",
    },
    "fr": {
        "trip_t30": "Plus que {days} jours avant {destination}. Vérifiez votre visa et les règles d'entrée.",
        "trip_t7": "Plus que {days} jours avant {destination}. C'est le moment de faire vos valises.",
        "trip_t1": "Demain, vous partez pour {destination}. Enregistrez-vous et vérifiez la météo.",
        "trip_morning": "Bonjour depuis {destination}. Ouvrez Aujourd'hui pour voir votre programme.",
        "trip_morning_slot": "Au programme : {slot}",
        "trip_morning_tip": "Astuce : {tip}",
        "trip_morning_weather": "Météo : {weather}",
        "nearby_arrival": "Vous êtes près de {place} : {item} est à {minutes} min",
    },
    "hi": {
        "trip_t30": "{destination} में अब {days} दिन बचे हैं। अपना वीज़ा और प्रवेश नियम जाँच लें।",
        "trip_t7": "{destination} में {days} दिन बचे हैं। पैकिंग का समय है।",
        "trip_t1": "कल आप {destination} के लिए उड़ान भर रहे हैं। चेक-इन करें और मौसम देख लें।",
        "trip_morning": "{destination} से सुप्रभात। अपनी योजना के लिए आज खोलें।",
        "trip_morning_slot": "सबसे पहले: {slot}",
        "trip_morning_tip": "सुझाव: {tip}",
        "trip_morning_weather": "मौसम: {weather}",
        "nearby_arrival": "आप {place} के पास हैं: {item} {minutes} मिनट दूर है",
    },
    "zh": {
        "trip_t30": "距离 {destination} 还有 {days} 天。请检查签证和入境规定。",
        "trip_t7": "距离 {destination} 还有 {days} 天。该收拾行李了。",
        "trip_t1": "明天飞往 {destination}。请办理值机并查看天气。",
        "trip_morning": "{destination} 的早安。打开“今天”查看你的行程。",
        "trip_morning_slot": "第一站：{slot}",
        "trip_morning_tip": "小贴士：{tip}",
        "trip_morning_weather": "天气：{weather}",
        "nearby_arrival": "你在 {place} 附近：{item} 距离 {minutes} 分钟",
    },
    "bn": {
        "trip_t30": "{destination} যেতে আর {days} দিন বাকি। আপনার ভিসা ও প্রবেশের নিয়ম দেখে নিন।",
        "trip_t7": "{destination} যেতে আর {days} দিন বাকি। এবার গোছগাছের সময়।",
        "trip_t1": "আগামীকাল আপনি {destination}-এর উদ্দেশে উড়ছেন। চেক-ইন করুন ও আবহাওয়া দেখে নিন।",
        "trip_morning": "{destination} থেকে সুপ্রভাত। আপনার পরিকল্পনার জন্য আজ খুলুন।",
        "trip_morning_slot": "প্রথমে: {slot}",
        "trip_morning_tip": "পরামর্শ: {tip}",
        "trip_morning_weather": "আবহাওয়া: {weather}",
        "nearby_arrival": "আপনি {place}-এর কাছে আছেন: {item} {minutes} মিনিট দূরে",
    },
}


def _locale(locale: str | None) -> str:
    base = (locale or DEFAULT_LOCALE).replace("_", "-").split("-")[0].lower()
    return base if base in TEMPLATES else DEFAULT_LOCALE


def catalog(locale: str | None) -> dict:
    """``{"locale", "templates"}``; an unknown locale falls back to English."""
    loc = _locale(locale)
    return {"locale": loc, "templates": dict(TEMPLATES[loc])}


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return ""


def render(key: str, locale: str | None, **params) -> str:
    """Fill template ``key``; a missing param renders empty, an unknown key or
    locale falls back (key -> ``KeyError``, locale -> English)."""
    loc = _locale(locale)
    tpl = TEMPLATES[loc].get(key) or TEMPLATES[DEFAULT_LOCALE][key]
    return tpl.format_map(_Safe(params))
