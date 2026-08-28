import { initI18n, t, getLang } from '/i18n.js';
import { initAuth } from '/auth.js';
import { createTurnstileWidget } from '/turnstile.js';
import { readNdjsonStream } from '/ndjson-stream.js';
import { renderMarkdown } from '/markdown.js';
import { createSpeechController } from '/speech.js';

// Nutzerwunsch (2026-08-26): Kreativ-Modus - anders als die strikte
// Konversationsansicht kein wachsender Chat-Verlauf, sondern ein
// persistentes Dokument (Textarea), das eine Anweisung nach der anderen
// KOMPLETT ersetzt (Ganzdokument-Ersatz, kein Diff/keine Abschnitts-
// Bearbeitung - das ist bewusst ein späterer Ausbauschritt). Turnstile-
// Anbindung analog zu question.js.
let turnstileWidget = { getToken: () => '', reset: () => {}, destroy: () => {} };
createTurnstileWidget('turnstile-container').then((widget) => {
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

// Nutzerwunsch (2026-08-26): das Wort "Konversationsansicht" im Disclaimer
// soll ein echter, normal gestylter Link auf die Konversationsansicht sein -
// die generische data-i18n-Anwendung (siehe i18n.js) setzt aber textContent,
// kann also kein eingebettetes <a> transportieren. Deshalb hier manuell per
// t(key, {vars}) (bestehendes Muster) mit Platzhaltern gerendert, die die
// Übersetzung selbst um den Link-Text herum liefert - bleibt so pro Sprache
// vollständig in i18n/*.json und muss bei Sprachwechsel (i18n:changed) neu
// gerendert werden, da data-i18n das für dieses Element nicht mehr übernimmt.
//
// Nutzerwunsch (2026-08-26): der Hinweis soll je nach Bildschirmbreite an
// zwei unterschiedlichen Stellen im DOM erscheinen (Desktop: eigener Rahmen
// über der Quellenliste rechts; Mobil: unter der Dokument-Textbox) - da beide
// Positionen in unterschiedlichen Elternelementen liegen (Formular vs.
// Aside), reicht reines CSS-Umsortieren (order/grid-area) nicht, ohne die
// Elemente aus ihrem jeweiligen fachlichen Kontext zu reißen. Einfacher und
// robuster: zwei <p>-Elemente mit identischem Inhalt, sichtbar geschaltet
// per CSS-Breakpoint (siehe .creative-disclaimer--mobile/--desktop in
// style.css) statt komplexer JS-DOM-Umhängung.
function renderCreativeDisclaimer() {
  const html = t('creative.disclaimer', {
    linkStart: '<a href="/">',
    linkEnd: '</a>',
  });
  ['creative-disclaimer-mobile', 'creative-disclaimer-desktop'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  });
}
renderCreativeDisclaimer();
document.addEventListener('i18n:changed', renderCreativeDisclaimer);

const form = document.getElementById('creative-form');
const documentField = document.getElementById('creative-document');
const instructionField = document.getElementById('creative-instruction');
const submitBtn = document.getElementById('creative-submit');
const statusEl = document.getElementById('creative-status');
const errorEl = document.getElementById('creative-error');
const betacodexListEl = document.getElementById('creative-sources-betacodex');
const webListEl = document.getElementById('creative-sources-web');
const toolbarButtons = Array.from(document.querySelectorAll('#creative-toolbar button[data-md-action]'));
const previewToggleBtn = document.getElementById('creative-preview-toggle');
const previewEl = document.getElementById('creative-document-preview');

// Nutzerwunsch (2026-08-26): Anweisungsfeld soll mit dem eingegebenen Text
// mitwachsen, statt intern zu scrollen - Höhe bei jeder Eingabe auf den
// tatsächlich benötigten Inhalt zurücksetzen (Standard-Auto-Grow-Muster,
// funktioniert plattformübergreifend ohne die neuere CSS-Eigenschaft
// field-sizing, die noch nicht überall unterstützt wird).
function autoGrowTextarea(el) {
  el.style.height = 'auto';
  // box-sizing: border-box (siehe input, textarea in style.css) heißt: die
  // gesetzte Höhe muss den Rahmen mit einschließen, scrollHeight tut das
  // nicht - ohne den Zuschlag bliebe die letzte Zeile um genau die
  // Rahmenbreite abgeschnitten.
  const borderHeight =
    parseFloat(getComputedStyle(el).borderTopWidth) + parseFloat(getComputedStyle(el).borderBottomWidth);
  el.style.height = `${el.scrollHeight + borderHeight}px`;
}
instructionField.addEventListener('input', () => autoGrowTextarea(instructionField));

// Nutzerwunsch (2026-08-28): dieselbe Spracheingabe wie im Konversations-
// modus (siehe question.js) - inklusive automatischem Absenden nach
// Diktat-Ende, exakt wie dort (Nutzerentscheidung, revidiert nach
// anfänglich bewusst OHNE Auto-Absenden). Nur der Diktat-Teil von
// createSpeechController wird genutzt, speak()/onSpeakingChange (Vorlesen)
// sind hier nicht sinnvoll - ein generiertes Dokument ist kein kurzer,
// vorlesbarer Chat-Antwortsatz.
const creativeMicButton = document.getElementById('creative-mic-button');
const creativeSpeechController = createSpeechController({
  onTranscript: (transcript) => {
    instructionField.value = transcript;
    autoGrowTextarea(instructionField);
    form.requestSubmit();
  },
  onInterimTranscript: (liveText) => {
    instructionField.value = liveText;
    autoGrowTextarea(instructionField);
  },
  onListeningChange: (listening) => {
    creativeMicButton.classList.toggle('recording', listening);
    instructionField.readOnly = listening;
    instructionField.classList.toggle('dictating', listening);
  },
});
creativeMicButton.classList.toggle('hidden', !creativeSpeechController.supported);
let creativeIsListening = false;
creativeMicButton.addEventListener('click', () => {
  if (creativeIsListening) {
    creativeSpeechController.stopListening();
  } else {
    creativeSpeechController.startListening();
  }
  creativeIsListening = !creativeIsListening;
});

// Reine, per Node testbare Funktion (siehe tests/test_frontend_js.py) - wendet
// eine Toolbar-Aktion auf den aktuellen Textarea-Wert/Selektionsbereich an
// und gibt den neuen Wert plus die neue Selektion zurück, statt selbst das
// DOM anzufassen (Aufrufer setzt documentField.value/selectionStart/End).
export function applyMarkdownToSelection(value, selectionStart, selectionEnd, action) {
  const selected = value.slice(selectionStart, selectionEnd);

  if (action === 'bold' || action === 'italic') {
    const marker = action === 'bold' ? '**' : '*';
    const before = value.slice(0, selectionStart);
    const after = value.slice(selectionEnd);
    const newValue = `${before}${marker}${selected}${marker}${after}`;
    const cursorStart = selectionStart + marker.length;
    return { value: newValue, selectionStart: cursorStart, selectionEnd: cursorStart + selected.length };
  }

  if (action === 'heading' || action === 'list') {
    const prefix = action === 'heading' ? '## ' : '- ';
    const lineStart = value.lastIndexOf('\n', selectionStart - 1) + 1;
    let lineEnd = value.indexOf('\n', selectionEnd);
    if (lineEnd === -1) lineEnd = value.length;

    const lines = value.slice(lineStart, lineEnd).split('\n');
    let addedChars = 0;
    const firstLineAdded = lines[0].startsWith(prefix) ? 0 : prefix.length;
    const newLines = lines.map((line) => {
      if (line.startsWith(prefix)) return line;
      addedChars += prefix.length;
      return prefix + line;
    });
    const newValue = value.slice(0, lineStart) + newLines.join('\n') + value.slice(lineEnd);
    return {
      value: newValue,
      selectionStart: selectionStart + firstLineAdded,
      selectionEnd: selectionEnd + addedChars,
    };
  }

  return { value, selectionStart, selectionEnd };
}

let previewMode = false;

// Nutzerwunsch (2026-08-26): Formatierung sichtbar machen, ohne das
// Editierfeld selbst zu einem Rich-Text-Editor zu machen - Bearbeiten/
// Vorschau-Umschalter (wie z.B. GitHub-Markdown-Editoren), Vorschau nutzt den
// bereits vorhandenen renderMarkdown() (siehe question.js/import.js für
// Chat-Antworten bzw. KI-Zusammenfassungen), keine neue Rendering-Logik.
// Bewusst NICHT live pro Token beim Streaming mitgerendert (siehe setBusy) -
// die Vorschau ist ein expliziter Umschalt-Zustand, kein Live-Abbild.
function setPreviewMode(active) {
  previewMode = active;
  documentField.classList.toggle('hidden', active);
  previewEl.classList.toggle('hidden', !active);
  toolbarButtons.forEach((btn) => {
    btn.disabled = active;
  });
  if (active) {
    previewEl.innerHTML = renderMarkdown(documentField.value);
  }
  relabelPreviewToggle();
}

previewToggleBtn.addEventListener('click', () => setPreviewMode(!previewMode));
// previewToggleBtn trägt bewusst KEIN data-i18n-Attribut (siehe
// renderCreativeDisclaimer oben für dasselbe Muster): sein Text hängt vom
// previewMode-Zustand ab, den die generische applyStaticTranslations()-
// Anwendung in i18n.js nicht kennt und sonst bei jedem Sprachwechsel
// fälschlich auf "Vorschau" zurücksetzen würde, selbst während die Vorschau
// bereits aktiv ist.
function relabelPreviewToggle() {
  previewToggleBtn.textContent = t(previewMode ? 'creative.previewToggleHide' : 'creative.previewToggleShow');
}
relabelPreviewToggle();
document.addEventListener('i18n:changed', relabelPreviewToggle);

toolbarButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    const result = applyMarkdownToSelection(
      documentField.value,
      documentField.selectionStart,
      documentField.selectionEnd,
      btn.dataset.mdAction
    );
    documentField.value = result.value;
    documentField.focus();
    documentField.setSelectionRange(result.selectionStart, result.selectionEnd);
  });
});

// Reine, per Node testbare Hilfsfunktion (siehe tests/test_frontend_js.py) -
// baut das Anzeige-Label für eine Quelle in der Seitenliste: Titel plus
// Hostname in Klammern, falls eine URL vorhanden ist.
export function creativeSourceLabel(source) {
  // Nutzerwunsch (2026-08-26): bei BetaCodex-Quellen (haben immer authors,
  // siehe _load_sources()/main.py) Autor:in statt Hostname zeigen - die URL
  // bleibt als Link-Ziel erhalten, nur das sichtbare Label ändert sich.
  // Web-Quellen (kein authors-Feld, siehe validated_web_sources in main.py)
  // behalten den bisherigen Hostname-Fallback, da dort kein Autor bekannt ist.
  if (source.authors && source.authors.length) {
    return `${source.title} — ${source.authors.join(', ')}`;
  }
  if (!source.url) return source.title;
  let host = '';
  try {
    host = new URL(source.url).hostname;
  } catch (err) {
    // Ungültige URL - Titel allein reicht als Label.
  }
  return host ? `${source.title} (${host})` : source.title;
}

function renderSourceList(listEl, sources, emptyKey) {
  listEl.replaceChildren();
  if (!sources.length) {
    const li = document.createElement('li');
    li.className = 'creative-sources-empty';
    li.textContent = t(emptyKey);
    listEl.appendChild(li);
    return;
  }
  sources.forEach((source) => {
    const li = document.createElement('li');
    if (source.url) {
      const link = document.createElement('a');
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = creativeSourceLabel(source);
      li.appendChild(link);
    } else {
      li.textContent = creativeSourceLabel(source);
    }
    listEl.appendChild(li);
  });
}

function setBusy(busy) {
  // Während der Erzeugung muss das Live-Streaming im Textfeld sichtbar
  // bleiben (siehe readNdjsonStream-Handler unten) - eine aktive Vorschau
  // würde das verdecken, deshalb hier zwingend zurück auf Bearbeiten-Ansicht.
  if (busy && previewMode) {
    setPreviewMode(false);
  }
  submitBtn.disabled = busy;
  instructionField.disabled = busy;
  creativeMicButton.disabled = busy;
  documentField.readOnly = busy;
  statusEl.classList.toggle('hidden', !busy);
  previewToggleBtn.disabled = busy;
  toolbarButtons.forEach((btn) => {
    btn.disabled = busy;
  });
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const instruction = instructionField.value.trim();
  if (!instruction) return;

  errorEl.classList.add('hidden');
  setBusy(true);
  const previousDocument = documentField.value;
  let liveText = '';
  documentField.value = '';

  try {
    const turnstileToken = await getTurnstileToken();
    const res = await fetch('/api/creative', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
      body: JSON.stringify({
        document: previousDocument,
        instruction,
        turnstile_token: turnstileToken,
      }),
    });
    // Turnstile-Tokens sind Einweg-Token - nach jedem Versuch zurücksetzen,
    // damit die nächste Anweisung ein frisches Token bekommt (siehe
    // question.js für dieselbe Konvention).
    resetTurnstile();
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('creative.error'));
    }

    const doneEvent = await readNdjsonStream(
      res,
      {
        delta: (evt) => {
          liveText += evt.text;
          documentField.value = liveText;
        },
        document: (evt) => {
          liveText = evt.document;
          documentField.value = liveText;
        },
      },
      t('creative.error')
    );

    renderSourceList(betacodexListEl, doneEvent.sources.betacodex, 'creative.noBetacodexSources');
    renderSourceList(webListEl, doneEvent.sources.web, 'creative.noWebSources');
    instructionField.value = '';
    autoGrowTextarea(instructionField);
  } catch (err) {
    // Ein fehlgeschlagener Versuch darf das bisherige Dokument nie
    // zerstören - Original wiederherstellen statt leer zu lassen.
    documentField.value = previousDocument;
    errorEl.textContent = t('common.errorPrefix') + err.message;
    errorEl.classList.remove('hidden');
  } finally {
    setBusy(false);
  }
});
