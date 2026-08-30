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

// Nutzerwunsch (2026-08-28): ein Verweis aus dem Konversationsmodus (siehe
// llm.CREATIVE_LINK_PLACEHOLDER/app/main.py) kann die ursprüngliche Frage
// als Anweisung vorausfüllen, damit sie hier nicht erneut eingetippt werden
// muss - liest den optionalen ?instruction=-Query-Parameter beim Laden und
// entfernt ihn danach aus der URL-Zeile (history.replaceState), damit ein
// Neuladen/Teilen der Seite nicht dieselbe Anweisung erneut einsetzt.
const prefilledInstruction = new URLSearchParams(window.location.search).get('instruction');
if (prefilledInstruction) {
  instructionField.value = prefilledInstruction;
  autoGrowTextarea(instructionField);
  history.replaceState(null, '', window.location.pathname);
}

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

// Nutzerwunsch (2026-08-30): abschnittsweises Überarbeiten auf
// Überschriftenebene statt Ganzdokument-Ersatz für die gesamte Anweisung -
// reine, per Node testbare Funktion (siehe tests/test_frontend_js.py),
// analog zu applyMarkdownToSelection.
// Trennt an jeder Zeile, die auf eine Markdown-Überschrift passt, beliebiges
// Level (konsistent mit renderMarkdown() in markdown.js, das alle Ebenen
// optisch gleich behandelt, siehe .md-heading). Text vor der ersten
// Überschrift wird als eigener Abschnitt mit heading: null geführt (auch
// überarbeitbar). Bekannte, akzeptierte Einschränkung: Überschriften-artige
// Zeilen innerhalb von Codeblöcken werden nicht erkannt, da renderMarkdown()
// ohnehin keine Fenced-Code-Blöcke unterstützt.
export function parseCreativeSections(markdown) {
  const headingRe = /^#{1,6}\s+.+$/gm;
  const matches = [...markdown.matchAll(headingRe)];

  if (matches.length === 0) {
    return markdown.length === 0 ? [] : [{ heading: null, text: markdown, start: 0, end: markdown.length }];
  }

  const sections = [];
  if (matches[0].index > 0) {
    sections.push({ heading: null, text: markdown.slice(0, matches[0].index), start: 0, end: matches[0].index });
  }
  matches.forEach((match, i) => {
    const start = match.index;
    const end = i + 1 < matches.length ? matches[i + 1].index : markdown.length;
    sections.push({
      heading: match[0].replace(/^#{1,6}\s+/, '').trim(),
      text: markdown.slice(start, end),
      start,
      end,
    });
  });
  return sections;
}

// Reine, per Node testbare Hilfsfunktion (siehe tests/test_frontend_js.py) -
// ersetzt genau den Abschnitt zwischen start/end (siehe parseCreativeSections)
// durch die überarbeitete Fassung. Trailing "\n\n" nur, wenn danach noch
// weitere Abschnitte folgen - sonst wüchse das Dokumentende bei jeder
// Überarbeitung des letzten Abschnitts um zusätzlichen Leerraum.
export function spliceCreativeSection(document, start, end, replacementText) {
  const isLast = end >= document.length;
  const replacement = replacementText.trim() + (isLast ? '' : '\n\n');
  return document.slice(0, start) + replacement + document.slice(end);
}

let previewMode = false;
// Vom rohen Bearbeiten-Textfeld unabhängige Zustände für das abschnittsweise
// Überarbeiten - werden bei jedem renderPreviewSections()-Aufruf neu
// aufgebaut (innerHTML-Neuaufbau, siehe dort), sectionDrafts bleibt darüber
// hinweg für die Dauer der Session erhalten (Nutzerwunsch: eine zugeklappte,
// noch nicht abgeschickte Anweisung darf nicht verloren gehen).
let currentSections = [];
let currentSectionEls = [];
let openSectionIndex = null;
const sectionDrafts = new Map();

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
    renderPreviewSections();
  }
  relabelPreviewToggle();
}

// Icon-Pfad identisch zu CREATIVE_ICON in header.js (ohne die dortigen
// Funken-Linien - bei der kleineren Größe hier wäre das ohnehin überladen,
// siehe Begründung dort), gleiche Bildsprache wie der Kreativ-Modus-Link
// selbst. SEND_ICON/SECTION_MIC_ICON: exakt dieselbe SVG-Struktur wie die
// bestehenden Buttons in index.html bzw. #creative-mic-button oben.
const SECTION_REVISE_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.855z"></path>' +
  '</svg>';
const SECTION_MIC_ICON =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>' +
  '<path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>' +
  '<line x1="12" y1="19" x2="12" y2="23"></line>' +
  '<line x1="8" y1="23" x2="16" y2="23"></line>' +
  '</svg>';
const SECTION_SEND_ICON =
  '<svg class="send-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="22" y1="2" x2="11" y2="13"></line>' +
  '<polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>' +
  '</svg>';

// Geteilte Sprachsteuerung für Abschnitts-Anweisungen (Nutzerwunsch
// 2026-08-30) - EIN Controller statt eines pro Abschnitt, da wegen der
// Akkordeon-Exklusivität ohnehin nie mehr als ein Panel gleichzeitig offen
// ist. activeSectionTextarea/activeSectionMicBtn zeigen auf das zuletzt per
// Klick aktivierte Panel; onListeningChange löscht sie bewusst NICHT (siehe
// creativeIsListening oben für dasselbe Muster: eine reine Klick-getriggerte
// Zustandsvariable statt einer aus onListeningChange abgeleiteten) - die
// Referenzen werden beim nächsten Mikrofon-Klick ohnehin neu gesetzt, ein
// verzögertes Zurücksetzen hier würde sonst onTranscript (feuert NACH
// onListeningChange(false), siehe speech.js) ins Leere laufen lassen.
// Bug (2026-08-30): sectionListeningIndex wurde bislang im Klick-Handler
// SOFORT/synchron auf null gesetzt, sobald auf ein aktives Mikrofon erneut
// geklickt wurde ("Aufnahme beenden") - onTranscript feuert aber erst
// asynchron NACH recognition.stop() (siehe speech.js: onend ruft zuerst
// onListeningChange(false), danach onTranscript auf). Der dortige Schutz
// `sectionListeningIndex === null` griff dadurch fälschlich IMMER, das
// automatische Absenden nach Diktat-Ende blieb aus - Text stand zwar im
// Feld, "Überarbeiten" musste manuell nachgeklickt werden. Fix: eigene,
// rein klick-getriggerte sectionIsListening-Variable (exakt das Muster von
// creativeIsListening oben für das Hauptfeld) statt den Ziel-Zeiger
// activeSectionIndex für diesen Zweck zu missbrauchen - activeSectionIndex/
// activeSectionTextarea werden dadurch nie vorzeitig zurückgesetzt und
// stehen onTranscript zuverlässig noch zur Verfügung.
let sectionIsListening = false;
let activeSectionIndex = null;
let activeSectionTextarea = null;
let activeSectionMicBtn = null;
const sectionSpeechController = createSpeechController({
  onTranscript: (transcript) => {
    if (!activeSectionTextarea) return;
    activeSectionTextarea.value = transcript;
    sectionDrafts.set(activeSectionIndex, transcript);
    autoGrowTextarea(activeSectionTextarea);
    submitSectionRevision(activeSectionIndex);
  },
  onInterimTranscript: (liveText) => {
    if (!activeSectionTextarea) return;
    activeSectionTextarea.value = liveText;
    autoGrowTextarea(activeSectionTextarea);
  },
  onListeningChange: (listening) => {
    activeSectionMicBtn?.classList.toggle('recording', listening);
    if (activeSectionTextarea) {
      activeSectionTextarea.readOnly = listening;
      activeSectionTextarea.classList.toggle('dictating', listening);
    }
  },
});

function onSectionMicClick(index, textarea, micBtn) {
  if (sectionIsListening && activeSectionIndex === index) {
    sectionSpeechController.stopListening();
    sectionIsListening = false;
    return;
  }
  if (sectionIsListening) sectionSpeechController.stopListening();
  activeSectionIndex = index;
  activeSectionTextarea = textarea;
  activeSectionMicBtn = micBtn;
  sectionIsListening = true;
  sectionSpeechController.startListening();
}

// Baut das DOM für einen Abschnitt samt Überarbeiten-Icon und -Bereich
// (siehe renderPreviewSections). Bewusst per document.createElement statt
// String-Konkatenation für alles außer dem bereits von renderMarkdown()
// selbst escapten Inhalt (siehe dort) - so landen z.B. Übersetzungstexte nie
// ungeprüft in innerHTML (gleiches Muster wie renderSourceList oben).
function buildSectionElement(section, index) {
  const wrapper = document.createElement('div');
  wrapper.className = 'creative-section';
  wrapper.dataset.sectionIndex = String(index);

  const content = document.createElement('div');
  content.className = 'creative-section-content';
  content.innerHTML = renderMarkdown(section.text);
  wrapper.appendChild(content);

  const reviseBtn = document.createElement('button');
  reviseBtn.type = 'button';
  reviseBtn.className = 'creative-section-revise-btn';
  reviseBtn.innerHTML = SECTION_REVISE_ICON;
  const reviseLabel = `${t('creative.sectionReviseButtonTitle')}: ${section.heading || t('creative.sectionIntroLabel')}`;
  reviseBtn.setAttribute('aria-label', reviseLabel);
  reviseBtn.title = reviseLabel;
  wrapper.appendChild(reviseBtn);

  const panel = document.createElement('div');
  panel.className = 'creative-section-revise-panel hidden';

  const question = document.createElement('p');
  question.className = 'creative-section-revise-heading';
  question.textContent = t('creative.sectionQuestionHeading');
  panel.appendChild(question);

  const textarea = document.createElement('textarea');
  textarea.className = 'creative-section-instruction';
  textarea.rows = 2;
  textarea.placeholder = t('creative.sectionInstructionPlaceholder');
  textarea.value = sectionDrafts.get(index) || '';
  textarea.addEventListener('input', () => {
    sectionDrafts.set(index, textarea.value);
    autoGrowTextarea(textarea);
  });
  panel.appendChild(textarea);

  // Nutzerwunsch (2026-08-30): Mikrofon-Button links neben dem
  // Absenden-Button statt neben der Textarea (siehe .creative-submit-row in
  // style.css, gleiches Muster wie im Hauptformular oberhalb).
  const submitRow = document.createElement('div');
  submitRow.className = 'creative-submit-row';

  const micBtn = document.createElement('button');
  micBtn.type = 'button';
  micBtn.className = 'mic-button creative-section-mic-button';
  micBtn.classList.toggle('hidden', !sectionSpeechController.supported);
  micBtn.innerHTML = SECTION_MIC_ICON;
  micBtn.title = t('creative.micButtonTitle');
  micBtn.setAttribute('aria-label', t('creative.micButtonTitle'));
  micBtn.addEventListener('click', () => onSectionMicClick(index, textarea, micBtn));
  submitRow.appendChild(micBtn);

  const submitBtn = document.createElement('button');
  submitBtn.type = 'button';
  submitBtn.className = 'send-button creative-section-submit-btn';
  const submitLabel = t('creative.sectionSubmitButton');
  submitBtn.innerHTML = `${SECTION_SEND_ICON}<span class="send-label"></span>`;
  submitBtn.querySelector('.send-label').textContent = submitLabel;
  submitBtn.title = submitLabel;
  submitBtn.setAttribute('aria-label', submitLabel);
  submitBtn.addEventListener('click', () => submitSectionRevision(index));
  submitRow.appendChild(submitBtn);

  panel.appendChild(submitRow);

  // Nutzerwunsch (2026-08-30): "Wird überarbeitet …" unter dem Anweisungs-
  // feld, exakt analog zu #creative-status im Hauptformular (dort ebenfalls
  // nach der Absenden-Zeile positioniert).
  const statusP = document.createElement('p');
  statusP.className = 'creative-section-status hidden';
  statusP.textContent = t('creative.sectionGenerating');
  panel.appendChild(statusP);

  wrapper.appendChild(panel);
  reviseBtn.addEventListener('click', () => toggleSectionPanel(index));

  return { wrapper, panel, textarea, micBtn, submitBtn, reviseBtn, statusEl: statusP };
}

// Baut die Vorschau komplett aus parseCreativeSections() neu auf (siehe
// dort) - ruft für jeden Abschnitt weiterhin das UNVERÄNDERTE renderMarkdown
// auf (Wiederverwendung, keine neue Rendering-Logik für den eigentlichen
// Inhalt). Wird bei jedem Wechsel in den Vorschau-Modus, nach jeder
// erfolgreichen Abschnitts-Überarbeitung und bei Sprachwechsel (siehe
// i18n:changed unten) neu aufgerufen - openSectionIndex/sectionDrafts
// überleben das, weil sie NICHT im DOM, sondern in Modul-Variablen liegen.
function renderPreviewSections() {
  if (sectionIsListening) {
    sectionSpeechController.stopListening();
    sectionIsListening = false;
  }
  currentSections = parseCreativeSections(documentField.value);
  previewEl.replaceChildren();
  currentSectionEls = currentSections.map((section, index) => {
    const els = buildSectionElement(section, index);
    previewEl.appendChild(els.wrapper);
    return els;
  });
  if (openSectionIndex !== null && openSectionIndex < currentSections.length) {
    currentSectionEls[openSectionIndex].panel.classList.remove('hidden');
  } else {
    openSectionIndex = null;
  }
}

// Akkordeon-Exklusivität (Nutzerwunsch 2026-08-30): Öffnen eines Bereichs
// schließt einen zuvor offenen anderen. Reines Klassen-Umschalten statt
// Neu-Rendern - günstiger und erhält den Fokus/die Scrollposition.
function toggleSectionPanel(index) {
  if (sectionIsListening) {
    sectionSpeechController.stopListening();
    sectionIsListening = false;
  }
  openSectionIndex = openSectionIndex === index ? null : index;
  currentSectionEls.forEach((els, i) => {
    els.panel.classList.toggle('hidden', i !== openSectionIndex);
  });
  if (openSectionIndex !== null) {
    currentSectionEls[openSectionIndex].textarea.focus();
  }
}

// Absenden einer Abschnitts-Überarbeitung (Nutzerwunsch 2026-08-30): anders
// als beim Hauptformular KEIN sichtbares Live-Streaming im Panel - der
// Bereich klappt erst nach vollständiger Antwort zu, die Vorschau wird dann
// an der Stelle neu geladen (readNdjsonStream ohne delta-Handler, siehe
// ndjson-stream.js: handlers[event.type]?.() ist bereits sicher gegen
// fehlende Handler).
async function submitSectionRevision(index) {
  const els = currentSectionEls[index];
  const section = currentSections[index];
  const instruction = els.textarea.value.trim();
  if (!instruction) return;

  errorEl.classList.add('hidden');
  setBusy(true, { forceEditMode: false });
  els.statusEl.classList.remove('hidden');

  try {
    const turnstileToken = await getTurnstileToken();
    const res = await fetch('/api/creative', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Lang': getLang() },
      body: JSON.stringify({
        document: documentField.value,
        instruction,
        section: section.text,
        turnstile_token: turnstileToken,
      }),
    });
    resetTurnstile();
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('creative.error'));
    }

    // Der überarbeitete Abschnittstext steckt im "document"-Event (siehe
    // app/main.py:_creative_event_stream), NICHT im "done"-Event (das trägt
    // nur die Quellenliste) - kein delta-Handler nötig, da im Panel kein
    // Live-Streaming sichtbar sein soll (siehe Funktionskommentar oben).
    let revisedSectionText = '';
    const doneEvent = await readNdjsonStream(
      res,
      { document: (evt) => { revisedSectionText = evt.document; } },
      t('creative.error')
    );
    documentField.value = spliceCreativeSection(documentField.value, section.start, section.end, revisedSectionText);
    sectionDrafts.delete(index);
    openSectionIndex = null;
    renderPreviewSections();
    renderSourceList(betacodexListEl, doneEvent.sources.betacodex, 'creative.noBetacodexSources');
    renderSourceList(webListEl, doneEvent.sources.web, 'creative.noWebSources');
  } catch (err) {
    // Fehlschlag darf die eingetippte Anweisung nicht zerstören und das
    // Panel nicht schließen - Nutzer:in soll ohne erneutes Eintippen
    // nochmal versuchen können (siehe Nutzervorgabe: Anweisung bleibt beim
    // Zuklappen erhalten - erst recht bei einem Fehler, wo gar nicht
    // zugeklappt wurde).
    errorEl.textContent = t('common.errorPrefix') + err.message;
    errorEl.classList.remove('hidden');
  } finally {
    setBusy(false, { forceEditMode: false });
    els.statusEl.classList.add('hidden');
  }
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
// Übersetzungstexte im Überarbeiten-Bereich (Frage-Überschrift, Platzhalter,
// Button-Labels) werden per t() direkt beim Rendern gesetzt (siehe
// buildSectionElement), nicht per data-i18n - die generische
// applyStaticTranslations()-Anwendung in i18n.js läuft nur einmalig beim
// Start bzw. bei i18n:changed und würde die bei jedem Rendering neu
// entstehenden Abschnitts-Elemente sonst nie erfassen. Deshalb hier
// zusätzlich neu rendern, wenn die Vorschau gerade sichtbar ist.
document.addEventListener('i18n:changed', () => {
  if (previewMode) renderPreviewSections();
});

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

// forceEditMode (Nutzerwunsch 2026-08-30, Default true = bisheriges
// Verhalten): eine Ganzdokument-Generierung erzwingt weiterhin die
// Bearbeiten-Ansicht (siehe Kommentar unten), eine Abschnitts-Überarbeitung
// (submitSectionRevision) übergibt hier bewusst false - die Vorschau IST
// dort die Oberfläche, aus ihr herauszuspringen würde den gerade genutzten
// Überarbeiten-Bereich unter den Füßen wegziehen.
function setBusy(busy, { forceEditMode = true } = {}) {
  // Während der Erzeugung muss das Live-Streaming im Textfeld sichtbar
  // bleiben (siehe readNdjsonStream-Handler unten) - eine aktive Vorschau
  // würde das verdecken, deshalb hier zwingend zurück auf Bearbeiten-Ansicht.
  if (busy && previewMode && forceEditMode) {
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
  // Verhindert überlappende Anfragen zwischen Ganzdokument-Generierung und
  // Abschnitts-Überarbeitung(en) - beide teilen sich Dokument/Turnstile.
  currentSectionEls.forEach((els) => {
    els.reviseBtn.disabled = busy;
    els.submitBtn.disabled = busy;
    els.micBtn.disabled = busy;
    els.textarea.disabled = busy;
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

    // Eine Ganzdokument-Ersetzung macht alle bisherigen Abschnitts-Offsets
    // und darauf bezogene, noch nicht abgeschickte Entwürfe ungültig - ein
    // Entwurf zu einem Abschnitt, der so danach nicht mehr existiert, wäre
    // beim nächsten Aufklappen der Vorschau irreführend.
    sectionDrafts.clear();
    openSectionIndex = null;
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
