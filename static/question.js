import { initI18n, t, getLang, setLang, detectTextLanguage } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { initAuth, onAuthChange } from '/auth.js';
import { createTurnstileWidget } from '/turnstile.js';
import { createSpeechController, stripMarkdownForSpeech } from '/speech.js';
import { safeHttpUrl, isHiddenForLang } from '/source-lang.js';
import { readNdjsonStream } from '/ndjson-stream.js';
import { buildAnswerFeedback } from '/answer-feedback.js';
import {
  CONVERSATION_STORAGE_KEY,
  CONVERSATION_ID_STORAGE_KEY,
  createConversationHandoffToken,
  consumeConversationHandoffToken,
} from '/conversation-handoff.js';
import {
  buildSourcesList,
  makeTermsClickable,
  placeInlineImage,
  makeCitationsClickable,
  extractCitedSources,
  buildImageStrip,
  buildChatMessage,
  scrollQuestionIntoView,
  rescrollAfterKeyboard,
  buildTypingIndicator,
} from '/question-sources.js';

// Spam-/Bot-Schutz für die Frage-Eingabe (Cloudflare Turnstile) - die
// eigentliche Anbindung ist gemeinsames Modul (siehe turnstile.js), das auch
// vom Feedback-Popover (footer.js) genutzt wird. Bis das Widget bereit ist,
// liefert getToken()/reset() no-ops statt Fehler zu werfen.
let turnstileWidget = { getToken: () => '', reset: () => {}, destroy: () => {} };
// Nutzerwunsch (2026-09-01): das automatische Absenden über ?q= (siehe
// consumeAskParam weiter unten) muss auf DIESES Promise warten, bevor es
// requestSubmit() aufruft - sonst feuert es, anders als eine echte
// Nutzer:in (die zum Tippen naturgemäß ein paar Sekunden braucht), quasi
// sofort beim Laden, oft BEVOR das extern/asynchron nachladende
// Turnstile-Skript das Widget fertig initialisiert hat. getToken() lieferte
// in diesem Fall den no-op-Platzhalter (leerer String), der Server lehnt
// den leeren Captcha-Token ab - die Frage erschien zwar (Nutzer:innen-
// Bubble wird noch vor dem Request angehängt), aber es kam nur eine
// Fehlermeldung statt einer echten Antwort.
const turnstileReadyPromise = createTurnstileWidget('turnstile-container').then((widget) => {
  turnstileWidget = widget;
});

async function getTurnstileToken() {
  return turnstileWidget.getToken();
}

function resetTurnstile() {
  turnstileWidget.reset();
}


await initI18n();
await initAuth();

const chatMessages = document.getElementById('chat-messages');
export const questionForm = document.getElementById('question-form');
export const questionInput = document.getElementById('question');
const micButton = document.getElementById('mic-button');
const sidebarSourcesList = document.getElementById('sidebar-sources-list');

// Nutzerwunsch (2026-08-31): #sources-sidebar existiert als eigene
// Grid-Spalte nur ab 900px Breite (siehe style.css) - darunter blieben
// zitierte Quellen bisher nur über die anklickbaren [1][2]-Verweise im
// Antworttext erreichbar. #sources-sidebar wird deshalb unterhalb dieser
// Breite per JS in #mobile-sources-slot (direkt unter #question-form,
// siehe index.html) umgehängt, statt die Liste zu duplizieren - eine
// Kommentar-Markierung an der ursprünglichen Stelle erlaubt das
// rückstandsfreie Zurückhängen, sobald wieder genug Platz ist. Nur in
// index.html vorhanden (embed.html hat weder Sidebar noch Slot). Nicht in
// embed.html nötig - dort gibt es #sources-sidebar gar nicht.
const sourcesSidebar = document.getElementById('sources-sidebar');
const mobileSourcesSlot = document.getElementById('mobile-sources-slot');
if (sourcesSidebar && mobileSourcesSlot) {
  const desktopSourcesSlotMarker = document.createComment('sources-sidebar-desktop-slot');
  sourcesSidebar.before(desktopSourcesSlotMarker);

  const isDesktopSidebarLayout = () => window.matchMedia('(min-width: 900px)').matches;

  const placeSourcesSidebarForViewport = () => {
    if (isDesktopSidebarLayout()) {
      desktopSourcesSlotMarker.after(sourcesSidebar);
      sourcesSidebar.classList.remove('sources-sidebar--mobile-inline');
    } else {
      mobileSourcesSlot.appendChild(sourcesSidebar);
      sourcesSidebar.classList.add('sources-sidebar--mobile-inline');
    }
  };
  placeSourcesSidebarForViewport();
  // Deckt z.B. das Drehen eines Tablets ab, wodurch der 900px-Umbruch
  // über-/unterschritten werden kann, ohne dass die Seite neu lädt.
  window.addEventListener('resize', placeSourcesSidebarForViewport);
}

// Nur in embed.html vorhanden, NICHT in index.html (dort ergibt "im
// vollständigen Companion öffnen" keinen Sinn) - Wächter statt einer
// "läuft das gerade im Embed?"-Erkennung, siehe embedExpandButton-Listener
// weiter unten.
const embedExpandButton = document.getElementById('embed-expand-button');

// Backlog #184: Ausgangshöhe EINMALIG beim Laden messen (das Feld ist zu
// diesem Zeitpunkt garantiert leer) - dient als Schwelle, ab der ein
// eingegebener Text als "größer als das initiale Feld" gilt und das
// Formular in den zweizeiligen Layout-Modus wechselt (siehe .question-form
// --expanded in style.css). Als expliziter Inline-Wert statt "auto"
// gesetzt, damit die CSS-Transition beim späteren Wachsen/Schrumpfen
// zwischen zwei konkreten Pixelwerten animiert, nicht zu/von "auto".
const questionBaseHeight = questionInput.scrollHeight;
questionInput.style.height = `${questionBaseHeight}px`;

function autosizeQuestionInput() {
  // Die Ausklapp-Entscheidung IMMER an der eingeklappten (schmaleren)
  // Breite treffen, auch wenn das Feld gerade schon ausgeklappt ist - dafür
  // die Klasse hier zuerst entfernen und NEU messen. Sonst würde das
  // Ausklappen selbst (das laut style.css die Breite vergrößert) den
  // Zeilenumbruch u.U. wieder aufheben, was sofort zum Wieder-Einklappen
  // führt und umgekehrt: ein sich an der Umbruch-Grenze selbst
  // verstärkendes Zittern zwischen beiden Zuständen.
  questionForm.classList.remove('question-form--expanded');
  questionInput.style.height = 'auto';
  const collapsedScrollHeight = questionInput.scrollHeight;
  const expanded = collapsedScrollHeight > questionBaseHeight;
  questionForm.classList.toggle('question-form--expanded', expanded);
  if (!expanded) {
    questionInput.style.height = `${questionBaseHeight}px`;
    return;
  }
  // Jetzt an der tatsächlichen (durch die Klasse ggf. breiteren) Zielbreite
  // messen, damit die Boxhöhe zur wirklich benötigten Zeilenzahl passt.
  questionInput.style.height = 'auto';
  // Obergrenze aus dem CSS (max-height): darüber scrollt das Feld selbst.
  const maxHeight = parseFloat(getComputedStyle(questionInput).maxHeight) || Infinity;
  const needed = questionInput.scrollHeight;
  questionInput.style.height = `${Math.min(needed, maxHeight)}px`;
  questionInput.style.overflowY = needed > maxHeight ? 'auto' : 'hidden';
}

questionInput.addEventListener('input', autosizeQuestionInput);

// <textarea> submittet Formulare (anders als <input>) nicht automatisch bei
// Enter - hier nachgebaut, Umschalt+Enter bleibt für einen manuellen
// Zeilenumbruch reserviert. isComposing schützt IME-Eingaben (z.B.
// Japanisch/Chinesisch), bei denen Enter die Zeichenauswahl bestätigt statt
// abzuschicken.
questionInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    questionForm.requestSubmit();
  }
});

// Backlog #49: Sprachdialog. Eine per Mikrofon gestellte Frage wird
// automatisch abgeschickt UND die Antwort automatisch vorgelesen (siehe
// pendingViaVoice unten) - eine getippte Frage bleibt stumm, bekommt aber
// pro Antwort ein Lautsprecher-Icon zum manuellen Vorlesen.
let pendingViaVoice = false;
// Zeigt an, welcher Lautsprecher-Button gerade "spricht" (manuell oder
// automatisch) - wird von speechController per onSpeakingChange aktuell
// gehalten, damit genau ein Icon gleichzeitig den "spricht"-Zustand zeigt
// und ein Klick darauf zum Stoppen statt erneutem Start führt.
let activeSpeakButton = null;

const speechController = createSpeechController({
  onTranscript: (transcript) => {
    questionInput.value = transcript;
    autosizeQuestionInput();
    pendingViaVoice = true;
    questionForm.requestSubmit();
  },
  // Backlog #190: Live-Transkript - schreibt den erkannten Text schon
  // WÄHREND des Sprechens ins Eingabefeld, statt erst nach Aufnahmeende
  // (onTranscript oben).
  onInterimTranscript: (liveText) => {
    questionInput.value = liveText;
    autosizeQuestionInput();
  },
  onListeningChange: (listening) => {
    micButton.classList.toggle('recording', listening);
    // Während der Aufnahme read-only: verhindert, dass eine manuelle
    // Tastatureingabe vom nächsten live eintreffenden Spracherkennungs-
    // Ergebnis (onInterimTranscript oben) einfach überschrieben wird.
    questionInput.readOnly = listening;
    questionInput.classList.toggle('dictating', listening);
  },
  onSpeakingChange: (speaking) => {
    if (!activeSpeakButton) return;
    activeSpeakButton.classList.toggle('speaking', speaking);
    if (!speaking) activeSpeakButton = null;
  },
});

micButton.classList.toggle('hidden', !speechController.supported);
let isListening = false;
micButton.addEventListener('click', () => {
  if (isListening) {
    speechController.stopListening();
  } else {
    speechController.startListening();
  }
  isListening = !isListening;
});

const SPEAKER_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>' +
  '<path d="M15.5 8.5a5 5 0 0 1 0 7"></path>' +
  '<path d="M18.5 5.5a9 9 0 0 1 0 13"></path>' +
  '</svg>';

// Startet/stoppt das Vorlesen eines Textes und hält activeSpeakButton
// aktuell - gemeinsamer Pfad für manuellen Klick UND automatisches
// Vorlesen (pendingViaVoice), damit in beiden Fällen genau ein Icon den
// "spricht"-Zustand zeigt und per Klick unterbrochen werden kann.
function startSpeaking(button, text) {
  if (activeSpeakButton && activeSpeakButton !== button) {
    activeSpeakButton.classList.remove('speaking');
  }
  activeSpeakButton = button;
  speechController.speak(text);
}

// Formatiert 1 als "1x", 1.25 als "1.25x" - toString() liefert für ganze
// Zahlen schon "1", für Nachkommastellen automatisch ohne trailing zeros.
function formatSpeechRate(rate) {
  return `${rate}x`;
}

function attachSpeedButton() {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'speed-answer-btn';
  btn.textContent = formatSpeechRate(speechController.getPlaybackRate());
  btn.title = t('index.speedButtonTitle');
  btn.setAttribute('aria-label', t('index.speedButtonTitle'));
  btn.addEventListener('click', () => {
    btn.textContent = formatSpeechRate(speechController.cyclePlaybackRate());
  });
  return btn;
}

// Daumen-hoch/-runter je Antwort - Komponente siehe answer-feedback.js.
function attachFeedbackButtons(bubble, question, answer) {
  bubble.appendChild(buildAnswerFeedback({ question, answer, conversationId }));
}

// Nutzerwunsch (2026-09-24): Antwort in die Zwischenablage - formatiert
// (HTML) und als Klartext, wie der Kopieren-Button im Kreativ-Modus.
// Zitat-Marker [n] fallen weg (ohne Quellenliste bedeutungslos), gleiche
// Regel wie beim Live-Streaming unten. Kurzer grüner Haken als Bestätigung.
const COPY_ANSWER_ICONS =
  '<svg class="copy-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<rect x="9" y="9" width="13" height="13" rx="2"></rect>' +
  '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>' +
  '<svg class="copy-check" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<polyline points="4 12.5 9.5 18 20 6.5"></polyline></svg>';
const COPIED_FEEDBACK_MS = 1600;

function buildCopyAnswerButton(answer) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'copy-answer-btn';
  btn.innerHTML = COPY_ANSWER_ICONS;
  btn.title = t('index.copyAnswerTitle');
  btn.setAttribute('aria-label', t('index.copyAnswerTitle'));
  let copiedTimer = null;
  btn.addEventListener('click', async () => {
    const text = answer.replace(/\s*\[\d+\]/g, '').replace(/\s*\[bild:\d{1,2}\.\d{1,2}\]/g, '');
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': new Blob([renderMarkdown(text)], { type: 'text/html' }),
          'text/plain': new Blob([text], { type: 'text/plain' }),
        }),
      ]);
    } catch (err) {
      try {
        await navigator.clipboard.writeText(text); // Browser ohne ClipboardItem
      } catch (err2) {
        return; // Zwischenablage nicht erlaubt - kein Haken.
      }
    }
    clearTimeout(copiedTimer);
    btn.classList.add('copied');
    copiedTimer = setTimeout(() => btn.classList.remove('copied'), COPIED_FEEDBACK_MS);
  });
  return btn;
}

function attachSpeakButton(bubble, question, answer) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'speak-answer-btn';
  btn.innerHTML = SPEAKER_ICON;
  btn.title = t('index.speakAnswerTitle');
  btn.setAttribute('aria-label', t('index.speakAnswerTitle'));
  btn.addEventListener('click', () => {
    if (activeSpeakButton === btn) {
      speechController.stopSpeaking();
      return;
    }
    startSpeaking(btn, stripMarkdownForSpeech(answer));
  });
  bubble.appendChild(btn);
  bubble.appendChild(attachSpeedButton());
  attachFeedbackButtons(bubble, question, answer);
  bubble.appendChild(buildCopyAnswerButton(answer));
  return btn;
}

// Ersetzt die generische Browser-Standardmeldung ("Bitte füllen Sie dieses
// Feld aus"/"Please fill out this field") für das required-Feld durch eine
// zum Kontext passende Aufforderung. setCustomValidity muss vor dem nächsten
// Validierungsversuch wieder geleert werden, sonst bliebe das Feld dauerhaft
// ungültig, selbst nachdem etwas eingegeben wurde.
questionInput.addEventListener('invalid', () => {
  questionInput.setCustomValidity(t('index.emptyQuestionValidation'));
});
questionInput.addEventListener('input', () => {
  questionInput.setCustomValidity('');
});

// Baut sich über die gesamte Konversation auf (chunk_id -> Quelle) - einmal
// zitierte Quellen bleiben in der Sidebar stehen, auch wenn eine spätere
// Antwort sie nicht erneut zitiert.
export const conversationCitedSources = new Map();

// Baut die Sidebar-Liste neu auf, behält dabei aber den Auf-/Zu-Zustand
// bereits aufgeklappter <details> bei (sonst klappt z.B. ein Sprachwechsel
// oder eine neue Antwort eine gerade gelesene Zusammenfassung wieder zu).
export function renderSidebarSources() {
  const openSourceIds = new Set(
    [...sidebarSourcesList.querySelectorAll('details[open]')].map((d) => d.dataset.sourceId)
  );
  sidebarSourcesList.replaceChildren(
    ...buildSourcesList([...conversationCitedSources.values()]).children
  );
  sidebarSourcesList.querySelectorAll('details').forEach((d) => {
    if (openSourceIds.has(d.dataset.sourceId)) d.open = true;
  });
}

// Zeigt/versteckt die Bearbeiten-Icons in der Sidebar sofort passend zum
// Login-Status, ohne dass eine neue Antwort nötig ist.
onAuthChange(() => {
  renderSidebarSources();
});

// Backlog-Fix: eine begonnene Konversation soll erhalten bleiben, wenn
// z.B. über einen Autor:innen-/Zitat-Link kurz in die Quellenverwaltung
// gesprungen und danach per Browser-Zurück (oder erneutem Aufruf von "/")
// hierher zurückgekehrt wird. sessionStorage statt localStorage, weil die
// Konversation nur für die Dauer dieses Tabs gelten soll - ein neuer Tab
// oder ein Neustart des Browsers beginnt bewusst wieder leer.
// CONVERSATION_STORAGE_KEY kommt aus conversation-handoff.js (siehe Import
// oben) - import.js braucht denselben Schlüssel für das Konversations-
// Handoff (2026-08-30), daher an einer einzigen Stelle definiert.

// Backlog (2026-08-03): ohne Verlauf beantwortete der Chatbot jede
// Folgefrage isoliert, ohne den bisherigen Gesprächsverlauf zu kennen - das
// wirkte wie ständige Wiederholung. Nur Frage+Antwort (keine Quellen) gehen
// mit, das reicht dem Modell für die Konversation und hält den Request
// klein; app/main.py kappt serverseitig defensiv nochmal auf dieselbe
// Anzahl (muss zu app/main.py passen).
// Idee 2070893d: 50 Turns und 200.000 UTF-8-Bytes (muss zu app/main.py passen,
// Test in tests/test_api.py) - das Frontend kürzt selbst, damit der Body
// unter dem Request-Limit bleibt (sonst 413 bei Extremfällen).
const ASK_HISTORY_MAX_TURNS = 50;
const ASK_HISTORY_MAX_BYTES = 200000;
// Gekürzt wird in Blöcken von 10 Turns (zustandsloser Startindex), damit der
// Verlaufsanfang über viele Folgefragen gleich bleibt (Prompt-Cache, llm.py).
const ASK_HISTORY_CUT_BLOCK = 10;
// Feldgrenze je Frage/Antwort im Verlauf (muss zu app/models.py passen) -
// sonst scheitert jede Folgefrage mit 422, wenn eine frühere Frage länger ist.
const ASK_HISTORY_MAX_FIELD_CHARS = 8000;
// Frage-Grenze (app/models.py QuestionIn.question); das Sprachdiktat setzt value
// per Code, dort greift maxlength nicht.
const ASK_QUESTION_MAX_CHARS = 8000;

// Gleiche Regel wie _trim_history in app/main.py: leere Turns raus, Felder
// kürzen, Anfang blockweise kappen (Turn-Grenze, dann Byte-Budget; höchstens
// bis zum letzten Turn, danach einzeln).
function buildAskHistory(turns) {
  const encoder = new TextEncoder();
  const kept = turns
    .map(({ question, answer }) => ({
      question: question.slice(0, ASK_HISTORY_MAX_FIELD_CHARS),
      answer: answer.slice(0, ASK_HISTORY_MAX_FIELD_CHARS),
    }))
    .filter((t) => t.question.trim() && t.answer.trim());
  const n = kept.length;
  const sizes = kept.map((t) => encoder.encode(t.question).length + encoder.encode(t.answer).length);
  const bytesFrom = (from) => sizes.slice(from).reduce((a, b) => a + b, 0);
  let start = n > ASK_HISTORY_MAX_TURNS ? Math.ceil((n - ASK_HISTORY_MAX_TURNS) / ASK_HISTORY_CUT_BLOCK) * ASK_HISTORY_CUT_BLOCK : 0;
  start = Math.min(start, Math.max(n - 1, 0));
  while (start < n - 1 && bytesFrom(start) > ASK_HISTORY_MAX_BYTES) {
    start = Math.min(start + ASK_HISTORY_CUT_BLOCK, n - 1);
  }
  while (start < n && bytesFrom(start) > ASK_HISTORY_MAX_BYTES) start += 1;
  return kept.slice(start);
}

function loadConversationHistory() {
  try {
    const raw = sessionStorage.getItem(CONVERSATION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (err) {
    return [];
  }
}

export function saveConversationHistory() {
  try {
    sessionStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(conversationHistory));
  } catch (err) {
    // z.B. sessionStorage voll oder deaktiviert (privates Fenster u.ä.) -
    // die Konversation bleibt dann nur für die laufende Seitenansicht
    // erhalten, ohne dass das die Nutzung sonst beeinträchtigt.
  }
}

export const conversationHistory = loadConversationHistory();

// Kennung dieser Konversation fürs Fragen-Log (conversation_id in /api/ask,
// /api/answer-feedback und Handoff). Die Modul-Variable ist maßgeblich,
// sessionStorage nur die Kopie für Reload/Seitenwechsel. Neue ID nur beim
// Laden, wenn kein Verlauf da ist (neuer Tab, Marken-Klick leert den Verlauf
// in header.js) - eine vorhandene Konversation behält ihre ID.
// Akzeptiert: Ein Fehler vor der ersten erfolgreichen Antwort ergibt zwei
// first_question mit derselben ID; ein duplizierter Tab teilt die ID.
function loadConversationId() {
  try {
    const stored = sessionStorage.getItem(CONVERSATION_ID_STORAGE_KEY);
    if (stored && conversationHistory.length > 0) return stored;
  } catch (err) {
    // sessionStorage nicht lesbar - dann eben eine frische ID.
  }
  return crypto.randomUUID();
}

function saveConversationId() {
  try {
    sessionStorage.setItem(CONVERSATION_ID_STORAGE_KEY, conversationId);
  } catch (err) {
    // wie saveConversationHistory: nur für die laufende Seitenansicht.
  }
}

export let conversationId = loadConversationId();
saveConversationId();
// Wurde in dieser Seitenansicht schon eine Frage dieser Konversation gesendet?
// (Nach Reload mit Verlauf entscheidet conversationHistory.)
let questionSentInConversation = false;

// Backlog (2026-07-31): in zwei Schritte aufgeteilt, damit eine live
// eintreffende Antwort den Vorlesen-Button schon anzeigen kann, sobald der
// Antworttext feststeht ("answer"-Event) - ohne auf die u.U. spürbar
// langsamere Quellen-/Highlight-Berechnung ("done"-Event) zu warten. Beim
// Wiederherstellen einer gespeicherten Konversation (beides schon bekannt)
// laufen weiterhin beide Schritte direkt hintereinander, siehe
// renderAnswerBubble unten.
const controlsByBubble = new WeakMap();

function renderAnswerText(bubble, question, answer) {
  bubble.innerHTML = renderMarkdown(answer);
  // Unabhängig von Quellen/Zitaten (die ggf. erst später/asynchron
  // eintreffen, siehe attachAnswerSources) - fett hervorgehobene Begriffe
  // stehen schon jetzt fest, einmalig statt bei jedem Zwischenstand während
  // des Streamens neu zu binden.
  makeTermsClickable(bubble);
  const contentCount = bubble.childNodes.length;
  const speakBtn = attachSpeakButton(bubble, question, answer);
  // Knöpfe (Vorlesen, Tempo, Feedback, Kopieren) merken, damit ein
  // Sprachwechsel nur den Antwortinhalt neu baut (rerenderAnswerBody).
  controlsByBubble.set(bubble, [...bubble.childNodes].slice(contentCount));
  return speakBtn;
}

function attachAnswerSources(bubble, sources) {
  placeInlineImage(bubble, sources);
  makeCitationsClickable(bubble, sources);
  // Nutzerfeedback (2026-09-01): die Sidebar (buildSourcesList) zeigt
  // Quellen-Ebene an (Titel/KI-Zusammenfassung/Link), nicht den einzelnen
  // Chunk-Ausschnitt - ein Dedup nach chunk_id ließ dieselbe Quelle mehrfach
  // auftauchen, sobald zwei verschiedene [n]-Vorkommen auf unterschiedliche
  // Chunks DERSELBEN Quelle verwiesen (z.B. [1] und [3] aus demselben
  // Artikel). Beide Einträge sahen dabei identisch aus (gleicher Titel,
  // gleiche Zusammenfassung), wirkten also wie ein Duplikat. source_id
  // dedupliziert stattdessen korrekt auf Quellen-Ebene - die individuellen
  // Chunk-Ausschnitte bleiben trotzdem weiterhin je [n]-Verweis eigenständig
  // aufklappbar (siehe makeCitationsClickable oben, das unabhängig davon
  // pro Chunk+Highlight arbeitet).
  const cited = extractCitedSources(bubble, sources);
  cited.forEach((s) => {
    conversationCitedSources.set(s.source_id, s);
  });
  refreshImageStrip(bubble, cited, sources);
}

// Ersetzt die Bildleiste der Bubble (nie zwei Leisten; ohne Bilder keine).
// Fix v0.94.1: nach den zitierten Quellen auch die übrigen gefundenen
// (das Inline-Bild darf ebenfalls von dort kommen); ausgeblendete nie.
export function refreshImageStrip(bubble, cited, found = []) {
  bubble.querySelectorAll('.source-image-strip').forEach((el) => el.remove());
  const inline = bubble.querySelectorAll('.inline-source-image')[0];
  const others = found.filter((s) => !cited.includes(s) && !isHiddenForLang(s));
  const strip = buildImageStrip([...cited, ...others], inline && inline.dataset.src);
  if (strip) bubble.appendChild(strip);
}

// done-Event: das Backend wählt das Bild einer geschützten Quelle am
// tatsächlich zitierten Chunk - die Bilder des frühen sources-Events
// ersetzen (gleiche Objekte wie in der gespeicherten Konversation).
function applyDoneImages(bubble, earlySources, doneSources) {
  doneSources.forEach((s, i) => {
    if (earlySources[i]) earlySources[i].images = s.images;
  });
  refreshImageStrip(bubble, extractCitedSources(bubble, earlySources), earlySources);
}

// Gemeinsame Rendering-Logik für eine Antwort-Bubble beim Wiederherstellen
// der gespeicherten Konversation nach einem Seitenwechsel - dort liegen
// Antwort und Quellen von Anfang an beide vor, kein Grund für die beiden
// Schritte oben zeitlich zu trennen.
function renderAnswerBubble(bubble, question, answer, sources) {
  const speakBtn = renderAnswerText(bubble, question, answer);
  attachAnswerSources(bubble, sources);
  return speakBtn;
}

// Antwort-Bubble je Verlaufseintrag - für das Neu-Rendern bei Sprachwechsel.
const bubbleByTurn = new WeakMap();

// Sprachwechsel zur Laufzeit: ausgeblendete Quellen (EN-UI) erscheinen bei DE
// wieder und umgekehrt, Titel/Links/Marker passen sich an. Geöffnete
// Zitat-Karten gehen dabei zu.
function rerenderConversation() {
  // Nur Quellen der gespeicherten Antworten neu einsammeln; Quellen einer
  // noch laufenden Antwort (noch nicht im Verlauf) bleiben stehen.
  const historyIds = new Set(
    conversationHistory.flatMap((turn) => (turn.sources || []).map((s) => s.source_id))
  );
  [...conversationCitedSources.keys()].forEach((id) => {
    if (historyIds.has(id)) conversationCitedSources.delete(id);
  });
  conversationHistory.forEach((turn) => {
    const bubble = bubbleByTurn.get(turn);
    const controls = controlsByBubble.get(bubble);
    if (!controls || !controls.length) return;
    // Antworttext, Zitate, Karten und Bildleiste neu; die Knöpfe bleiben
    // (Feedback-Sperre, Vorlese-Zustand).
    [...bubble.childNodes].filter((node) => !controls.includes(node)).forEach((node) => node.remove());
    controls[0].insertAdjacentHTML('beforebegin', renderMarkdown(turn.answer));
    makeTermsClickable(bubble);
    attachAnswerSources(bubble, turn.sources);
  });
  renderSidebarSources();
}

function restoreConversationHistory() {
  if (conversationHistory.length === 0) return;
  document.body.classList.add('chat-started');
  questionInput.placeholder = t('index.questionPlaceholderContinue');
  conversationHistory.forEach((turn) => {
    const { question, answer, sources } = turn;
    const { message: userMessage, bubble: userBubble } = buildChatMessage('user');
    userBubble.textContent = question;
    chatMessages.appendChild(userMessage);

    const { message: assistantMessage, bubble: assistantBubble } = buildChatMessage('assistant');
    chatMessages.appendChild(assistantMessage);
    renderAnswerBubble(assistantBubble, question, answer, sources);
    bubbleByTurn.set(turn, assistantBubble);
  });
  renderSidebarSources();
  // Ohne "smooth"/Verzögerung: beim Wiederherstellen soll die Ansicht
  // sofort am letzten Stand sein, kein sichtbares Hochscrollen von oben.
  chatMessages.lastElementChild?.scrollIntoView({ block: 'end' });
}

// Nutzerwunsch (2026-08-30): Konversations-Handoff (siehe conversation-
// handoff.js) - ein per Embed-"Vollständig öffnen"-Icon oder Quellen-Link
// mitgegebenes ?handoff=-Token ersetzt die (i.d.R. leere) sessionStorage-
// Historie DIESES neuen Tabs, bevor sie gerendert wird. Kein Token
// vorhanden oder abgelaufen/bereits verwendet: conversationHistory bleibt
// unverändert (bisheriger sessionStorage-Stand dieses Tabs).
const handoff = await consumeConversationHandoffToken();
if (handoff && handoff.history.length) {
  conversationHistory.length = 0;
  conversationHistory.push(...handoff.history);
  saveConversationHistory();
  if (handoff.conversationId) {
    conversationId = handoff.conversationId;
    saveConversationId();
  }
}

restoreConversationHistory();

// Nutzerwunsch (2026-09-01): Fragen-Log-Einträge (siehe question-log.js)
// verlinken die protokollierte Frage über einen ?q=-Parameter - öffnet den
// Konversationsmodus in einem neuen Tab und stellt genau diese Frage
// automatisch, ohne sie erneut abtippen zu müssen. So lässt sich ein
// gemeldeter Fall nachvollziehen und eine Quellenverbesserung direkt
// dagegen testen. Entfernt NUR diesen einen Parameter aus der Adresszeile
// (Muster wie conversation-handoff.js:consumeConversationHandoffToken),
// andere gleichzeitig vorhandene Parameter (z.B. ?lang=) bleiben erhalten.
function consumeAskParam() {
  const params = new URLSearchParams(window.location.search);
  const ask = params.get('q');
  if (!ask) return null;
  params.delete('q');
  const query = params.toString();
  history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : ''));
  return ask;
}

// Nutzerwunsch (2026-08-30): "Vollständig öffnen"-Icon im Embed-Widget -
// öffnet den vollständigen Companion in einem neuen Tab, mit der laufenden
// Konversation (falls vorhanden). Popup-Blocker-sicheres Muster: window.open
// MUSS synchron im Klick-Handler aufgerufen werden - ein await davor lässt
// Browser den Aufruf sonst als nicht-nutzergesten-getriggert verwerfen und
// blocken. Deshalb wird der Tab SOFORT leer geöffnet und erst danach, nach
// dem asynchronen Token-Abruf, per .location.href umgeleitet. Bewusst OHNE
// "noopener" - das Ziel ist die eigene, vertrauenswürdige Domain, noopener
// würde window.open() null zurückgeben lassen und die spätere
// .location-Zuweisung verhindern.
if (embedExpandButton) {
  embedExpandButton.addEventListener('click', async () => {
    // Nutzerwunsch (2026-09-01): der neue Tab soll in der im Embed
    // gewählten Sprache starten, statt selbst neu zu raten (siehe i18n.js:
    // detectLang - eigener, ggf. durch Storage-Partitionierung sogar
    // komplett getrennter localStorage in einem neuen Top-Level-Tab).
    const langParam = `lang=${encodeURIComponent(getLang())}`;
    if (conversationHistory.length === 0) {
      window.open(`/?${langParam}`, '_blank');
      return;
    }
    const newTab = window.open('', '_blank');
    embedExpandButton.disabled = true;
    const token = await createConversationHandoffToken(conversationHistory, conversationId);
    const query = token ? `handoff=${encodeURIComponent(token)}&${langParam}` : langParam;
    if (newTab) newTab.location.href = `/?${query}`;
    embedExpandButton.disabled = false;
  });
}

// Robuster gegen transiente Netzwerkfehler (z.B. Safaris "TypeError: Load
// failed" bei kurzem Verbindungsabbruch/Tab-Wechsel im Hintergrund) - fetch()
// wirft in diesem Fall VOR jeder Antwort, unabhängig vom Server. Ein einziger
// automatischer, kurz verzögerter Retry reicht für den typischen Kurzausfall;
// echte HTTP-Fehlerantworten (res.ok === false) lösen KEINEN Retry aus, da
// fetch() dafür normal auflöst statt zu werfen - die landen unverändert im
// bestehenden !res.ok-Zweig unten.
async function fetchWithRetry(url, options, retries = 1, delayMs = 600) {
  try {
    return await fetch(url, options);
  } catch (err) {
    if (retries <= 0) throw err;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    return fetchWithRetry(url, options, retries - 1, delayMs);
  }
}

// Backlog (2026-07-29): Antwortzeit gefühlt beschleunigen, analog zum
// Streaming im CRT-Tool - /api/ask liefert die Antwort seitdem als NDJSON-
// Stream (eine JSON-Zeile pro Event) statt als einzelne JSON-Antwort.
// Liest den Response-Body inkrementell und ruft onDelta(text) für jedes
// "delta"-Event auf, sobald es ankommt, onSources(sources) für das ganz
// frühe "sources"-Event (Titel/Autor:in/Link, siehe Backlog 2026-08-03 -
// noch ohne Hervorhebungen) sowie onAnswer(answer) für das "answer"-Event
// (fertiger Antworttext, kommt VOR den im "done"-Event nachgereichten
// Hervorhebungen, siehe Backlog 2026-07-31/2026-08-03); löst am Ende mit
// dem "done"-Event auf (bzw. wirft bei einem "error"-Event oder wenn der
// Stream ohne "done" endet - z.B. abgebrochene Verbindung).
// Nutzerwunsch (2026-10-25): verständliche Meldung statt "Failed to fetch".
// fetch wirft bei Netzwerkfehlern einen TypeError (Safari: "Load failed").
function askErrorText(err) {
  if (err instanceof TypeError) return t('index.askErrorNetwork');
  return err.message || t('index.askFailed');
}

// Fehler in der Antwort-Bubble mit Button, der dieselbe Frage erneut stellt.
function renderAskError(bubble, err, onRetry) {
  bubble.textContent = '';
  const text = document.createElement('p');
  text.textContent = askErrorText(err);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'retry-button link-button';
  button.textContent = t('index.retry');
  button.title = t('index.retryTooltip');
  button.addEventListener('click', onRetry);
  bubble.appendChild(text);
  bubble.appendChild(button);
}

async function readAskStream(response, onDelta, onAnswer, onSources) {
  return readNdjsonStream(
    response,
    {
      delta: (event) => onDelta(event.text),
      answer: (event) => onAnswer(event.answer),
      sources: (event) => onSources?.(event.sources),
    },
    t('index.askFailed')
  );
}

questionForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim().slice(0, ASK_QUESTION_MAX_CHARS);
  if (!question) return;

  // Sofort lesen+zurücksetzen (nicht erst nach der Antwort) - eine neue,
  // während dieser Anfrage per Mikrofon gestartete Frage soll das Flag für
  // IHRE EIGENE spätere Auswertung neu setzen können, ohne von diesem noch
  // laufenden Request überschrieben zu werden.
  const viaVoice = pendingViaVoice;
  pendingViaVoice = false;

  // Schaltet vom zentrierten Startzustand (nur Eingabefeld) auf die volle
  // Ansicht (Sidebar + Nachrichtenverlauf) um, sobald die erste Frage
  // gestellt wird - siehe .chat-started in style.css.
  document.body.classList.add('chat-started');

  const { message: userMessage, bubble: userBubble } = buildChatMessage('user');
  userBubble.textContent = question;
  chatMessages.appendChild(userMessage);
  // Touch-Geräte (Handy, iPad, auch quer): Feld sofort verlassen, damit die
  // Tastatur schließt und iOS das fokussierte Feld nicht erneut ins Bild
  // scrollt (Idee b5bd431b). Der Scroll wird nach dem Schließen einmal
  // wiederholt.
  const isTouch = window.matchMedia('(pointer: coarse)').matches;
  if (isTouch) questionInput.blur();
  scrollQuestionIntoView(userMessage);
  if (isTouch) {
    rescrollAfterKeyboard(window.visualViewport, setTimeout, () => scrollQuestionIntoView(userMessage));
  }

  questionInput.value = '';
  autosizeQuestionInput();
  questionInput.placeholder = t('index.questionPlaceholderContinue');
  // Auf Touch-Geräten öffnet .focus() die virtuelle Tastatur, deren eigenes
  // "gefokussiertes Feld ins Bild scrollen"-Verhalten den obigen Scroll auf
  // die gerade gestellte Frage sofort wieder zunichtemacht (die Frage
  // verschwindet hinter der Tastatur). Am Desktop (Maus) gibt es dieses Problem
  // nicht - dort bleibt das automatische Fokussieren fürs schnelle
  // Nachfragen bestehen.
  if (!isTouch) {
    questionInput.focus();
  }

  const { message: assistantMessage, bubble: assistantBubble } = buildChatMessage('assistant');
  assistantBubble.setAttribute('aria-label', t('index.searching'));
  assistantBubble.appendChild(buildTypingIndicator());
  chatMessages.appendChild(assistantMessage);

  // Vor dem ersten await lesen+setzen: zwei schnell nacheinander abgeschickte
  // Fragen (die zweite, während die erste noch streamt - conversationHistory
  // füllt sich erst nach "done") wären sonst beide "erste Frage".
  const isFirstMessage = conversationHistory.length === 0 && !questionSentInConversation;
  questionSentInConversation = true;

  try {
    const turnstileToken = await getTurnstileToken();
    const res = await fetchWithRetry('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
      body: JSON.stringify({
        question,
        top_k: 5,
        turnstile_token: turnstileToken,
        is_first_message: isFirstMessage,
        conversation_id: conversationId,
        history: buildAskHistory(conversationHistory),
      }),
    });
    // Turnstile-Tokens sind Einweg-Token - nach jedem Versuch (egal ob
    // erfolgreich oder nicht) zurücksetzen, damit die nächste Frage ein
    // frisches Token bekommt.
    resetTurnstile();
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      // 422 liefert detail als Liste von Objekten - dann allgemeine Meldung.
      throw new Error(typeof err.detail === 'string' ? err.detail : t('index.askFailed'));
    }

    // Erstes Text-Fragment: Tippindikator durch die (noch unfertige)
    // Antwort ersetzen. Zitat-Verweise [n] und Hervorhebungen brauchen die
    // Quellen - werden dank des frühen "sources"-Events (Backlog
    // 2026-08-03) aber schon beim "answer"-Event aktiv, nicht erst am Ende.
    let liveText = '';
    let indicatorCleared = false;
    let finalAnswer = '';
    let speakBtn = null;
    // Von onSources befüllt, sobald das (sehr frühe) "sources"-Event
    // ankommt - noch ohne highlighted_texts, siehe unten. Dieselben
    // Objekt-Referenzen werden von attachAnswerSources() u.a. in
    // conversationCitedSources (Sidebar) sowie in den Klick-Handlern der
    // Zitat-Buttons (makeCitationsClickable) gehalten; ein nachträgliches
    // Mutieren der Felder wirkt sich dadurch überall gleichzeitig aus, ohne
    // dass irgendwas neu gerendert werden müsste.
    let earlySources = null;
    const doneEvent = await readAskStream(
      res,
      (delta) => {
        liveText += delta;
        if (!indicatorCleared) {
          indicatorCleared = true;
          assistantBubble.removeAttribute('aria-label');
        }
        // Nutzerwunsch (2026-09-23): [n]-Zitatverweise zeigen sich während
        // des Streamings noch als reiner Text mit der ROHEN, vom Modell
        // vergebenen Nummer - sobald die Antwort fertig ist, ersetzt
        // makeCitationsClickable() sie durch fortlaufend NEU nummerierte
        // Buttons (siehe dortiger Kommentar), die von der rohen Nummer
        // abweichen können. Der kurze Zahlenwechsel wirkte verwirrend -
        // während des Streamings werden die Zahlen deshalb gar nicht erst
        // angezeigt (\s* frisst ein eventuelles Leerzeichen davor mit, damit
        // keine Lücke vor dem folgenden Satzzeichen entsteht).
        assistantBubble.innerHTML = renderMarkdown(liveText.replace(/\s*\[\d+\]/g, ''));
        // Bildmarker: Skeleton-Platzhalter statt Markertext (Idee fe44f080).
        placeInlineImage(assistantBubble, null);
      },
      async (answer) => {
        // Backlog (2026-07-31, ergänzt 2026-08-03): Vorlesen-Button UND
        // Zitat-Verweise so früh wie möglich freischalten, ohne auf die
        // u.U. spürbar langsamere Hervorhebungs-Berechnung zu warten - die
        // kommt erst später über das "done"-Event nach (siehe unten).
        finalAnswer = answer;
        // Fix (Livegang-Vorbereitung, 2026-09-10, gemeldeter Bug): die
        // Sprache wird jetzt aus der TATSÄCHLICHEN ANTWORT erkannt statt aus
        // der Frage - das Modell entscheidet selbst (siehe SYSTEM_PROMPTS in
        // app/llm.py: "Detect the question's language yourself"), unabhängig
        // vom X-Lang-Header. Eine Erkennung anhand der Frage konnte deshalb
        // von der tatsächlichen Antwortsprache abweichen (z.B. bei
        // mehrdeutigen Fragen wie "What ist X about?") - die UI hätte dann
        // "auf Englisch umgeschaltet" gemeldet, während die Antwort auf
        // Deutsch kam. Anhand der (meist deutlich längeren, zuverlässiger
        // erkennbaren) Antwort kann UI und Inhalt nie widersprüchlich sein.
        const detectedLang = detectTextLanguage(answer);
        if (detectedLang && detectedLang !== getLang()) {
          await setLang(detectedLang);
          const { message: noticeMessage, bubble: noticeBubble } = buildChatMessage('system');
          noticeBubble.textContent = t('index.autoLangSwitchNotice');
          chatMessages.insertBefore(noticeMessage, assistantMessage);
        }
        speakBtn = renderAnswerText(assistantBubble, question, answer);
        if (earlySources) {
          attachAnswerSources(assistantBubble, earlySources);
          renderSidebarSources();
        }
        // Backlog #49: nur bei per Mikrofon gestellten Fragen automatisch
        // vorlesen - getippte Fragen bleiben stumm (mit dem Icon manuell
        // vorlesbar, siehe attachSpeakButton).
        if (viaVoice) {
          startSpeaking(speakBtn, stripMarkdownForSpeech(answer));
        }
      },
      (sources) => {
        earlySources = sources;
      }
    );

    if (earlySources) {
      // Nachtrag statt Neu-Rendern: dieselben Objekte, die attachAnswerSources
      // oben schon verteilt hat (Sidebar, Zitat-Karten), bekommen jetzt ihre
      // Hervorhebungen - ein späterer Klick auf "[n]" zeigt dann den
      // passenden Ausschnitt, auch wenn die Karte schon vorher geöffnet war.
      doneEvent.sources.forEach((s, i) => {
        if (earlySources[i]) earlySources[i].highlighted_texts = s.highlighted_texts;
      });
      applyDoneImages(assistantBubble, earlySources, doneEvent.sources);
    } else {
      // Fallback, falls das "sources"-Event wider Erwarten nie ankam.
      attachAnswerSources(assistantBubble, doneEvent.sources);
      renderSidebarSources();
    }
    const turn = { question, answer: finalAnswer, sources: earlySources || doneEvent.sources };
    conversationHistory.push(turn);
    bubbleByTurn.set(turn, assistantBubble);
    saveConversationHistory();
    // Fix (2026-08-31): attachConversationHandoff (siehe appendEditSourceLink/
    // appendViewSourceLink) prüft beim Bauen der Sidebar-Links
    // conversationHistory.length, um zu entscheiden, ob ein Handoff-Token
    // angehängt wird - die obigen renderSidebarSources()-Aufrufe liefen aber
    // VOR dem push() oben, sahen die gerade abgeschlossene Antwort also noch
    // nicht. Betraf v.a. die allererste Frage einer Konversation
    // (conversationHistory dort noch leer): der "Quelle bearbeiten"-Link
    // bekam kein Token und damit auch keine mitgenommene Konversation im
    // Ziel-Tab. Erneutes Rendern mit jetzt korrekt gefüllter
    // conversationHistory behebt das.
    renderSidebarSources();
  } catch (err) {
    renderAskError(assistantBubble, err, () => {
      userMessage.remove();
      assistantMessage.remove();
      questionSentInConversation = conversationHistory.length > 0;
      questionInput.value = question;
      questionForm.requestSubmit();
    });
  }
});

// Fix (2026-09-01, real gemeldet: Frage verschwand nach kurzem Aufblitzen,
// keine Antwort): stand vorher VOR der obigen questionForm.addEventListener
// ('submit', ...)-Registrierung - requestSubmit() löste das "submit"-Event
// zu diesem Zeitpunkt bereits synchron aus, aber ohne den JS-Handler (der
// e.preventDefault() aufruft) griff die native Browser-Formular-Absendung
// (echter GET-Reload derselben Seite, da #question-form kein eigenes
// action/method hat) - genau das erklärt Bild-Flackern + verschwundene
// Frage + nie ankommende Antwort. Muss deshalb NACH dem obigen
// addEventListener('submit', ...) stehen.
const askParam = consumeAskParam();
if (askParam) {
  questionInput.value = askParam;
  // Siehe Kommentar bei turnstileReadyPromise oben - ohne dieses Warten
  // feuert requestSubmit() oft mit noch leerem Captcha-Token. Zeitlich
  // gedeckelt (Muster wie turnstile.js:getToken) - lädt Cloudflares
  // externes Skript aus irgendeinem Grund nie (z.B. Netzwerkproblem,
  // Ad-Blocker), würde sonst nie abgesendet, statt wenigstens mit einer
  // erkennbaren Fehlermeldung zu scheitern.
  await Promise.race([turnstileReadyPromise, new Promise((resolve) => setTimeout(resolve, 5000))]);
  questionForm.requestSubmit();
}

async function refreshCitedSourceSummaries() {
  if (conversationCitedSources.size === 0) return;
  const res = await fetch('/api/sources?include_text=false', { headers: { 'X-Lang': getLang() } });
  if (!res.ok) return;
  const currentSources = await res.json();
  const summaryBySourceId = new Map(currentSources.map((s) => [s.id, s.summary]));
  conversationCitedSources.forEach((s) => {
    if (summaryBySourceId.has(s.source_id)) {
      s.summary = summaryBySourceId.get(s.source_id) || null;
    }
  });
  renderSidebarSources();
}

document.addEventListener('i18n:changed', () => {
  // Der Platzhalter wird normalerweise per data-i18n-placeholder gesetzt,
  // das kennt aber nicht den "fortsetzen"-Zustand nach der ersten Frage -
  // bei einem Sprachwechsel mitten im Gespräch sonst falsch zurückgesetzt.
  if (chatMessages.children.length > 0) {
    questionInput.placeholder = t('index.questionPlaceholderContinue');
  }
  // Die KI-Zusammenfassungen in der "Verwendete Quellen"-Sidebar sind
  // sprachabhängig (summary_de/summary_en) - bei Sprachwechsel neu laden,
  // statt die zuvor in der alten Sprache eingesammelten Texte stehen zu
  // lassen.
  refreshCitedSourceSummaries();
  rerenderConversation();
});
