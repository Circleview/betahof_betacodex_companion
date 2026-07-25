MESSAGES = {
    "de": {
        "text_empty": "Text darf nicht leer sein.",
        "no_chunks": "Aus dem Text konnten keine Chunks erzeugt werden.",
        "source_not_found": "Quelle nicht gefunden.",
        "no_sources": "Noch keine Quellen importiert.",
        "no_matching_chunks": "Keine passenden Inhalte in den Quellen gefunden.",
        "role_required": "Diese Aktion erfordert die Rolle '{role}' (aktuell: '{user}').",
        "rate_limited": "Zu viele Anfragen - bitte kurz warten und es erneut versuchen.",
        "captcha_failed": "Sicherheitsprüfung fehlgeschlagen. Bitte Seite neu laden und erneut versuchen.",
    },
    "en": {
        "text_empty": "Text must not be empty.",
        "no_chunks": "No chunks could be created from the text.",
        "source_not_found": "Source not found.",
        "no_sources": "No sources imported yet.",
        "no_matching_chunks": "No matching content found in the sources.",
        "role_required": "This action requires the role '{role}' (current: '{user}').",
        "rate_limited": "Too many requests - please wait a moment and try again.",
        "captcha_failed": "Security check failed. Please reload the page and try again.",
    },
}

DEFAULT_LANG = "de"


def get_message(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    lang = lang if lang in MESSAGES else DEFAULT_LANG
    template = MESSAGES[lang].get(key, key)
    return template.format(**kwargs)
