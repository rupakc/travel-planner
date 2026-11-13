"""Notification text, served to apps (``GET /notifications/catalog``) and used
by the server senders. Placeholders are ``{name}`` format fields."""

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
        "social_idea_saved": "Someone saved your trip idea.",
        "social_new_follower": "You have a new follower.",
        "social_idea_liked": "Someone liked your trip idea.",
        "social_idea_comment": "Someone commented on your trip idea.",
        "quiz_h2h_invite": "You have a new head-to-head quiz challenge.",
        "quiz_h2h_result": "Your head-to-head quiz result is in.",
        "quiz_daily": "Your daily travel quiz is ready.",
        "weather_rain": "Rain is likely around {time}: take an umbrella for {slot}.",
        "weather_heat": "It will feel very hot around {time}: plan {slot} with water and shade.",
        "weather_cold": "It will be freezing around {time}: dress warmly for {slot}.",
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
        "social_idea_saved": "Alguien guardó tu idea de viaje.",
        "social_new_follower": "Tienes un nuevo seguidor.",
        "social_idea_liked": "A alguien le gustó tu idea de viaje.",
        "social_idea_comment": "Alguien comentó tu idea de viaje.",
        "quiz_h2h_invite": "Tienes un nuevo desafío de quiz cara a cara.",
        "quiz_h2h_result": "Ya está el resultado de tu quiz cara a cara.",
        "quiz_daily": "Tu quiz de viajes diario está listo.",
        "weather_rain": "Es probable que llueva sobre las {time}: lleva paraguas para {slot}.",
        "weather_heat": "Hará mucho calor sobre las {time}: prepara agua y sombra para {slot}.",
        "weather_cold": "Habrá heladas sobre las {time}: abrígate para {slot}.",
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
        "social_idea_saved": "Jemand hat deine Reiseidee gespeichert.",
        "social_new_follower": "Du hast einen neuen Follower.",
        "social_idea_liked": "Jemand hat deine Reiseidee geliked.",
        "social_idea_comment": "Jemand hat deine Reiseidee kommentiert.",
        "quiz_h2h_invite": "Du hast eine neue Quiz-Herausforderung im Duell.",
        "quiz_h2h_result": "Das Ergebnis deines Quiz-Duells ist da.",
        "quiz_daily": "Dein tägliches Reisequiz ist bereit.",
        "weather_rain": "Gegen {time} ist Regen wahrscheinlich: nimm einen Regenschirm für {slot} mit.",
        "weather_heat": "Gegen {time} wird es sehr heiß: plane {slot} mit Wasser und Schatten.",
        "weather_cold": "Gegen {time} herrscht Frost: zieh dich für {slot} warm an.",
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
        "social_idea_saved": "Quelqu'un a enregistré votre idée de voyage.",
        "social_new_follower": "Vous avez un nouvel abonné.",
        "social_idea_liked": "Quelqu'un a aimé votre idée de voyage.",
        "social_idea_comment": "Quelqu'un a commenté votre idée de voyage.",
        "quiz_h2h_invite": "Vous avez un nouveau défi quiz en duel.",
        "quiz_h2h_result": "Le résultat de votre duel quiz est arrivé.",
        "quiz_daily": "Votre quiz voyage du jour est prêt.",
        "weather_rain": "De la pluie est probable vers {time} : prenez un parapluie pour {slot}.",
        "weather_heat": "Il fera très chaud vers {time} : prévoyez eau et ombre pour {slot}.",
        "weather_cold": "Il gèlera vers {time} : habillez-vous chaudement pour {slot}.",
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
        "social_idea_saved": "किसी ने आपका यात्रा विचार सहेजा है।",
        "social_new_follower": "आपका एक नया फ़ॉलोअर है।",
        "social_idea_liked": "किसी को आपका यात्रा विचार पसंद आया।",
        "social_idea_comment": "किसी ने आपके यात्रा विचार पर टिप्पणी की।",
        "quiz_h2h_invite": "आपके लिए एक नई आमने-सामने क्विज़ चुनौती है।",
        "quiz_h2h_result": "आपके आमने-सामने क्विज़ का नतीजा आ गया है।",
        "quiz_daily": "आपका दैनिक यात्रा क्विज़ तैयार है।",
        "weather_rain": "{time} के आसपास बारिश की संभावना है: {slot} के लिए छाता रखें।",
        "weather_heat": "{time} के आसपास बहुत गर्मी होगी: {slot} के लिए पानी और छाया का इंतज़ाम रखें।",
        "weather_cold": "{time} के आसपास पाला पड़ेगा: {slot} के लिए गर्म कपड़े पहनें।",
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
        "social_idea_saved": "有人收藏了你的旅行创意。",
        "social_new_follower": "你有了一位新关注者。",
        "social_idea_liked": "有人赞了你的旅行创意。",
        "social_idea_comment": "有人评论了你的旅行创意。",
        "quiz_h2h_invite": "你收到了新的一对一问答挑战。",
        "quiz_h2h_result": "你的一对一问答结果出来了。",
        "quiz_daily": "你的每日旅行问答已就绪。",
        "weather_rain": "{time}前后可能下雨：{slot}请带伞。",
        "weather_heat": "{time}前后会非常炎热：{slot}请备好水并注意遮阴。",
        "weather_cold": "{time}前后气温在冰点以下：{slot}请穿暖和些。",
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
        "social_idea_saved": "কেউ আপনার ভ্রমণের আইডিয়া সংরক্ষণ করেছেন।",
        "social_new_follower": "আপনার একজন নতুন ফলোয়ার হয়েছে।",
        "social_idea_liked": "কেউ আপনার ভ্রমণের আইডিয়া পছন্দ করেছেন।",
        "social_idea_comment": "কেউ আপনার ভ্রমণের আইডিয়ায় মন্তব্য করেছেন।",
        "quiz_h2h_invite": "আপনার জন্য একটি নতুন মুখোমুখি কুইজ চ্যালেঞ্জ এসেছে।",
        "quiz_h2h_result": "আপনার মুখোমুখি কুইজের ফল এসেছে।",
        "quiz_daily": "আপনার দৈনিক ভ্রমণ কুইজ প্রস্তুত।",
        "weather_rain": "{time} নাগাদ বৃষ্টির সম্ভাবনা: {slot}-এর জন্য ছাতা নিন।",
        "weather_heat": "{time} নাগাদ প্রচণ্ড গরম পড়বে: {slot}-এর জন্য পানি ও ছায়ার ব্যবস্থা রাখুন।",
        "weather_cold": "{time} নাগাদ তাপমাত্রা হিমাঙ্কের নিচে থাকবে: {slot}-এর জন্য গরম কাপড় পরুন।",
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
