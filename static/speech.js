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

// Vorlesegeschwindigkeit: eine feste Stufenliste statt eines Sliders, per
// Klick durchgeschaltet (siehe cyclePlaybackRate) - reicht für diesen
// Anwendungsfall und braucht kein zusätzliches UI-Element. In localStorage
// gemerkt (wie die Sprachwahl in i18n.js), gilt also für alle Antworten
// gleichermaßen, nicht nur für die gerade abgespielte.
export const SPEECH_RATES = [1, 1.25, 1.5, 1.75, 2];
const SPEECH_RATE_STORAGE_KEY = 'speechRate';

function getStoredPlaybackRate() {
  const stored = parseFloat(localStorage.getItem(SPEECH_RATE_STORAGE_KEY));
  return SPEECH_RATES.includes(stored) ? stored : SPEECH_RATES[0];
}

// Bewusste Entscheidung (2026-07-28): Safari/iOS implementiert die Web
// Speech Recognition API bis heute grundsätzlich nicht (jeder Browser auf
// iOS basiert auf WebKit, betrifft also alle iOS-Browser gleichermaßen) -
// dort bleibt der Mikrofon-Button daher ausgeblendet (supported=false),
// Tippen + Vorlesen der Antwort (TTS, unabhängig von STT) bleiben aber
// nutzbar. Alternative wäre serverseitige Spracherkennung gewesen
// (Aufnahme per MediaRecorder + Transkription z.B. über OpenAI, analog zum
// bestehenden Audio-Import) - explizit NICHT umgesetzt, da das echte Kosten
// pro gestellter Sprachfrage verursacht hätte; Aufwand/Kosten wurden dem
// Nutzen (Mikrofon auch auf iPhone) nicht für gerechtfertigt gehalten.
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
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)(.*?)\1/g, '$2')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function createSpeechController({ onTranscript, onListeningChange, onSpeakingChange } = {}) {
  const RecognitionCtor = getRecognitionCtor();
  const supported = Boolean(RecognitionCtor) && Boolean(window.speechSynthesis);

  let playbackRate = getStoredPlaybackRate();

  function getPlaybackRate() {
    return playbackRate;
  }

  // Schaltet zur nächsten Stufe in SPEECH_RATES weiter (mit Wraparound) und
  // wendet sie sofort auf eine gerade laufende Cloud-Wiedergabe an -
  // HTMLAudioElement erlaubt das live, ohne Neustart. Bei der
  // Browser-Stimme (speechSynthesis) greift die neue Rate dagegen erst bei
  // der nächsten Vorlesung, da eine laufende SpeechSynthesisUtterance ihre
  // rate nicht nachträglich ändern kann.
  function cyclePlaybackRate() {
    const currentIndex = SPEECH_RATES.indexOf(playbackRate);
    playbackRate = SPEECH_RATES[(currentIndex + 1) % SPEECH_RATES.length];
    localStorage.setItem(SPEECH_RATE_STORAGE_KEY, String(playbackRate));
    if (currentAudio) currentAudio.playbackRate = playbackRate;
    return playbackRate;
  }

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

    function playLocal(spokenText) {
      const utterance = new SpeechSynthesisUtterance(spokenText);
      utterance.lang = lang;
      utterance.rate = playbackRate;
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

    // Satzweise statt als ein einziger Google-TTS-Aufruf für die komplette
    // Antwort: bei mehrsätzigen Antworten musste bislang der GESAMTE Text
    // fertig synthetisiert sein, bevor überhaupt etwas hörbar war - hörbar
    // lange Verzögerung gerade bei längeren Antworten. Jetzt werden alle
    // Sätze SOFORT parallel angefragt (Google TTS braucht für einen
    // einzelnen Satz nur einen Bruchteil der Zeit einer ganzen Antwort),
    // die Wiedergabe startet schon mit dem ersten fertigen Satz, während
    // die übrigen im Hintergrund weiter synthetisiert werden - klassisches
    // Audio-Pipelining, keine Google-Streaming-API nötig (die wäre nur per
    // gRPC statt des hier genutzten einfachen REST-Aufrufs verfügbar).
    function splitSentences(fullText) {
      return fullText
        .split(/(?<=[.!?])\s+/)
        .map((s) => s.trim())
        .filter(Boolean);
    }

    // priority nutzt die Fetch-Priority-Hints-API (unterstützt in Chrome/
    // Edge, in anderen Browsern folgenlos ignoriert): der erste Satz blockiert
    // den Beginn der Wiedergabe und bekommt deshalb 'high', alle folgenden
    // 'low' - Aufruf-Reihenfolge allein (map() unten) garantiert zwar schon,
    // dass Satz 1 immer ALS ERSTES angefragt wird, aber erst der Priority-
    // Hint sorgt dafür, dass er bei tatsächlicher Konkurrenz um eine
    // begrenzte Ressource (Browser-Verbindungslimit, Bandbreite) nicht von
    // den gleichzeitig abgeschickten späteren Sätzen eingeholt werden kann.
    function fetchSpeechBlob(sentenceText, priority) {
      return fetch('/api/speech', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
        body: JSON.stringify({ text: sentenceText }),
        priority,
      }).then((res) => {
        if (!res.ok) throw new Error('speech request failed');
        return res.blob();
      });
    }

    async function playCloud() {
      const sentences = splitSentences(text);
      if (sentences.length === 0) return;
      const blobPromises = sentences.map((sentence, i) =>
        fetchSpeechBlob(sentence, i === 0 ? 'high' : 'low')
      );

      for (let i = 0; i < sentences.length; i++) {
        if (sequenceToken !== token) return;
        let blob;
        try {
          blob = await blobPromises[i];
        } catch {
          if (sequenceToken === token) playLocal(sentences.slice(i).join(' '));
          return;
        }
        if (sequenceToken !== token) return;

        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.playbackRate = playbackRate;
        currentAudio = audio;
        audio.onplaying = () => {
          if (sequenceToken !== token) return;
          onSpeakingChange?.(true);
        };

        // Zusätzliche Absicherung: play() kann in manchen Umgebungen (z.B.
        // ohne echte Nutzer-Interaktion) weder auflösen noch ablehnen -
        // ohne Zeitlimit bliebe die Vorlesung dann lautlos für immer hängen.
        const started = await Promise.race([
          audio.play().then(() => true).catch(() => false),
          new Promise((resolve) => setTimeout(() => resolve(false), PLAY_TIMEOUT_MS)),
        ]);
        if (!started) {
          audio.onplaying = null;
          audio.pause();
          if (sequenceToken === token) playLocal(sentences.slice(i).join(' '));
          return;
        }

        let hadError = false;
        await new Promise((resolve) => {
          audio.onended = () => {
            URL.revokeObjectURL(url);
            resolve();
          };
          audio.onerror = () => {
            hadError = true;
            resolve();
          };
        });
        if (sequenceToken !== token) return;
        if (hadError) {
          // Wiedergabefehler ab GENAU diesem Satz - auf die Browser-Stimme
          // zurückfallen statt stumm zu bleiben oder abzubrechen.
          playLocal(sentences.slice(i).join(' '));
          return;
        }
      }

      if (sequenceToken === token) {
        sequenceToken = null;
        onSpeakingChange?.(false);
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

  return {
    supported,
    startListening,
    stopListening,
    speak,
    stopSpeaking,
    getPlaybackRate,
    cyclePlaybackRate,
  };
}
