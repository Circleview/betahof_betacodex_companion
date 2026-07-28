import { getLang } from '/i18n.js';

// Backlog #49: Sprachein-/ausgabe für den Frage-Antwort-Chat, portiert aus
// dem Beta Hof Logical Thinking Tool (client/src/hooks/useSpeech.js) - dort
// als React-Hook, hier als einfache Fabrikfunktion, da dieses Projekt kein
// React nutzt. Architektur unverändert übernommen:
// - STT bleibt browser-nativ (Web Speech API, kostenlos) - Text-Eingabe
//   funktioniert immer, auch ohne Unterstützung.
// - TTS läuft primär über den eigenen Server-Proxy (POST /api/speech,
//   Google Cloud TTS mit serverseitigem Key), mit automatischem Rückfall
//   auf die browsereigene speechSynthesis, falls kein Key hinterlegt ist
//   oder der Cloud-Aufruf fehlschlägt - Sprachausgabe fällt nie ganz aus.
const RECOGNITION_LANG_BY_LANG = { de: 'de-DE', en: 'en-US' };

function getRecognitionCtor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

// Gleiche Heuristik wie im CRT-Tool: lokale (Betriebssystem-)Stimmen vor
// Chrome-eigenen "Google"-Netzwerkstimmen bevorzugen, da letztere pro
// Vorlesung einen zusätzlichen Server-Roundtrip brauchen und damit eine
// unnötige, zusätzliche Fehlerquelle sind - hier ohnehin nur der Fallback,
// falls der Cloud-Weg über /api/speech nicht funktioniert.
const ENHANCED_VOICE_MARKERS = ['premium', 'enhanced', 'neural', 'natural', 'erweitert', 'verbessert'];
const PLAY_TIMEOUT_MS = 4000;

function pickBestVoice(voices, lang) {
  const langPrefix = lang.split('-')[0].toLowerCase();
  const candidates = voices.filter((v) => v.lang?.toLowerCase().startsWith(langPrefix));
  if (candidates.length === 0) return null;

  const rank = (voice) => {
    const name = voice.name.toLowerCase();
    if (voice.localService && ENHANCED_VOICE_MARKERS.some((marker) => name.includes(marker))) return 3;
    if (voice.localService) return 2;
    if (name.includes('google')) return 1;
    return 0;
  };

  return [...candidates].sort((a, b) => rank(b) - rank(a))[0];
}

// Entfernt Markdown-Syntax und Zitationsmarker ([1], [2], ...) aus einer
// Chat-Antwort, bevor sie vorgelesen wird - im CRT-Tool nicht nötig, da dort
// reiner Fließtext ohne Markdown/Zitate vorgelesen wurde. Bewusst
// regex-basiert statt über einen eigenen Parser, da für Sprachausgabe eine
// grobe Bereinigung reicht (keine korrekte HTML-Struktur nötig).
export function stripMarkdownForSpeech(text) {
  return text
    .replace(/\[(\d+)\]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)(.*?)\1/g, '$2')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function createSpeechController({ onTranscript, onListeningChange, onSpeakingChange } = {}) {
  const RecognitionCtor = getRecognitionCtor();
  const supported = Boolean(RecognitionCtor) && Boolean(window.speechSynthesis);

  let voices = [];
  if (window.speechSynthesis) {
    const loadVoices = () => {
      voices = window.speechSynthesis.getVoices();
    };
    loadVoices();
    window.speechSynthesis.addEventListener('voiceschanged', loadVoices);
  }

  let recognition = null;
  let transcriptBuffer = '';

  if (RecognitionCtor) {
    recognition = new RecognitionCtor();
    // continuous: true, damit eine kurze Sprechpause die Aufnahme nicht
    // automatisch beendet - die Frage soll erst beantwortet werden, wenn
    // die Aufnahme wirklich (durch erneuten Klick) abgeschlossen ist.
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) {
          transcriptBuffer = `${transcriptBuffer} ${result[0].transcript}`.trim();
        }
      }
    };
    recognition.onend = () => {
      onListeningChange?.(false);
      const finalText = transcriptBuffer.trim();
      transcriptBuffer = '';
      if (finalText) onTranscript?.(finalText);
    };
    recognition.onerror = () => {
      onListeningChange?.(false);
    };
  }

  function startListening() {
    if (!recognition) return;
    // Sprache erst beim Start setzen (nicht einmalig bei der Erstellung),
    // damit ein zwischenzeitlicher Sprachwechsel (DE/EN-Umschalter)
    // berücksichtigt wird.
    recognition.lang = RECOGNITION_LANG_BY_LANG[getLang()] || RECOGNITION_LANG_BY_LANG.de;
    transcriptBuffer = '';
    onListeningChange?.(true);
    recognition.start();
  }

  function stopListening() {
    // isListening/onTranscript werden erst in onend ausgelöst, sobald die
    // Aufnahme nach diesem Aufruf tatsächlich beendet ist.
    recognition?.stop();
  }

  // sequenceToken verweist auf die aktuell laufende Vorlesung - jeder
  // speak()/stopSpeaking()-Aufruf ersetzt ihn, wodurch noch ausstehende
  // Callbacks einer bereits abgebrochenen Vorlesung sich selbst als
  // überholt erkennen, statt eine veraltete Wiedergabe fortzusetzen.
  let sequenceToken = null;
  let currentAudio = null;

  function speak(text) {
    if (!text) return;
    window.speechSynthesis?.cancel();
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }

    const token = {};
    sequenceToken = token;
    const lang = RECOGNITION_LANG_BY_LANG[getLang()] || RECOGNITION_LANG_BY_LANG.de;

    function playLocal() {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      const bestVoice = pickBestVoice(voices, lang);
      if (bestVoice) utterance.voice = bestVoice;
      utterance.onstart = () => {
        if (sequenceToken !== token) return;
        onSpeakingChange?.(true);
      };
      const finish = () => {
        if (sequenceToken !== token) return;
        sequenceToken = null;
        onSpeakingChange?.(false);
      };
      utterance.onend = finish;
      utterance.onerror = finish;
      // Bekannter Browser-Bug: speak() direkt nach cancel() im selben Tick
      // kann stillschweigend verworfen werden - minimaler Timeout entkoppelt
      // beide Aufrufe.
      setTimeout(() => {
        if (sequenceToken !== token) return;
        window.speechSynthesis.speak(utterance);
      }, 50);
    }

    async function playCloud() {
      let blob;
      try {
        const res = await fetch('/api/speech', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
          body: JSON.stringify({ text }),
        });
        if (!res.ok) throw new Error('speech request failed');
        blob = await res.blob();
      } catch {
        if (sequenceToken === token) playLocal();
        return;
      }
      if (sequenceToken !== token) return;

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      currentAudio = audio;

      audio.onplaying = () => {
        if (sequenceToken !== token) return;
        onSpeakingChange?.(true);
      };
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (sequenceToken !== token) return;
        sequenceToken = null;
        onSpeakingChange?.(false);
      };
      audio.onerror = () => {
        // Wiedergabefehler für GENAU diese Antwort - auf die Browser-
        // Stimme zurückfallen statt stumm zu bleiben.
        if (sequenceToken !== token) return;
        playLocal();
      };

      // Zusätzliche Absicherung: play() kann in manchen Umgebungen (z.B.
      // ohne echte Nutzer-Interaktion) weder auflösen noch ablehnen - ohne
      // Zeitlimit bliebe die Vorlesung dann lautlos für immer hängen.
      const played = await Promise.race([
        audio.play().then(() => true).catch(() => false),
        new Promise((resolve) => setTimeout(() => resolve(false), PLAY_TIMEOUT_MS)),
      ]);
      if (!played) {
        audio.onplaying = null;
        audio.onended = null;
        audio.onerror = null;
        audio.pause();
        if (sequenceToken === token) playLocal();
      }
    }

    playCloud();
  }

  function stopSpeaking() {
    sequenceToken = null;
    window.speechSynthesis?.cancel();
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    onSpeakingChange?.(false);
  }

  return { supported, startListening, stopListening, speak, stopSpeaking };
}
