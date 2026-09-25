import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { initAuth, hasRole, onAuthChange } from '/auth.js';
import { CONVERSATION_STORAGE_KEY, consumeConversationHandoffToken } from '/conversation-handoff.js';
import { readNdjsonStream } from '/ndjson-stream.js';
import {
  EXTERNAL_LINK_ICON,
  TRASH_ICON,
  MAGIC_ICON,
  UNDO_DURATION_MS,
  buildMarkupToolbar,
  urlErrorText,
  jsonHeaders,
  normalizeAuthor,
  buildAuthorFields,
  buildEditPanel,
  attachTagSuggestions,
  addMagicButton,
  normalizeTerm,
  SOCIAL_PLATFORM_HOSTS,
  detectSocialPlatform,
  buildSocialLinksField,
  extractHostname,
  resetKnownTerms,
  setKnownAuthors,
} from '/source-edit.js';

const importBereich = document.getElementById('import-bereich');
const urlPopover = document.getElementById('url-popover');
const filePopover = document.getElementById('file-popover');
const quelltypBereich = document.getElementById('quelltyp-bereich');
const reindexBereich = document.getElementById('reindex-bereich');
const brokenLinksBtn = document.getElementById('typ-broken-links');
const mobileImportSlot = document.getElementById('mobile-import-slot');
// Ursprünglicher Elternknoten (die schmale Icon-Spalte, siehe
// .quelltyp-item--anchor) - wird beim Öffnen auf Mobile gegen
// mobileImportSlot getauscht (siehe setPopoverAccordionMode) und beim
// nächsten Öffnen auf Desktop wieder hergestellt. Muss VOR jeder Umhängung
// eingelesen werden, deshalb hier ganz am Modulanfang.
const urlPopoverHome = urlPopover.parentElement;
const filePopoverHome = filePopover.parentElement;

// Backlog: LLM/Internet-Fallback bei dünner Quellenlage.
const webAllowlistBtn = document.getElementById('typ-web-allowlist');
const webAllowlistWarning = document.getElementById('web-allowlist-warning');
const webAllowlistBereich = document.getElementById('web-allowlist-bereich');
const webAllowlistList = document.getElementById('web-allowlist-list');
const webAllowlistPendingList = document.getElementById('web-allowlist-pending-list');
const webAllowlistForm = document.getElementById('web-allowlist-form');

// Nutzerwunsch: proaktive Quellen-Vorschläge aus dem offenen Web.
const sourceSuggestionsBtn = document.getElementById('typ-source-suggestions');
const sourceSuggestionsBereich = document.getElementById('source-suggestions-bereich');
const sourceSuggestionsList = document.getElementById('source-suggestions-list');
const sourceSuggestionsEmpty = document.getElementById('source-suggestions-empty');

const EDIT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  "</svg>";

const WARNING_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M14 4l1.5-1.5a3.54 3.54 0 1 1 5 5L19 9"></path>' +
  '<path d="M10 15l-1.5 1.5a3.54 3.54 0 1 1-5-5L5 10"></path>' +
  '<line x1="3" y1="3" x2="21" y2="21"></line>' +
  "</svg>";

// Nutzerwunsch (Positivselektion): macht sichtbar, wenn app/web_crawler.py
// für eine Website automatisch von "Negativselektion" (bereits indizierte
// Seiten bereinigen) auf "Positivselektion" (Kandidaten gezielt auswählen)
// umgeschaltet hat - Warndreieck statt des durchgestrichenen Ketten-Symbols
// (das steht für defekte Links, ein anderer Sachverhalt).
const POSITIVE_SELECTION_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 9v4"></path><path d="M12 17h.01"></path>' +
  '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"></path>' +
  "</svg>";


let allSources = [];
// Die zuletzt an renderSourceList() übergebene, NICHT expandierte Quellenliste
// (z.B. allSources oder eine gefilterte Teilmenge) - wird für Re-Renders der
// gleichen Ansicht (Auf-/Zuklappen, nach Bearbeiten, ...) verwendet. Würde man
// stattdessen currentDisplayedSources erneut übergeben, würde sortSources()
// im Autoren-Modus die dort bereits (Quelle, Autor)-expandierten Einträge bei
// jedem Re-Render erneut expandieren (Quelle erscheint dann mehrfach).
let currentSourceList = [];
let currentDisplayedSources = [];
// Backlog #57: die Quellenliste wird nicht komplett auf einmal ins DOM
// gerendert, sondern nur die ersten SOURCES_PAGE_SIZE Einträge - beim
// Erreichen des Listenendes (IntersectionObserver auf einem Sentinel-Element,
// siehe renderSourceList) wächst visibleSourceCount um eine weitere Seite.
// Die Daten selbst (allSources) sind weiterhin komplett geladen - es geht
// hier nur um die Menge an gleichzeitig existierenden DOM-Knoten.
const SOURCES_PAGE_SIZE = 20;
let visibleSourceCount = SOURCES_PAGE_SIZE;
let sourceListObserver = null;
let activeEditId = null;
// Fix (2026-09-22, gemeldeter Bug): im Autor:innen-Modus bekommt eine Quelle
// mit mehreren Autor:innen pro Autor:in eine eigene Zeile (siehe
// sortSources) - activeEditId allein (nur die Quellen-ID) matchte bisher
// ALLE davon gleichzeitig, öffnete also mehrere Bearbeiten-Panels derselben
// Quelle auf einmal (der zuvor behobene ID-Kollisions-Bug war nur ein
// Symptom davon). __sortAuthor identifiziert zusätzlich, UNTER WELCHER
// Autor:in-Überschrift die konkrete Zeile steht - außerhalb des Autor:innen-
// Modus (dort immer null bei allen Zeilen) bleibt das wirkungslos.
let activeEditAuthorKey = null;
// Schlagwort-Ansicht (2026-09-24): dieselbe Quelle kann dort unter mehreren
// aufgeklappten Schlagworten stehen - __editRowKey unterscheidet diese Zeilen
// wie __sortAuthor die Autor:innen-Zeilen.
function editRowKey(s) {
  return s.__editRowKey || s.__sortAuthor || null;
}
function isActiveEditRow(s) {
  return activeEditId === s.id && activeEditAuthorKey === editRowKey(s);
}
let pendingUploadId = null;
let pendingUploadType = null; // 'pdf' | 'audio'
let currentSortMode = 'author';
// Backlog #94: kein Popover (auf Mobile unpraktikabel, siehe git-Historie)
// - stattdessen klappt dieser Bereich unterhalb der Icon-Leiste auf und
// ersetzt dabei die Alphabet-Sprungleiste (siehe updateAlphabetJumpBar).
let searchBarOpen = false;
const pendingDeletions = new Map();
const expandedSourceIds = new Set();

// Wird bei jedem Wechsel auf eine inhaltlich NEUE Liste aufgerufen (neuer
// Filter, Filter aufgehoben) - nicht aber bei einem bloßen Re-Render der
// gleichen Ansicht (Auf-/Zuklappen, Bearbeiten, Neuladen nach einer Änderung),
// damit die Scroll-/Lade-Position dabei nicht unnötig auf die erste Seite
// zurückspringt.
function resetSourcePagination() {
  visibleSourceCount = SOURCES_PAGE_SIZE;
}

// Stellt sicher, dass eine bestimmte Quelle (z.B. per Deep-Link direkt im
// Bearbeiten-Modus geöffnet) unabhängig von ihrer Position in der sortierten
// Liste bereits im sichtbaren, paginierten Bereich liegt.
function ensureSourceVisible(sourceId) {
  const index = sortSources(currentSourceList).findIndex((s) => s.id === sourceId);
  if (index >= 0) {
    visibleSourceCount = Math.max(visibleSourceCount, index + 1);
  }
}

let allAuthors = [];
// Das aktuell nach Filter angezeigte Autor:innen-Profil (nur gesetzt, wenn
// per Namen gefiltert wird) - steuert die zweigeteilte Ansicht neben der
// gefilterten Quellenliste (buildAuthorInfoView/buildAuthorEditPanel).
let filteredAuthorEntry = null;
let authorPanelEditMode = false;

function hasPflegerRole() {
  return hasRole('quellen_pfleger');
}

function updateSourceManagementVisibility() {
  // Nutzerwunsch (2026-09-02): Nutzer:innen ohne Quellen-Pfleger:innen-Rolle
  // können auf dieser Seite nichts verwalten, nur die bereits importierten
  // Quellen einsehen - "Quellen verwalten" als Überschrift ist für sie
  // irreführend. Muss auch bei einem Sprachwechsel erneut gesetzt werden
  // (siehe i18n:changed weiter unten), da applyStaticTranslations() das
  // [data-i18n]-Attribut sonst wieder auf den Standardtext zurücksetzt.
  document.getElementById('import-page-heading').textContent = hasPflegerRole()
    ? t('import.title')
    : t('import.titleReadOnly');
  quelltypBereich.classList.toggle('hidden', !hasPflegerRole());
  reindexBereich.classList.toggle('hidden', !hasPflegerRole());
  // Sichtbarkeit des Broken-Links-Buttons hängt zusätzlich von der Anzahl
  // defekter Links ab - das übernimmt updateBrokenLinksButton() komplett
  // (wird am Ende jedes loadSources()-Laufs aufgerufen).
  if (!hasPflegerRole()) {
    importBereich.classList.add('hidden');
    urlPopover.classList.add('hidden');
    filePopover.classList.add('hidden');
    webAllowlistBereich.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
    sourceSuggestionsBereich.classList.add('hidden');
    stopJobsPolling();
  } else {
    startJobsPolling();
    loadWebAllowlist();
    loadSourceSuggestions();
  }
}

// Grobe Stufen-zu-Füllstand-Zuordnung fürs Fortschritts-Icon - die OpenAI-
// Transkriptions-API liefert kein echtes Fortschritts-Signal, daher kein
// exakter Prozentsatz, nur eine Annäherung je Verarbeitungsschritt.
const JOB_STAGE_FRACTIONS = { transcribe: 0.3, ocr: 0.3, chunking: 0.8, indexing: 0.9, summarizing: 0.97 };
const JOBS_RING_CIRCUMFERENCE = 56.5;
let jobsPollTimer = null;

function jobStepLabel(job) {
  const key = {
    transcribe: 'import.processingStepTranscribe',
    ocr: 'import.processingStepOcr',
    chunking: 'import.processingStepChunking',
    indexing: 'import.processingStepIndexing',
    summarizing: 'import.processingStepSummarizing',
  }[job.processing_step];
  return t(key || 'import.processingStepPending');
}

function renderJobsIcon(jobs) {
  const typJobsBtn = document.getElementById('typ-jobs');
  const countBadge = document.getElementById('jobs-icon-count');
  const warningBadge = document.getElementById('jobs-icon-warning');
  const progressCircle = document.getElementById('jobs-icon-progress');

  if (!jobs.length) {
    typJobsBtn.classList.add('hidden');
    document.getElementById('jobs-popover').classList.add('hidden');
    document.getElementById('jobs-bar').classList.add('hidden');
    return;
  }
  typJobsBtn.classList.remove('hidden');
  const hasError = jobs.some((job) => job.processing_status === 'error');
  typJobsBtn.classList.toggle('has-error', hasError);
  warningBadge.classList.toggle('hidden', !hasError);

  const activeJob = jobs.find((job) => job.processing_status === 'running') || jobs[0];
  const fraction = JOB_STAGE_FRACTIONS[activeJob.processing_step] || 0.05;
  progressCircle.setAttribute('stroke-dashoffset', String(JOBS_RING_CIRCUMFERENCE * (1 - fraction)));

  countBadge.textContent = String(jobs.length);
  countBadge.classList.toggle('hidden', jobs.length <= 1);
}

// Befüllt EINE Ziel-Liste (Desktop-Popover ODER Mobile-Bar, siehe
// renderJobsList) mit denselben Job-Einträgen inkl. Retry-Button - beide
// Listen bleiben so immer synchron, unabhängig davon, welche gerade
// sichtbar ist.
function renderJobsListInto(list, jobs) {
  list.innerHTML = '';
  jobs.forEach((job) => {
    const li = document.createElement('li');
    const title = document.createElement('span');
    title.className = 'jobs-list-title';
    title.textContent = job.title;
    li.appendChild(title);

    if (job.processing_status === 'error') {
      const errorText = document.createElement('p');
      errorText.className = 'jobs-list-error';
      errorText.textContent = job.processing_error || '';
      li.appendChild(errorText);

      const retryBtn = document.createElement('button');
      retryBtn.type = 'button';
      retryBtn.className = 'link-button';
      retryBtn.textContent = t('import.reprocessButton');
      retryBtn.addEventListener('click', async () => {
        retryBtn.disabled = true;
        try {
          await fetch(`/api/sources/${job.id}/reprocess`, { method: 'POST', headers: jsonHeaders() });
          await Promise.all([fetchImportJobs(), loadSources()]);
        } finally {
          retryBtn.disabled = false;
        }
      });
      li.appendChild(retryBtn);

      // Nutzerwunsch: "Erneut versuchen" kann einen fehlgeschlagenen Import
      // nicht immer retten (z.B. wenn die zugrunde liegende Datei/URL nie
      // erreichbar war - reprocess lehnt dann selbst sofort mit "keine
      // Datei gefunden" ab). Ohne einen direkten Abbrechen-Weg blieb so ein
      // Job für immer in dieser Liste hängen, das eigentliche Löschen war
      // nur über die separate Quellenliste möglich. Zweistufige
      // Bestätigung direkt am Link statt eines nativen confirm()-Dialogs,
      // gleiches Muster wie beim Löschen einer Website-Quelle.
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'link-button';
      cancelBtn.textContent = cancelConfirmPendingJobIds.has(job.id)
        ? t('import.cancelImportConfirmButton')
        : t('import.cancelImportButton');
      cancelBtn.addEventListener('click', async () => {
        if (!cancelConfirmPendingJobIds.has(job.id)) {
          cancelConfirmPendingJobIds.add(job.id);
          cancelBtn.textContent = t('import.cancelImportConfirmButton');
          return;
        }
        cancelBtn.disabled = true;
        try {
          await fetch(`/api/sources/${job.id}`, { method: 'DELETE', headers: jsonHeaders() });
          cancelConfirmPendingJobIds.delete(job.id);
          await Promise.all([fetchImportJobs(), loadSources()]);
        } finally {
          cancelBtn.disabled = false;
        }
      });
      li.appendChild(cancelBtn);
    } else {
      const step = document.createElement('span');
      step.className = 'jobs-list-step';
      step.textContent = jobStepLabel(job);
      li.appendChild(step);
    }
    list.appendChild(li);
  });
}

function renderJobsList(jobs) {
  renderJobsListInto(document.getElementById('jobs-list'), jobs);
  renderJobsListInto(document.getElementById('jobs-bar-list'), jobs);
}

let previousJobIds = new Set();

// Fix: der 3-Sekunden-Poll-Takt (pollBackgroundImportStatus) ruft
// renderJobsListInto bei JEDEM Tick neu auf (baut die Buttons komplett neu
// auf), das warf den "Sicher?"-Bestätigungsstatus des Abbrechen-Buttons
// weg, bevor der zweite Klick möglich war, wenn dazwischen ein Poll-Takt
// lag. Zustand deshalb hier auf Modul-Ebene statt in einer lokalen
// Button-Closure - übersteht den Re-Render.
const cancelConfirmPendingJobIds = new Set();

async function fetchImportJobs() {
  if (!hasPflegerRole()) return;
  try {
    const res = await fetch('/api/import-jobs', { headers: jsonHeaders() });
    if (!res.ok) return;
    const jobs = await res.json();
    renderJobsIcon(jobs);
    renderJobsList(jobs);

    // Die "Wird verarbeitet..."-Markierung an der Quellen-Zeile stammt aus
    // dem zuletzt geladenen Quellen-Snapshot (allSources) - ohne diesen
    // gezielten Refresh bliebe sie stehen, bis die Seite manuell neu
    // geladen wird, selbst wenn der Job längst fertig ist. Nur bei
    // TATSÄCHLICHER Änderung der Job-Menge neu laden (nicht bei jedem
    // Poll-Takt).
    const currentJobIds = new Set(jobs.map((job) => job.id));
    const jobsChanged =
      currentJobIds.size !== previousJobIds.size ||
      [...currentJobIds].some((id) => !previousJobIds.has(id));
    previousJobIds = currentJobIds;
    if (jobsChanged) {
      loadSources();
    }
  } catch (err) {
    // Stille Hintergrund-Aktualisierung - der nächste Poll-Takt versucht
    // es einfach erneut, keine Fehlermeldung nötig.
  }
}

function pollBackgroundImportStatus() {
  fetchImportJobs();
  // Nutzerwunsch: derselbe Poll-Takt zeigt auch den Website-
  // Indizierungsstatus (Fortschrittsring am Globus-Icon) live an, statt
  // dafür ein zweites Intervall zu eröffnen. Bewusst NICHT loadWebAllowlist()
  // (baut #web-allowlist-list komplett neu auf, siehe renderWebAllowlistList)
  // - Bugfix (Nutzerfeedback): das riss ein gerade erst geöffnetes
  // Seiten-Akkordeon (<details>, siehe buildWebAllowlistPagesAccordion)
  // beim nächsten Poll-Takt sofort wieder zu, weil jedes Mal ein
  // brandneues, geschlossenes <details>-Element entsteht. pollWebAllowlist-
  // Status() (weiter unten) aktualisiert nur Ring + Warn-Badge, ohne die
  // Liste selbst anzufassen.
  pollWebAllowlistStatus();
}

function startJobsPolling() {
  if (jobsPollTimer) return;
  pollBackgroundImportStatus();
  // Erstes und bisher einziges Polling im Projekt (siehe README/Kommentar
  // hier bewusst) - kein Vorbild für generelle Live-Aktualisierungen,
  // sondern gezielt für den Import-Warteschlangen-Status (Audio/PDF-
  // Verarbeitung + Website-Indizierung).
  jobsPollTimer = setInterval(pollBackgroundImportStatus, 3000);
}

function stopJobsPolling() {
  if (jobsPollTimer) {
    clearInterval(jobsPollTimer);
    jobsPollTimer = null;
  }
  document.getElementById('typ-jobs').classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
}

// Backlog: gleiche Bildschirmbreite, ab der .popover auf position:static
// wechselt (siehe style.css) - unterhalb dieser Breite verschob das
// Job-Popover als Flex-Item innerhalb der Icon-Leiste alle Icons sichtbar
// (siehe .quelltyp-item--anchor), analog zum bereits gelösten Suchfeld-
// Problem (#94). Deshalb dieselbe Lösung: auf Mobile ein eigener,
// vollbreiter Bereich (#jobs-bar) statt des Popovers.
function isMobileLayout() {
  return window.matchMedia('(max-width: 480px)').matches;
}

// Backlog (2026-08-04): Nutzerwunsch - #url-popover/#file-popover sollen auf
// Mobile nicht mehr als (schwebendes oder als Overlay über der Seite
// liegendes) Popover erscheinen, sondern wie ein Akkordeon den restlichen
// Seiteninhalt nach unten schieben, mit einem kleinen Kreuz zum Schließen.
// Statt das Popover zu duplizieren (zwei Sets derselben Formularfelder mit
// unterschiedlichen IDs, wie es die reine Anzeige-Liste bei
// #jobs-list/#jobs-bar-list tut), wird hier dasselbe Element mit all seinen
// IDs/Event-Listenern einfach an einen anderen Elternknoten gehängt -
// dokumentInterne Referenzen (getElementById) bleiben davon unberührt.
function setPopoverAccordionMode(popover, home, closeBtn, accordionMode) {
  (accordionMode ? mobileImportSlot : home).appendChild(popover);
  popover.classList.toggle('accordion-panel', accordionMode);
  closeBtn.classList.toggle('hidden', !accordionMode);
}

function showForm() {
  importBereich.classList.remove('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  // Sonst stand nach einem erfolgreichen Import und direktem Anlegen der
  // nächsten Quelle noch die alte Erfolgsmeldung unter dem Formular.
  document.getElementById('import-status').textContent = '';
}

// Fix: Formular zum Anlegen einer neuen Quelle ließ sich bisher nur über
// einen erfolgreichen Import wieder schließen - weder ein Abbrechen-Button
// noch ein erneuter Klick auf das Papier-Icon (typ-text) hatten einen
// Effekt. Setzt auch einen eventuell angehängten Audio-/PDF-Upload-Bezug
// zurück, damit der beim nächsten Öffnen nicht versehentlich mit
// übernommen wird.
function hideForm() {
  importBereich.classList.add('hidden');
  pendingUploadId = null;
  pendingUploadType = null;
  document.getElementById('import-status').textContent = '';
}

// hintElementId wählt den passenden Hinweistext (Audio-Transkription vs.
// PDF-Texterkennung, siehe #audio-text-pending-hint/#pdf-text-pending-hint)
// - der jeweils andere Hinweis wird dabei stets mitversteckt, damit nach
// einem Wechsel zwischen Audio- und PDF-Upload nicht beide gleichzeitig
// sichtbar bleiben.
function setTextFieldPending(pending, hintElementId) {
  document.getElementById('text-field-label').classList.toggle('hidden', pending);
  document.getElementById('text').required = !pending;
  document.getElementById('audio-text-pending-hint').classList.toggle(
    'hidden',
    !(pending && hintElementId === 'audio-text-pending-hint')
  );
  document.getElementById('pdf-text-pending-hint').classList.toggle(
    'hidden',
    !(pending && hintElementId === 'pdf-text-pending-hint')
  );
}

// Backlog #201 (2026-08-03): auf Produktion blockiert YouTube automatisierte
// Transkript-Anfragen (siehe app/extraction.py) - anders als bei Audio-
// Transkription/PDF-OCR gibt es dafür KEINEN Hintergrund-Job, der den Text
// nachliefert (setTextFieldPending waere hier also irrefuehrend: das Feld
// bleibt bewusst sichtbar UND required, die Person muss den Text selbst
// einfuegen). Zusaetzlich zum bestehenden generischen "extractionEmpty"-
// Status-Text erscheint hier ein klickbarer Link zum externen Transkript-
// Dienst plus kurzer Anleitung - baut das Element bei Bedarf einmalig aus
// JS auf (data-i18n kann nur textContent setzen, hier wird aber ein
// verschachtelter <a>-Link innerhalb des Hinweistexts gebraucht).
function setYoutubeTranscriptFallbackHintVisible(visible) {
  const hint = document.getElementById('youtube-transcript-fallback-hint');
  hint.classList.toggle('hidden', !visible);
  if (!visible || hint.childNodes.length) return;
  hint.append(t('import.youtubeTranscriptFallbackHint') + ' ');
  const link = document.createElement('a');
  link.href = 'https://www.youtube-transcript.io/';
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = t('import.youtubeTranscriptFallbackLinkLabel');
  hint.appendChild(link);
}

// Die meisten Audio-Direktlinks (z.B. die eigentliche mp3-Datei) stammen von
// einer Website/einem Blogbeitrag, der die Folge einbettet - dieses Feld
// existiert im Datenmodell schon lange (listen_url, siehe Bearbeiten-
// Formular), fehlte aber im Neu-anlegen-Formular. Wird nur bei erkannter
// Audio-Quelle eingeblendet, damit der/die Quellen-Pfleger:in die
// zugehörige Anhör-Seite gleich mit erfassen kann.
function setListenUrlFieldVisible(visible) {
  document.getElementById('listen-url-label').classList.toggle('hidden', !visible);
}

function fillForm({
  title = '',
  authors = [],
  date = '',
  url = '',
  text = '',
  restricted = false,
}) {
  document.getElementById('title').value = title;
  renderCreateAuthorDateRow(authors, date);
  document.getElementById('url').value = url;
  document.getElementById('text').value = text;
  document.getElementById('restricted').checked = restricted;
  document.getElementById('listen-url').value = '';
  setTextFieldPending(false, null);
  setYoutubeTranscriptFallbackHintVisible(false);
  setListenUrlFieldVisible(false);
}

document.getElementById('typ-text').addEventListener('click', () => {
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  webAllowlistBereich.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
  closeSearchBar();
  if (!importBereich.classList.contains('hidden')) {
    hideForm();
    return;
  }
  pendingUploadId = null;
  pendingUploadType = null;
  fillForm({});
  showForm();
});

document.getElementById('import-cancel-button').addEventListener('click', hideForm);

// Wird von den Popover-Buttons (url/file/jobs) mitverwendet, damit sich der
// Suchbereich schließt, sobald eine andere Aktion in der Icon-Leiste
// gestartet wird - analog dazu, dass diese sich gegenseitig schließen.
function closeSearchBar() {
  if (!searchBarOpen) return;
  searchBarOpen = false;
  document.getElementById('search-bar').classList.add('hidden');
  renderSourceList(currentSourceList);
}

const urlPopoverCloseBtn = document.getElementById('url-popover-close');
const filePopoverCloseBtn = document.getElementById('file-popover-close');

document.getElementById('typ-url').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  filePopover.classList.add('hidden');
  webAllowlistBereich.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
  closeSearchBar();
  setPopoverAccordionMode(urlPopover, urlPopoverHome, urlPopoverCloseBtn, isMobileLayout());
  urlPopover.classList.toggle('hidden');
  document.getElementById('popover-status').textContent = '';
  if (!urlPopover.classList.contains('hidden')) {
    // Fix: stand sonst noch die URL eines vorherigen (auch fehlgeschlagenen
    // oder abgebrochenen) Versuchs im Feld, wenn das Popover erneut geöffnet
    // wurde - nicht nur nach einem tatsächlich abgeschlossenen Import (siehe
    // das bestehende Leeren weiter unten im Submit-Handler).
    document.getElementById('popover-url').value = '';
    document.getElementById('popover-url').focus();
  }
});

document.getElementById('typ-file').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  webAllowlistBereich.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
  closeSearchBar();
  setPopoverAccordionMode(filePopover, filePopoverHome, filePopoverCloseBtn, isMobileLayout());
  filePopover.classList.toggle('hidden');
  document.getElementById('upload-status').textContent = '';
});

urlPopoverCloseBtn.addEventListener('click', () => urlPopover.classList.add('hidden'));
filePopoverCloseBtn.addEventListener('click', () => filePopover.classList.add('hidden'));

document.getElementById('typ-jobs').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  webAllowlistBereich.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
  closeSearchBar();
  if (isMobileLayout()) {
    document.getElementById('jobs-popover').classList.add('hidden');
    document.getElementById('jobs-bar').classList.toggle('hidden');
  } else {
    document.getElementById('jobs-bar').classList.add('hidden');
    document.getElementById('jobs-popover').classList.toggle('hidden');
  }
});

document.getElementById('jobs-bar-close').addEventListener('click', () => {
  document.getElementById('jobs-bar').classList.add('hidden');
});

document.getElementById('typ-search').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  webAllowlistBereich.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
  searchBarOpen = !searchBarOpen;
  document.getElementById('search-bar').classList.toggle('hidden', !searchBarOpen);
  renderSourceList(currentSourceList);
  if (searchBarOpen) {
    document.getElementById('search-input').focus();
  }
});

document.getElementById('typ-web-allowlist').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
  closeSearchBar();
  // Fix (Nutzerfeedback): #web-allowlist-bereich saß ursprünglich als
  // eigene <section> weit unten im DOM, NACH der (potenziell langen)
  // Quellenliste - beim Öffnen blieb der sichtbare Ausschnitt unverändert,
  // wirkte dadurch wie "der Button tut nichts". Sitzt jetzt wie #search-bar
  // direkt hier oben im Werkzeugleisten-Bereich (siehe import.html), klappt
  // also unmittelbar sichtbar auf - kein zusätzliches Scrollen nötig.
  webAllowlistBereich.classList.toggle('hidden');
});

document.getElementById('typ-source-suggestions').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  webAllowlistBereich.classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
  closeSearchBar();
  sourceSuggestionsBereich.classList.toggle('hidden');
});

// Nutzerwunsch (2026-08-27): eigenes "x" zum Schließen direkt im Panel,
// analog zu #jobs-bar-close - der Glühbirnen-Button (oben) bleibt zusätzlich
// als Öffnen/Schließen-Toggle funktionsfähig.
document.getElementById('source-suggestions-close').addEventListener('click', () => {
  sourceSuggestionsBereich.classList.add('hidden');
});

// Nutzerwunsch (2026-09-22): bestehende Schlagworte auf inhaltliche Nähe
// prüfen ("hierarchiefreie Organisationen" vs. "hierarchielose
// Organisation") und zusammenführen - Analyse startet bewusst erst auf
// Klick (kostenpflichtiger KI-Aufruf über beide Sprachen), keine Vorschläge
// werden ohne explizite Bestätigung pro Gruppe angewendet.
const termMergeBereich = document.getElementById('term-merge-bereich');
const termMergeList = document.getElementById('term-merge-list');
const termMergeStatus = document.getElementById('term-merge-status');
const termMergeEmpty = document.getElementById('term-merge-empty');
const termMergeAnalyzeBtn = document.getElementById('term-merge-analyze');

document.getElementById('typ-term-merge').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  webAllowlistBereich.classList.add('hidden');
  sourceSuggestionsBereich.classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
  closeSearchBar();
  termMergeBereich.classList.toggle('hidden');
});

document.getElementById('term-merge-close').addEventListener('click', () => {
  termMergeBereich.classList.add('hidden');
});

function renderTermMergeGroup(group) {
  const li = document.createElement('li');
  const text = document.createElement('p');
  text.className = 'jobs-list-title';
  li.appendChild(text);

  // Nutzerwunsch (2026-09-23): DE- und EN-Begriffe können sich in der
  // Schreibweise ähneln, ohne gleich zu sein - eigenes Sprach-Badge pro
  // Gruppe, damit auf einen Blick klar ist, aus welcher Sprache sie stammt
  // (gilt für Zielschlagwort UND alle Varianten gleichermaßen, eine Gruppe
  // wird immer nur innerhalb EINER Sprache gebildet, siehe
  // get_term_merge_suggestions in app/main.py).
  const langBadge = document.createElement('span');
  langBadge.className = 'restricted-badge';
  langBadge.textContent = group.lang.toUpperCase();

  // Nutzerwunsch (2026-09-23): nicht immer passt der vorgeschlagene
  // Zielbegriff ODER die vorgeschlagenen Varianten - das Zielschlagwort
  // lässt sich deshalb frei eintippen, mit demselben Vorschlags-Widget wie
  // beim manuellen Bearbeiten einer Quelle (siehe attachTagSuggestions),
  // damit ein neuer Zielbegriff nicht versehentlich zu einer weiteren
  // Schreibvariante eines längst vorhandenen Begriffs wird. Nutzerwunsch
  // (Nachtrag): ein dauerhaft sichtbares Eingabefeld wirkte im Fließtext zu
  // unruhig - normal nur Text, ein Klick aufs Stift-Icon (dasselbe wie beim
  // Quellen-Bearbeiten-Button) blendet stattdessen das Eingabefeld ein.
  // Alle Elemente EINMAL über die gesamte Lebensdauer der Zeile erzeugt
  // (nicht bei jedem renderGroupText()-Aufruf neu) - sonst würde jeder
  // Varianten-Tausch eine weitere Vorschlagsliste anhängen und eine gerade
  // laufende Eingabe verwerfen.
  const canonicalWrap = document.createElement('span');
  canonicalWrap.className = 'term-merge-canonical-wrap';

  const canonicalText = document.createElement('span');
  canonicalText.className = 'term-merge-canonical-text';

  const editCanonicalBtn = document.createElement('button');
  editCanonicalBtn.type = 'button';
  editCanonicalBtn.className = 'icon-button term-merge-edit-canonical';
  editCanonicalBtn.innerHTML = EDIT_ICON;
  const editCanonicalLabel = t('import.termMergeEditCanonicalTitle');
  editCanonicalBtn.title = editCanonicalLabel;
  editCanonicalBtn.setAttribute('aria-label', editCanonicalLabel);

  const canonicalInput = document.createElement('input');
  canonicalInput.type = 'text';
  canonicalInput.className = 'term-merge-canonical-input hidden';
  canonicalInput.title = t('import.termMergeCanonicalInputTitle');
  const canonicalSuggestions = attachTagSuggestions(canonicalInput, { multi: false, lang: group.lang });

  function enterCanonicalEditMode() {
    canonicalInput.value = canonicalText.textContent;
    canonicalText.classList.add('hidden');
    editCanonicalBtn.classList.add('hidden');
    canonicalInput.classList.remove('hidden');
    canonicalInput.focus();
    canonicalInput.select();
  }
  function exitCanonicalEditMode() {
    canonicalText.textContent = canonicalInput.value.trim() || group.canonical;
    canonicalInput.classList.add('hidden');
    canonicalText.classList.remove('hidden');
    editCanonicalBtn.classList.remove('hidden');
  }
  editCanonicalBtn.addEventListener('click', enterCanonicalEditMode);
  canonicalInput.addEventListener('blur', exitCanonicalEditMode);
  canonicalInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      canonicalInput.blur();
    }
  });
  canonicalWrap.append(canonicalText, editCanonicalBtn, canonicalInput, canonicalSuggestions);

  // "Zusammenführen" liest IMMER den aktuellen Feldinhalt statt group.
  // canonical - tippt man einen neuen, bisher unbeteiligten Begriff ein,
  // wandert der bisherige Zielbegriff automatisch mit in die zu
  // ersetzenden Varianten. "Alle Schlagworte löschen" bleibt bewusst an
  // group.canonical/group.variants (den ursprünglich erkannten Begriffen)
  // hängen - eine noch nicht bestätigte, frei eingetippte Zieleingabe soll
  // beim Löschen nicht versehentlich mitgelöscht werden.
  function effectiveCanonical() {
    return canonicalInput.value.trim() || group.canonical;
  }
  function effectiveVariants() {
    const canonical = effectiveCanonical();
    const variants = group.variants.filter((v) => v !== canonical);
    if (canonical !== group.canonical && !variants.includes(group.canonical)) {
      variants.push(group.canonical);
    }
    return variants;
  }

  // Nutzerwunsch (2026-09-23): das vorgeschlagene Zielschlagwort ist nur
  // eine KI-Einschätzung - ein Klick auf eines der "schlechten" Schlagworte
  // tauscht dessen Platz mit dem aktuellen Zielschlagwort. Ändert group.
  // canonical/group.variants direkt (nicht nur die Anzeige) - applyBtn/
  // deleteBtn unten lesen bei jedem Klick den aktuellen Stand von group,
  // der Tausch wirkt sich also unmittelbar auf Zusammenführen/Löschen aus.
  function renderGroupText() {
    canonicalText.textContent = group.canonical;
    canonicalInput.value = group.canonical;
    canonicalInput.classList.add('hidden');
    canonicalText.classList.remove('hidden');
    editCanonicalBtn.classList.remove('hidden');
    text.replaceChildren(langBadge, ' ', canonicalWrap, ' ← ');
    group.variants.forEach((variant, index) => {
      if (index > 0) text.append(', ');
      const variantWrap = document.createElement('span');
      variantWrap.className = 'term-merge-variant';

      const variantBtn = document.createElement('button');
      variantBtn.type = 'button';
      variantBtn.className = 'link-button';
      variantBtn.textContent = variant;
      variantBtn.title = t('import.termMergeMakeCanonicalTitle');
      variantBtn.addEventListener('click', () => {
        const oldCanonical = group.canonical;
        group.canonical = variant;
        group.variants = group.variants.map((v) => (v === variant ? oldCanonical : v));
        renderGroupText();
      });
      variantWrap.appendChild(variantBtn);

      // Nutzerwunsch (2026-09-23): eine Zusammenfassung passt oft
      // grundsätzlich, nur ein einzelnes Schlagwort in der Gruppe nicht -
      // eigenes "×" pro Variante entfernt NUR dieses eine, statt die ganze
      // Gruppe ignorieren zu müssen. Bewusst NICHT erst bei :hover
      // eingeblendet (auf Touch-Geräten gäbe es dafür kein Äquivalent) -
      // immer sichtbar, nur dezent gedimmt, per CSS kräftiger bei Hover/
      // Fokus (siehe .term-merge-remove-variant in style.css).
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'term-merge-remove-variant';
      removeBtn.textContent = '×';
      removeBtn.title = t('import.termMergeRemoveVariantTitle');
      removeBtn.setAttribute('aria-label', t('import.termMergeRemoveVariantTitle'));
      removeBtn.addEventListener('click', () => {
        group.variants = group.variants.filter((v) => v !== variant);
        // Keine Varianten mehr übrig -> nichts mehr zum Zusammenführen da,
        // die ganze Zeile verschwindet wie bei "Ignorieren".
        if (!group.variants.length) {
          li.remove();
          return;
        }
        renderGroupText();
      });
      variantWrap.appendChild(removeBtn);

      text.appendChild(variantWrap);
    });
  }
  renderGroupText();

  const status = document.createElement('p');
  status.className = 'jobs-list-error hidden';

  const actions = document.createElement('div');
  actions.className = 'web-allowlist-candidate-actions';

  function setRowButtonsDisabled(disabled) {
    applyBtn.disabled = disabled;
    ignoreBtn.disabled = disabled;
    deleteBtn.disabled = disabled;
  }

  const applyBtn = document.createElement('button');
  applyBtn.type = 'button';
  applyBtn.className = 'link-button';
  applyBtn.textContent = t('import.termMergeApplyButton');
  applyBtn.addEventListener('click', async () => {
    setRowButtonsDisabled(true);
    status.classList.add('hidden');
    try {
      const res = await fetch('/api/terms/merge', {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({ lang: group.lang, canonical: effectiveCanonical(), variants: effectiveVariants() }),
      });
      if (!res.ok) throw new Error();
      li.remove();
      resetKnownTerms(); // Tag-Vorschläge (attachTagSuggestions) sollen die geänderte Liste sehen.
    } catch {
      status.textContent = t('import.termMergeApplyFailed');
      status.classList.remove('hidden');
      setRowButtonsDisabled(false);
    }
  });

  const ignoreBtn = document.createElement('button');
  ignoreBtn.type = 'button';
  ignoreBtn.className = 'link-button';
  ignoreBtn.textContent = t('import.termMergeIgnoreButton');
  ignoreBtn.addEventListener('click', () => li.remove());

  // Nutzerwunsch (2026-09-22): eine als Rauschen erkannte Gruppe (z.B.
  // OCR-Artefakte) lässt sich statt eines Zusammenführens auch komplett
  // entfernen. Zweistufige Sicherheitsabfrage direkt am Link statt eines
  // nativen confirm()-Dialogs, analog zum Website-Löschen weiter unten in
  // dieser Datei - erster Klick wandelt nur den Text um, erst der zweite
  // Klick löst tatsächlich das Löschen aus. Änderung landet wie beim
  // Zusammenführen im Änderungs-Log und ist darüber pro Quelle rückgängig
  // machbar (siehe app/main.py: delete_terms).
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'link-button';
  deleteBtn.textContent = t('import.termMergeDeleteButton');
  let deleteConfirmPending = false;
  deleteBtn.addEventListener('click', async () => {
    if (!deleteConfirmPending) {
      deleteConfirmPending = true;
      deleteBtn.textContent = t('import.termMergeDeleteConfirmButton');
      return;
    }
    setRowButtonsDisabled(true);
    status.classList.add('hidden');
    try {
      const res = await fetch('/api/terms/delete', {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({ lang: group.lang, terms: [group.canonical, ...group.variants] }),
      });
      if (!res.ok) throw new Error();
      li.remove();
      resetKnownTerms();
    } catch {
      status.textContent = t('import.termMergeDeleteFailed');
      status.classList.remove('hidden');
      deleteConfirmPending = false;
      deleteBtn.textContent = t('import.termMergeDeleteButton');
      setRowButtonsDisabled(false);
    }
  });

  actions.append(applyBtn, ignoreBtn, deleteBtn);
  li.append(status, actions);
  return li;
}

// Nutzerwunsch (2026-09-22): bei ~1000+ Begriffen je Sprache dauerte ein
// kompletter Analyse-Durchlauf spürbar - erste Treffer sollen deutlich
// früher zur Bearbeitung erscheinen, statt bis zum Ende des gesamten
// Durchlaufs zu warten. /api/terms/merge-suggestions liefert die Treffer
// deshalb als NDJSON-Stream (Häppchen-weise, siehe app/main.py), gleiches
// Muster wie /api/ask (static/ndjson-stream.js) - jede Gruppe erscheint
// sofort, sobald sie ankommt. DE/EN laufen parallel, damit ein langsameres
// Sprach-Ergebnis das schnellere nicht ausbremst.
async function streamTermMergeSuggestions(lang, onGroup) {
  const res = await fetch('/api/terms/merge-suggestions', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ lang }),
  });
  if (!res.ok) throw new Error();
  await readNdjsonStream(res, { group: onGroup });
}

termMergeAnalyzeBtn.addEventListener('click', async () => {
  // Nutzerwunsch (2026-09-23): "Wird analysiert..." steht im ausgegrauten
  // Button selbst, wie bei den anderen Aktions-Buttons (z.B. submitBtn im
  // Bearbeiten-Formular), statt in einem separaten Statustext daneben.
  termMergeAnalyzeBtn.disabled = true;
  termMergeAnalyzeBtn.textContent = t('import.termMergeAnalyzing');
  termMergeStatus.textContent = '';
  termMergeEmpty.classList.add('hidden');
  termMergeList.innerHTML = '';
  let anyGroup = false;
  try {
    await Promise.all(
      ['de', 'en'].map((lang) =>
        streamTermMergeSuggestions(lang, (group) => {
          anyGroup = true;
          termMergeList.appendChild(renderTermMergeGroup(group));
        })
      )
    );
    if (!anyGroup) termMergeEmpty.classList.remove('hidden');
  } catch {
    termMergeStatus.textContent = t('import.termMergeAnalyzeFailed');
  } finally {
    termMergeAnalyzeBtn.disabled = false;
    termMergeAnalyzeBtn.textContent = t('import.termMergeAnalyzeButton');
  }
});

// Rumpf des #popover-load-Klick-Handlers (Extraktion + Formular-Befüllung),
// als eigene Funktion herausgezogen (Nutzerwunsch: Quellen-Vorschläge
// "Annehmen" soll denselben Weg wie ein manueller URL-Import nehmen) - reiner
// Extract-Cut, keine Verhaltensänderung für den bestehenden Klick-Handler.
async function extractAndFillFromUrl(url) {
  const status = document.getElementById('popover-status');
  const loadBtn = document.getElementById('popover-load');
  if (!url) {
    status.textContent = t('import.pleaseEnterUrl');
    return;
  }
  // Nutzerwunsch (2026-08-31): Tracking-Parameter direkt hier entfernen,
  // BEVOR extrahiert/verglichen/ins Formular übernommen wird - betrifft so
  // automatisch auch #url im Formular und den späteren Absende-Payload.
  url = stripTrackingParams(url);
  const existing = findExistingSourceByUrl(url);
  if (existing) {
    status.textContent = t('import.urlAlreadyExists', { title: existing.title });
    return;
  }
  loadBtn.disabled = true;
  loadBtn.textContent = t('import.loadingExtracting');
  status.textContent = '';
  try {
    const res = await fetch('/api/extract-url', {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.extractionFailedGeneric'));
    }
    const data = await res.json();
    pendingUploadId = null;
    pendingUploadType = null;
    if (!data.extracted) {
      if (data.is_audio) {
        status.textContent = t('import.audioTranscriptionPending');
        fillForm({ title: data.title, url });
        showForm();
        setTextFieldPending(true, 'audio-text-pending-hint');
        setListenUrlFieldVisible(true);
        return;
      }
      if (data.is_pdf) {
        // Gescannte PDF ohne Text-Ebene (siehe extraction.extract_pdf) -
        // Text-Feld analog zur Audio-Transkription entschärfen, Text wird
        // nach dem Anlegen per Hintergrund-Job (KI-OCR) ergänzt.
        status.textContent = '';
        fillForm({ title: data.title, url });
        showForm();
        setTextFieldPending(true, 'pdf-text-pending-hint');
        setListenUrlFieldVisible(true);
        return;
      }
      if (extractYoutubeVideoId(url)) {
        // Backlog #201: YouTube blockiert automatisierte Transkript-
        // Anfragen auf Produktion (siehe app/extraction.py) - Titel/Datum
        // kommen trotzdem an (davon unabhaengige Anfrage, siehe v0.46.3),
        // nur der Text muss hier manuell per externem Dienst nachgetragen
        // werden.
        status.textContent = '';
        fillForm({ title: data.title, authors: data.authors, date: data.date, url });
        showForm();
        setYoutubeTranscriptFallbackHintVisible(true);
        return;
      }
      status.textContent = t('import.extractionEmpty');
      fillForm({ url });
      showForm();
      return;
    }
    fillForm({ title: data.title, authors: data.authors, date: data.date, url, text: data.text });
    showForm();
    setListenUrlFieldVisible(data.is_audio || data.is_pdf);
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  } finally {
    loadBtn.disabled = false;
    loadBtn.textContent = t('import.loadButton');
  }
}

document.getElementById('popover-load').addEventListener('click', () => {
  extractAndFillFromUrl(document.getElementById('popover-url').value.trim());
});

const AUDIO_UPLOAD_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.mp4', '.mpeg', '.mpga', '.webm'];
const AUDIO_UPLOAD_MAX_BYTES = 25 * 1024 * 1024;

function isAudioUploadFile(file) {
  if (file.type && file.type.startsWith('audio/')) return true;
  const name = file.name.toLowerCase();
  return AUDIO_UPLOAD_EXTENSIONS.some((ext) => name.endsWith(ext));
}

document.getElementById('popover-upload').addEventListener('click', async () => {
  const fileInput = document.getElementById('popover-file');
  const status = document.getElementById('upload-status');
  const file = fileInput.files[0];
  if (!file) {
    status.textContent = t('import.pleaseChooseFile');
    return;
  }
  const isAudio = isAudioUploadFile(file);
  status.textContent = isAudio && file.size > AUDIO_UPLOAD_MAX_BYTES
    ? t('import.uploadingExtractingLargeAudio')
    : t('import.uploadingExtracting');
  try {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(isAudio ? '/api/extract-audio-upload' : '/api/extract-pdf-upload', {
      method: 'POST',
      headers: { 'X-Lang': getLang() },
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.uploadFailedGeneric'));
    }
    const data = await res.json();
    pendingUploadId = data.upload_id;
    pendingUploadType = isAudio ? 'audio' : 'pdf';
    if (!data.extracted) {
      if (isAudio) {
        status.textContent = t('import.audioTranscriptionPending');
        fillForm({ title: data.title });
        showForm();
        setTextFieldPending(true, 'audio-text-pending-hint');
        setListenUrlFieldVisible(true);
        return;
      }
      // Hochgeladene PDF ohne Text-Ebene (siehe extraction.extract_pdf) -
      // Text-Feld analog zur Audio-Transkription entschärfen, Text wird
      // nach dem Anlegen per Hintergrund-Job (KI-OCR) ergänzt.
      status.textContent = '';
      fillForm({ title: data.title });
      showForm();
      setTextFieldPending(true, 'pdf-text-pending-hint');
      setListenUrlFieldVisible(true);
      return;
    }
    fillForm({ title: data.title, authors: data.authors, date: data.date, text: data.text });
    showForm();
    // Nutzerwunsch (2026-08-03): Anhör-/Verweis-URL jetzt auch fuer PDFs -
    // dieser Handler kennt nur die beiden Upload-Typen Audio und PDF, isAudio
    // ist daher hier gleichbedeutend mit "nicht PDF".
    setListenUrlFieldVisible(true);
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
});

// Analog zu app/extraction.py:_extract_video_id() - dieselbe Quelle kann
// unter mehreren URL-Formen eingefügt werden (youtu.be/ID vs.
// youtube.com/watch?v=ID, zusätzliche Parameter wie "&t=42s"), die der
// generische String-Vergleich unten sonst als unterschiedlich ansieht.
function extractYoutubeVideoId(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const host = parsed.hostname.toLowerCase();
  if (host.includes('youtu.be')) {
    return parsed.pathname.replace(/^\/+/, '').split('/')[0] || null;
  }
  if (host.includes('youtube.com')) {
    if (parsed.pathname === '/watch') {
      return parsed.searchParams.get('v');
    }
    if (parsed.pathname.startsWith('/shorts/')) {
      return parsed.pathname.split('/shorts/')[1].split('/')[0] || null;
    }
  }
  return null;
}

// Spiegelt app/extraction.py#strip_tracking_params - Nutzerwunsch
// (2026-08-31): dieselbe per Social Media/Newsletter geteilte Seite wirkte
// je nach mitgeschickten Tracking-Anhängen (utm_*, fbclid, ...) wie eine
// ANDERE URL und die Duplikat-Prüfung schlug nicht an. Bewusst nur eine
// kuratierte Liste bekannter, rein Tracking-dienender Parameternamen statt
// pauschal aller Query-Parameter - ein funktional relevanter Parameter
// (z.B. eine Artikel-ID) darf nicht verloren gehen, sonst würde die URL
// kaputtgehen.
const TRACKING_PARAM_NAMES = new Set([
  'fbclid',
  'gclid',
  'gclsrc',
  'dclid',
  'wbraid',
  'gbraid',
  'msclkid',
  'mc_cid',
  'mc_eid',
  'igshid',
  '_hsenc',
  '_hsmi',
  'mkt_tok',
  'yclid',
  'ttclid',
  'twclid',
]);

function stripTrackingParams(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }
  const toDelete = [];
  parsed.searchParams.forEach((_, key) => {
    if (TRACKING_PARAM_NAMES.has(key.toLowerCase()) || key.toLowerCase().startsWith('utm_')) {
      toDelete.push(key);
    }
  });
  toDelete.forEach((key) => parsed.searchParams.delete(key));
  return parsed.toString();
}

function normalizeUrlForComparison(url) {
  const videoId = extractYoutubeVideoId(url);
  if (videoId) return `youtube:${videoId.toLowerCase()}`;
  return stripTrackingParams(url).trim().replace(/\/+$/, '').toLowerCase();
}

function findExistingSourceByUrl(url) {
  const normalized = normalizeUrlForComparison(url);
  if (!normalized) return null;
  return allSources.find((s) => s.url && normalizeUrlForComparison(s.url) === normalized) || null;
}

// Anbindung der Bearbeiten-Komponente (static/source-edit.js) an die Liste.
const EDIT_PANEL_CALLBACKS = {
  onSaved() {
    activeEditId = null;
    activeEditAuthorKey = null;
    loadSources();
    loadAuthors();
  },
  onCancel() {
    activeEditId = null;
    activeEditAuthorKey = null;
    renderSourceList(currentSourceList);
  },
  onDelete: (s) => scheduleDeletion(s),
  onUndoDelete: (id) => cancelDeletion(id),
  onLinkVerified: () => loadSources(),
};

function scheduleDeletion(s) {
  const timeoutId = setTimeout(async () => {
    pendingDeletions.delete(s.id);
    if (activeEditId === s.id) {
      // Löschen betrifft die ganze Quelle, unabhängig davon, unter welcher
      // Autor:in-Zeile gerade bearbeitet wurde - deshalb hier bewusst ohne
      // isActiveEditRow()/__sortAuthor-Abgleich.
      activeEditId = null;
      activeEditAuthorKey = null;
    }
    try {
      await fetch(`/api/sources/${s.id}`, { method: 'DELETE', headers: jsonHeaders() });
    } catch (err) {
      // Fehler beim endgültigen Löschen: Quelle taucht beim nächsten Laden wieder auf.
    }
    loadSources();
    loadAuthors();
  }, UNDO_DURATION_MS);
  pendingDeletions.set(s.id, { timeoutId });
  renderSourceList(currentSourceList);
}

function cancelDeletion(id) {
  const entry = pendingDeletions.get(id);
  if (entry) {
    clearTimeout(entry.timeoutId);
    pendingDeletions.delete(id);
  }
  renderSourceList(currentSourceList);
}

function buildUndoRow(s) {
  const li = document.createElement('li');
  li.className = 'source-row source-row--deleting';

  const topRow = document.createElement('div');
  topRow.className = 'source-row-top';

  const textSpan = document.createElement('span');
  textSpan.textContent = t('common.deletingStatus', { title: s.title });
  topRow.appendChild(textSpan);

  const undoBtn = document.createElement('button');
  undoBtn.type = 'button';
  undoBtn.className = 'link-button';
  undoBtn.textContent = t('common.undo');
  undoBtn.addEventListener('click', () => cancelDeletion(s.id));
  topRow.appendChild(undoBtn);

  li.appendChild(topRow);

  const bar = document.createElement('div');
  bar.className = 'undo-bar';
  const fill = document.createElement('div');
  fill.className = 'undo-bar-fill';
  bar.appendChild(fill);
  li.appendChild(bar);

  requestAnimationFrame(() => {
    fill.style.transitionDuration = `${UNDO_DURATION_MS}ms`;
    fill.style.width = '0%';
  });

  return li;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightTermsInElement(container, keyTerms) {
  if (!keyTerms || keyTerms.length === 0) return;
  // Von der KI vorgeschlagene Schlagworte dürfen Eigennamen enthalten, die
  // zufällig mit einer erfassten Autor:in übereinstimmen - dieser Abgleich
  // war zu fehleranfällig (z.B. bei Namensgleichheit/-teilen), deshalb werden
  // solche Treffer grundsätzlich nicht mehr hervorgehoben, auch nicht als
  // generisches Schlagwort.
  const filteredTerms = keyTerms.filter(
    (term) => !allAuthors.some((a) => a.name.toLowerCase() === term.toLowerCase())
  );
  if (filteredTerms.length === 0) return;
  const pattern = new RegExp(`(${filteredTerms.map(escapeRegExp).join('|')})`, 'gi');
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  let node = walker.nextNode();
  while (node) {
    pattern.lastIndex = 0;
    if (pattern.test(node.textContent)) textNodes.push(node);
    node = walker.nextNode();
  }
  textNodes.forEach((textNode) => {
    pattern.lastIndex = 0;
    const parts = textNode.textContent.split(pattern);
    if (parts.length <= 1) return;
    const frag = document.createDocumentFragment();
    parts.forEach((part) => {
      const isTerm = filteredTerms.some((term) => term.toLowerCase() === part.toLowerCase());
      if (isTerm) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'term-highlight-button';
        const title = t('import.filterByTermTitle', { term: part });
        btn.title = title;
        btn.setAttribute('aria-label', title);
        const strong = document.createElement('strong');
        strong.textContent = part;
        btn.appendChild(strong);
        btn.addEventListener('click', () => filterByTerm(part));
        frag.appendChild(btn);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    });
    textNode.parentNode.replaceChild(frag, textNode);
  });
}

function renderSummaryWithTerms(summaryText, keyTerms) {
  const wrapper = document.createElement('div');
  wrapper.className = 'source-summary-text';
  wrapper.innerHTML = renderMarkdown(summaryText);
  highlightTermsInElement(wrapper, keyTerms);
  return wrapper;
}

function isFilterActive() {
  return !document.getElementById('source-filter-status').classList.contains('hidden');
}

// Heuristik: Nachname = letztes Wort des Namens (keine getrennten Vor-/
// Nachname-Felder im Datenmodell). Für die alphabetische Autor:innen-
// Sortierung soll "Günther Adam" unter "A" einsortiert werden, nicht unter
// "G" - deckt sich mit gängiger bibliografischer Praxis.
function getSurname(name) {
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1];
}

// In der Autor:innen-Sortierung steht bei einer Quelle mit mehreren
// Autor:innen immer die Person voran, deren Nachname gerade die aktuelle
// Sektion bestimmt (__sortAuthor) - z.B. taucht "Günther Adam, Christa
// Bernd" unter "A" auf, aber "Christa Bernd, Günther Adam" unter "B".
function authorsForDisplay(s) {
  if (!s.__sortAuthor || !s.authors || s.authors.length <= 1) return s.authors || [];
  const rest = s.authors.filter((name) => name !== s.__sortAuthor);
  return [s.__sortAuthor, ...rest];
}

// Backlog #65: Alphabet-Sprungleiste - nur in der Autor:innen-Sortierung
// sinnvoll (in der Datums-Ansicht/gefiltert gibt es keine alphabetische
// Ordnung nach Nachnamen) und nur für Buchstaben klickbar, zu denen es
// tatsächlich mindestens eine Quelle gibt.
const JUMP_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

function updateAlphabetJumpBar(sorted) {
  const bar = document.getElementById('alphabet-jump-bar');
  if (!bar) return;
  if (searchBarOpen || currentSortMode !== 'author' || isFilterActive()) {
    bar.classList.add('hidden');
    bar.replaceChildren();
    return;
  }

  const availableLetters = new Set();
  sorted.forEach((s) => {
    const surname = getSurname(s.__sortAuthor || '');
    if (surname) availableLetters.add(surname[0].toUpperCase());
  });

  bar.classList.toggle('hidden', availableLetters.size === 0);
  bar.replaceChildren();
  JUMP_ALPHABET.forEach((letter) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'alphabet-jump-btn';
    btn.textContent = letter;
    if (availableLetters.has(letter)) {
      const label = t('import.jumpToLetterTitle', { letter });
      btn.title = label;
      btn.setAttribute('aria-label', label);
      btn.addEventListener('click', () => jumpToLetter(letter));
    } else {
      btn.disabled = true;
    }
    bar.appendChild(btn);
  });
}

// Springt zur ersten Quelle, deren Autor:in-Nachname mit "letter" beginnt.
// Liegt dieser Eintrag jenseits der aktuell per Infinite Scroll (Backlog
// #57) geladenen Seite, wird die sichtbare Menge erst erweitert (analog
// ensureSourceVisible bei Deep-Links) - sonst würde der Sprung ins Leere
// laufen, weil die Zeile noch gar nicht im DOM existiert.
function jumpToLetter(letter) {
  const sorted = sortSources(currentSourceList);
  const index = sorted.findIndex((s) => getSurname(s.__sortAuthor || '').toUpperCase().startsWith(letter));
  if (index < 0) return;

  if (index >= visibleSourceCount) {
    visibleSourceCount = index + 1;
    renderSourceList(currentSourceList);
  }

  requestAnimationFrame(() => {
    document
      .querySelector(`#source-list [data-row-index="${index}"]`)
      ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
}

function sortSources(sources) {
  // In einer bereits gefilterten Ansicht (z.B. "nach Autor:in gefiltert")
  // ist die Liste schon auf die relevanten Quellen eingeschränkt - hier NICHT
  // zusätzlich pro Autor:in expandieren, sonst erscheint eine Quelle mit
  // mehreren Autor:innen mehrfach identisch untereinander.
  if (currentSortMode === 'date' || isFilterActive()) {
    const copy = [...sources];
    copy.sort((a, b) => {
      if (!a.date && !b.date) return a.title.localeCompare(b.title);
      if (!a.date) return 1;
      if (!b.date) return -1;
      return b.date.localeCompare(a.date);
    });
    return copy;
  }

  // Autor-Modus: jede:r Autor:in bekommt eine eigene Zwischenüberschrift
  // (Nutzerwunsch 2026-08-31, auch bei nur einer Quelle) - eine Quelle mit
  // mehreren Autor:innen bekommt deshalb einen Eintrag PRO Autor:in, damit
  // sie unter jeder Sektion auffindbar ist. Quellen ganz ohne Autor bleiben
  // ein Eintrag.
  const expanded = [];
  sources.forEach((s) => {
    const sourceAuthors = s.authors || [];
    if (!sourceAuthors.length) {
      expanded.push({ ...s, __sortAuthor: null });
      return;
    }
    sourceAuthors.forEach((authorName) => {
      expanded.push({ ...s, __sortAuthor: authorName });
    });
  });

  expanded.sort((a, b) => {
    const authorA = getSurname(a.__sortAuthor || '￿').toLowerCase();
    const authorB = getSurname(b.__sortAuthor || '￿').toLowerCase();
    if (authorA !== authorB) return authorA.localeCompare(authorB);
    if (!a.date && !b.date) return a.title.localeCompare(b.title);
    if (!a.date) return 1;
    if (!b.date) return -1;
    if (a.date !== b.date) return b.date.localeCompare(a.date);
    return a.title.localeCompare(b.title);
  });
  return expanded;
}

const MONTH_NAMES = {
  de: [
    'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
    'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
  ],
  en: [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ],
};

function formatYear(dateStr) {
  if (!dateStr) return t('common.noDate');
  return dateStr.split('-')[0];
}

function monthYearKey(dateStr) {
  if (!dateStr) return '';
  const [year, month] = dateStr.split('-');
  return `${year}-${month}`;
}

function formatMonthYear(dateStr) {
  if (!dateStr) return t('common.noDate');
  const [year, month] = dateStr.split('-');
  const monthNames = MONTH_NAMES[getLang()] || MONTH_NAMES.en;
  const monthIndex = parseInt(month, 10) - 1;
  const monthName = monthNames[monthIndex] || month;
  return `${monthName} ${year}`;
}

function appendOpenLink(container, citationUrl) {
  const link = document.createElement('a');
  link.href = citationUrl;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.className = 'source-open-link';
  const openLabel = t('common.openSource');
  link.title = openLabel;
  link.setAttribute('aria-label', openLabel);
  link.innerHTML = EXTERNAL_LINK_ICON;
  const target = container.querySelector('p:last-of-type') || container;
  target.appendChild(document.createTextNode(' '));
  target.appendChild(link);
}

function prependAiIcon(container, tooltipKey = 'import.aiSummaryTooltip') {
  const icon = document.createElement('span');
  icon.className = 'source-summary-icon';
  icon.innerHTML = MAGIC_ICON;
  const tooltip = t(tooltipKey);
  icon.title = tooltip;
  icon.setAttribute('aria-label', tooltip);
  const target = container.querySelector('p:first-of-type') || container;
  target.insertBefore(icon, target.firstChild);
  icon.after(document.createTextNode(' '));
}

function buildSourceDetails(s, citationUrl) {
  const container = document.createElement('div');
  container.className = 'source-summary';

  const summaryEl = renderSummaryWithTerms(s.summary, s.key_terms);
  if (s.summary_ai_generated) prependAiIcon(summaryEl);
  container.appendChild(summaryEl);
  if (citationUrl) appendOpenLink(summaryEl, citationUrl);

  return container;
}

function buildTimelineMarker(label) {
  const li = document.createElement('li');
  li.className = 'timeline-marker';
  li.textContent = label;
  return li;
}

function buildAuthorMarker(name) {
  const li = document.createElement('li');
  li.className = 'author-marker';
  li.textContent = name;
  return li;
}

// ToDo: Anzahl der importierten Quellen in der Überschrift - bewusst NICHT
// aus dem sources-Parameter von renderSourceList() abgeleitet, da der dort
// gelegentlich eine gefilterte Teilmenge ist (Autor:innen-/Begriffs-Filter,
// Alphabet-Sprungziele) - stattdessen immer aus der vollständigen
// allSources-Liste, abzüglich Quellen, die gerade im Lösch-Countdown stehen
// (siehe pendingDeletions/scheduleDeletion) und damit für die Nutzer:in
// bereits als gelöscht gelten.
function updateImportedSourcesCount() {
  const countEl = document.getElementById('imported-sources-count');
  if (!countEl) return;
  const count = allSources.filter((s) => !pendingDeletions.has(s.id)).length;
  countEl.textContent = `(${count})`;
}

// Eine Quelle als Listeneintrag(e): normale Zeile (Titel aufklappbar mit
// Kurzbeschreibung, Autor:innen, Aktionen), ggf. gefolgt vom Bearbeiten-
// Formular, bzw. die Rückgängig-Zeile nach dem Löschen. Genutzt von der
// Quellenliste UND der Schlagwort-Ansicht (Nutzerwunsch 2026-09-24: Quellen
// dort "vor Ort" aufklappen/bearbeiten). Alle Interaktionen zeichnen über
// renderSourceList neu - das aktualisiert in der Schlagwort-Ansicht auch
// diese mit (siehe Ende von renderSourceList).
function buildSourceEntries(s, rowIndex, options = {}) {
  if (pendingDeletions.has(s.id)) {
    return [isActiveEditRow(s) ? buildEditPanel(s, { ...EDIT_PANEL_CALLBACKS, pendingDeletion: true, rowIndex }) : buildUndoRow(s)];
  }

  const li = document.createElement('li');
  li.className = 'source-row';
  if (s.url_reachable === false) {
    li.classList.add('source-row--unreachable');
  }
  li.dataset.sourceId = s.id;
  // Backlog #65: eindeutiges Sprungziel für die Alphabet-Leiste - anders
  // als data-source-id (mehrdeutig, wenn eine Quelle im Autor:innen-Modus
  // mehrfach expandiert erscheint) trifft der Index in der sortierten
  // Liste immer genau DIESE eine Zeile.
  if (typeof rowIndex === 'number') li.dataset.rowIndex = String(rowIndex);

  const header = document.createElement('div');
  header.className = 'source-row-header';

  // Nutzerwunsch (2026-09-23): eine Quelle mit erkanntem defektem Link
  // (url_reachable === false, siehe source-row--unreachable oben) soll
  // nirgendwo mehr verlinkt werden - auch nicht hier in der eigenen
  // Quellenverwaltung.
  const citationUrl = s.url_reachable === false ? null : s.listen_url || s.url;
  const hasDetails = !!s.summary;
  const isProcessing = !!s.processing_status;
  // Nutzerwunsch (2026-08-03): "error" zaehlt NICHT als aktiv - da laeuft
  // nichts mehr, das ein manueller Edit ueberschreiben koennte (siehe
  // Kommentar am editBtn unten). Nur pending/running sperren Bearbeiten.
  const isActivelyProcessing = s.processing_status === 'pending' || s.processing_status === 'running';

  const textSpan = document.createElement('span');
  if (hasDetails) {
    const titleBtn = document.createElement('button');
    titleBtn.type = 'button';
    titleBtn.className = 'link-button source-title-toggle';
    titleBtn.textContent = s.title;
    titleBtn.addEventListener('click', () => {
      if (expandedSourceIds.has(s.id)) {
        expandedSourceIds.delete(s.id);
      } else {
        expandedSourceIds.add(s.id);
      }
      renderSourceList(currentSourceList, options);
    });
    textSpan.appendChild(titleBtn);
    textSpan.append(' – ');
  } else {
    textSpan.append(`${s.title} – `);
  }
  if (s.authors && s.authors.length) {
    authorsForDisplay(s).forEach((name, index) => {
      if (index > 0) textSpan.append(', ');
      const authorBtn = document.createElement('button');
      authorBtn.type = 'button';
      authorBtn.className = 'link-button';
      authorBtn.textContent = name;
      authorBtn.addEventListener('click', () => filterByAuthor(name));
      textSpan.appendChild(authorBtn);
    });
  } else {
    textSpan.append(t('common.unknownAuthor'));
  }
  textSpan.append(` (${formatYear(s.date)})`);
  if (s.restricted) {
    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('common.restrictedBadge');
    textSpan.appendChild(document.createTextNode(' '));
    textSpan.appendChild(badge);
  }
  if (isProcessing) {
    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('import.processingBadge');
    textSpan.appendChild(document.createTextNode(' '));
    textSpan.appendChild(badge);
  }
  if (options.mentionOnlyIds?.has(s.id)) {
    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('import.mentionOnlyBadge');
    badge.title = t('import.mentionOnlyBadgeTitle', { name: options.mentionOnlyName || '' });
    textSpan.appendChild(document.createTextNode(' '));
    textSpan.appendChild(badge);
  }
  header.appendChild(textSpan);

  const actions = document.createElement('span');
  actions.className = 'source-row-actions';

  if (s.url_reachable === false) {
    const warning = document.createElement(hasPflegerRole() ? 'button' : 'span');
    if (hasPflegerRole()) warning.type = 'button';
    warning.className = 'icon-button warning-icon';
    // Backlog #163: für Pfleger:innen/Admins den konkreten Fehlergrund
    // direkt im Tooltip ergänzen (url_reason_code/url_status_code sind
    // für alle anderen bereits serverseitig auf null gesetzt, siehe
    // app/main.py: _to_source_out).
    const warnLabel = hasPflegerRole()
      ? `${t('common.urlUnreachable')} – ${urlErrorText(s)}`
      : t('common.urlUnreachable');
    warning.title = warnLabel;
    warning.setAttribute('aria-label', warnLabel);
    warning.innerHTML = WARNING_ICON;
    if (hasPflegerRole()) {
      warning.addEventListener('click', () => {
        if (isActiveEditRow(s)) {
          activeEditId = null;
          activeEditAuthorKey = null;
        } else {
          activeEditId = s.id;
          activeEditAuthorKey = editRowKey(s);
        }
        renderSourceList(currentSourceList, options);
      });
    }
    actions.appendChild(warning);
  }

  if (citationUrl) {
    const linkBtn = document.createElement('a');
    linkBtn.href = citationUrl;
    linkBtn.target = '_blank';
    linkBtn.rel = 'noopener noreferrer';
    linkBtn.className = 'icon-button';
    const openLabel = t('common.openSource');
    linkBtn.title = openLabel;
    linkBtn.setAttribute('aria-label', openLabel);
    linkBtn.innerHTML = EXTERNAL_LINK_ICON;
    actions.appendChild(linkBtn);
  }

  if (hasPflegerRole()) {
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'icon-button';
    // Solange die Quelle noch AKTIV verarbeitet wird (pending/running),
    // würde ein manueller Edit vom später eintreffenden Transkript
    // überschrieben - deshalb für GENAU diese eine Quelle deaktiviert,
    // alle anderen bleiben normal bearbeitbar (das ist ja gerade der Zweck
    // der Hintergrund-Verarbeitung). Bei "error" laeuft dagegen nichts
    // mehr - Bearbeiten ist dort die Reparatur (siehe update_source, das
    // den Fehlerzustand bei erfolgreichem Speichern zuruecksetzt).
    editBtn.disabled = isActivelyProcessing;
    const editLabel = isActivelyProcessing ? t('import.editDisabledWhileProcessing') : t('common.editSource');
    editBtn.title = editLabel;
    editBtn.setAttribute('aria-label', editLabel);
    editBtn.innerHTML = EDIT_ICON;
    editBtn.addEventListener('click', async () => {
      // Fix (2026-08-31): das Bearbeiten-Formular zeigt den Volltext (s.text)
      // - der wird seit der zweiphasigen Ladereihenfolge (siehe loadSources/
      // loadFullSourceText) erst NACH der sichtbaren Liste im Hintergrund
      // nachgeladen. Ohne dieses Warten hätte ein sehr schnelles Klicken
      // kurz nach dem Seitenaufruf ein leeres Textfeld gezeigt - und ein
      // Speichern hätte den echten Volltext der Quelle gelöscht.
      if (fullTextReady) await fullTextReady;
      if (isActiveEditRow(s)) {
        activeEditId = null;
        activeEditAuthorKey = null;
      } else {
        activeEditId = s.id;
        activeEditAuthorKey = editRowKey(s);
      }
      renderSourceList(currentSourceList, options);
    });
    actions.appendChild(editBtn);
  }

  header.appendChild(actions);
  li.appendChild(header);

  if (hasDetails && expandedSourceIds.has(s.id)) {
    li.appendChild(buildSourceDetails(s, citationUrl));
  }

  if (isActiveEditRow(s)) return [li, buildEditPanel(s, { ...EDIT_PANEL_CALLBACKS, rowIndex })];
  return [li];
}

function renderSourceList(sources, options = {}) {
  currentSourceList = sources;
  const sorted = sortSources(sources);
  currentDisplayedSources = sorted;
  updateAlphabetJumpBar(sorted);
  updateImportedSourcesCount();
  const list = document.getElementById('source-list');
  // Schlagwort-Ansicht ersetzt die Quellenliste nur ungefiltert - ein
  // Filter (z.B. "nach diesem Schlagwort filtern") oder die Suche zeigt
  // wieder die passenden Quellen.
  const showTerms = currentSortMode === 'term' && !isFilterActive() && !searchBarOpen;
  list.classList.toggle('hidden', showTerms);
  document.getElementById('term-overview').classList.toggle('hidden', !showTerms);
  list.innerHTML = '';
  // Versteckte Quellenliste gar nicht erst aufbauen - ein offenes Bearbeiten-
  // Formular stünde sonst doppelt im DOM (gleiche IDs, Labels träfen das
  // versteckte Feld). Alle Neuzeichnen-Wege laufen über diese Funktion, so
  // bleibt die Schlagwort-Ansicht (mit ihren Quellen-Zeilen) aktuell.
  if (showTerms) {
    sourceListObserver?.disconnect();
    renderTermOverview();
    return;
  }
  let lastMonthYear = null;
  let lastAuthorKey = null;
  let gridRow = 0;
  // In der Timeline-Ansicht braucht jede <li> eine EXPLIZITE Grid-Zeile:
  // ohne das packt CSS-Grid-Auto-Placement eine Quellen-Zeile fälschlich
  // in dieselbe Zeile wie das direkt vorangehende Monat-Jahr-Label
  // (Spalte 3 ist dort ja noch frei) - dadurch verschwanden Punkt und
  // Zeitlinie für genau diese Zeilen.
  const appendTimelineRow = (el) => {
    if (currentSortMode === 'date') {
      gridRow += 1;
      el.style.gridRow = String(gridRow);
    }
    list.appendChild(el);
  };

  const visible = sorted.slice(0, visibleSourceCount);
  visible.forEach((s, rowIndex) => {
    if (currentSortMode === 'date' && !pendingDeletions.has(s.id)) {
      const key = monthYearKey(s.date);
      if (key !== lastMonthYear) {
        appendTimelineRow(buildTimelineMarker(formatMonthYear(s.date)));
        lastMonthYear = key;
      }
    }

    if (currentSortMode === 'author' && !pendingDeletions.has(s.id)) {
      const key = s.__sortAuthor ? normalizeAuthor(s.__sortAuthor) : null;
      const isNewAuthor = key && key !== lastAuthorKey;
      if (isNewAuthor) {
        list.appendChild(buildAuthorMarker(s.__sortAuthor));
      }
      lastAuthorKey = key;
    }

    buildSourceEntries(s, rowIndex, options).forEach(appendTimelineRow);
  });

  if (currentSortMode === 'date') {
    // "-1" als Grid-Zeilen-Ende bezieht sich nur auf EXPLIZIT deklarierte
    // Zeilen (grid-template-rows), nicht auf implizit erzeugte - deshalb hier
    // das tatsächliche Zeilenende als Variable setzen, damit die Zeitlinie
    // (::after) wirklich bis zur letzten Zeile durchläuft.
    list.style.setProperty('--timeline-row-end', String(gridRow + 1));
  }

  // Backlog #57: solange noch mehr Einträge als aktuell gerendert vorhanden
  // sind, ein unsichtbares Sentinel-Element ans Listenende hängen - kommt es
  // beim Scrollen in den sichtbaren Bereich, wird die nächste Seite
  // nachgeladen (d.h. neu gerendert, die Daten liegen ja bereits vor).
  sourceListObserver?.disconnect();
  if (sorted.length > visible.length) {
    const sentinel = document.createElement('li');
    sentinel.className = 'source-list-sentinel';
    list.appendChild(sentinel);
    sourceListObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          sourceListObserver.disconnect();
          visibleSourceCount += SOURCES_PAGE_SIZE;
          renderSourceList(currentSourceList, options);
        }
      },
      { rootMargin: '400px' }
    );
    sourceListObserver.observe(sentinel);
  }

  // Fix: die native Browser-Suche (Cmd/Strg+F) fand bisher nur Titel
  // innerhalb der bereits gerenderten ersten Seite(n) - alles, was die
  // Pagination (Backlog #57) noch nicht nachgeladen hatte, existierte
  // schlicht nicht im DOM und lieferte 0 Treffer. Für jede noch nicht
  // gerenderte Quelle hängen wir deshalb einen minimalen, mit
  // hidden="until-found" versteckten Platzhalter an: Chrome/Edge können
  // solche Elemente trotzdem durchsuchen und blenden sie bei einem Treffer
  // automatisch ein (beforematch-Event), bevor sie zur Fundstelle scrollen.
  // Der Platzhalter wird danach (leicht verzögert, um das synchrone
  // Scrollen der Suche nicht zu stören) durch die vollwertige, interaktive
  // Zeile ersetzt.
  sorted.slice(visible.length).forEach((s) => {
    const placeholder = document.createElement('li');
    placeholder.setAttribute('hidden', 'until-found');
    placeholder.textContent = `${s.title} ${authorsForDisplay(s).join(' ')}`;
    placeholder.addEventListener(
      'beforematch',
      () => {
        placeholder.removeAttribute('hidden');
        setTimeout(() => {
          const index = sortSources(currentSourceList).findIndex((entry) => entry.id === s.id);
          if (index >= 0) {
            visibleSourceCount = Math.max(visibleSourceCount, index + 1);
          }
          renderSourceList(currentSourceList, options);
        }, 0);
      },
      { once: true }
    );
    list.appendChild(placeholder);
  });
}

// Der Klick auf einen Autor/Begriff kann von weit unten in der Liste
// kommen (z.B. aus dem Autoren-Verzeichnis oder einer Quellenzeile) - die
// gefilterte Ergebnisliste erscheint aber oben bei "Importierte Quellen",
// deshalb dorthin scrollen statt die aktuelle Scroll-Position zu behalten.
function scrollToFilteredResults() {
  document.getElementById('quellen-liste-bereich')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Merkt sich den aktiven Filter, damit loadSources() (z.B. nach dem
// Aktualisieren/Löschen einer Quelle) ihn erneut anwenden kann, statt
// stillschweigend auf die ungefilterte Liste zurückzufallen.
let activeFilter = null;

async function applyAuthorFilter(name) {
  // Nutzerwunsch (2026-08-24): Der Klick auf einen im Explore-Netzwerk mit
  // einem Schlagwort zusammengeführten Autor:innen-Knoten (siehe app/
  // main.py:_build_knowledge_graph) soll BEIDE Quellenmengen liefern -
  // eigene Texte UND fremde Texte, die die Person nur als Schlagwort
  // erwähnen (z.B. "Jos de Blok" im Text von Elisabeth Sechser). Ohne
  // diesen Abgleich gegen /api/terms würde applyAuthorFilter nur eigene
  // Texte finden, obwohl der Graph-Knoten längst beides zusammenführt.
  const [authorsRes, termsRes] = await Promise.all([
    fetch('/api/authors', { headers: { 'X-Lang': getLang() } }),
    fetch('/api/terms'),
  ]);
  const authorEntries = await authorsRes.json();
  const termEntries = await termsRes.json();
  const match = authorEntries.find((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
  const displayName = match ? match.name : name;
  const ownIds = match ? match.source_ids : [];
  const termMatch = termEntries.find((te) => normalizeAuthor(te.term) === normalizeAuthor(name));
  const mentionIds = termMatch ? termMatch.source_ids : [];
  const ids = Array.from(new Set([...ownIds, ...mentionIds]));
  const mentionOnlyIds = new Set(mentionIds.filter((id) => !ownIds.includes(id)));

  document.getElementById('source-filter-label').textContent = t(
    mentionOnlyIds.size > 0
      ? 'import.filteredByAuthorAndMentions'
      : ids.length === 1
        ? 'import.filteredByAuthor'
        : 'import.filteredByAuthorPlural'
  );
  document.getElementById('source-filter-name').textContent = displayName;
  // Muss VOR renderSourceList() gesetzt werden - sortSources() liest den
  // Filter-Status, um die Autoren-Expansion in der gefilterten Ansicht zu
  // unterdrücken (siehe isFilterActive()).
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => ids.includes(s.id)), { mentionOnlyIds, mentionOnlyName: displayName });

  filteredAuthorEntry = match || null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

async function filterByAuthor(name) {
  activeFilter = { type: 'author', value: name };
  resetSourcePagination();
  await applyAuthorFilter(name);
  scrollToFilteredResults();
}

async function applyTermFilter(term) {
  const res = await fetch('/api/terms');
  const termEntries = await res.json();
  const match = termEntries.find((t2) => normalizeTerm(t2.term) === normalizeTerm(term));
  const ids = match ? match.source_ids : [];
  ids.forEach((id) => expandedSourceIds.add(id));

  document.getElementById('source-filter-label').textContent = t('import.filteredByTerm');
  document.getElementById('source-filter-name').textContent = match ? match.term : term;
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => ids.includes(s.id)));

  filteredAuthorEntry = null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

async function filterByTerm(term) {
  activeFilter = { type: 'term', value: term };
  resetSourcePagination();
  await applyTermFilter(term);
  scrollToFilteredResults();
}

// Backlog #94: Volltextsuche - anders als bei Autor/Begriff kein Backend-
// Aufruf nötig, allSources ist bereits vollständig (inkl. Volltext) im
// Speicher geladen, daher direkte, sofortige Filterung pro Tastenanschlag.
function normalizeSearch(value) {
  return (value || '').toLowerCase();
}

function sourceMatchesSearch(source, query) {
  const q = normalizeSearch(query);
  if (!q) return true;
  const haystacks = [
    source.title,
    source.text,
    source.summary,
    (source.authors || []).join(' '),
    (source.key_terms || []).join(' '),
  ];
  return haystacks.some((h) => normalizeSearch(h).includes(q));
}

function applySearchFilter(query) {
  document.getElementById('source-filter-label').textContent = t('import.filteredBySearch');
  document.getElementById('source-filter-name').textContent = query;
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => sourceMatchesSearch(s, query)));

  filteredAuthorEntry = null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

function searchSources(query) {
  activeFilter = { type: 'search', value: query };
  resetSourcePagination();
  applySearchFilter(query);
}

// Backlog (2026-08-02): Filter auf Quellen mit defektem Link, erreichbar
// über den neuen Button in der Toolbar (Badge zeigt die Anzahl) - kein
// eigener Backend-Aufruf nötig, url_reachable steckt bereits in allSources
// (siehe GET /api/sources).
function applyBrokenLinksFilter() {
  document.getElementById('source-filter-label').textContent = t('import.filteredByBrokenLinks');
  document.getElementById('source-filter-name').textContent = '';
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => s.url_reachable === false));

  filteredAuthorEntry = null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
}

function filterByBrokenLinks() {
  activeFilter = { type: 'broken-links', value: null };
  resetSourcePagination();
  applyBrokenLinksFilter();
  scrollToFilteredResults();
}

// Zählt bei jedem Laden/Neuladen neu, wie viele Quellen aktuell einen
// defekten Link haben, und spiegelt das im Zähler-Badge am Toolbar-Button.
// Der Button selbst wird bei 0 defekten Links komplett ausgeblendet (nicht
// nur das Badge) - ohne betroffene Quellen gibt es nichts zu filtern.
function updateBrokenLinksButton() {
  const badge = document.getElementById('broken-links-count-badge');
  if (!badge) return;
  const count = allSources.filter((s) => s.url_reachable === false).length;
  badge.textContent = String(count);
  badge.classList.toggle('hidden', count === 0);
  brokenLinksBtn.classList.toggle('hidden', !hasPflegerRole() || count === 0);
}

// Backlog: LLM/Internet-Fallback bei dünner Quellenlage - Pflege der
// freigegebenen externen Domains/Pfade (siehe app/web_allowlist.py).
let webAllowlistEntries = [];
// Nutzerwunsch: unmittelbar nach dem Anlegen soll sichtbar sein, dass die
// Website wirklich angelegt wurde UND die Verarbeitung begonnen hat - dafür
// wandert sie in eine eigene Pending-Liste direkt unterm Formular (statt nur
// den ohnehin schon vorhandenen "Wird indiziert..."-Badge in der normalen
// Liste zu zeigen, siehe weiter unten). Bewusst NICHT einfach "jeder Eintrag
// mit indexing_status === running", sonst würde auch eine bereits etablierte
// Website (z. B. 25 indizierte Seiten) beim ganz normalen wöchentlichen
// Sweep kurzzeitig aus der Liste verschwinden und wieder auftauchen - hier
// nur IDs, die in DIESER Sitzung tatsächlich frisch über das Formular
// angelegt wurden, verlassen die Menge automatisch wieder, sobald ihre
// Erstverarbeitung fertig ist (siehe renderWebAllowlistList).
let recentlyAddedWebAllowlistIds = new Set();
// Analog zu previousJobIds bei fetchImportJobs: die volle Liste wird beim
// Polling nur dann komplett neu aufgebaut (und riskiert damit ein offenes
// Akkordeon zu schließen), wenn sich die Menge der GERADE laufenden
// Einträge tatsächlich verändert hat - nicht bei jedem 3-Sekunden-Takt.
let previousRunningWebAllowlistIds = new Set();

function formatWebAllowlistDate(isoString) {
  if (!isoString) return t('import.webAllowlistNeverReviewed');
  return isoString.split('T')[0];
}

// Nutzerwunsch: einzelne indizierte Seiten einer Website sollen sich gezielt
// vom Fallback ausschließen (und wieder aufnehmen) lassen, ohne die ganze
// Freigabe zu löschen - Ausklapp-Liste je Eintrag, nach demselben <details>/
// <summary>-Muster wie die Quellenliste im Chat (siehe question.js:
// buildSourcesList). Seiten werden erst beim ersten Öffnen nachgeladen.
function formatWebIndexPageDate(page) {
  return page.date || t('import.webAllowlistPageNoDate');
}

function renderWebAllowlistPagesList(listEl, entryId, pages) {
  listEl.innerHTML = '';
  pages.forEach((page) => {
    const li = document.createElement('li');
    li.className = 'web-allowlist-page';
    li.classList.toggle('web-allowlist-page--excluded', page.excluded);

    const info = document.createElement('p');
    info.className = 'web-allowlist-page-info';
    const titleLink = document.createElement('a');
    titleLink.href = page.url;
    titleLink.target = '_blank';
    titleLink.rel = 'noopener noreferrer';
    titleLink.textContent = page.title;
    info.appendChild(titleLink);
    info.append(` · ${formatWebIndexPageDate(page)}`);
    li.appendChild(info);

    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'link-button';
    toggleBtn.textContent = t(
      page.excluded ? 'import.webAllowlistPageIncludeButton' : 'import.webAllowlistPageExcludeButton'
    );
    toggleBtn.addEventListener('click', async () => {
      toggleBtn.disabled = true;
      try {
        const action = page.excluded ? 'include' : 'exclude';
        const res = await fetch(`/api/web-allowlist/${entryId}/pages/${page.id}/${action}`, {
          method: 'POST',
          headers: jsonHeaders(),
        });
        if (res.ok) {
          page.excluded = !page.excluded;
          li.classList.toggle('web-allowlist-page--excluded', page.excluded);
          toggleBtn.textContent = t(
            page.excluded ? 'import.webAllowlistPageIncludeButton' : 'import.webAllowlistPageExcludeButton'
          );
        }
      } finally {
        toggleBtn.disabled = false;
      }
    });
    li.appendChild(toggleBtn);

    listEl.appendChild(li);
  });
}

function buildWebAllowlistPagesAccordion(entry) {
  const details = document.createElement('details');
  details.className = 'web-allowlist-pages';
  const summary = document.createElement('summary');
  summary.textContent = t('import.webAllowlistPagesToggle', { count: entry.page_count });
  details.appendChild(summary);
  const list = document.createElement('ul');
  list.className = 'web-allowlist-pages-list';
  details.appendChild(list);

  let loaded = false;
  details.addEventListener('toggle', async () => {
    if (!details.open || loaded) return;
    loaded = true;
    try {
      const res = await fetch(`/api/web-allowlist/${entry.id}/pages`, { headers: { 'X-Lang': getLang() } });
      if (!res.ok) return;
      renderWebAllowlistPagesList(list, entry.id, await res.json());
    } catch (err) {
      loaded = false;
    }
  });

  return details;
}

// Nutzerwunsch (Positivselektion): statt bereits indizierter Seiten (siehe
// buildWebAllowlistPagesAccordion) zeigt dieser Bereich gegen den
// bestehenden Quellenbestand bewertete VORSCHLÄGE, aus denen eine Pfleger:in
// gezielt einzelne für die Aufnahme auswählt - nur sichtbar, wenn
// entry.selection_mode === "positiv" (siehe renderWebAllowlistList). Lädt
// die komplette, bereits absteigend sortierte Liste einmalig und paginiert
// clientseitig in 10er-Schritten, statt bei jedem "mehr…"-Klick neu zu
// fragen.
const WEB_ALLOWLIST_CANDIDATES_PAGE_SIZE = 10;

function renderWebAllowlistCandidateRow(entryId, candidate, onDecided) {
  const li = document.createElement('li');
  li.className = 'web-allowlist-candidate';

  const info = document.createElement('p');
  info.className = 'web-allowlist-candidate-info';
  const titleLink = document.createElement('a');
  titleLink.href = candidate.url;
  titleLink.target = '_blank';
  titleLink.rel = 'noopener noreferrer';
  titleLink.textContent = candidate.title;
  info.appendChild(titleLink);
  li.appendChild(info);

  const snippet = document.createElement('p');
  snippet.className = 'web-allowlist-candidate-snippet';
  snippet.textContent = candidate.snippet;
  li.appendChild(snippet);

  const actions = document.createElement('div');
  actions.className = 'web-allowlist-candidate-actions';

  const approveBtn = document.createElement('button');
  approveBtn.type = 'button';
  approveBtn.className = 'link-button';
  approveBtn.textContent = t('import.webAllowlistCandidateApproveButton');

  const rejectBtn = document.createElement('button');
  rejectBtn.type = 'button';
  rejectBtn.className = 'link-button';
  rejectBtn.textContent = t('import.webAllowlistCandidateRejectButton');

  async function decide(action, btn) {
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    try {
      const res = await fetch(`/api/web-allowlist/${entryId}/candidates/${candidate.id}/${action}`, {
        method: 'POST',
        headers: jsonHeaders(),
      });
      if (res.ok) {
        onDecided();
        return;
      }
    } catch (err) {
      // fällt unten durch, Buttons werden wieder freigegeben
    }
    approveBtn.disabled = false;
    rejectBtn.disabled = false;
  }

  approveBtn.addEventListener('click', () => decide('approve', approveBtn));
  rejectBtn.addEventListener('click', () => decide('reject', rejectBtn));

  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);
  li.appendChild(actions);

  return li;
}

function buildWebAllowlistCandidatesSection(entry) {
  const container = document.createElement('div');
  container.className = 'web-allowlist-candidates';

  const hint = document.createElement('p');
  hint.className = 'web-allowlist-candidates-hint';
  hint.innerHTML = POSITIVE_SELECTION_ICON;
  const hintText = document.createElement('span');
  hintText.textContent = t('import.webAllowlistPositiveSelectionHint');
  hint.appendChild(hintText);
  container.appendChild(hint);

  const list = document.createElement('ul');
  list.className = 'web-allowlist-candidates-list';
  container.appendChild(list);

  const moreBtn = document.createElement('button');
  moreBtn.type = 'button';
  moreBtn.className = 'link-button web-allowlist-candidates-more-btn hidden';
  moreBtn.textContent = t('import.webAllowlistCandidatesShowMore');
  container.appendChild(moreBtn);

  let allCandidates = [];
  let shownCount = 0;

  function renderVisible() {
    list.innerHTML = '';
    if (allCandidates.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'web-allowlist-candidates-empty';
      empty.textContent = t('import.webAllowlistCandidatesEmpty');
      list.appendChild(empty);
      moreBtn.classList.add('hidden');
      return;
    }
    allCandidates.slice(0, shownCount).forEach((candidate) => {
      list.appendChild(
        renderWebAllowlistCandidateRow(entry.id, candidate, () => {
          // Entfernte Kandidaten rutschen die Liste einfach nach oben nach -
          // shownCount bleibt gleich, außer die Gesamtliste ist jetzt kürzer.
          allCandidates = allCandidates.filter((c) => c.id !== candidate.id);
          shownCount = Math.min(shownCount, allCandidates.length);
          renderVisible();
        })
      );
    });
    moreBtn.classList.toggle('hidden', shownCount >= allCandidates.length);
  }

  moreBtn.addEventListener('click', () => {
    shownCount = Math.min(allCandidates.length, shownCount + WEB_ALLOWLIST_CANDIDATES_PAGE_SIZE);
    renderVisible();
  });

  (async () => {
    try {
      const res = await fetch(`/api/web-allowlist/${entry.id}/candidates`, {
        headers: { 'X-Lang': getLang() },
      });
      if (!res.ok) return;
      allCandidates = await res.json();
      shownCount = Math.min(allCandidates.length, WEB_ALLOWLIST_CANDIDATES_PAGE_SIZE);
      renderVisible();
    } catch (err) {
      // Stiller Fehlschlag, wie beim übrigen Web-Allowlist-Bereich.
    }
  })();

  return container;
}

// Nutzerwunsch: kleine, bewusst schlichte Zeile pro Eintrag - keine Aktionen
// (Löschen/Als-geprüft-markieren/Akkordeon), die für einen Eintrag ohne
// jeden Inhalt noch keinen Sinn ergeben. Sobald die Erstverarbeitung fertig
// ist, verschwindet der Eintrag von hier und erscheint stattdessen ganz
// normal in der etablierten Liste (siehe renderWebAllowlistList).
function renderWebAllowlistPendingList(pendingEntries) {
  webAllowlistPendingList.innerHTML = '';
  webAllowlistPendingList.classList.toggle('hidden', pendingEntries.length === 0);
  pendingEntries.forEach((entry) => {
    const li = document.createElement('li');
    li.className = 'web-allowlist-pending-item';
    li.dataset.entryId = entry.id;

    const heading = document.createElement('p');
    heading.className = 'web-allowlist-pending-item-heading';
    const labelSpan = document.createElement('strong');
    labelSpan.textContent = entry.label;
    heading.appendChild(labelSpan);
    heading.append(` – ${entry.url_prefix}`);
    li.appendChild(heading);

    const badge = document.createElement('span');
    badge.className = 'restricted-badge';
    badge.textContent = t('import.webAllowlistIndexingBadge');
    li.appendChild(badge);

    webAllowlistPendingList.appendChild(li);
  });
}

function renderWebAllowlistList() {
  // Nutzerwunsch: nur in DIESER Sitzung frisch angelegte, noch laufende
  // Einträge zählen als "pending" - die Menge bereinigt sich hier von
  // selbst, sobald ein Eintrag fertig verarbeitet ist (indexing_status
  // nicht mehr "running"), damit ein späterer wöchentlicher Sweep desselben
  // Eintrags ihn nicht erneut in die Pending-Liste zurückholt.
  const pendingEntries = webAllowlistEntries.filter(
    (e) => recentlyAddedWebAllowlistIds.has(e.id) && e.indexing_status === 'running'
  );
  recentlyAddedWebAllowlistIds = new Set(pendingEntries.map((e) => e.id));
  renderWebAllowlistPendingList(pendingEntries);
  const pendingIds = new Set(pendingEntries.map((e) => e.id));

  webAllowlistList.innerHTML = '';
  webAllowlistEntries
    .filter((entry) => !pendingIds.has(entry.id))
    .forEach((entry) => {
    const li = document.createElement('li');
    li.className = 'web-allowlist-item';
    // Nutzerwunsch: der Indizierungs-Badge (siehe unten) muss auch beim
    // leichtgewichtigen Polling aktualisiert werden können, ohne die ganze
    // Liste neu aufzubauen (sonst würde ein offenes Seiten-Akkordeon bei
    // jedem Takt zuklappen, siehe pollWebAllowlistStatus-Kommentar) - dafür
    // braucht updateWebAllowlistIndexingBadges() ein stabiles Zuordnungsmerkmal.
    li.dataset.entryId = entry.id;

    // Nutzerwunsch: der Löschen-Link steht rechts oben neben dem Titel,
    // dezent/klein statt wie die übrigen Aktionen unterhalb - lädt so nicht
    // zum versehentlichen Klicken ein.
    const headingRow = document.createElement('div');
    headingRow.className = 'web-allowlist-item-heading-row';

    const heading = document.createElement('p');
    heading.className = 'web-allowlist-item-heading';
    const labelSpan = document.createElement('strong');
    labelSpan.textContent = entry.label;
    heading.appendChild(labelSpan);
    heading.append(` – ${entry.url_prefix}`);
    // Nutzerwunsch: wie bei PDF-/Audio-Quellen (import.processingBadge) soll
    // auch bei einer Website sichtbar sein, dass GENAU DIESER Eintrag gerade
    // indiziert wird - bisher gab es nur den globalen Fortschrittsring am
    // Icon (renderWebAllowlistIcon), der nicht verrät, welcher von mehreren
    // Einträgen betroffen ist.
    const indexingBadge = document.createElement('span');
    indexingBadge.className = 'restricted-badge web-allowlist-indexing-badge';
    indexingBadge.textContent = t('import.webAllowlistIndexingBadge');
    indexingBadge.classList.toggle('hidden', entry.indexing_status !== 'running');
    heading.appendChild(document.createTextNode(' '));
    heading.appendChild(indexingBadge);
    headingRow.appendChild(heading);

    // Nutzerwunsch: zweistufige Sicherheitsabfrage direkt am Link statt
    // eines nativen confirm()-Dialogs - erster Klick wandelt nur den Text
    // um, erst der zweite Klick (auf denselben, jetzt bestätigenden Link)
    // löst tatsächlich DELETE aus.
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'web-allowlist-delete-link';
    deleteBtn.textContent = t('import.webAllowlistDeleteButton');
    let deleteConfirmPending = false;
    deleteBtn.addEventListener('click', async () => {
      if (!deleteConfirmPending) {
        deleteConfirmPending = true;
        deleteBtn.textContent = t('import.webAllowlistDeleteConfirmButton');
        return;
      }
      deleteBtn.disabled = true;
      try {
        await fetch(`/api/web-allowlist/${entry.id}`, { method: 'DELETE', headers: jsonHeaders() });
        await loadWebAllowlist();
      } finally {
        deleteBtn.disabled = false;
      }
    });
    headingRow.appendChild(deleteBtn);
    li.appendChild(headingRow);

    const meta = document.createElement('p');
    meta.className = 'web-allowlist-item-meta';
    const pageCountKey =
      entry.page_count === 1 ? 'import.webAllowlistPageCountOne' : 'import.webAllowlistPageCountMany';
    meta.textContent =
      `${t(pageCountKey, { count: entry.page_count })} · ` +
      `${t('import.webAllowlistReviewedAt', { date: formatWebAllowlistDate(entry.reviewed_at) })}`;
    if (entry.needs_review) {
      const badge = document.createElement('span');
      badge.className = 'web-allowlist-review-badge';
      badge.textContent = t('import.webAllowlistNeedsReview');
      meta.appendChild(document.createTextNode(' '));
      meta.appendChild(badge);
    }
    li.appendChild(meta);

    const reason = document.createElement('p');
    reason.className = 'web-allowlist-item-reason';
    reason.textContent = entry.reason;
    li.appendChild(reason);

    const actions = document.createElement('div');
    actions.className = 'web-allowlist-item-actions';

    // Nutzerfeedback: "Als geprüft markieren" setzt nur den reviewed_at-
    // Zeitstempel zurück (siehe mark-reviewed-Endpoint) - ohne fällige
    // Prüfung (needs_review) gibt es nichts zu bestätigen, der Link würde
    // nur verwirren.
    if (entry.needs_review) {
      const reviewBtn = document.createElement('button');
      reviewBtn.type = 'button';
      reviewBtn.className = 'link-button';
      reviewBtn.textContent = t('import.webAllowlistMarkReviewedButton');
      reviewBtn.addEventListener('click', async () => {
        reviewBtn.disabled = true;
        try {
          await fetch(`/api/web-allowlist/${entry.id}/mark-reviewed`, {
            method: 'POST',
            headers: jsonHeaders(),
          });
          await loadWebAllowlist();
        } finally {
          reviewBtn.disabled = false;
        }
      });
      actions.appendChild(reviewBtn);
    }

    li.appendChild(actions);
    li.appendChild(buildWebAllowlistPagesAccordion(entry));
    if (entry.selection_mode === 'positiv') {
      li.appendChild(buildWebAllowlistCandidatesSection(entry));
    }
    webAllowlistList.appendChild(li);
  });
}

// Warn-Icon am Toolbar-Button (Mouse-Over-Tooltip via title-Attribut) -
// nur für Quellen-Pfleger:innen/Admins überhaupt sichtbar (Button selbst
// wird bereits über updateSourceManagementVisibility()/#quelltyp-bereich
// für alle anderen ausgeblendet).
function updateWebAllowlistButton() {
  const needsReviewCount = webAllowlistEntries.filter((e) => e.needs_review).length;
  webAllowlistWarning.classList.toggle('hidden', needsReviewCount === 0);
  webAllowlistWarning.title =
    needsReviewCount > 0
      ? t('import.webAllowlistNeedsReviewTooltip', { count: needsReviewCount })
      : '';
}

// Nutzerwunsch: Indizierungsstatus als fortlaufender Kreis am Globus-Icon,
// analog zum Fortschrittsring bei #typ-jobs (siehe renderJobsIcon). Anders
// als bei Audio/PDF gibt es keine festen Verarbeitungsstufen - als grobe
// Annäherung dient das Verhältnis bereits indizierter Seiten zur
// eingestellten Obergrenze (max_pages). Läuft praktisch immer für höchstens
// einen Eintrag gleichzeitig (Sofort-Crawl und wöchentlicher Sweep
// verarbeiten Einträge nacheinander, siehe app/main.py).
const WEB_ALLOWLIST_RING_CIRCUMFERENCE = 87.9;

function renderWebAllowlistIcon(entries) {
  const ring = document.getElementById('web-allowlist-icon-ring');
  const progressCircle = document.getElementById('web-allowlist-icon-progress');
  const runningEntry = entries.find((e) => e.indexing_status === 'running');
  ring.classList.toggle('hidden', !runningEntry);
  if (runningEntry) {
    const fraction = Math.min((runningEntry.page_count || 0) / Math.max(runningEntry.max_pages, 1), 0.95);
    progressCircle.setAttribute(
      'stroke-dashoffset',
      String(WEB_ALLOWLIST_RING_CIRCUMFERENCE * (1 - fraction))
    );
  }
}

// Nutzerwunsch: proaktive Quellen-Vorschläge aus dem offenen Web (app/
// source_discovery.py) - "Annehmen" legt bewusst KEINE Quelle direkt an,
// sondern öffnet das bestehende URL-Popover vorausgefüllt (siehe
// extractAndFillFromUrl oben) - Extraktion/Review/Speichern laufen 1:1 wie
// beim manuellen Import.
//
// Nutzerwunsch (2026-08-23): die Liste soll IMMER SOURCE_SUGGESTIONS_
// VISIBLE_COUNT Vorschläge zeigen, sofern der Backend-Vorrat das hergibt -
// beim Annehmen/Ablehnen rückt sofort (ohne neue Websuche abzuwarten, siehe
// SOURCE_SUGGESTION_QUEUE_TARGET in app/main.py) der nächste Vorschlag aus
// dem beim Laden bereits mitgelieferten Rest nach. Zwei getrennte Arrays
// statt einer einzigen Liste: sourceSuggestionsVisible sind die aktuell
// gerenderten Zeilen, sourceSuggestionsReserve der noch nicht gezeigte
// Rest, aus dem genau EIN Element pro Entscheidung nachrückt.
const SOURCE_SUGGESTIONS_VISIBLE_COUNT = 5;
let sourceSuggestionsVisible = [];
let sourceSuggestionsReserve = [];

// Nutzerfeedback (2026-08-23): kein Warn-Badge am Lampen-Icon - da praktisch
// immer mindestens ein Vorschlag vorliegt, wäre es dauerhaft aktiv und damit
// bedeutungslos. Stattdessen verschwindet das Icon selbst vollständig,
// sobald es wirklich mal keine offenen Vorschläge gibt (weder sichtbar noch
// im Vorrat) - inkl. Schließen der Vorschlagsliste, falls die gerade offen
// war (sonst gäbe es keinen Weg mehr, sie zuzuklappen, da genau dieses Icon
// dafür fehlt).
function updateSourceSuggestionsButtonVisibility() {
  const hasAny = sourceSuggestionsVisible.length > 0 || sourceSuggestionsReserve.length > 0;
  sourceSuggestionsBtn.classList.toggle('hidden', !hasAny);
  if (!hasAny) sourceSuggestionsBereich.classList.add('hidden');
}

function openUrlPopoverWithUrl(url) {
  sourceSuggestionsBereich.classList.add('hidden');
  importBereich.classList.add('hidden');
  filePopover.classList.add('hidden');
  setPopoverAccordionMode(urlPopover, urlPopoverHome, urlPopoverCloseBtn, isMobileLayout());
  urlPopover.classList.remove('hidden');
  document.getElementById('popover-status').textContent = '';
  document.getElementById('popover-url').value = stripTrackingParams(url);
  extractAndFillFromUrl(url);
  // Nutzerwunsch (2026-09-01, real gemeldet): beim Annehmen eines
  // Quellenvorschlags (einziger Aufrufer dieser Funktion) kann die
  // Nutzer:in tief in der Vorschlagsliste gescrollt sein - im
  // Akkordeon-Modus (Mobile, siehe setPopoverAccordionMode) landet das
  // Formular dabei normal im Dokumentfluss (#mobile-import-slot) statt als
  // schwebendes Overlay über der Kopfzeile, blieb also ohne aktives
  // Scrollen außerhalb des sichtbaren Bereichs. Analog zum bereits
  // bestehenden Rück-Scroll nach erfolgreichem Import (siehe
  // quelltypBereich.scrollIntoView weiter unten im Submit-Handler).
  urlPopover.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSourceSuggestionRow(suggestion) {
  const li = document.createElement('li');
  li.className = 'web-allowlist-candidate';

  const info = document.createElement('p');
  info.className = 'web-allowlist-candidate-info';
  const link = document.createElement('a');
  link.href = suggestion.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  // Nutzerfeedback: Standard-Blau des Browsers passt nicht ins Design -
  // dieselbe Klasse wie bei Quellentitel-Links in der Konversationsansicht
  // (static/style.css), statt dem Browser-Default zu überlassen.
  link.className = 'citation-title-link';
  link.textContent = suggestion.title;
  info.appendChild(link);
  li.appendChild(info);

  const reason = document.createElement('p');
  reason.className = 'web-allowlist-candidate-snippet';
  reason.textContent = suggestion.reason;
  li.appendChild(reason);

  const actions = document.createElement('div');
  actions.className = 'web-allowlist-candidate-actions';
  const acceptBtn = document.createElement('button');
  acceptBtn.type = 'button';
  acceptBtn.className = 'link-button';
  acceptBtn.textContent = t('import.sourceSuggestionAcceptButton');
  const rejectBtn = document.createElement('button');
  rejectBtn.type = 'button';
  rejectBtn.className = 'link-button';
  rejectBtn.textContent = t('import.sourceSuggestionRejectButton');

  async function decide(action) {
    acceptBtn.disabled = true;
    rejectBtn.disabled = true;
    try {
      const res = await fetch(`/api/source-suggestions/${suggestion.id}/${action}`, {
        method: 'POST',
        headers: jsonHeaders(),
      });
      if (!res.ok) throw new Error('failed');
      // Nutzerwunsch: "Abgelehnte Quellen verschwinden mit einer einfachen
      // Transition" - gilt hier bewusst für beide Aktionen (Annehmen UND
      // Ablehnen), damit eine Zeile nie abrupt verschwindet. Erst nach
      // Ablauf der CSS-Transition (removeSourceSuggestionRow) tatsächlich
      // aus dem DOM entfernen und ggf. nachrücken lassen.
      removeSourceSuggestionRow(li, suggestion.id);
      if (action === 'accept') {
        openUrlPopoverWithUrl(suggestion.url);
      }
    } catch (err) {
      acceptBtn.disabled = false;
      rejectBtn.disabled = false;
    }
  }

  acceptBtn.addEventListener('click', () => decide('accept'));
  rejectBtn.addEventListener('click', () => decide('reject'));
  actions.appendChild(acceptBtn);
  actions.appendChild(rejectBtn);
  li.appendChild(actions);
  return li;
}

// Dauer MUSS zur CSS-Transition auf .web-allowlist-candidate--leaving
// passen (siehe style.css) - setTimeout statt transitionend, da dort
// mehrere Eigenschaften gleichzeitig übergehen (transitionend würde sonst
// mehrfach feuern) und "eine einfache Transition" (Nutzerwunsch) keinen
// Sonderfall-Code dafür braucht.
const SOURCE_SUGGESTION_LEAVE_MS = 200;

// Nutzerwunsch (2026-08-23): entfernt eine entschiedene Zeile mit
// Fade-Out und lässt danach - sofern vorhanden - sofort den nächsten
// Vorschlag aus dem bereits geladenen Vorrat mit Fade-In nachrücken, damit
// die Liste wenn möglich immer SOURCE_SUGGESTIONS_VISIBLE_COUNT Zeilen
// zeigt, ohne auf eine neue (mehrere Sekunden dauernde) Websuche zu warten.
function removeSourceSuggestionRow(li, id) {
  li.classList.add('web-allowlist-candidate--leaving');
  sourceSuggestionsVisible = sourceSuggestionsVisible.filter((s) => s.id !== id);
  setTimeout(() => {
    li.remove();
    if (sourceSuggestionsReserve.length > 0) {
      const next = sourceSuggestionsReserve.shift();
      sourceSuggestionsVisible.push(next);
      const nextLi = renderSourceSuggestionRow(next);
      nextLi.classList.add('web-allowlist-candidate--entering');
      sourceSuggestionsList.appendChild(nextLi);
    }
    sourceSuggestionsEmpty.classList.toggle('hidden', sourceSuggestionsVisible.length > 0);
    updateSourceSuggestionsButtonVisibility();
  }, SOURCE_SUGGESTION_LEAVE_MS);
}

function renderSourceSuggestionsList() {
  sourceSuggestionsList.replaceChildren();
  sourceSuggestionsEmpty.classList.toggle('hidden', sourceSuggestionsVisible.length > 0);
  sourceSuggestionsVisible.forEach((s) => sourceSuggestionsList.appendChild(renderSourceSuggestionRow(s)));
}

async function loadSourceSuggestions() {
  if (!hasPflegerRole()) return;
  const res = await fetch('/api/source-suggestions', { headers: { 'X-Lang': getLang() } });
  if (!res.ok) return;
  const all = await res.json();
  sourceSuggestionsVisible = all.slice(0, SOURCE_SUGGESTIONS_VISIBLE_COUNT);
  sourceSuggestionsReserve = all.slice(SOURCE_SUGGESTIONS_VISIBLE_COUNT);
  renderSourceSuggestionsList();
  updateSourceSuggestionsButtonVisibility();
}

async function loadWebAllowlist() {
  if (!hasPflegerRole()) return;
  const res = await fetch('/api/web-allowlist', { headers: { 'X-Lang': getLang() } });
  if (!res.ok) return;
  webAllowlistEntries = await res.json();
  renderWebAllowlistList();
  updateWebAllowlistButton();
  renderWebAllowlistIcon(webAllowlistEntries);
  previousRunningWebAllowlistIds = new Set(
    webAllowlistEntries.filter((e) => e.indexing_status === 'running').map((e) => e.id)
  );
}

// Bugfix (Nutzerfeedback): der 3-Sekunden-Poll-Takt (siehe
// pollBackgroundImportStatus) darf NICHT bei jedem Takt renderWebAllowlistList()
// aufrufen - das baut #web-allowlist-list komplett neu auf und riss dadurch
// ein gerade geöffnetes Seiten-Akkordeon (<details>) sofort wieder zu.
// Aktualisiert deshalb im Normalfall nur den Warn-Badge und den
// Fortschrittsring. Nur wenn sich die MENGE der gerade laufenden Einträge
// tatsächlich verändert (ein Crawl startet/endet), wird einmalig komplett
// neu aufgebaut - analog zum jobsChanged-Muster bei fetchImportJobs, damit
// z.B. ein frisch fertig gewordener Pending-Eintrag zeitnah (statt erst
// beim nächsten manuellen Neuladen) in die etablierte Liste wandert.
async function pollWebAllowlistStatus() {
  if (!hasPflegerRole()) return;
  try {
    const res = await fetch('/api/web-allowlist', { headers: { 'X-Lang': getLang() } });
    if (!res.ok) return;
    webAllowlistEntries = await res.json();
    const currentRunningIds = new Set(
      webAllowlistEntries.filter((e) => e.indexing_status === 'running').map((e) => e.id)
    );
    const runningChanged =
      currentRunningIds.size !== previousRunningWebAllowlistIds.size ||
      [...currentRunningIds].some((id) => !previousRunningWebAllowlistIds.has(id));
    previousRunningWebAllowlistIds = currentRunningIds;
    if (runningChanged) {
      renderWebAllowlistList();
    }
    updateWebAllowlistButton();
    renderWebAllowlistIcon(webAllowlistEntries);
  } catch (err) {
    // Stille Hintergrund-Aktualisierung, wie bei fetchImportJobs.
  }
}

webAllowlistForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const status = document.getElementById('web-allowlist-status');
  const urlPrefixInput = document.getElementById('web-allowlist-url-prefix');
  const labelInput = document.getElementById('web-allowlist-label');
  const reasonInput = document.getElementById('web-allowlist-reason');
  const maxPagesInput = document.getElementById('web-allowlist-max-pages');
  status.textContent = '';
  try {
    const res = await fetch('/api/web-allowlist', {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({
        url_prefix: urlPrefixInput.value.trim(),
        label: labelInput.value.trim(),
        reason: reasonInput.value.trim(),
        max_pages: parseInt(maxPagesInput.value, 10) || 50,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.webAllowlistAddFailed'));
    }
    // Nutzerwunsch: sofortiges Feedback, dass das Anlegen geklappt hat UND
    // die Verarbeitung begonnen hat - die neue ID merken wir uns hier, damit
    // renderWebAllowlistList() sie (solange indexing_status "running" ist)
    // in die eigene Pending-Liste einsortiert statt in die etablierte Liste.
    const created = await res.json();
    recentlyAddedWebAllowlistIds.add(created.id);
    webAllowlistForm.reset();
    maxPagesInput.value = '50';
    status.textContent = t('import.webAllowlistAddedStatus');
    await loadWebAllowlist();
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  }
});

// scroll=false beim Leeren des Suchfelds während des Tippens - die Ansicht
// soll dabei nicht plötzlich unter der noch fokussierten, oben in der
// Kopfzeile sitzenden Suchbox wegspringen (anders als beim expliziten
// Klick auf "Alle anzeigen", wo ein Sprung an den Listenanfang erwartet wird).
function clearSourceFilter({ scroll = true } = {}) {
  activeFilter = null;
  resetSourcePagination();
  document.getElementById('source-filter-status').classList.add('hidden');
  document.getElementById('search-input').value = '';
  renderSourceList(allSources);
  filteredAuthorEntry = null;
  authorPanelEditMode = false;
  renderAuthorInfoPanel();
  if (scroll) scrollToFilteredResults();
}

// Zeigt eine einzelne Quelle in der ungefilterten Autor:innen-Ansicht:
// scrollt hin und hebt sie kurz hervor. Genutzt vom ?source=-Deep-Link und
// von den Quellen-Links der Schlagwort-Ansicht (Nutzerwunsch 2026-09-23:
// dort soll ein Klick nicht in der Schlagwort-/Filter-Ansicht hängen
// bleiben).
function focusSource(sourceId) {
  closeSearchBar();
  if (isFilterActive()) clearSourceFilter({ scroll: false });
  setSortMode('author');
  ensureSourceVisible(sourceId);
  renderSourceList(currentSourceList);
  requestAnimationFrame(() => {
    const row = document.querySelector(`#source-list [data-source-id="${sourceId}"]`);
    row?.scrollIntoView({ block: 'center' });
    row?.classList.add('source-highlight-flash');
    row?.addEventListener('animationend', () => row.classList.remove('source-highlight-flash'), { once: true });
  });
}

document.getElementById('search-input').addEventListener('input', (e) => {
  const query = e.target.value.trim();
  if (!query) {
    clearSourceFilter({ scroll: false });
    return;
  }
  searchSources(query);
});

document.getElementById('source-filter-clear').addEventListener('click', () => clearSourceFilter());

brokenLinksBtn.addEventListener('click', () => filterByBrokenLinks());

document.getElementById('sort-author').addEventListener('click', () => setSortMode('author'));
document.getElementById('sort-date').addEventListener('click', () => setSortMode('date'));
document.getElementById('sort-term').addEventListener('click', () => setSortMode('term'));

document.getElementById('reindex-sources-btn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const status = document.getElementById('reindex-status');
  btn.disabled = true;
  status.textContent = t('import.reindexing');
  status.classList.remove('hidden');
  try {
    const res = await fetch('/api/admin/reindex-sources', { method: 'POST', headers: { 'X-Lang': getLang() } });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.reindexFailed'));
    }
    const data = await res.json();
    status.textContent = data.detail;
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  } finally {
    btn.disabled = false;
  }
});

function setSortMode(mode) {
  currentSortMode = mode;
  document.getElementById('sort-author').classList.toggle('active', mode === 'author');
  document.getElementById('sort-date').classList.toggle('active', mode === 'date');
  document.getElementById('sort-term').classList.toggle('active', mode === 'term');
  document.getElementById('source-list').classList.toggle('timeline-mode', mode === 'date');
  renderSourceList(currentSourceList);
}

// Nutzerwunsch (2026-08-23, erweitert 2026-09-23): Reicht die Breite in der
// Werkzeugleiste (Quelltyp-Icons + Sortierung + Suche) nicht mehr für alle
// Icons in einer Zeile, wird nacheinander (günstigster Verlust zuerst) Platz
// eingespart, statt Icons zu verkleinern oder unschön umbrechen zu lassen:
// zuerst nur die rein dekorative Trennlinie vor den web-bezogenen Werkzeugen
// (.quelltyp-web-tools), dann der Datums-Sortier-Button (#sort-date), dann
// das Icon "Ähnliche Schlagworte" (#typ-term-merge), zuletzt - falls IMMER
// NOCH nicht genug Platz - die restliche Sortierung (Autor:in/Schlagwort)
// samt Trennlinie (.sort-toolbar). Die Suche samt Link-Filter (.search-toolbar)
// bleibt bewusst IMMER sichtbar (Nutzerwunsch 2026-09-23, revidiert die
// vorherige Fassung, die stattdessen die Suche ausgeblendet hätte). Ein
// fester Media-Query-Breakpoint würde hier mal zu früh, mal zu spät greifen,
// da die Zahl der sichtbaren Quelltyp-Icons laufend je nach Rolle und
// Zustand wechselt (aktive Jobs, defekte Links) - stattdessen wird die
// tatsächlich benötigte Breite aller sichtbaren Geschwister gemessen und mit
// der verfügbaren Breite verglichen. ResizeObserver auf dem Container selbst
// reicht als einziger Trigger: sowohl eine Fensterbreiten-Änderung als auch
// ein ein-/ausblendendes Geschwister-Icon verändert bei flex-wrap:wrap auch
// die (ggf. umbrochene) eigene Höhe des Containers.
function initSourceToolbarOverflow() {
  const row = document.querySelector('.section-heading-row');
  const actions = document.querySelector('.section-heading-actions');
  const sortToolbar = document.querySelector('.sort-toolbar');
  const webTools = document.querySelector('.quelltyp-web-tools');
  const termMergeBtn = document.getElementById('typ-term-merge');
  const sortDateBtn = document.getElementById('sort-date');
  if (!row || !actions || !sortToolbar) return;

  function neededWidth() {
    const gap = parseFloat(getComputedStyle(actions).columnGap) || 0;
    const visibleChildren = [...actions.children].filter((el) => getComputedStyle(el).display !== 'none');
    return (
      visibleChildren.reduce((sum, el) => sum + el.getBoundingClientRect().width, 0) +
      gap * Math.max(0, visibleChildren.length - 1)
    );
  }

  function fitsNow() {
    return neededWidth() <= actions.clientWidth + 1;
  }

  // Reihenfolge ist bewusst gestaffelt (statt alles auf einmal zu prüfen):
  // jeder Schritt misst NACH dem vorherigen neu, damit ein knapper
  // Platzgewinn (z.B. nur die Trennlinie einsparen) nicht unnötig auch
  // noch Funktionalität kostet, wenn er allein schon reicht.
  function update() {
    sortToolbar.classList.remove('sort-toolbar--hidden-for-space');
    sortDateBtn.classList.remove('hidden');
    if (webTools) webTools.classList.remove('quelltyp-web-tools--no-divider');
    if (termMergeBtn) termMergeBtn.classList.remove('hidden');

    if (fitsNow()) return;
    if (webTools) webTools.classList.add('quelltyp-web-tools--no-divider');

    // Nutzerwunsch (2026-09-23): Sortierung nach Autor:in und Schlagwort
    // soll mobil sichtbar bleiben - vor der ganzen Sortier-Leiste fallen
    // erst der Datums-Button und "Ähnliche Schlagworte" weg.
    if (fitsNow()) return;
    sortDateBtn.classList.add('hidden');

    if (fitsNow() || !termMergeBtn) return;
    termMergeBtn.classList.add('hidden');

    if (fitsNow()) return;
    sortToolbar.classList.add('sort-toolbar--hidden-for-space');
  }

  // Fix: NICHT .section-heading-actions selbst beobachten - sobald
  // .sort-toolbar einmal ausgeblendet ist, schrumpft dessen eigene Box auf
  // die verbleibenden Icons und ändert sich danach nicht mehr, selbst wenn
  // der Nutzer das Fenster wieder breiter zieht (der Container "merkt"
  // nichts von mehr verfügbarem Platz, den er ja gar nicht ausfüllen muss).
  // .section-heading-row dagegen ändert seine Breite zuverlässig mit der
  // Seitenbreite selbst, unabhängig vom eigenen Sichtbarkeits-Zustand.
  new ResizeObserver(update).observe(row);
  update();
}

// Nutzerwunsch (2026-08-31): erst die sichtbare Liste laden, den Volltext
// (nur für die client-seitige Volltextsuche, Backlog #94 - sonst nirgends
// gebraucht außer im Bearbeiten-Formular, siehe editBtn unten) danach im
// Hintergrund nachladen - GET /api/sources?include_text=false ist um
// Größenordnungen kleiner als die Vollversion und lässt die Liste sofort
// erscheinen, statt auf mehrere MB Volltext aller Quellen zu warten.
let fullTextReady = null;

async function loadSources() {
  const res = await fetch('/api/sources?include_text=false', {
    headers: { 'X-Lang': getLang() },
  });
  allSources = await res.json();
  // Ein aktiver Autor:innen-/Begriffs-/Broken-Links-Filter soll ein
  // Neuladen (z.B. nach dem Aktualisieren oder Löschen einer Quelle)
  // überleben, statt stillschweigend auf die ungefilterte Liste
  // zurückzuspringen.
  if (activeFilter?.type === 'author') {
    await applyAuthorFilter(activeFilter.value);
  } else if (activeFilter?.type === 'term') {
    await applyTermFilter(activeFilter.value);
  } else if (activeFilter?.type === 'search') {
    applySearchFilter(activeFilter.value);
  } else if (activeFilter?.type === 'broken-links') {
    applyBrokenLinksFilter();
  } else {
    renderSourceList(allSources);
    filteredAuthorEntry = null;
    authorPanelEditMode = false;
    renderAuthorInfoPanel();
  }
  updateBrokenLinksButton();
  loadTermOverview();

  fullTextReady = loadFullSourceText();
}

async function loadFullSourceText() {
  const res = await fetch('/api/sources', { headers: { 'X-Lang': getLang() } });
  const full = await res.json();
  const textById = new Map(full.map((s) => [s.id, s.text]));
  allSources.forEach((s) => {
    if (textById.has(s.id)) s.text = textById.get(s.id);
  });
  // Eine bereits laufende Volltextsuche sah bis hierhin nur die Titel/
  // Zusammenfassungen/Autor:innen/Schlagworte der schlanken Liste - jetzt mit
  // vollständigen Daten erneut filtern, damit Volltext-Treffer nicht fehlen.
  if (activeFilter?.type === 'search') {
    applySearchFilter(activeFilter.value);
  }
}

async function loadAuthors() {
  const res = await fetch('/api/authors', { headers: { 'X-Lang': getLang() } });
  allAuthors = await res.json();
  setKnownAuthors(allAuthors);
  renderAuthorList();

  const datalist = document.getElementById('author-suggestions');
  datalist.innerHTML = '';
  allAuthors.forEach((a) => {
    const option = document.createElement('option');
    option.value = a.name;
    datalist.appendChild(option);
  });
}

function renderAuthorList() {
  const list = document.getElementById('author-list');
  list.replaceChildren(...allAuthors.map(buildAuthorListItem));
}

// Nutzerwunsch (2026-09-23): Schlagwort-Übersicht - alle Begriffe der
// gerade gewählten Sprache, alphabetisch, mit eigener Alphabet-Sprungleiste
// (analog updateAlphabetJumpBar) und seitenweisem Rendern per Sentinel
// (analog renderSourceList). Pro Begriff aufklappbar die zugehörigen
// Quellen, die Menge zusätzlich als Balken proportional zum Maximum.
// Gezählt werden nur Quellen, die in allSources auch sichtbar sind.
const TERMS_PAGE_SIZE = 50;
let overviewTerms = [];
let visibleTermCount = TERMS_PAGE_SIZE;
let termListObserver = null;

function termLetter(term) {
  const letter = term.normalize('NFD')[0].toUpperCase();
  return JUMP_ALPHABET.includes(letter) ? letter : '';
}

function buildOverviewTerms(entries, sources, lang) {
  const sourceById = new Map(sources.map((s) => [s.id, s]));
  return entries
    .filter((e) => e.langs.includes(lang))
    .map((e) => ({ term: e.term, sources: e.source_ids.map((id) => sourceById.get(id)).filter(Boolean) }))
    .filter((e) => e.sources.length)
    .sort((a, b) => a.term.localeCompare(b.term, lang));
}

async function loadTermOverview() {
  const res = await fetch('/api/terms');
  overviewTerms = buildOverviewTerms(await res.json(), allSources, getLang());
  renderTermJumpBar();
  renderTermOverview();
}

function renderTermJumpBar() {
  const bar = document.getElementById('term-jump-bar');
  const available = new Set(overviewTerms.map((e) => termLetter(e.term)));
  bar.replaceChildren(
    ...JUMP_ALPHABET.map((letter) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'alphabet-jump-btn';
      btn.textContent = letter;
      if (available.has(letter)) {
        const label = t('import.termJumpToLetterTitle', { letter });
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.addEventListener('click', () => jumpToTermLetter(letter));
      } else {
        btn.disabled = true;
      }
      return btn;
    })
  );
}

function jumpToTermLetter(letter) {
  const index = overviewTerms.findIndex((e) => termLetter(e.term) === letter);
  if (index >= visibleTermCount) {
    visibleTermCount = index + 1;
    renderTermOverview();
  }
  document
    .querySelector(`#term-overview-list [data-term-index="${index}"]`)
    ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function renderTermOverview() {
  const list = document.getElementById('term-overview-list');
  document.getElementById('term-overview-empty').classList.toggle('hidden', overviewTerms.length > 0);
  const maxCount = Math.max(1, ...overviewTerms.map((e) => e.sources.length));
  list.replaceChildren(
    ...overviewTerms.slice(0, visibleTermCount).map((e, index) => buildTermOverviewItem(e, index, maxCount))
  );

  termListObserver?.disconnect();
  if (overviewTerms.length > visibleTermCount) {
    const sentinel = document.createElement('li');
    sentinel.className = 'term-overview-sentinel';
    list.appendChild(sentinel);
    termListObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          termListObserver.disconnect();
          visibleTermCount += TERMS_PAGE_SIZE;
          renderTermOverview();
        }
      },
      { rootMargin: '400px' }
    );
    termListObserver.observe(sentinel);
  }
}

// Nutzerwunsch (2026-09-23): Quellen-Pfleger:innen können Schlagworte
// direkt in der Übersicht umbenennen (Stift wie beim Zielschlagwort im
// Zusammenführen-Panel) oder löschen (zweistufig wie dort). Umbenennen ist
// ein Zusammenführen auf den neuen Namen, beides über die bestehenden
// Endpunkte - landet damit im Änderungs-Log und ist pro Quelle rückgängig
// machbar. Übergeben werden alle Schreibweisen, die in den Quellen
// tatsächlich stehen (z.B. "Agile"/"agile" teilen sich einen Eintrag).
function termSpellings(entry) {
  const key = normalizeTerm(entry.term);
  const spellings = new Set([entry.term]);
  entry.sources.forEach((s) => (s.key_terms || []).forEach((k) => normalizeTerm(k) === key && spellings.add(k)));
  return [...spellings];
}

async function postTermChange(url, body, status, failedKey) {
  status.classList.add('hidden');
  try {
    const res = await fetch(url, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
    if (!res.ok) throw new Error();
    resetKnownTerms();
    await loadSources();
    return true;
  } catch {
    status.textContent = t(failedKey);
    status.classList.remove('hidden');
    setTermExpanded(status.closest('li'), true);
    return false;
  }
}

function buildTermRenameControls(entry, toggle, status) {
  const editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'icon-button term-merge-edit-canonical';
  editBtn.innerHTML = EDIT_ICON;
  const editLabel = t('import.termRenameTitle');
  editBtn.title = editLabel;
  editBtn.setAttribute('aria-label', editLabel);

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'term-merge-canonical-input hidden';
  input.title = t('import.termRenameInputTitle');
  const suggestions = attachTagSuggestions(input, { multi: false, lang: getLang() });

  const wrap = document.createElement('span');
  wrap.className = 'term-merge-canonical-wrap term-overview-head';
  const deleteBtn = buildTermDeleteButton(entry, status);
  // Stift + Mülleimer als Einheit rechts neben dem Begriff, vertikal mittig
  // auch bei mehrzeiligen Begriffen (siehe .term-overview-head).
  const actions = document.createElement('span');
  actions.className = 'term-overview-actions';
  actions.append(editBtn, deleteBtn);
  wrap.append(toggle, actions, input, suggestions);

  function setEditing(editing) {
    toggle.classList.toggle('hidden', editing);
    actions.classList.toggle('hidden', editing);
    input.classList.toggle('hidden', !editing);
  }
  editBtn.addEventListener('click', () => {
    input.value = entry.term;
    setEditing(true);
    input.focus();
    input.select();
  });
  // Nur Enter speichert - Escape oder Wegklicken verwirft, damit nichts
  // versehentlich über alle Quellen hinweg umbenannt wird.
  input.addEventListener('blur', () => setEditing(false));
  input.addEventListener('keydown', async (e) => {
    if (e.key === 'Escape') input.blur();
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const canonical = input.value.trim();
    if (!canonical || canonical === entry.term) {
      input.blur();
      return;
    }
    input.disabled = true;
    const ok = await postTermChange(
      '/api/terms/merge',
      { lang: getLang(), canonical, variants: termSpellings(entry) },
      status,
      'import.termRenameFailed'
    );
    input.disabled = false;
    if (!ok) input.blur();
  });
  return wrap;
}

function buildTermDeleteButton(entry, status) {
  // Erster Klick aufs Mülleimer-Icon macht daraus die Rückfrage als Text
  // (wie "Alle Schlagworte löschen" im Zusammenführen-Panel), erst der
  // zweite löscht.
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  const label = t('import.termDeleteButton');
  function resetDeleteBtn() {
    confirmPending = false;
    deleteBtn.className = 'icon-button term-merge-edit-canonical';
    deleteBtn.innerHTML = TRASH_ICON;
    deleteBtn.title = label;
    deleteBtn.setAttribute('aria-label', label);
    deleteBtn.disabled = false;
  }
  let confirmPending = false;
  resetDeleteBtn();
  deleteBtn.addEventListener('click', async () => {
    if (!confirmPending) {
      confirmPending = true;
      deleteBtn.className = 'link-button term-overview-delete-confirm';
      deleteBtn.textContent = t('import.termDeleteConfirmButton');
      deleteBtn.removeAttribute('aria-label');
      return;
    }
    deleteBtn.disabled = true;
    const ok = await postTermChange(
      '/api/terms/delete',
      { lang: getLang(), terms: termSpellings(entry) },
      status,
      'import.termMergeDeleteFailed'
    );
    if (!ok) resetDeleteBtn();
  });
  return deleteBtn;
}

// Aufgeklappte Schlagworte überleben so jedes Neuzeichnen (z.B. nach dem
// Speichern einer Quelle im Bearbeiten-Formular darunter).
const expandedTermKeys = new Set();

function setTermExpanded(li, expanded) {
  if (expanded) li.fillSources();
  li.querySelector('.term-overview-toggle').setAttribute('aria-expanded', String(expanded));
  li.querySelector('.term-overview-panel').hidden = !expanded;
  if (expanded) expandedTermKeys.add(li.dataset.termKey);
  else expandedTermKeys.delete(li.dataset.termKey);
}

// Bewusst kein <details>/<summary>: Stift und Mülleimer sind eigene Buttons,
// und interaktive Elemente innerhalb eines <summary> sind per Tastatur/
// Screenreader nicht verlässlich bedienbar (Chrome-Issue). Stattdessen das
// Disclosure-Muster - nur der Begriff selbst ist der Aufklapp-Button.
function buildTermOverviewItem(entry, index, maxCount) {
  const li = document.createElement('li');
  li.dataset.termIndex = String(index);
  const termKey = normalizeTerm(entry.term);
  li.dataset.termKey = termKey;
  const expanded = expandedTermKeys.has(termKey);
  const row = document.createElement('div');
  row.className = 'term-overview-summary';

  const panel = document.createElement('div');
  panel.className = 'term-overview-panel';
  panel.id = `term-overview-panel-${index}`;
  panel.hidden = !expanded;

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'term-overview-name term-overview-toggle';
  toggle.textContent = entry.term;
  toggle.setAttribute('aria-expanded', String(expanded));
  toggle.setAttribute('aria-controls', panel.id);
  toggle.addEventListener('click', () => setTermExpanded(li, panel.hidden));

  const bar = document.createElement('span');
  bar.className = 'term-overview-bar';
  const fill = document.createElement('span');
  fill.className = 'term-overview-bar-fill';
  fill.style.width = `${(entry.sources.length / maxCount) * 100}%`;
  bar.appendChild(fill);

  // Mobil nur die Zahl (Nutzerwunsch 2026-09-23) - der volle Text bleibt
  // dort für Screenreader erhalten (visuell ausgeblendet, siehe CSS).
  const count = document.createElement('span');
  count.className = 'term-overview-count';
  const countKey = entry.sources.length === 1 ? 'common.sourceCountOne' : 'common.sourceCountMany';
  const countFull = document.createElement('span');
  countFull.className = 'term-overview-count-full';
  countFull.textContent = t(countKey, { count: entry.sources.length });
  const countNum = document.createElement('span');
  countNum.className = 'term-overview-count-num';
  countNum.setAttribute('aria-hidden', 'true');
  countNum.textContent = String(entry.sources.length);
  count.append(countFull, countNum);

  const status = document.createElement('p');
  status.className = 'jobs-list-error hidden';
  row.append(toggle, bar, count);
  // Der Stift-Wrapper übernimmt toggle (verschiebt es aus row) und rückt an dessen Platz.
  if (hasPflegerRole()) row.prepend(buildTermRenameControls(entry, toggle, status));

  // Nutzerwunsch (2026-09-24): Quellen hier "vor Ort" aufklappen
  // (Kurzbeschreibung) und bearbeiten - dieselben Zeilen wie in der
  // Quellenliste. Nur für aufgeklappte Schlagworte gebaut.
  // Erst beim (ersten) Aufklappen gebaut - bei Hunderten sichtbarer
  // Schlagworte wären das sonst Tausende Zeilen samt Buttons vorab.
  const sourceList = document.createElement('ul');
  sourceList.className = 'term-overview-sources';
  li.fillSources = () => {
    if (sourceList.children.length) return;
    entry.sources.forEach((s, i) => {
      sourceList.append(...buildSourceEntries({ ...s, __editRowKey: `term:${termKey}` }, `t${index}-${i}`));
    });
  };
  if (expanded) li.fillSources();
  const filterBtn = document.createElement('button');
  filterBtn.type = 'button';
  filterBtn.className = 'link-button term-overview-filter';
  filterBtn.textContent = t('import.termOverviewFilter');
  filterBtn.addEventListener('click', () => filterByTerm(entry.term));
  panel.append(sourceList, filterBtn, status);

  li.append(row, panel);
  return li;
}

function buildAuthorLink(url, label) {
  const link = document.createElement('a');
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.className = 'author-link';
  const icon = document.createElement('span');
  icon.className = 'author-link-icon';
  icon.innerHTML = EXTERNAL_LINK_ICON;
  link.appendChild(icon);
  link.append(label);
  return link;
}

function buildAuthorBioSection(a) {
  const container = document.createElement('div');
  container.className = 'author-bio-section';

  if (a.bio) {
    const bioP = document.createElement('p');
    bioP.className = 'author-bio-text';
    bioP.textContent = a.bio;
    container.appendChild(bioP);
    if (a.bio_ai_generated) prependAiIcon(container, 'import.aiBioTooltip');
  }

  const linksRow = document.createElement('div');
  linksRow.className = 'author-links-row';
  if (a.website) linksRow.appendChild(buildAuthorLink(a.website, t('import.fieldWebsite')));
  (a.social_links || []).forEach((link) => {
    if (link.url) linksRow.appendChild(buildAuthorLink(link.url, link.platform || link.url));
  });
  if (linksRow.children.length) container.appendChild(linksRow);

  if (!a.bio && !linksRow.children.length && !a.photo_url) {
    const emptyP = document.createElement('p');
    emptyP.className = 'author-bio-text author-bio-text--empty';
    emptyP.textContent = t('import.authorProfileEmpty');
    container.appendChild(emptyP);
  }

  return container;
}

async function generateAuthorBio(name, bioInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingBio');
  try {
    const res = await fetch(`/api/authors/${encodeURIComponent(name)}/generate-bio`, {
      method: 'POST',
      headers: jsonHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateBioFailed'));
    }
    const data = await res.json();
    if (!bioInput.value.trim()) bioInput.value = data.bio;
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

// Nutzerfeedback (2026-08-26): manche Foto-URLs liegen auf technisch
// korrekten, aber für Leser:innen kaum erkennbaren CDN-Subdomains großer
// Plattformen (z.B. media.licdn.com) - auf den bekannten Plattformnamen
// abbilden, analog zu SOCIAL_PLATFORM_HOSTS/detectSocialPlatform oben.
// Bewusst NICHT enthalten: gstatic.com (Google-Bilder-Thumbnail-Cache) -
// die eigentliche Quelle ist aus so einer URL nicht mehr rekonstruierbar,
// das wird stattdessen Zug um Zug direkt in den Autor:innen-Profilen durch
// echte Quellen-URLs ersetzt statt hier beschönigt.
const PHOTO_HOST_LABELS = [
  { pattern: /(^|\.)licdn\.com$/, label: 'LinkedIn' },
  { pattern: /(^|\.)rgstatic\.net$/, label: 'ResearchGate' },
  { pattern: /(^|\.)googleusercontent\.com$/, label: 'Google' },
  { pattern: /(^|\.)media-amazon\.com$/, label: 'Amazon' },
  { pattern: /(^|\.)gravatar\.com$/, label: 'Gravatar' },
  { pattern: /(^|\.)wp\.com$/, label: 'WordPress' },
];

// Nutzerwunsch (2026-08-26): kleiner, unauffälliger Bildquellennachweis
// unter dem Autor:innen-Foto (siehe buildAuthorInfoView) - nennt die Domain
// der ORIGINALEN externen Foto-URL (a.photo_url), nicht den vollen Pfad und
// nicht die eigene, ggf. lokal gecachte photo_large-URL (siehe app/
// author_photos.py). "www." wird entfernt, da es für die Quellennennung
// keinen Mehrwert hat; bekannte CDN-Domains werden auf ihren Plattformnamen
// abgebildet (siehe PHOTO_HOST_LABELS oben).
function photoCreditDomain(url) {
  const hostname = extractHostname(url);
  if (!hostname) return null;
  const match = PHOTO_HOST_LABELS.find(({ pattern }) => pattern.test(hostname));
  return match ? match.label : hostname;
}

function buildAuthorInfoView(a) {
  const wrapper = document.createElement('div');
  wrapper.className = 'author-info-view';

  const headerRow = document.createElement('div');
  headerRow.className = 'author-info-header-row';

  const heading = document.createElement('h4');
  heading.className = 'author-info-heading';
  heading.textContent = a.name;
  headerRow.appendChild(heading);

  const photoCol = document.createElement('div');
  photoCol.className = 'author-info-photo-col';

  const vitaPhotoUrl = a.photo_large || a.photo_url;
  if (vitaPhotoUrl) {
    const img = document.createElement('img');
    img.src = vitaPhotoUrl;
    img.alt = a.name;
    img.className = 'author-photo';
    photoCol.appendChild(img);

    const creditDomain = photoCreditDomain(a.photo_url);
    if (creditDomain) {
      const credit = document.createElement('p');
      credit.className = 'author-photo-credit';
      credit.textContent = t('import.photoCreditLabel', { domain: creditDomain });
      photoCol.appendChild(credit);
    }
  }

  headerRow.appendChild(photoCol);
  wrapper.appendChild(headerRow);
  wrapper.appendChild(buildAuthorBioSection(a));

  if (hasPflegerRole()) {
    const editRow = document.createElement('div');
    editRow.className = 'author-info-edit-row';
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'icon-button author-info-edit-btn';
    const editLabel = t('common.editAuthor');
    editBtn.title = editLabel;
    editBtn.setAttribute('aria-label', editLabel);
    editBtn.innerHTML = EDIT_ICON;
    editBtn.addEventListener('click', () => {
      authorPanelEditMode = true;
      renderAuthorInfoPanel();
    });
    editRow.appendChild(editBtn);
    wrapper.appendChild(editRow);
  }

  return wrapper;
}

function renderAuthorInfoPanel() {
  const panel = document.getElementById('author-info-panel');
  const body = document.getElementById('quellen-liste-body');
  if (!filteredAuthorEntry) {
    panel.replaceChildren();
    panel.classList.add('hidden');
    body.classList.remove('quellen-liste-body--author-filtered');
    return;
  }
  body.classList.add('quellen-liste-body--author-filtered');
  panel.classList.remove('hidden');
  panel.replaceChildren(
    authorPanelEditMode ? buildAuthorEditPanel(filteredAuthorEntry) : buildAuthorInfoView(filteredAuthorEntry)
  );
}

function buildAuthorEditPanel(a) {
  const wrapper = document.createElement('div');
  wrapper.className = 'author-edit-panel';

  const form = document.createElement('form');
  const status = document.createElement('p');
  status.className = 'edit-status';

  function field(labelKey, idSuffix, value, type) {
    const label = document.createElement('label');
    label.textContent = t(labelKey);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 4;
    input.id = `edit-author-${idSuffix}-${a.name}`;
    input.value = value || '';
    label.appendChild(input);
    label.htmlFor = input.id;
    form.appendChild(label);
    return input;
  }

  const nameInput = field('import.fieldAuthorName', 'name', a.name, 'text');

  const bioInput = field('import.fieldBio', 'bio', a.bio, 'textarea');
  const magicButtons = [];
  const triggerGenerateBio = () => generateAuthorBio(a.name, bioInput, status, magicButtons);
  magicButtons.push(addMagicButton(bioInput, triggerGenerateBio, 'import.generateBioTitle'));

  const photoUrlInput = field('import.fieldPhotoUrl', 'photo-url', a.photo_url, 'url');
  const photoFieldRow = document.createElement('div');
  photoFieldRow.className = 'photo-field-row';
  photoUrlInput.parentNode.insertBefore(photoFieldRow, photoUrlInput);
  photoFieldRow.appendChild(photoUrlInput);

  const photoPreview = document.createElement('img');
  photoPreview.className = 'author-photo-preview';
  photoPreview.alt = a.name;
  photoPreview.hidden = !a.photo_url;
  if (a.photo_url) photoPreview.src = a.photo_url;
  // Bild lädt/existiert nicht (z.B. während der Eingabe noch unvollständige
  // URL) - dann lieber gar nichts zeigen statt ein kaputtes Bild-Icon.
  photoPreview.addEventListener('error', () => {
    photoPreview.hidden = true;
  });
  photoUrlInput.addEventListener('input', () => {
    const value = photoUrlInput.value.trim();
    photoPreview.hidden = !value;
    if (value) photoPreview.src = value;
  });
  photoFieldRow.appendChild(photoPreview);

  const websiteInput = field('import.fieldWebsite', 'website', a.website, 'url');

  const socialLabel = document.createElement('label');
  socialLabel.textContent = t('import.fieldSocialLinks');
  const { wrapper: socialWrapper, getSocialLinkValues } = buildSocialLinksField(a.social_links);
  socialLabel.appendChild(socialWrapper);
  form.appendChild(socialLabel);

  const actionsRow = document.createElement('div');
  actionsRow.className = 'edit-panel-actions';

  const primaryActions = document.createElement('div');
  const submitBtn = document.createElement('button');
  submitBtn.type = 'submit';
  submitBtn.textContent = t('import.updateButton');
  primaryActions.appendChild(submitBtn);

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'link-button';
  cancelBtn.textContent = t('common.cancel');
  cancelBtn.addEventListener('click', () => {
    authorPanelEditMode = false;
    renderAuthorInfoPanel();
  });
  primaryActions.appendChild(cancelBtn);
  actionsRow.appendChild(primaryActions);

  form.appendChild(actionsRow);
  form.appendChild(status);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = t('import.updating');
    status.textContent = '';
    try {
      let currentName = a.name;
      const newName = nameInput.value.trim();
      if (newName && newName !== currentName) {
        const renameRes = await fetch(`/api/authors/${encodeURIComponent(currentName)}/rename`, {
          method: 'POST',
          headers: jsonHeaders(),
          body: JSON.stringify({ new_name: newName }),
        });
        if (!renameRes.ok) {
          const err = await renameRes.json().catch(() => ({}));
          throw new Error(err.detail || t('import.renameFailed'));
        }
        currentName = newName;
      }

      const res = await fetch(`/api/authors/${encodeURIComponent(currentName)}`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify({
          bio: bioInput.value,
          photo_url: photoUrlInput.value,
          website: websiteInput.value,
          social_links: getSocialLinkValues(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || t('import.updateFailed'));
      }
      authorPanelEditMode = false;
      await applyAuthorFilter(currentName);
      await loadAuthors();
    } catch (err) {
      status.textContent = t('common.errorPrefix') + err.message;
      submitBtn.disabled = false;
      submitBtn.textContent = t('import.updateButton');
    }
  });

  wrapper.appendChild(form);
  return wrapper;
}

function buildAuthorListItem(a) {
  const li = document.createElement('li');
  const authorBtn = document.createElement('button');
  authorBtn.type = 'button';
  authorBtn.className = 'link-button';
  authorBtn.textContent = a.name;
  authorBtn.addEventListener('click', () => filterByAuthor(a.name));
  li.appendChild(authorBtn);
  const countKey = a.source_count === 1 ? 'common.sourceCountOne' : 'common.sourceCountMany';
  li.append(` (${t(countKey, { count: a.source_count })})`);
  return li;
}

document.getElementById('source-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    title: document.getElementById('title').value,
    authors: getCreateAuthorValues(),
    date: document.getElementById('date').value || null,
    url: document.getElementById('url').value || null,
    listen_url: document.getElementById('listen-url').value || null,
    text: document.getElementById('text').value,
    restricted: document.getElementById('restricted').checked,
    pdf_upload_id: pendingUploadType === 'pdf' ? pendingUploadId : null,
    audio_upload_id: pendingUploadType === 'audio' ? pendingUploadId : null,
  };
  const status = document.getElementById('import-status');
  if (payload.url) {
    const existing = findExistingSourceByUrl(payload.url);
    if (existing) {
      status.textContent = t('import.urlAlreadyExists', { title: existing.title });
      return;
    }
  }
  const submitButton = document.getElementById('import-submit-button');
  submitButton.disabled = true;
  submitButton.textContent = t('import.importing');
  status.textContent = '';
  try {
    const res = await fetch('/api/sources', {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.importFailed'));
    }
    const data = await res.json();
    status.textContent = t('import.importedStatus', { title: data.title, count: data.chunk_count });
    if (data.processing_status) {
      // Sofort abrufen statt bis zum nächsten Poll-Takt zu warten - das
      // neue Status-Icon soll direkt nach dem Anlegen sichtbar sein.
      fetchImportJobs();
    }
    // add_source registriert neue Autor:innen synchron (authors.register_author),
    // daher kann das Profil direkt im Anschluss per PUT gespeichert werden.
    const newAuthorProfiles = getCreateNewAuthorProfiles();
    for (const [name, profile] of Object.entries(newAuthorProfiles)) {
      await fetch(`/api/authors/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify(profile),
      }).catch(() => {});
    }
    document.getElementById('source-form').reset();
    // form.reset() setzt bei den dynamisch erzeugten Autoren-Feldern nur den
    // Wert zurück, entfernt aber keine per "+" hinzugefügten Extra-Zeilen -
    // hier explizit auf ein einzelnes leeres Feld zurücksetzen.
    renderCreateAuthorDateRow([], '');
    pendingUploadId = null;
    pendingUploadType = null;
    setTextFieldPending(false, null);
    setListenUrlFieldVisible(false);
    importBereich.classList.add('hidden');
    // Nutzerwunsch (2026-08-31): nach erfolgreichem Import zurück zu den
    // Quelltyp-Icons scrollen - das Formular kann je nach Inhalt (z.B.
    // langer Text) deutlich unterhalb des sichtbaren Bereichs geendet haben,
    // nach dem Schließen blieben die Icons zum Importieren weiterer Quellen
    // dadurch außerhalb des Bildschirms.
    quelltypBereich.scrollIntoView({ behavior: 'smooth', block: 'start' });
    // Die URL-Eingabe im "Von URL importieren"-Popover gehört NICHT zu
    // #source-form (separates Formular für /api/extract-url) und wurde
    // daher vom obigen reset() nicht mit geleert - beim nächsten Import
    // stand sonst noch die vorherige URL darin.
    document.getElementById('popover-url').value = '';
    document.getElementById('popover-status').textContent = '';
    loadSources();
    loadAuthors();
  } catch (err) {
    status.textContent = t('common.errorPrefix') + err.message;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = t('import.importButton');
  }
});

let getCreateAuthorValues = () => [];
let getCreateNewAuthorProfiles = () => ({});

function renderCreateAuthorDateRow(overrideAuthorValues, overrideDateValue) {
  const existingAuthor = document.getElementById('author');
  const existingDate = document.getElementById('date');
  const authorValues =
    overrideAuthorValues !== undefined
      ? overrideAuthorValues
      : existingAuthor
        ? getCreateAuthorValues()
        : [];
  const dateValue =
    overrideDateValue !== undefined ? overrideDateValue : existingDate ? existingDate.value : '';
  const target = existingAuthor
    ? existingAuthor.closest('.author-fields')
    : document.getElementById('create-author-date-row');
  const getSourceText = () =>
    `${document.getElementById('title').value}: ${document.getElementById('text').value}`;
  const built = buildAuthorFields('author', authorValues, 'date', dateValue, true, getSourceText);
  target.replaceWith(built.wrapper);
  getCreateAuthorValues = built.getAuthorValues;
  getCreateNewAuthorProfiles = built.getNewAuthorProfiles;
}

document.addEventListener('i18n:changed', () => {
  updateSourceManagementVisibility();
  loadSources();
  loadAuthors();
  renderCreateAuthorDateRow();
});

// buildAuthorFields()/buildMarkupToolbar() rufen t() auf - das darf erst
// NACH await initI18n() passieren, sonst ist das Wörterbuch noch leer und
// es erscheinen die rohen Übersetzungsschlüssel statt echtem Text (genau
// dieser Fehler wurde hier gemeldet und behoben).
await initI18n();
await initAuth();

// Nutzerwunsch (2026-08-30): Konversations-Handoff (siehe conversation-
// handoff.js sowie question.js: appendViewSourceLink/appendEditSourceLink)
// - ein "Quelle ansehen/bearbeiten"-Link aus der Konversationsansicht kann
// ein ?handoff=-Token mitgeben, wenn dort bereits eine Konversation lief.
// import.html zeigt selbst keinen Chat, schreibt die Historie deshalb nur
// in denselben sessionStorage-Schlüssel wie question.js - ein späterer
// Klick auf den "Konversation"-Link im gemeinsamen Header lädt sie dann im
// selben Tab automatisch (unveränderte loadConversationHistory()).
const handoffHistory = await consumeConversationHandoffToken();
if (handoffHistory && handoffHistory.length) {
  try {
    sessionStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(handoffHistory));
  } catch (err) {
    // z.B. sessionStorage voll oder deaktiviert - dann bleibt die
    // Konversation eben nur in diesem Tab unerreichbar, kein Absturz.
  }
}

updateSourceManagementVisibility();
initSourceToolbarOverflow();
onAuthChange(() => {
  updateSourceManagementVisibility();
  loadSources();
});

renderCreateAuthorDateRow();

const createTextInput = document.getElementById('text');
const createToolbarRow = document.createElement('div');
createToolbarRow.className = 'markup-toolbar-row';
createToolbarRow.appendChild(buildMarkupToolbar(createTextInput));
createTextInput.parentNode.insertBefore(createToolbarRow, createTextInput);

await loadSources();
loadAuthors();

// Deep-Link aus der Konversationsansicht (Stift-Icon an Zitat-Snippets, nur
// für Quellen-Pfleger:innen sichtbar): /import.html?edit=<source_id> öffnet
// die betreffende Quelle direkt im Bearbeiten-Modus und scrollt sie in den
// sichtbaren Bereich.
const deepLinkEditId = new URLSearchParams(window.location.search).get('edit');
if (deepLinkEditId && hasPflegerRole() && allSources.some((s) => s.id === deepLinkEditId)) {
  // Fix (2026-08-31): siehe Kommentar am editBtn in renderSourceList - auch
  // dieser direkte Einstieg ins Bearbeiten-Formular braucht den erst im
  // Hintergrund nachgeladenen Volltext, sonst wäre das Textfeld leer.
  if (fullTextReady) await fullTextReady;
  activeEditId = deepLinkEditId;
  // Fix (2026-09-22): im Autor:innen-Modus reicht die Quellen-ID allein
  // nicht mehr (siehe isActiveEditRow) - welche der ggf. mehreren Zeilen
  // (eine pro Autor:in) gemeint ist, wird hier über dieselbe Sortierung wie
  // die eigentliche Liste bestimmt: die im aktuellen Sortiermodus ZUERST
  // gerenderte Zeile dieser Quelle.
  const deepLinkRow = sortSources(allSources).find((s) => s.id === deepLinkEditId);
  activeEditAuthorKey = deepLinkRow ? deepLinkRow.__sortAuthor || null : null;
  ensureSourceVisible(deepLinkEditId);
  renderSourceList(currentSourceList);
  requestAnimationFrame(() => {
    document
      .querySelector(`#source-list [data-source-id="${deepLinkEditId}"]`)
      ?.scrollIntoView({ block: 'center' });
  });
}

// Deep-Link auf eine einzelne Quelle (Backlog #75: u.a. aus dem Embed-Widget,
// aber für ALLE Besucher:innen nutzbar) - anders als ?edit= kein Rollen-Gate
// und kein Bearbeitungsmodus (activeEditId bleibt unverändert), nur Scroll +
// kurze Hervorhebung. Existiert die ID nicht (falsch/gelöscht), passiert
// nichts - es bleibt bei der normalen ungefilterten Übersicht.
const deepLinkSourceId = new URLSearchParams(window.location.search).get('source');
if (deepLinkSourceId && allSources.some((s) => s.id === deepLinkSourceId)) {
  focusSource(deepLinkSourceId);
}

// Deep-Link aus der Konversationsansicht (Autor:innen-Links an Zitaten):
// /import.html?author=<name> filtert direkt auf die Texte dieser Person und
// zeigt ihr Profil (inkl. Vita) im Info-Panel an.
const deepLinkAuthor = new URLSearchParams(window.location.search).get('author');
if (deepLinkAuthor) {
  await filterByAuthor(deepLinkAuthor);
}

// Deep-Link aus dem Explore-Modus (Klick auf einen Schlagwort-Knoten):
// /import.html?term=<begriff> filtert direkt auf Quellen mit diesem
// Schlagwort - dieselbe filterByTerm()-Funktion, die auch die Begriffs-
// Badges in der Quellenliste selbst nutzen.
const deepLinkTerm = new URLSearchParams(window.location.search).get('term');
if (deepLinkTerm) {
  await filterByTerm(deepLinkTerm);
}
