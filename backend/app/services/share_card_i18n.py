"""Localised strings for share cards (en es de fr hi zh bn).

Pure data, no imports beyond typing. ``scripts/build_card_fonts.py`` reads
this module to decide which glyphs each bundled font subset must keep, so
every string a card can draw must live here.
"""

from __future__ import annotations

LANGS = ("en", "es", "de", "fr", "hi", "zh", "bn")
DEFAULT_LANG = "en"

_EN_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()


def _t(
    *,
    one,
    other,
    trip,
    recap_place,
    recap,
    generic,
    trip_days,
    savings_total,
    savings_watch,
    quiz_daily,
    quiz_packs,
    quiz,
    quiz_score,
    status_day,
    status_place,
    status,
    by,
    origin,
    months,
    month_fmt,
    stats,
    stat_fmt="{n} {label}",
):
    return {
        "days_in_one": one,
        "days_in_other": other,
        "trip": trip,
        "recap_place": recap_place,
        "recap": recap,
        "generic": generic,
        "trip_days": trip_days,
        "savings_total": savings_total,
        "savings_watch": savings_watch,
        "quiz_daily": quiz_daily,
        "quiz_packs": quiz_packs,
        "quiz": quiz,
        "quiz_score": quiz_score,
        "status_day": status_day,
        "status_place": status_place,
        "status": status,
        "by": by,
        "from": origin,
        "months": months,
        "month_fmt": month_fmt,
        "stats": stats,
        "stat_fmt": stat_fmt,
    }


STRINGS: dict[str, dict] = {
    "en": _t(
        one="{n} day in {place}",
        other="{n} days in {place}",
        trip="Trip to {place}",
        recap_place="My trip to {place}: recap",
        recap="My trip: recap",
        generic="My trip",
        trip_days="{n}-day trip",
        savings_total="Caught drops worth {amount}",
        savings_watch="Watching prices for my next trip",
        quiz_daily="Daily quiz",
        quiz_packs={
            "flags": "Flags quiz",
            "capitals": "Capitals quiz",
            "landmarks": "Landmarks quiz",
            "cuisine": "Cuisine quiz",
        },
        quiz="Quiz",
        quiz_score="{label}: {correct}/{total}",
        status_day="Day {n} in {place}",
        status_place="On a trip in {place}",
        status="On a trip",
        by="by {name}",
        origin="from {origin}",
        months=_EN_MONTHS,
        month_fmt="{month} {year}",
        stats={
            "activities": ("activity", "activities"),
            "hotels": ("hotel", "hotels"),
            "places": ("place", "places"),
            "drops_caught": ("drop caught", "drops caught"),
            "targets_hit": ("target hit", "targets hit"),
            "correct": ("correct answer", "correct answers"),
        },
    ),
    "es": _t(
        one="{n} día en {place}",
        other="{n} días en {place}",
        trip="Viaje a {place}",
        recap_place="Mi viaje a {place}: resumen",
        recap="Mi viaje: resumen",
        generic="Mi viaje",
        trip_days="Viaje de {n} días",
        savings_total="Bajadas de precio por valor de {amount}",
        savings_watch="Vigilando precios para mi próximo viaje",
        quiz_daily="Quiz diario",
        quiz_packs={
            "flags": "Quiz de banderas",
            "capitals": "Quiz de capitales",
            "landmarks": "Quiz de monumentos",
            "cuisine": "Quiz de gastronomía",
        },
        quiz="Quiz",
        quiz_score="{label}: {correct}/{total}",
        status_day="Día {n} en {place}",
        status_place="De viaje en {place}",
        status="De viaje",
        by="por {name}",
        origin="desde {origin}",
        months=(
            "enero febrero marzo abril mayo junio julio agosto septiembre "
            "octubre noviembre diciembre"
        ).split(),
        month_fmt="{month} de {year}",
        stats={
            "activities": ("actividad", "actividades"),
            "hotels": ("hotel", "hoteles"),
            "places": ("lugar", "lugares"),
            "drops_caught": ("bajada detectada", "bajadas detectadas"),
            "targets_hit": ("objetivo alcanzado", "objetivos alcanzados"),
            "correct": ("respuesta correcta", "respuestas correctas"),
        },
    ),
    "de": _t(
        one="{n} Tag in {place}",
        other="{n} Tage in {place}",
        trip="Reise nach {place}",
        recap_place="Meine Reise nach {place}: Rückblick",
        recap="Meine Reise: Rückblick",
        generic="Meine Reise",
        trip_days="{n}-Tage-Reise",
        savings_total="Preissenkungen im Wert von {amount} erwischt",
        savings_watch="Ich beobachte Preise für meine nächste Reise",
        quiz_daily="Tägliches Quiz",
        quiz_packs={
            "flags": "Flaggen-Quiz",
            "capitals": "Hauptstädte-Quiz",
            "landmarks": "Sehenswürdigkeiten-Quiz",
            "cuisine": "Küchen-Quiz",
        },
        quiz="Quiz",
        quiz_score="{label}: {correct}/{total}",
        status_day="Tag {n} in {place}",
        status_place="Unterwegs in {place}",
        status="Unterwegs",
        by="von {name}",
        origin="ab {origin}",
        months=(
            "Januar Februar März April Mai Juni Juli August September "
            "Oktober November Dezember"
        ).split(),
        month_fmt="{month} {year}",
        stats={
            "activities": ("Aktivität", "Aktivitäten"),
            "hotels": ("Hotel", "Hotels"),
            "places": ("Ort", "Orte"),
            "drops_caught": ("Preissenkung entdeckt", "Preissenkungen entdeckt"),
            "targets_hit": ("Ziel erreicht", "Ziele erreicht"),
            "correct": ("richtige Antwort", "richtige Antworten"),
        },
    ),
    "fr": _t(
        one="{n} jour à {place}",
        other="{n} jours à {place}",
        trip="Voyage à {place}",
        recap_place="Mon voyage à {place} : récap",
        recap="Mon voyage : récap",
        generic="Mon voyage",
        trip_days="Voyage de {n} jours",
        savings_total="Baisses de prix repérées : {amount}",
        savings_watch="Je surveille les prix pour mon prochain voyage",
        quiz_daily="Quiz du jour",
        quiz_packs={
            "flags": "Quiz drapeaux",
            "capitals": "Quiz capitales",
            "landmarks": "Quiz monuments",
            "cuisine": "Quiz cuisine",
        },
        quiz="Quiz",
        quiz_score="{label} : {correct}/{total}",
        status_day="Jour {n} à {place}",
        status_place="En voyage à {place}",
        status="En voyage",
        by="par {name}",
        origin="depuis {origin}",
        months=(
            "janvier février mars avril mai juin juillet août septembre "
            "octobre novembre décembre"
        ).split(),
        month_fmt="{month} {year}",
        stats={
            "activities": ("activité", "activités"),
            "hotels": ("hôtel", "hôtels"),
            "places": ("lieu", "lieux"),
            "drops_caught": ("baisse repérée", "baisses repérées"),
            "targets_hit": ("objectif atteint", "objectifs atteints"),
            "correct": ("bonne réponse", "bonnes réponses"),
        },
    ),
    "hi": _t(
        one="{place} में {n} दिन",
        other="{place} में {n} दिन",
        trip="{place} की यात्रा",
        recap_place="{place} की मेरी यात्रा: झलकियाँ",
        recap="मेरी यात्रा: झलकियाँ",
        generic="मेरी यात्रा",
        trip_days="{n} दिन की यात्रा",
        savings_total="{amount} तक की कीमत गिरावट पकड़ी",
        savings_watch="अगली यात्रा के लिए कीमतों पर नज़र",
        quiz_daily="रोज़ का क्विज़",
        quiz_packs={
            "flags": "झंडा क्विज़",
            "capitals": "राजधानी क्विज़",
            "landmarks": "मशहूर जगह क्विज़",
            "cuisine": "खान-पान क्विज़",
        },
        quiz="क्विज़",
        quiz_score="{label}: {correct}/{total}",
        status_day="{place} में दिन {n}",
        status_place="{place} की यात्रा पर",
        status="यात्रा पर",
        by="{name} द्वारा",
        origin="{origin} से",
        months=("जनवरी फ़रवरी मार्च अप्रैल मई जून जुलाई अगस्त सितंबर अक्टूबर नवंबर दिसंबर").split(),
        month_fmt="{month} {year}",
        stats={
            "activities": ("गतिविधि", "गतिविधियाँ"),
            "hotels": ("होटल", "होटल"),
            "places": ("जगह", "जगहें"),
            "drops_caught": ("गिरावट पकड़ी", "गिरावटें पकड़ीं"),
            "targets_hit": ("लक्ष्य पूरा", "लक्ष्य पूरे"),
            "correct": ("सही जवाब", "सही जवाब"),
        },
    ),
    "zh": _t(
        one="{place} {n} 天",
        other="{place} {n} 天",
        trip="{place}之旅",
        recap_place="我的{place}之旅：回顾",
        recap="我的旅行：回顾",
        generic="我的旅行",
        trip_days="{n} 天旅行",
        savings_total="捕捉到价值 {amount} 的降价",
        savings_watch="正在为下一次旅行关注价格",
        quiz_daily="每日测验",
        quiz_packs={
            "flags": "国旗测验",
            "capitals": "首都测验",
            "landmarks": "地标测验",
            "cuisine": "美食测验",
        },
        quiz="测验",
        quiz_score="{label}：{correct}/{total}",
        status_day="在{place}的第 {n} 天",
        status_place="正在{place}旅行",
        status="旅行中",
        by="作者：{name}",
        origin="出发地：{origin}",
        months=[f"{i}月" for i in range(1, 13)],
        month_fmt="{year}年{month}",
        stats={
            "activities": ("项活动", "项活动"),
            "hotels": ("家酒店", "家酒店"),
            "places": ("个地点", "个地点"),
            "drops_caught": ("次降价", "次降价"),
            "targets_hit": ("个目标达成", "个目标达成"),
            "correct": ("题答对", "题答对"),
        },
        stat_fmt="{n} {label}",
    ),
    "bn": _t(
        one="{place}-এ {n} দিন",
        other="{place}-এ {n} দিন",
        trip="{place} ভ্রমণ",
        recap_place="আমার {place} ভ্রমণ: ঝলক",
        recap="আমার ভ্রমণ: ঝলক",
        generic="আমার ভ্রমণ",
        trip_days="{n} দিনের ভ্রমণ",
        savings_total="{amount} মূল্যের দাম কমা ধরেছি",
        savings_watch="পরের ভ্রমণের জন্য দামের ওপর নজর",
        quiz_daily="দৈনিক কুইজ",
        quiz_packs={
            "flags": "পতাকা কুইজ",
            "capitals": "রাজধানী কুইজ",
            "landmarks": "দর্শনীয় স্থান কুইজ",
            "cuisine": "খাবার কুইজ",
        },
        quiz="কুইজ",
        quiz_score="{label}: {correct}/{total}",
        status_day="{place}-এ দিন {n}",
        status_place="{place} ভ্রমণে",
        status="ভ্রমণে",
        by="{name} কর্তৃক",
        origin="{origin} থেকে",
        months=(
            "জানুয়ারি ফেব্রুয়ারি মার্চ এপ্রিল মে জুন জুলাই আগস্ট সেপ্টেম্বর অক্টোবর নভেম্বর ডিসেম্বর"
        ).split(),
        month_fmt="{month} {year}",
        stats={
            "activities": ("কার্যক্রম", "কার্যক্রম"),
            "hotels": ("হোটেল", "হোটেল"),
            "places": ("স্থান", "স্থান"),
            "drops_caught": ("দাম কমা ধরা", "দাম কমা ধরা"),
            "targets_hit": ("লক্ষ্য পূরণ", "লক্ষ্য পূরণ"),
            "correct": ("সঠিক উত্তর", "সঠিক উত্তর"),
        },
    ),
}


def norm_lang(lang: str | None) -> str:
    return lang if lang in STRINGS else DEFAULT_LANG


def all_text() -> str:
    """Every literal character the catalogue can draw (for font subsetting)."""
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(STRINGS)
    return "".join(out)
