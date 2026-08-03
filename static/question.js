import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { initAuth, hasRole, onAuthChange } from '/auth.js';
import { createTurnstileWidget } from '/turnstile.js';
import { createSpeechController, stripMarkdownForSpeech } from '/speech.js';

// Spam-/Bot-Schutz für die Frage-Eingabe (Cloudflare Turnstile) - die
// eigentliche Anbindung ist gemeinsames Modul (siehe turnstile.js), das auch
// vom Feedback-Popover (footer.js) genutzt wird. Bis das Widget bereit ist,
// liefert getToken()/reset() no-ops statt Fehler zu werfen.
let turnstileWidget = { getToken: () => '', reset: () => {}, destroy: () => {} };
createTurnstileWidget('turnstile-container').then((widget) => {
  turnstileWidget = widget;
});

function getTurnstileToken() {
  return turnstileWidget.getToken();
}

function resetTurnstile() {
  turnstileWidget.reset();
}

const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

const MAGIC_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none">' +
  '<path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z"></path>' +
  '<path d="M19 13l.9 2.1L22 16l-2.1.9L19 19l-.9-2.1L16 16l2.1-.9L19 13z"></path>' +
  "</svg>";

const EDIT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  "</svg>";

// Backlog #75: eigenes Icon fürs reine Ansehen (statt EDIT_ICON zweckzu-
// entfremden, was "Bearbeiten" suggerieren würde) und statt EXTERNAL_LINK_ICON
// (steht bereits für den externen Original-Link direkt daneben) - ein Auge
// macht den Unterschied "unsere Quellenübersicht ansehen" vs. "Originalquelle
// öffnen" auf einen Blick klar.
const VIEW_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"></path>' +
  '<circle cx="12" cy="12" r="3"></circle>' +
  "</svg>";

function hasPflegerRole() {
  return hasRole('quellen_pfleger');
}

function appendEditSourceLink(container, sourceId) {
  if (!hasPflegerRole()) return;
  const a = document.createElement('a');
  a.href = `/import.html?edit=${encodeURIComponent(sourceId)}`;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.className = 'external-link';
  const label = t('common.editSource');
  a.title = label;
  a.setAttribute('aria-label', label);
  a.innerHTML = EDIT_ICON;
  container.appendChild(a);
}

// Backlog #75: Gegenstück zu appendEditSourceLink für alle anderen
// Besucher:innen (inkl. anonym, inkl. Embed-Widget) - öffnet dieselbe
// Quellenübersicht, aber nur zum Ansehen statt im Bearbeiten-Modus.
// target="_blank" bricht auch innerhalb eines <iframe>-Embeds zuverlässig in
// einen echten Browser-Tab auf der normalen Website aus.
function appendViewSourceLink(container, sourceId) {
  const a = document.createElement('a');
  a.href = `/import.html?source=${encodeURIComponent(sourceId)}`;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.className = 'external-link';
  const label = t('common.viewSource');
  a.title = label;
  a.setAttribute('aria-label', label);
  a.innerHTML = VIEW_ICON;
  container.appendChild(a);
}

function appendSourceLink(container, sourceId) {
  if (hasPflegerRole()) {
    appendEditSourceLink(container, sourceId);
  } else {
    appendViewSourceLink(container, sourceId);
  }
}

function formatYear(dateStr) {
  if (!dateStr) return t('common.noDate');
  return dateStr.split('-')[0];
}

function truncateWords(text, maxWords) {
  const words = text.trim().split(/\s+/);
  if (words.length <= maxWords) {
    return text.trim();
  }
  return words.slice(0, maxWords).join(' ') + '…';
}

function appendAuthorLinks(container, authorNames) {
  if (!authorNames || !authorNames.length) {
    container.appendChild(document.createTextNode(t('common.unknownAuthor')));
    return;
  }
  authorNames.forEach((name, index) => {
    if (index > 0) container.appendChild(document.createTextNode(', '));
    const a = document.createElement('a');
    a.href = `/import.html?author=${encodeURIComponent(name)}`;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'citation-author-link';
    const label = t('common.viewAuthorProfile', { name });
    a.title = label;
    a.setAttribute('aria-label', label);
    a.textContent = name;
    // Verhindert, dass ein Klick auf den Link innerhalb eines <summary>
    // (siehe buildSourcesList) zusätzlich das umgebende <details>-Element
    // auf-/zuklappt.
    a.addEventListener('click', (e) => e.stopPropagation());
    container.appendChild(a);
  });
}

function findHighlightRange(text, highlight) {
  const exactIndex = text.indexOf(highlight);
  if (exactIndex !== -1) return [exactIndex, exactIndex + highlight.length];

  // Das KI-Zitat kann Zeilenumbrüche/Mehrfach-Leerzeichen aus der
  // Originalquelle (z.B. PDF-Layoutumbrüche) leicht anders normalisiert
  // wiedergeben als der exakte Chunk-Text - deshalb zusätzlich mit
  // whitespace-toleranter Suche versuchen, bevor ganz auf Highlighting
  // verzichtet wird.
  const pattern = highlight
    .trim()
    .split(/\s+/)
    .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('\\s+');
  if (!pattern) return null;
  const match = text.match(new RegExp(pattern, 'i'));
  return match ? [match.index, match.index + match[0].length] : null;
}

function appendTextWithHighlight(container, text, highlight) {
  const range = highlight ? findHighlightRange(text, highlight) : null;
  if (!range) {
    container.appendChild(document.createTextNode(text));
    return;
  }
  const [start, end] = range;
  if (start > 0) container.appendChild(document.createTextNode(text.slice(0, start)));
  const mark = document.createElement('mark');
  mark.className = 'citation-highlight';
  mark.textContent = text.slice(start, end);
  container.appendChild(mark);
  if (end < text.length) container.appendChild(document.createTextNode(text.slice(end)));
}

function buildSourceInfo(s, highlight) {
  const wrapper = document.createElement('div');
  wrapper.className = 'citation-card-content';

  const heading = document.createElement('p');
  heading.className = 'citation-card-heading';
  heading.appendChild(document.createTextNode(`${s.title} – `));
  appendAuthorLinks(heading, s.authors);
  heading.appendChild(document.createTextNode(` (${formatYear(s.date)})`));
  wrapper.appendChild(heading);

  const excerpt = document.createElement('p');
  excerpt.className = 'citation-card-text';
  // Voller Chunk-Text statt Kappung bei 100 Wörtern - das ist der Teil, der
  // beim Beantworten tatsächlich als Quelle herangezogen wurde (Backlog #59).
  // Der beleg-relevante Satz (KI-Zitat oder lokales Fallback-Highlighting,
  // siehe app/main.py) wird darin zusätzlich optisch hervorgehoben - je
  // nachdem, WELCHES Vorkommen dieser Quelle im Antworttext aufgeklappt
  // wurde (`highlight`-Parameter), nicht pauschal dasselbe für die ganze
  // Quelle, da derselbe Chunk mehrere unterschiedliche Aussagen belegen kann.
  appendTextWithHighlight(excerpt, s.text, highlight);
  wrapper.appendChild(excerpt);

  const citationUrl = s.listen_url || s.url;
  if (citationUrl) {
    const a = document.createElement('a');
    a.href = citationUrl;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'external-link';
    const label = t('common.openSource');
    a.title = label;
    a.setAttribute('aria-label', label);
    a.innerHTML = EXTERNAL_LINK_ICON;
    excerpt.appendChild(a);
  }
  appendSourceLink(excerpt, s.source_id);

  return wrapper;
}

function buildSourcesList(sources) {
  const sourcesList = document.createElement('ol');
  sourcesList.className = 'chat-sources-list';
  sources.forEach((s) => {
    const li = document.createElement('li');
    const details = document.createElement('details');
    details.dataset.chunkId = s.chunk_id;
    const summaryToggle = document.createElement('summary');
    summaryToggle.appendChild(document.createTextNode(`${s.title} – `));
    appendAuthorLinks(summaryToggle, s.authors);
    summaryToggle.appendChild(document.createTextNode(` (${formatYear(s.date)})`));
    details.appendChild(summaryToggle);
    const p = document.createElement('p');
    // Hier bewusst die KI-Zusammenfassung statt des Chunk-Ausschnitts (anders
    // als buildSourceInfo() in der Konversationsansicht) - fehlt sie (noch)
    // für eine Quelle, auf den Chunk-Ausschnitt zurückfallen.
    if (s.summary) {
      const icon = document.createElement('span');
      icon.className = 'source-summary-icon';
      const tooltip = t('import.aiSummaryTooltip');
      icon.title = tooltip;
      icon.setAttribute('aria-label', tooltip);
      icon.innerHTML = MAGIC_ICON;
      p.appendChild(icon);
      p.appendChild(document.createTextNode(' ' + s.summary));
    } else {
      p.textContent = truncateWords(s.text, 100);
    }
    const citationUrl = s.listen_url || s.url;
    if (citationUrl) {
      const a = document.createElement('a');
      a.href = citationUrl;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.className = 'external-link';
      const label = t('common.openSource');
      a.title = label;
      a.setAttribute('aria-label', label);
      a.innerHTML = EXTERNAL_LINK_ICON;
      p.appendChild(a);
    }
    appendSourceLink(p, s.source_id);
    details.appendChild(p);
    li.appendChild(details);
    sourcesList.appendChild(li);
  });
  return sourcesList;
}

function makeCitationsClickable(container, sources) {
  // Schlüssel ist der tatsächliche INHALT (Chunk + Highlight), nicht die
  // Zitat-Nummer und nicht der einzelne Button: Verweisen zwei verschiedene
  // [n]-Vorkommen auf denselben Chunk mit demselben Highlight (z.B. dieselbe
  // Aussage wird zweimal referenziert), teilen sie sich eine Karte statt
  // dieselbe Box mehrfach aufzuklappen - haben sie dagegen unterschiedliche
  // Highlights (unterschiedliche Aussagen im selben Chunk), bleiben es
  // unabhängig auf-/zuklappbare Karten.
  const openCards = new Map();
  // Zählt pro Quellen-Index, das wievielte Mal sie im Antworttext auftaucht -
  // damit jedes Vorkommen sein eigenes, zu genau dieser Aussage passendes
  // Highlight bekommt (`source.highlighted_texts[occurrence]`), statt bei
  // Mehrfachzitaten derselben Quelle immer dasselbe erste Highlight zu
  // zeigen (siehe app/main.py: highlighted_texts ist pro Vorkommen sortiert).
  const occurrenceCounts = new Map();
  const textNodes = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    if (/\[\d+\]/.test(node.textContent)) {
      textNodes.push(node);
    }
    node = walker.nextNode();
  }

  textNodes.forEach((textNode) => {
    const parts = textNode.textContent.split(/(\[\d+\])/g);
    if (parts.length === 1) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < parts.length; i += 1) {
      const part = parts[i];
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        const index = parseInt(match[1], 10) - 1;
        const source = sources[index];
        if (!source) {
          frag.appendChild(document.createTextNode(part));
          continue;
        }
        // Zum Erstellungszeitpunkt festhalten, nicht erst im Klick-Handler
        // lesen - sonst würde bei einem späteren Klick der inzwischen schon
        // weitergezählte, falsche Vorkommens-Index verwendet.
        const myOccurrence = occurrenceCounts.get(index) || 0;
        occurrenceCounts.set(index, myOccurrence + 1);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'citation-ref';
        btn.textContent = part;
        // Bug (2026-08-03): source.highlighted_texts wurde bisher SCHON HIER
        // beim Bauen des Buttons gelesen und als "highlight" fest in den
        // Klick-Handler eingefroren. Seit source.highlighted_texts erst
        // verzoegert nachtraeglich befuellt wird (frühes "sources"-Event vor
        // den eigentlichen Hervorhebungen, siehe attachAnswerSources im
        // submit-Handler), war highlight beim Erzeugen des Buttons IMMER
        // leer - die spaeter nachgetragenen Werte kamen nie mehr an.
        // Fix: erst im Klick-Handler selbst lesen, dann steht der aktuelle
        // Stand zur Verfuegung. openKey merkt sich (pro Button), unter
        // welchem Content-Schluessel die eigene Karte in openCards liegt -
        // unabhaengig davon, ob eine sich zwischenzeitlich aendernde
        // Hervorhebung beim naechsten Klick einen anderen Schluessel
        // ergeben wuerde.
        let openKey = null;
        btn.addEventListener('click', () => {
          const paragraph = btn.closest('p') || container;
          if (openKey !== null) {
            openCards.get(openKey)?.remove();
            openCards.delete(openKey);
            openKey = null;
            return;
          }
          const highlights = source.highlighted_texts || [];
          const highlight = highlights[myOccurrence] ?? highlights[0] ?? null;
          const contentKey = `${source.chunk_id}::${highlight || ''}`;
          if (openCards.has(contentKey)) {
            openKey = contentKey;
            return;
          }
          const card = document.createElement('div');
          card.className = 'citation-card';
          card.appendChild(buildSourceInfo(source, highlight));
          paragraph.insertAdjacentElement('afterend', card);
          openCards.set(contentKey, card);
          openKey = contentKey;
        });
        // Satzzeichen, die direkt (ohne Leerzeichen) auf die Quellenangabe
        // folgen (z. B. "[1]."), sollen beim Zeilenumbruch nicht von ihr
        // getrennt werden - beides zusammen in einen nowrap-Wrapper packen,
        // im Zweifel bricht die ganze Einheit gemeinsam um.
        const wrap = document.createElement('span');
        wrap.className = 'citation-ref-wrap';
        wrap.appendChild(btn);
        const nextPart = parts[i + 1];
        if (nextPart) {
          const punctMatch = nextPart.match(/^[.,;:!?)]+/);
          if (punctMatch) {
            wrap.appendChild(document.createTextNode(punctMatch[0]));
            parts[i + 1] = nextPart.slice(punctMatch[0].length);
          }
        }
        frag.appendChild(wrap);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    }
    textNode.parentNode.replaceChild(frag, textNode);
  });
}

function buildChatMessage(role) {
  const message = document.createElement('div');
  message.className = `chat-message chat-message--${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  message.appendChild(bubble);
  return { message, bubble };
}

function buildTypingIndicator() {
  const typing = document.createElement('div');
  typing.className = 'chat-typing';
  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement('span');
    dot.className = 'chat-typing-dot';
    typing.appendChild(dot);
  }
  return typing;
}

function scrollQuestionIntoView(element) {
  // Verankert die gerade gestellte Frage oben im sichtbaren Bereich, statt
  // ans Ende der (noch wachsenden) Antwort zu scrollen - vorher sprang der
  // Fokus sichtbar hoch und runter, weil einmal direkt nach dem Absenden
  // (kurzer Tippindikator) und ein zweites Mal nach Eintreffen der oft viel
  // längeren Antwort ans jeweilige Element-Ende gescrollt wurde. So bleibt
  // die eigene Frage als Orientierungspunkt stehen, während die Antwort
  // darunter erscheint - besonders auf dem Handy wichtig, wo sonst der
  // Überblick verloren geht. scrollIntoView statt container.scrollTop, weil
  // ab 900px die Chat-Box mit dem Antworttext mitwächst statt intern zu
  // scrollen (siehe style.css) - der scrollende Bereich ist dann die Seite
  // selbst, nicht mehr #chat-messages; scrollIntoView findet den jeweils
  // richtigen scrollenden Vorfahren automatisch und funktioniert daher für
  // beide Layouts.
  element.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Nur Quellen, die im gerenderten Antworttext tatsächlich per "[n]" zitiert
// werden, sollen in der Sidebar auftauchen - data.sources enthält auch
// Top-K-Treffer, die die KI am Ende gar nicht zitiert hat.
function extractCitedSources(container, sources) {
  const matches = container.textContent.match(/\[(\d+)\]/g) || [];
  const cited = [];
  const seen = new Set();
  matches.forEach((m) => {
    const index = parseInt(m.slice(1, -1), 10) - 1;
    if (seen.has(index) || !sources[index]) return;
    seen.add(index);
    cited.push(sources[index]);
  });
  return cited;
}

await initI18n();
await initAuth();

const chatMessages = document.getElementById('chat-messages');
const questionForm = document.getElementById('question-form');
const questionInput = document.getElementById('question');
const micButton = document.getElementById('mic-button');
const sidebarSourcesList = document.getElementById('sidebar-sources-list');

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
  questionInput.style.height = `${questionInput.scrollHeight}px`;
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

function attachSpeakButton(bubble, answer) {
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
const conversationCitedSources = new Map();

// Baut die Sidebar-Liste neu auf, behält dabei aber den Auf-/Zu-Zustand
// bereits aufgeklappter <details> bei (sonst klappt z.B. ein Sprachwechsel
// oder eine neue Antwort eine gerade gelesene Zusammenfassung wieder zu).
function renderSidebarSources() {
  const openChunkIds = new Set(
    [...sidebarSourcesList.querySelectorAll('details[open]')].map((d) => d.dataset.chunkId)
  );
  sidebarSourcesList.replaceChildren(
    ...buildSourcesList([...conversationCitedSources.values()]).children
  );
  sidebarSourcesList.querySelectorAll('details').forEach((d) => {
    if (openChunkIds.has(d.dataset.chunkId)) d.open = true;
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
const CONVERSATION_STORAGE_KEY = 'conversationHistory';

function loadConversationHistory() {
  try {
    const raw = sessionStorage.getItem(CONVERSATION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (err) {
    return [];
  }
}

function saveConversationHistory() {
  try {
    sessionStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(conversationHistory));
  } catch (err) {
    // z.B. sessionStorage voll oder deaktiviert (privates Fenster u.ä.) -
    // die Konversation bleibt dann nur für die laufende Seitenansicht
    // erhalten, ohne dass das die Nutzung sonst beeinträchtigt.
  }
}

const conversationHistory = loadConversationHistory();

// Backlog (2026-07-31): in zwei Schritte aufgeteilt, damit eine live
// eintreffende Antwort den Vorlesen-Button schon anzeigen kann, sobald der
// Antworttext feststeht ("answer"-Event) - ohne auf die u.U. spürbar
// langsamere Quellen-/Highlight-Berechnung ("done"-Event) zu warten. Beim
// Wiederherstellen einer gespeicherten Konversation (beides schon bekannt)
// laufen weiterhin beide Schritte direkt hintereinander, siehe
// renderAnswerBubble unten.
function renderAnswerText(bubble, answer) {
  bubble.innerHTML = renderMarkdown(answer);
  return attachSpeakButton(bubble, answer);
}

function attachAnswerSources(bubble, sources) {
  makeCitationsClickable(bubble, sources);
  extractCitedSources(bubble, sources).forEach((s) => {
    conversationCitedSources.set(s.chunk_id, s);
  });
}

// Gemeinsame Rendering-Logik für eine Antwort-Bubble beim Wiederherstellen
// der gespeicherten Konversation nach einem Seitenwechsel - dort liegen
// Antwort und Quellen von Anfang an beide vor, kein Grund für die beiden
// Schritte oben zeitlich zu trennen.
function renderAnswerBubble(bubble, answer, sources) {
  const speakBtn = renderAnswerText(bubble, answer);
  attachAnswerSources(bubble, sources);
  return speakBtn;
}

function restoreConversationHistory() {
  if (conversationHistory.length === 0) return;
  document.body.classList.add('chat-started');
  questionInput.placeholder = t('index.questionPlaceholderContinue');
  conversationHistory.forEach(({ question, answer, sources }) => {
    const { message: userMessage, bubble: userBubble } = buildChatMessage('user');
    userBubble.textContent = question;
    chatMessages.appendChild(userMessage);

    const { message: assistantMessage, bubble: assistantBubble } = buildChatMessage('assistant');
    chatMessages.appendChild(assistantMessage);
    renderAnswerBubble(assistantBubble, answer, sources);
  });
  renderSidebarSources();
  // Ohne "smooth"/Verzögerung: beim Wiederherstellen soll die Ansicht
  // sofort am letzten Stand sein, kein sichtbares Hochscrollen von oben.
  chatMessages.lastElementChild?.scrollIntoView({ block: 'end' });
}

restoreConversationHistory();

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
async function readAskStream(response, onDelta, onAnswer, onSources) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let doneEvent = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === 'delta') {
        onDelta(event.text);
      } else if (event.type === 'answer') {
        onAnswer(event.answer);
      } else if (event.type === 'sources') {
        onSources?.(event.sources);
      } else if (event.type === 'error') {
        throw new Error(event.message);
      } else if (event.type === 'done') {
        doneEvent = event;
      }
    }
  }

  if (!doneEvent) throw new Error(t('index.askError'));
  return doneEvent;
}

questionForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
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
  scrollQuestionIntoView(userMessage);

  questionInput.value = '';
  autosizeQuestionInput();
  questionInput.placeholder = t('index.questionPlaceholderContinue');
  // Auf dem Handy öffnet .focus() die virtuelle Tastatur, deren eigenes
  // "gefokussiertes Feld ins Bild scrollen"-Verhalten den obigen Scroll auf
  // die gerade gestellte Frage sofort wieder zunichtemacht (die Frage
  // verschwindet hinter der Tastatur). Am Desktop gibt es dieses Problem
  // nicht - dort bleibt das automatische Fokussieren fürs schnelle
  // Nachfragen bestehen.
  if (!window.matchMedia('(max-width: 640px)').matches) {
    questionInput.focus();
  }

  const { message: assistantMessage, bubble: assistantBubble } = buildChatMessage('assistant');
  assistantBubble.setAttribute('aria-label', t('index.searching'));
  assistantBubble.appendChild(buildTypingIndicator());
  chatMessages.appendChild(assistantMessage);

  try {
    const res = await fetchWithRetry('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
      body: JSON.stringify({
        question,
        top_k: 5,
        turnstile_token: getTurnstileToken(),
        is_first_message: conversationHistory.length === 0,
      }),
    });
    // Turnstile-Tokens sind Einweg-Token - nach jedem Versuch (egal ob
    // erfolgreich oder nicht) zurücksetzen, damit die nächste Frage ein
    // frisches Token bekommt.
    resetTurnstile();
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('index.askError'));
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
        assistantBubble.innerHTML = renderMarkdown(liveText);
      },
      (answer) => {
        // Backlog (2026-07-31, ergänzt 2026-08-03): Vorlesen-Button UND
        // Zitat-Verweise so früh wie möglich freischalten, ohne auf die
        // u.U. spürbar langsamere Hervorhebungs-Berechnung zu warten - die
        // kommt erst später über das "done"-Event nach (siehe unten).
        finalAnswer = answer;
        speakBtn = renderAnswerText(assistantBubble, answer);
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
    } else {
      // Fallback, falls das "sources"-Event wider Erwarten nie ankam.
      attachAnswerSources(assistantBubble, doneEvent.sources);
      renderSidebarSources();
    }
    conversationHistory.push({ question, answer: finalAnswer, sources: earlySources || doneEvent.sources });
    saveConversationHistory();
  } catch (err) {
    assistantBubble.textContent = t('common.errorPrefix') + err.message;
  }
});

async function refreshCitedSourceSummaries() {
  if (conversationCitedSources.size === 0) return;
  const res = await fetch('/api/sources', { headers: { 'X-Lang': getLang() } });
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
});
