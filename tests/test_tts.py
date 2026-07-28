import base64
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from app import tts


def _mock_response(payload: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


def test_synthesize_speech_returns_decoded_audio_bytes(monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test-key")
    audio_bytes = b"fake-mp3-bytes"
    resp = _mock_response({"audioContent": base64.b64encode(audio_bytes).decode("ascii")})

    with patch("app.tts.urllib.request.urlopen", return_value=resp) as mock_urlopen:
        result = tts.synthesize_speech("Hallo Welt", lang="de")

    assert result == audio_bytes
    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["input"] == {"text": "Hallo Welt"}
    assert body["voice"]["languageCode"] == "de-DE"


def test_synthesize_speech_uses_language_specific_voice(monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test-key")
    resp = _mock_response({"audioContent": base64.b64encode(b"x").decode("ascii")})

    with patch("app.tts.urllib.request.urlopen", return_value=resp) as mock_urlopen:
        tts.synthesize_speech("Hello", lang="en")

    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["voice"]["languageCode"] == "en-US"
    assert body["voice"]["name"] == tts.VOICE_NAMES_BY_LANG["en"]


def test_synthesize_speech_env_override_wins_for_voice_name(monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_TTS_VOICE_NAME", "de-DE-Custom-Voice")
    resp = _mock_response({"audioContent": base64.b64encode(b"x").decode("ascii")})

    with patch("app.tts.urllib.request.urlopen", return_value=resp) as mock_urlopen:
        tts.synthesize_speech("Hallo", lang="de")

    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["voice"]["name"] == "de-DE-Custom-Voice"


def test_synthesize_speech_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)

    with pytest.raises(tts.SpeechSynthesisError):
        tts.synthesize_speech("Hallo Welt")


def test_synthesize_speech_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test-key")
    error = urllib.error.HTTPError(
        url="https://texttospeech.googleapis.com/v1/text:synthesize",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=MagicMock(read=lambda: b'{"error": "quota exceeded"}'),
    )

    with patch("app.tts.urllib.request.urlopen", side_effect=error):
        with pytest.raises(tts.SpeechSynthesisError):
            tts.synthesize_speech("Hallo Welt")


def test_synthesize_speech_raises_when_no_audio_content_returned(monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test-key")
    resp = _mock_response({})

    with patch("app.tts.urllib.request.urlopen", return_value=resp):
        with pytest.raises(tts.SpeechSynthesisError):
            tts.synthesize_speech("Hallo Welt")
