"""Backlog #49: Sprachausgabe (TTS) für Chat-Antworten - Server-seitiger
Proxy zu Google Cloud Text-to-Speech, damit der API-Key nie im Frontend
landet. Reiner REST-Call statt SDK (gleiches Muster wie app/captcha.py für
Cloudflare Turnstile) - kein zusätzliches SDK/Framework nötig.

Übernommen aus dem Beta Hof Logical Thinking Tool (server/src/tts.js),
dort bereits erfolgreich mit Chirp3-HD-Stimmen im Einsatz.
"""
import base64
import json
import os
import urllib.error
import urllib.request

ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
TIMEOUT_SECONDS = 15

# Beide Stimmennamen per echter GET /v1/voices-Abfrage verifiziert (nicht
# nur aus dem Chirp3-HD-Namensschema geraten - das CRT-Tool warnt in
# server/src/tts.js ausdrücklich vor genau diesem Fehler, dort führte ein
# nicht verifizierter Name - de-DE-Neural2-F - zu stillen Fehlern) und live
# gegen die echte API getestet (2026-07-28, beide liefern gültiges MP3).
VOICE_NAMES_BY_LANG = {
    "de": "de-DE-Chirp3-HD-Enceladus",
    "en": "en-US-Chirp3-HD-Charon",
}
LANGUAGE_CODES_BY_LANG = {
    "de": "de-DE",
    "en": "en-US",
}


def _resolve_voice_name(lang: str) -> str:
    # Env-Var-Override hat Vorrang (z.B. für eine andere Stimme oder zur
    # Korrektur der obigen, unverifizierten en-US-Annahme ohne Code-Änderung).
    override = os.environ.get("GOOGLE_TTS_VOICE_NAME")
    if override:
        return override
    return VOICE_NAMES_BY_LANG.get(lang, VOICE_NAMES_BY_LANG["de"])


class SpeechSynthesisError(Exception):
    pass


def synthesize_speech(text: str, lang: str = "de", speaking_rate: float = 1.0) -> bytes:
    api_key = os.environ.get("GOOGLE_TTS_API_KEY", "")
    if not api_key:
        raise SpeechSynthesisError("Kein Google-TTS-Key konfiguriert")

    language_code = LANGUAGE_CODES_BY_LANG.get(lang, LANGUAGE_CODES_BY_LANG["de"])
    voice_name = _resolve_voice_name(lang)
    # Live gegen die echte API verifiziert (2026-07-31, Chirp3-HD): speakingRate
    # 0.5/1.0/1.75/2.0 liefern jeweils gültiges, korrekt proportional kürzeres/
    # längeres Audio - das Sprachmodell synthetisiert selbst in der Zielrate.
    # Wichtig, DAMIT client-seitig source.playbackRate bei 1 bleiben kann (kein
    # Resampling mehr nötig): das vermeidet gleich zwei Nebenwirkungen -
    # AudioBufferSourceNode.playbackRate verzerrt sonst die Tonhöhe (ohne
    # Korrektur, wie ein schneller abgespieltes Tonband), UND ein <audio>-
    # Element mit reassigned src zwischen Sätzen (Alternativlösung, verworfen)
    # verursacht ein hörbares Knacken zwischen Sätzen, da <audio> unabhängig
    # kodierte MP3-Segmente nicht wirklich "gapless" wiedergibt - anders als
    # decodeAudioData/AudioBufferSourceNode, das dafür spezifiziert ist.
    clamped_rate = max(0.25, min(4.0, speaking_rate))

    payload = json.dumps(
        {
            "input": {"text": text},
            "voice": {"languageCode": language_code, "name": voice_name},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": clamped_rate},
        }
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{ENDPOINT}?key={api_key}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SpeechSynthesisError(f"Google TTS Fehler ({e.code}): {body}") from e
    except Exception as e:
        raise SpeechSynthesisError(f"Google TTS nicht erreichbar: {e}") from e

    audio_content = result.get("audioContent")
    if not audio_content:
        raise SpeechSynthesisError("Google TTS lieferte keine Audiodaten")
    return base64.b64decode(audio_content)
