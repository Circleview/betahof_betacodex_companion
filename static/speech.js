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

const AudioContextCtor = window.AudioContext || window.webkitAudioContext || null;

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

  // Schaltet zur nächsten Stufe in SPEECH_RATES weiter (mit Wraparound).
  // Greift erst ab der nächsten Vorlesung (bzw. dem nächsten, noch nicht
  // angefragten Satz einer laufenden Vorlesung): die Rate wird serverseitig
  // von Google TTS selbst synthetisiert (siehe fetchSpeechBlob/playCloud
  // unten), ein bereits angefragter/abgespielter Satz kann seine Rate daher
  // nicht mehr nachträglich ändern, ohne ihn neu anzufragen. Zwei
  // Alternativen wurden verworfen (siehe Git-Historie 2026-07-31): (1)
  // client-seitiges Resampling per AudioBufferSourceNode.playbackRate -
  // verzerrt ohne Tonhöhenkorrektur die Stimme bei höherem Tempo; (2) ein
  // wiederverwendetes <audio>-Element mit dessen (tonhöhenkorrigierendem)
  // playbackRate - verursachte ein hörbares Knacken zwischen Sätzen, da
  // <audio> unabhängig kodierte MP3-Segmente nicht wirklich gapless
  // wiedergibt (bekannte Browser-Einschränkung, anders als
  // decodeAudioData/AudioBufferSourceNode unten, das dafür spezifiziert ist).
  function cyclePlaybackRate() {
    const currentIndex = SPEECH_RATES.indexOf(playbackRate);
    playbackRate = SPEECH_RATES[(currentIndex + 1) % SPEECH_RATES.length];
    localStorage.setItem(SPEECH_RATE_STORAGE_KEY, String(playbackRate));
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
  let currentSource = null;

  // Bug (2026-07-31, live auf Produktion nachgestellt): ein klassisches
  // <audio>.play() schlug dort öfter mit "NotAllowedError: play() failed
  // because the user didn't interact with the document first" fehl - der
  // Fallback auf die Browser-Stimme (playLocal) brauchte dieselbe frische
  // Nutzer-Geste und scheiterte dann ebenfalls, meist lautlos. Ursache: bis
  // die Audiodaten von /api/speech eintreffen, ist ein spürbarer Netzwerk-
  // Roundtrip vergangen (auf Produktion länger als lokal) - das kurze
  // Zeitfenster, in dem Browser Ton-Wiedergabe nach einem Klick erlauben
  // ("transient activation"), ist bis dahin oft schon abgelaufen. Fix:
  // einen AudioContext SYNCHRON im Klick-Handler (noch vor jedem await)
  // "entsperren" - einmal entsperrt, bleibt er es dauerhaft, auch wenn die
  // eigentliche Wiedergabe (über decodeAudioData/AudioBufferSourceNode)
  // erst Sekunden später beginnt. Einmalig erzeugt und wiederverwendet
  // (viele AudioContext-Instanzen sind unnötig und in manchen Browsern
  // limitiert). Zwei Alternativen dazu (jeweils ein <audio>-Element statt
  // AudioContext) wurden ausprobiert und wieder verworfen, siehe
  // Kommentar bei cyclePlaybackRate.
  let audioContext = null;

  function ensureAudioContextUnlocked() {
    if (AudioContextCtor && !audioContext) {
      audioContext = new AudioContextCtor();
    }
    if (audioContext?.state === 'suspended') {
      audioContext.resume();
    }
  }

  // Bug (2026-08-01): das automatische Vorlesen nach einer per Mikrofon
  // gestellten Frage ("Gespräch") blieb stumm. Ursache: die Freischaltung
  // oben passierte bisher NUR innerhalb von speak() - für eine getippte
  // Frage reicht das, weil der Klick auf den Vorlesen-Button direkt davor
  // liegt. Bei der Sprachfrage läuft speak() aber automatisch erst am Ende
  // einer langen asynchronen Kette (Aufnahme stoppen -> Transkription ->
  // Absenden -> auf die komplette Antwort warten) - zu dem Zeitpunkt ist
  // die ursprüngliche Klick-Geste (Mikrofon-Button) längst verstrichen.
  // Freischaltung deshalb zusätzlich hier, synchron im Klick-Handler, der
  // die Aufnahme startet - bleibt dann (wie oben beschrieben) dauerhaft
  // entsperrt, auch für das spätere automatische speak().
  function startListening() {
    if (!recognition) return;
    ensureAudioContextUnlocked();
    // Sprache erst beim Start setzen (nicht einmalig bei der Erstellung),
    // damit ein zwischenzeitlicher Sprachwechsel (DE/EN-Umschalter)
    // berücksichtigt wird.
    recognition.lang = RECOGNITION_LANG_BY_LANG[getLang()] || RECOGNITION_LANG_BY_LANG.de;
    transcriptBuffer = '';
    onListeningChange?.(true);
    recognition.start();
  }

  function speak(text) {
    if (!text) return;
    window.speechSynthesis?.cancel();
    if (currentSource) {
      try {
        currentSource.stop();
      } catch (err) {
        // Bereits gestoppt/durchgelaufen - kein Fehlerfall.
      }
      currentSource = null;
    }

    // .resume() muss synchron im Klick-Handler aufgerufen werden - nicht
    // erst später in playCloud() nach dem ersten await, sonst wäre die
    // Nutzer-Geste für die Freischaltung schon verstrichen. Für eine
    // getippte Frage übernimmt DAS genau diese Zeile hier; für eine per
    // Mikrofon gestellte Frage ist der AudioContext an dieser Stelle bereits
    // durch startListening() oben entsperrt.
    ensureAudioContextUnlocked();

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
        body: JSON.stringify({ text: sentenceText, rate: playbackRate }),
        priority,
      }).then((res) => {
        if (!res.ok) throw new Error('speech request failed');
        return res.blob();
      });
    }

    async function playCloud() {
      // Ohne Web-Audio-API-Unterstützung (praktisch nur sehr alte Browser)
      // direkt auf die Browser-Stimme ausweichen, statt eine Kette aus
      // Fehlversuchen zu provozieren.
      if (!audioContext) {
        playLocal(text);
        return;
      }

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

        // Decodieren statt eines <audio src=blob:...>-Elements - siehe
        // Kommentar bei audioContext oben: das eigentliche Abspielen läuft
        // über den bereits per Nutzer-Geste entsperrten AudioContext und
        // braucht dadurch KEINE eigene, frische Aktivierung mehr, egal wie
        // lange der Roundtrip zu /api/speech gedauert hat. decodeAudioData
        // dekodiert MP3s zudem lückenlos (kein Encoder-Priming-Artefakt an
        // Satzgrenzen) - <audio>-Elemente können das nicht zuverlässig
        // ("gapless MP3 playback" ist eine bekannte Browser-Einschränkung).
        let audioBuffer;
        try {
          const arrayBuffer = await blob.arrayBuffer();
          audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        } catch {
          if (sequenceToken === token) playLocal(sentences.slice(i).join(' '));
          return;
        }
        if (sequenceToken !== token) return;

        // KEIN source.playbackRate hier setzen (Bug, 2026-07-31): Google TTS
        // liefert das Audio oben bereits fertig in der gewünschten Rate
        // (fetchSpeechBlob schickt sie mit) - das Sprachmodell synthetisiert
        // selbst schneller/langsamer. AudioBufferSourceNode.playbackRate
        // dagegen resamplet nachträglich OHNE Tonhöhenkorrektur - das
        // frühere Setzen hier war die Ursache für die "Micky-Maus-Stimme"
        // bei höherem Tempo.
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);
        currentSource = source;

        const ended = new Promise((resolve) => {
          source.onended = resolve;
        });
        source.start();
        onSpeakingChange?.(true);
        await ended;
        if (sequenceToken !== token) return;
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
    if (currentSource) {
      try {
        currentSource.stop();
      } catch (err) {
        // Bereits gestoppt/durchgelaufen - kein Fehlerfall.
      }
      currentSource = null;
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
