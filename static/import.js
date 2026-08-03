import { initI18n, t, getLang } from '/i18n.js';
import { renderMarkdown } from '/markdown.js';
import { initAuth, hasRole, onAuthChange } from '/auth.js';

const importBereich = document.getElementById('import-bereich');
const urlPopover = document.getElementById('url-popover');
const filePopover = document.getElementById('file-popover');
const quelltypBereich = document.getElementById('quelltyp-bereich');
const reindexBereich = document.getElementById('reindex-bereich');
const brokenLinksBtn = document.getElementById('typ-broken-links');

const EDIT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  "</svg>";

const EXTERNAL_LINK_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
  '<polyline points="15 3 21 3 21 9"></polyline>' +
  '<line x1="10" y1="14" x2="21" y2="3"></line>' +
  "</svg>";

const TRASH_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="3 6 5 6 21 6"></polyline>' +
  '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>' +
  '<path d="M10 11v6"></path><path d="M14 11v6"></path>' +
  '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>' +
  "</svg>";

const MAGIC_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none">' +
  '<path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z"></path>' +
  '<path d="M19 13l.9 2.1L22 16l-2.1.9L19 19l-.9-2.1L16 16l2.1-.9L19 13z"></path>' +
  "</svg>";

const WARNING_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M14 4l1.5-1.5a3.54 3.54 0 1 1 5 5L19 9"></path>' +
  '<path d="M10 15l-1.5 1.5a3.54 3.54 0 1 1-5-5L5 10"></path>' +
  '<line x1="3" y1="3" x2="21" y2="21"></line>' +
  "</svg>";

const PLUS_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="12" y1="5" x2="12" y2="19"></line>' +
  '<line x1="5" y1="12" x2="19" y2="12"></line>' +
  "</svg>";

const REMOVE_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<line x1="5" y1="12" x2="19" y2="12"></line>' +
  "</svg>";


const UNDO_DURATION_MS = 30000;

function wrapSelection(textarea, marker) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.slice(0, start);
  const selected = textarea.value.slice(start, end) || t('import.markupPlaceholder');
  const after = textarea.value.slice(end);
  textarea.value = `${before}${marker}${selected}${marker}${after}`;
  textarea.focus();
  textarea.selectionStart = start + marker.length;
  textarea.selectionEnd = start + marker.length + selected.length;
}

function insertHeading(textarea) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.slice(0, start);
  const selected = textarea.value.slice(start, end) || t('import.markupPlaceholder');
  const after = textarea.value.slice(end);
  const lineStart = before.lastIndexOf('\n') + 1;
  textarea.value = `${before.slice(0, lineStart)}## ${before.slice(lineStart)}${selected}${after}`;
  textarea.focus();
}

function buildMarkupToolbar(textarea) {
  const toolbar = document.createElement('div');
  toolbar.className = 'markup-toolbar';

  const buttons = [
    { text: 'B', className: 'markup-bold', titleKey: 'import.markupBold', action: () => wrapSelection(textarea, '**') },
    { text: 'I', className: 'markup-italic', titleKey: 'import.markupItalic', action: () => wrapSelection(textarea, '*') },
    { text: 'H', className: 'markup-heading', titleKey: 'import.markupHeading', action: () => insertHeading(textarea) },
  ];

  buttons.forEach((cfg) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `markup-button ${cfg.className}`;
    btn.textContent = cfg.text;
    btn.title = t(cfg.titleKey);
    btn.addEventListener('click', cfg.action);
    toolbar.appendChild(btn);
  });

  return toolbar;
}

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
let pendingUploadId = null;
let pendingUploadType = null; // 'pdf' | 'audio'
let currentSortMode = 'author';
// Backlog #94: kein Popover (auf Mobile unpraktikabel, siehe git-Historie)
// - stattdessen klappt dieser Bereich unterhalb der Icon-Leiste auf und
// ersetzt dabei die Alphabet-Sprungleiste (siehe updateAlphabetJumpBar).
let searchBarOpen = false;
const pendingDeletions = new Map();
const expandedSourceIds = new Set();

// Backlog (2026-08-02): der Erreichbarkeits-Status kommt jetzt fertig
// berechnet aus GET /api/sources mit (url_reachable/url_reason_code/
// url_status_code, siehe app/main.py: wöchentlicher Hintergrund-Check),
// statt live pro Seitenaufruf per Fan-out über alle Quellen geprüft zu
// werden (vorheriges unreachableSourceInfo/checkUrlHealth, siehe
// Git-Historie) - urlErrorText liest deshalb direkt vom Source-Objekt.
//
// Backlog #163: reason_code (app/monitoring.py) auf übersetzten,
// menschenlesbaren Text abbilden - bei "http_error" wird der konkrete
// Statuscode eingesetzt.
function urlErrorText(source) {
  switch (source.url_reason_code) {
    case 'http_error':
      return t('common.urlErrorHttp', { code: source.url_status_code });
    case 'timeout':
      return t('common.urlErrorTimeout');
    case 'dns_error':
      return t('common.urlErrorDns');
    case 'ssl_error':
      return t('common.urlErrorSsl');
    case 'connection_error':
      return t('common.urlErrorConnection');
    default:
      return t('common.urlErrorUnknown');
  }
}

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

function devUserHeaders() {
  // Name beibehalten (viele Call-Sites), sendet aber keinen Header mehr -
  // die Identität kommt jetzt automatisch über das Session-Cookie mit.
  return {
    'Content-Type': 'application/json',
    'X-Lang': getLang(),
  };
}

function updateSourceManagementVisibility() {
  quelltypBereich.classList.toggle('hidden', !hasPflegerRole());
  reindexBereich.classList.toggle('hidden', !hasPflegerRole());
  brokenLinksBtn.classList.toggle('hidden', !hasPflegerRole());
  if (!hasPflegerRole()) {
    importBereich.classList.add('hidden');
    urlPopover.classList.add('hidden');
    filePopover.classList.add('hidden');
    stopJobsPolling();
  } else {
    startJobsPolling();
  }
}

// Grobe Stufen-zu-Füllstand-Zuordnung fürs Fortschritts-Icon - die OpenAI-
// Transkriptions-API liefert kein echtes Fortschritts-Signal, daher kein
// exakter Prozentsatz, nur eine Annäherung je Verarbeitungsschritt.
const JOB_STAGE_FRACTIONS = { transcribe: 0.3, ocr: 0.3, chunking: 0.8, indexing: 0.95 };
const JOBS_RING_CIRCUMFERENCE = 56.5;
let jobsPollTimer = null;

function jobStepLabel(job) {
  const key = {
    transcribe: 'import.processingStepTranscribe',
    ocr: 'import.processingStepOcr',
    chunking: 'import.processingStepChunking',
    indexing: 'import.processingStepIndexing',
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
          await fetch(`/api/sources/${job.id}/reprocess`, { method: 'POST', headers: devUserHeaders() });
          await Promise.all([fetchImportJobs(), loadSources()]);
        } finally {
          retryBtn.disabled = false;
        }
      });
      li.appendChild(retryBtn);
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

async function fetchImportJobs() {
  if (!hasPflegerRole()) return;
  try {
    const res = await fetch('/api/import-jobs', { headers: devUserHeaders() });
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

function startJobsPolling() {
  if (jobsPollTimer) return;
  fetchImportJobs();
  // Erstes und bisher einziges Polling im Projekt (siehe README/Kommentar
  // hier bewusst) - kein Vorbild für generelle Live-Aktualisierungen,
  // sondern gezielt für den Import-Warteschlangen-Status.
  jobsPollTimer = setInterval(fetchImportJobs, 3000);
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

document.getElementById('typ-url').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  filePopover.classList.add('hidden');
  closeSearchBar();
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
  closeSearchBar();
  filePopover.classList.toggle('hidden');
  document.getElementById('upload-status').textContent = '';
});

document.getElementById('typ-jobs').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
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
  urlPopover.classList.add('hidden');
  filePopover.classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
  searchBarOpen = !searchBarOpen;
  document.getElementById('search-bar').classList.toggle('hidden', !searchBarOpen);
  renderSourceList(currentSourceList);
  if (searchBarOpen) {
    document.getElementById('search-input').focus();
  }
});

document.getElementById('popover-load').addEventListener('click', async () => {
  const url = document.getElementById('popover-url').value.trim();
  const status = document.getElementById('popover-status');
  const loadBtn = document.getElementById('popover-load');
  if (!url) {
    status.textContent = t('import.pleaseEnterUrl');
    return;
  }
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
      headers: devUserHeaders(),
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

function normalizeAuthor(name) {
  return name.trim().split(/\s+/).join(' ').toLowerCase();
}

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

function normalizeUrlForComparison(url) {
  const videoId = extractYoutubeVideoId(url);
  if (videoId) return `youtube:${videoId.toLowerCase()}`;
  return url.trim().replace(/\/+$/, '').toLowerCase();
}

function findExistingSourceByUrl(url) {
  const normalized = normalizeUrlForComparison(url);
  if (!normalized) return null;
  return allSources.find((s) => s.url && normalizeUrlForComparison(s.url) === normalized) || null;
}

function buildFieldLabelWithId(labelKey, id, value, type) {
  const label = document.createElement('label');
  label.textContent = t(labelKey);
  const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
  if (type !== 'textarea') input.type = type;
  else input.rows = 10;
  input.id = id;
  input.value = value || '';
  label.appendChild(input);
  return { label, input };
}

// Aufklappbarer Bereich unterhalb eines Autor:innen-Feldes, der nur bei
// einer noch nicht erfassten Person sichtbar wird (siehe attachNewAuthorToggle
// weiter unten) - dieselben Felder wie im bestehenden Autor:innen-Profil
// (buildAuthorEditPanel). Die Person ist noch nicht als Autor:in registriert,
// es gibt also keine gespeicherten Quellen, aus denen sich per bestehendem
// /generate-bio-Endpunkt eine Vita generieren ließe - der KI-Vita-Button
// nutzt deshalb /api/authors/generate-bio-preview mit dem gerade im Formular
// stehenden Titel/Text der aktuellen Quelle als Grundlage (nameInput/
// getSourceText werden von attachNewAuthorToggle übergeben).
function buildNewAuthorProfilePanel(nameInput, getSourceText) {
  const details = document.createElement('details');
  details.className = 'new-author-profile hidden';

  const summary = document.createElement('summary');
  summary.textContent = t('import.newAuthorProfileToggle');
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'new-author-profile-body';
  details.appendChild(body);

  function fieldRow(labelKey, type) {
    const label = document.createElement('label');
    const span = document.createElement('span');
    span.textContent = t(labelKey);
    label.appendChild(span);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type === 'textarea') input.rows = 3;
    else input.type = type;
    label.appendChild(input);
    body.appendChild(label);
    return input;
  }

  const photoUrlInput = fieldRow('import.fieldPhotoUrl', 'url');
  const photoFieldRow = document.createElement('div');
  photoFieldRow.className = 'photo-field-row';
  photoUrlInput.parentNode.insertBefore(photoFieldRow, photoUrlInput);
  photoFieldRow.appendChild(photoUrlInput);
  const photoPreview = document.createElement('img');
  photoPreview.className = 'author-photo-preview';
  // Anders als beim Bearbeiten-Panel eines bestehenden Profils ist der Name
  // hier noch nicht final (wird gerade erst getippt) - deshalb ein
  // generisches Alt statt a.name.
  photoPreview.alt = t('import.newAuthorPhotoPreviewAlt');
  photoPreview.hidden = true;
  photoPreview.addEventListener('error', () => {
    photoPreview.hidden = true;
  });
  photoUrlInput.addEventListener('input', () => {
    const value = photoUrlInput.value.trim();
    photoPreview.hidden = !value;
    if (value) photoPreview.src = value;
  });
  photoFieldRow.appendChild(photoPreview);

  const websiteInput = fieldRow('import.fieldWebsite', 'url');

  const socialLabel = document.createElement('label');
  socialLabel.textContent = t('import.fieldSocialLinks');
  const { wrapper: socialWrapper, getSocialLinkValues } = buildSocialLinksField([]);
  socialLabel.appendChild(socialWrapper);
  body.appendChild(socialLabel);

  const bioInput = fieldRow('import.fieldBio', 'textarea');
  const bioStatus = document.createElement('p');
  bioStatus.className = 'edit-status';
  body.appendChild(bioStatus);
  const bioMagicButtons = [];
  const triggerGenerateBioPreview = () =>
    generateAuthorBioPreview(nameInput.value.trim(), getSourceText(), bioInput, bioStatus, bioMagicButtons);
  bioMagicButtons.push(addMagicButton(bioInput, triggerGenerateBioPreview, 'import.generateBioTitle'));

  function getProfileValues() {
    return {
      photo_url: photoUrlInput.value.trim(),
      website: websiteInput.value.trim(),
      social_links: getSocialLinkValues(),
      bio: bioInput.value.trim(),
    };
  }

  function hasAnyValue() {
    const v = getProfileValues();
    return !!(v.photo_url || v.website || v.social_links.length || v.bio);
  }

  return { details, getProfileValues, hasAnyValue };
}

// Wird sowohl im Bearbeiten- als auch im Neu-anlegen-Formular verwendet
// (siehe unten im Skript), damit Autor(en)/Datum an genau einer Stelle
// gepflegt werden und in beiden Masken automatisch gleich aussehen.
// Eine Quelle kann mehrere Autor:innen haben - das erste Feld steht mit dem
// Datum in einer Zeile, über das "+"-Icon lassen sich beliebig viele weitere
// Autoren-Zeilen darunter ergänzen (jede mit eigenem "+"), ab der zweiten
// Zeile zusätzlich mit einem "-"-Icon zum Entfernen.
//
// enableNewAuthorProfile: zeigt unter einer noch nicht erfassten Person
// "Autorenprofil pflegen" an (Backlog #86) - sowohl im Neu-anlegen- als auch
// im Bearbeiten-Formular (siehe renderCreateAuthorDateRow bzw. der Aufruf in
// buildEditPanel). Beide Formulare speichern die Profildaten nach dem
// erfolgreichen POST/PUT der Quelle direkt per PUT /api/authors/{name} -
// funktioniert in beiden Fällen, weil sowohl add_source als auch
// update_source neu hinzugefügte Autor:innen bereits synchron registrieren.
function buildAuthorFields(
  authorId,
  authorValues,
  dateId,
  dateValue,
  enableNewAuthorProfile = false,
  getSourceText = () => ''
) {
  const values = authorValues && authorValues.length ? authorValues : [''];
  const profileEntries = [];

  function attachNewAuthorToggle(input, container) {
    if (!enableNewAuthorProfile) return;
    const { details, getProfileValues, hasAnyValue } = buildNewAuthorProfilePanel(input, getSourceText);
    container.appendChild(details);
    profileEntries.push({ input, getProfileValues, hasAnyValue });

    function refreshVisibility() {
      const name = input.value.trim();
      const isKnownOrEmpty = !name || allAuthors.some((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
      details.classList.toggle('hidden', isKnownOrEmpty);
      if (isKnownOrEmpty) details.open = false;
    }
    input.addEventListener('input', refreshVisibility);
    refreshVisibility();
  }

  function buildAuthorInput(value) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'author-input';
    input.setAttribute('list', 'author-suggestions');
    input.setAttribute('autocomplete', 'off');
    input.value = value || '';
    return input;
  }

  function buildAddButton(insertNewRow) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button add-author-btn';
    btn.innerHTML = PLUS_ICON;
    const label = t('import.addAuthor');
    btn.title = label;
    btn.setAttribute('aria-label', label);
    // Nutzerwunsch (2026-08-03): nach Klick auf "+" soll der Cursor direkt
    // im neuen Eingabefeld stehen, damit der Name ohne zusätzlichen Klick
    // eingetippt werden kann.
    btn.addEventListener('click', () => {
      const newRow = buildExtraRow('');
      insertNewRow(newRow);
      newRow.querySelector('.author-input')?.focus();
    });
    return btn;
  }

  function buildRemoveButton(group) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button remove-author-btn';
    btn.innerHTML = REMOVE_ICON;
    const label = t('import.removeAuthor');
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.addEventListener('click', () => group.remove());
    return btn;
  }

  function buildExtraRow(value) {
    // "group" hält Eingabezeile UND das dazugehörige "Autorenprofil
    // pflegen"-Panel zusammen, damit beide gemeinsam per "-" entfernt bzw.
    // per "+" als Einheit nach diesem Eintrag eingefügt werden.
    const group = document.createElement('div');
    group.className = 'author-extra-row-group';

    const row = document.createElement('div');
    row.className = 'author-extra-row';
    const input = buildAuthorInput(value);
    row.appendChild(input);
    row.appendChild(buildAddButton((newGroup) => group.insertAdjacentElement('afterend', newGroup)));
    row.appendChild(buildRemoveButton(group));
    group.appendChild(row);

    attachNewAuthorToggle(input, group);
    return group;
  }

  const extraRowsContainer = document.createElement('div');
  extraRowsContainer.className = 'author-extra-rows';
  values.slice(1).forEach((value) => {
    extraRowsContainer.appendChild(buildExtraRow(value));
  });

  const firstInput = buildAuthorInput(values[0]);
  firstInput.id = authorId;
  const authorInputGroup = document.createElement('span');
  authorInputGroup.className = 'author-input-group';
  authorInputGroup.appendChild(firstInput);
  authorInputGroup.appendChild(buildAddButton((newRow) => extraRowsContainer.prepend(newRow)));

  const authorLabel = document.createElement('label');
  authorLabel.textContent = t('import.fieldAuthor');
  authorLabel.appendChild(authorInputGroup);

  const dateField = buildFieldLabelWithId('import.fieldDate', dateId, dateValue, 'date');

  const row = document.createElement('div');
  row.className = 'field-row';
  row.appendChild(authorLabel);
  row.appendChild(dateField.label);

  const wrapper = document.createElement('div');
  wrapper.className = 'author-fields';
  wrapper.appendChild(row);
  attachNewAuthorToggle(firstInput, wrapper);
  wrapper.appendChild(extraRowsContainer);

  function getAuthorValues() {
    return [...wrapper.querySelectorAll('.author-input')]
      .map((input) => input.value.trim())
      .filter((value) => value);
  }

  // Liefert Profildaten NUR für Namen, die (a) noch nicht in allAuthors
  // erfasst sind UND (b) tatsächlich ausgefüllt wurden - ein leer
  // gelassenes, nur aufgeklapptes Panel erzeugt keinen Eintrag.
  function getNewAuthorProfiles() {
    const result = {};
    profileEntries.forEach(({ input, getProfileValues, hasAnyValue }) => {
      const name = input.value.trim();
      if (!name || !hasAnyValue()) return;
      const isKnown = allAuthors.some((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
      if (isKnown) return;
      result[name] = getProfileValues();
    });
    return result;
  }

  return { wrapper, dateInput: dateField.input, getAuthorValues, getNewAuthorProfiles };
}

function buildEditPanel(s, options = {}) {
  const pendingDeletion = !!options.pendingDeletion;

  const li = document.createElement('li');
  li.className = 'source-edit-panel';
  if (pendingDeletion) {
    li.classList.add('source-edit-panel--pending-deletion');
  }

  const form = document.createElement('form');
  const status = document.createElement('p');
  status.className = 'edit-status';

  function buildFieldLabel(labelKey, idSuffix, value, type) {
    const label = document.createElement('label');
    label.textContent = t(labelKey);
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 10;
    input.id = `edit-${idSuffix}-${s.id}`;
    input.value = value || '';
    label.appendChild(input);
    // Explizit setzen statt auf die implizite "erstes labelfähiges Kind"-Regel
    // zu vertrauen - sonst wird ein später in dieses Label eingefügter Button
    // (z.B. das Öffnen-Icon vor dem URL-Feld) zum Klick-Ziel des gesamten
    // Labels, und ein Klick irgendwo in der Zeile löst den Button aus statt
    // nur einen Klick direkt auf das Icon.
    label.htmlFor = input.id;
    return { label, input };
  }

  function field(labelKey, idSuffix, value, type) {
    const { label, input } = buildFieldLabel(labelKey, idSuffix, value, type);
    form.appendChild(label);
    return input;
  }

  const titleField = buildFieldLabel('import.fieldTitle', 'title', s.title, 'text');
  const titleInput = titleField.input;
  titleInput.required = true;

  // Backlog #51: Relevanz-Score (1-10) - nur für Quellen-Pfleger:innen/
  // System-Admins sichtbar (diese ganze Bearbeitungsansicht ist bereits auf
  // diese Rollen beschränkt) und bewusst auf Höhe des Titels platziert,
  // statt als eigene Zeile weiter unten - der Titel rückt dafür von voller
  // Breite auf 2/3 (Slider nimmt das übrige Drittel ein).
  const relevanceValue = s.relevance_score ?? 5;
  const relevanceRow = document.createElement('div');
  relevanceRow.className = 'title-relevance-row';
  const relevanceField = document.createElement('div');
  relevanceField.className = 'relevance-slider-field';
  const relevanceLabelRow = document.createElement('div');
  relevanceLabelRow.className = 'relevance-slider-label-row';
  const relevanceLabel = document.createElement('span');
  relevanceLabel.textContent = t('import.fieldRelevanceScore');
  const relevanceValueDisplay = document.createElement('span');
  relevanceValueDisplay.className = 'relevance-slider-value';
  relevanceValueDisplay.textContent = String(relevanceValue);
  relevanceLabelRow.append(relevanceLabel, relevanceValueDisplay);
  const relevanceInput = document.createElement('input');
  relevanceInput.type = 'range';
  relevanceInput.min = '1';
  relevanceInput.max = '10';
  relevanceInput.step = '1';
  relevanceInput.value = String(relevanceValue);
  relevanceInput.className = 'relevance-slider';
  relevanceInput.id = `edit-relevance-${s.id}`;
  const relevanceTitle = t('import.fieldRelevanceScore');
  relevanceInput.title = relevanceTitle;
  relevanceInput.setAttribute('aria-label', relevanceTitle);
  relevanceInput.addEventListener('input', () => {
    relevanceValueDisplay.textContent = relevanceInput.value;
  });
  relevanceField.append(relevanceLabelRow, relevanceInput);
  relevanceRow.append(titleField.label, relevanceField);
  form.appendChild(relevanceRow);

  // Lazy statt direkt gebunden: titleInput/textInput existieren an dieser
  // Stelle noch nicht (werden erst weiter unten deklariert) - der Getter wird
  // aber erst beim Klick auf den KI-Vita-Button ausgewertet, zu diesem
  // Zeitpunkt sind beide Variablen bereits zugewiesen.
  const getSourceText = () => `${titleInput.value}: ${textInput.value}`;
  const {
    wrapper: authorFieldsWrapper,
    dateInput,
    getAuthorValues,
    getNewAuthorProfiles,
  } = buildAuthorFields(
    `edit-author-${s.id}`,
    s.authors,
    `edit-date-${s.id}`,
    s.date,
    true,
    getSourceText
  );
  form.appendChild(authorFieldsWrapper);

  const urlField = buildFieldLabel('import.fieldUrl', 'url', s.url, 'url');
  const urlInput = urlField.input;
  const openUrlBtn = document.createElement('button');
  openUrlBtn.type = 'button';
  openUrlBtn.className = 'icon-button label-inline-icon';
  const openUrlLabel = t('common.openSource');
  openUrlBtn.title = openUrlLabel;
  openUrlBtn.setAttribute('aria-label', openUrlLabel);
  openUrlBtn.innerHTML = EXTERNAL_LINK_ICON;
  openUrlBtn.addEventListener('click', () => {
    const value = urlInput.value.trim();
    if (value) window.open(value, '_blank', 'noopener,noreferrer');
  });
  urlField.label.insertBefore(openUrlBtn, urlInput);
  form.appendChild(urlField.label);

  // Backlog #163: konkreter Fehlergrund als Statuszeile direkt im
  // Bearbeiten-Panel - im Gegensatz zum Tooltip auf dem Warn-Icon (nur
  // Hover, auf Mobile kaum nutzbar) hier immer sichtbar, genau dort, wo
  // der Link auch repariert wird.
  if (s.url_reachable === false) {
    const healthStatus = document.createElement('p');
    healthStatus.className = 'url-health-status';
    healthStatus.textContent = `${t('common.urlUnreachable')}: ${urlErrorText(s)}`;
    form.appendChild(healthStatus);
  }

  const listenUrlField = buildFieldLabel('import.fieldListenUrl', 'listen-url', s.listen_url, 'url');
  const listenUrlInput = listenUrlField.input;
  // Nutzerwunsch (2026-08-03): das Feld existiert im Datenmodell schon
  // lange fuer Audio-Quellen (Verweis auf die Podcast-/Anhoer-Seite) - PDFs
  // profitieren genauso davon (Verweis auf die Seite, auf der das PDF
  // abgerufen werden kann), nur der Audio-Player darunter bleibt
  // audio-spezifisch.
  if (s.has_audio || s.has_pdf) {
    form.appendChild(listenUrlField.label);
  }
  if (s.has_audio) {
    const audioPreviewLabel = document.createElement('label');
    const audioPreviewText = document.createElement('span');
    audioPreviewText.textContent = t('import.audioPreviewLabel');
    const audioPlayer = document.createElement('audio');
    audioPlayer.controls = true;
    audioPlayer.className = 'audio-preview-player';
    audioPlayer.src = `/api/sources/${s.id}/audio`;
    audioPreviewLabel.appendChild(audioPreviewText);
    audioPreviewLabel.appendChild(audioPlayer);
    form.appendChild(audioPreviewLabel);
  }

  const textInput = field('import.fieldText', 'text', s.text, 'textarea');
  if (s.restricted) {
    textInput.placeholder = t('import.restrictedTextPlaceholder');
  } else {
    textInput.required = true;
  }

  const toolbarRow = document.createElement('div');
  toolbarRow.className = 'markup-toolbar-row';
  toolbarRow.appendChild(buildMarkupToolbar(textInput));

  if (s.has_pdf) {
    const pdfBtn = document.createElement('button');
    pdfBtn.type = 'button';
    pdfBtn.className = 'link-button';
    pdfBtn.textContent = t('import.openPdf');
    pdfBtn.addEventListener('click', async () => {
      // Fenster MUSS synchron innerhalb des Klick-Handlers geöffnet werden -
      // ruft man window.open() erst nach einem await (fetch/blob), fehlt der
      // Bezug zur User-Geste und der Browser blockiert das Popup lautlos.
      const pdfWindow = window.open('', '_blank');
      try {
        const res = await fetch(`/api/sources/${s.id}/pdf`, { headers: devUserHeaders() });
        if (!res.ok) throw new Error(t('import.openPdfFailed'));
        const blob = await res.blob();
        if (pdfWindow) {
          pdfWindow.location = URL.createObjectURL(blob);
        } else {
          window.open(URL.createObjectURL(blob), '_blank');
        }
      } catch (err) {
        if (pdfWindow) pdfWindow.close();
        status.textContent = t('common.errorPrefix') + err.message;
      }
    });
    toolbarRow.appendChild(pdfBtn);
  }

  textInput.parentNode.insertBefore(toolbarRow, textInput);

  const restrictedLabel = document.createElement('label');
  restrictedLabel.className = 'checkbox-label';
  const restrictedInput = document.createElement('input');
  restrictedInput.type = 'checkbox';
  restrictedInput.checked = !!s.restricted;
  const restrictedText = document.createElement('span');
  restrictedText.textContent = t('import.restrictedLabel');
  restrictedLabel.appendChild(restrictedInput);
  restrictedLabel.appendChild(restrictedText);
  form.appendChild(restrictedLabel);

  const summaryInput = field('import.fieldSummary', 'summary', s.summary, 'textarea');
  summaryInput.rows = 4;
  const keyTermsInput = field(
    'import.fieldKeyTerms',
    'key-terms',
    (s.key_terms || []).join(', '),
    'text'
  );

  if (!pendingDeletion) {
    const magicButtons = [];
    const triggerGenerate = () =>
      generateSummaryFields(s.id, summaryInput, keyTermsInput, status, magicButtons);
    magicButtons.push(addMagicButton(summaryInput, triggerGenerate));
    // Eigener Button statt triggerGenerate: leitet Begriffe NUR aus dem
    // aktuell im Feld darüber stehenden (ggf. von Hand überarbeiteten)
    // Zusammenfassungstext ab und überschreibt sie unconditional - anders
    // als triggerGenerate (regeneriert beide Felder aus dem rohen
    // Quellentext, füllt aber nur leere Felder) hält das die Begriffsliste
    // gezielt mit einer manuellen Textüberarbeitung synchron.
    const triggerExtractKeyTerms = () =>
      extractKeyTermsFromSummary(summaryInput, keyTermsInput, status, magicButtons);
    magicButtons.push(
      addMagicButton(keyTermsInput, triggerExtractKeyTerms, 'import.generateKeyTermsFromSummaryTitle')
    );
  }

  if (pendingDeletion) {
    [
      titleInput,
      ...authorFieldsWrapper.querySelectorAll('.author-input'),
      dateInput,
      urlInput,
      listenUrlInput,
      textInput,
      restrictedInput,
      summaryInput,
      keyTermsInput,
      relevanceInput,
    ].forEach((input) => {
      input.disabled = true;
    });
  }

  const actionsRow = document.createElement('div');
  actionsRow.className = 'edit-panel-actions';

  let submitBtn = null;

  if (pendingDeletion) {
    const noticeRow = document.createElement('div');
    noticeRow.className = 'source-row-top';

    const noticeText = document.createElement('span');
    noticeText.textContent = t('common.deletingStatus', { title: s.title });
    noticeRow.appendChild(noticeText);

    const undoBtn = document.createElement('button');
    undoBtn.type = 'button';
    undoBtn.className = 'link-button';
    undoBtn.textContent = t('common.undo');
    undoBtn.addEventListener('click', () => cancelDeletion(s.id));
    noticeRow.appendChild(undoBtn);

    form.appendChild(noticeRow);

    const bar = document.createElement('div');
    bar.className = 'undo-bar';
    const fill = document.createElement('div');
    fill.className = 'undo-bar-fill';
    bar.appendChild(fill);
    form.appendChild(bar);

    requestAnimationFrame(() => {
      fill.style.transitionDuration = `${UNDO_DURATION_MS}ms`;
      fill.style.width = '0%';
    });
  } else {
    const primaryActions = document.createElement('div');

    submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.textContent = t('import.updateButton');
    primaryActions.appendChild(submitBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'link-button';
    cancelBtn.textContent = t('common.cancel');
    cancelBtn.addEventListener('click', () => {
      activeEditId = null;
      renderSourceList(currentSourceList);
    });
    primaryActions.appendChild(cancelBtn);

    actionsRow.appendChild(primaryActions);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'icon-button delete-button';
    const deleteLabel = t('common.deleteSource');
    deleteBtn.title = deleteLabel;
    deleteBtn.setAttribute('aria-label', deleteLabel);
    deleteBtn.innerHTML = TRASH_ICON;
    deleteBtn.addEventListener('click', () => scheduleDeletion(s));
    actionsRow.appendChild(deleteBtn);
  }

  form.appendChild(actionsRow);
  form.appendChild(status);

  if (!pendingDeletion) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      submitBtn.disabled = true;
      submitBtn.textContent = t('import.updating');
      status.textContent = '';
      try {
        const res = await fetch(`/api/sources/${s.id}`, {
          method: 'PUT',
          headers: devUserHeaders(),
          body: JSON.stringify({
            title: titleInput.value,
            authors: getAuthorValues(),
            date: dateInput.value || null,
            url: urlInput.value || null,
            listen_url: listenUrlInput.value || null,
            text: textInput.value,
            restricted: restrictedInput.checked,
            summary: summaryInput.value,
            key_terms: keyTermsInput.value
              .split(',')
              .map((term) => term.trim())
              .filter((term) => term),
            relevance_score: parseInt(relevanceInput.value, 10),
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || t('import.updateFailed'));
        }
        // update_source registriert neu hinzugefügte Autor:innen synchron
        // (authors.register_author), daher kann das Profil direkt im
        // Anschluss per PUT gespeichert werden - identisch zum Anlegen-Formular.
        const newAuthorProfiles = getNewAuthorProfiles();
        for (const [name, profile] of Object.entries(newAuthorProfiles)) {
          await fetch(`/api/authors/${encodeURIComponent(name)}`, {
            method: 'PUT',
            headers: devUserHeaders(),
            body: JSON.stringify(profile),
          }).catch(() => {});
        }
        activeEditId = null;
        loadSources();
        loadAuthors();
      } catch (err) {
        status.textContent = t('common.errorPrefix') + err.message;
        submitBtn.disabled = false;
        submitBtn.textContent = t('import.updateButton');
      }
    });
  }

  li.appendChild(form);
  return li;
}

function addMagicButton(input, onClick, titleKey = 'import.generateSummaryTitle') {
  const wrapper = document.createElement('div');
  wrapper.className = 'field-with-magic';
  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'magic-button';
  const title = t(titleKey);
  btn.title = title;
  btn.setAttribute('aria-label', title);
  btn.innerHTML = MAGIC_ICON;
  btn.addEventListener('click', onClick);
  wrapper.appendChild(btn);
  return btn;
}

async function generateSummaryFields(sourceId, summaryInput, keyTermsInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingSummary');
  try {
    const res = await fetch(`/api/sources/${sourceId}/generate-summary`, {
      method: 'POST',
      headers: devUserHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateSummaryFailed'));
    }
    const data = await res.json();
    if (!summaryInput.value.trim()) summaryInput.value = data.summary;
    if (!keyTermsInput.value.trim()) keyTermsInput.value = data.key_terms.join(', ');
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

// Anders als generateSummaryFields (regeneriert Zusammenfassung UND Begriffe
// aus dem rohen Quellentext, füllt aber nur leere Felder): leitet Begriffe
// gezielt aus dem AKTUELLEN Inhalt von summaryInput ab (auch wenn er gerade
// von Hand überarbeitet und noch nicht gespeichert wurde) und überschreibt
// keyTermsInput unconditional - das ist der ganze Zweck dieses eigenen
// Buttons, siehe buildEditPanel.
async function extractKeyTermsFromSummary(summaryInput, keyTermsInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingKeyTerms');
  try {
    const res = await fetch('/api/sources/generate-key-terms-preview', {
      method: 'POST',
      headers: devUserHeaders(),
      body: JSON.stringify({ text: summaryInput.value }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t('import.generateKeyTermsFailed'));
    }
    const data = await res.json();
    keyTermsInput.value = data.key_terms.join(', ');
    statusEl.textContent = '';
  } catch (err) {
    statusEl.textContent = t('common.errorPrefix') + err.message;
  } finally {
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

function scheduleDeletion(s) {
  const timeoutId = setTimeout(async () => {
    pendingDeletions.delete(s.id);
    if (activeEditId === s.id) {
      activeEditId = null;
    }
    try {
      await fetch(`/api/sources/${s.id}`, { method: 'DELETE', headers: devUserHeaders() });
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
  const pattern = new RegExp(`(${keyTerms.map(escapeRegExp).join('|')})`, 'gi');
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
      const isTerm = keyTerms.some((term) => term.toLowerCase() === part.toLowerCase());
      if (isTerm) {
        // Eine Hervorhebung, die einer bereits erfassten Autor:in entspricht,
        // bleibt ein klickbarer Link zum Autor:innen-Profil (auffällig,
        // Akzentfarbe) - alle anderen Begriffe filtern beim Klick stattdessen
        // die Quellenübersicht nach diesem Schlagwort (filterByTerm), bewusst
        // OHNE Link-Optik (keine Akzentfarbe/Unterstreichung im Ruhezustand),
        // damit allgemeine Schlagworte nicht fälschlich wie Autor:innen-Links
        // aussehen - siehe .term-highlight-button in style.css.
        const matchingAuthor = allAuthors.find((a) => a.name.toLowerCase() === part.toLowerCase());
        if (matchingAuthor) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'term-link';
          const strong = document.createElement('strong');
          strong.textContent = part;
          btn.appendChild(strong);
          btn.addEventListener('click', () => filterByAuthor(matchingAuthor.name));
          frag.appendChild(btn);
        } else {
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
        }
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

  // Autor:innen-Häufigkeit VOR dem Expandieren ermitteln: eine eigene
  // Zwischenüberschrift (siehe renderSourceList) bekommt nur, wer mehr als
  // eine Quelle hat - nur für DIESE Autor:innen lohnt sich ein eigener
  // Eintrag pro Person. Hätten wir für JEDE Autor:in expandiert, würde eine
  // Quelle mit mehreren Autor:innen, die alle nur genau diese eine Quelle
  // haben, mehrfach optisch identisch untereinander erscheinen - ohne dass
  // irgendwo eine Überschrift den Grund dafür erklärt.
  const authorSourceCounts = new Map();
  sources.forEach((s) => {
    (s.authors || []).forEach((name) => {
      const key = normalizeAuthor(name);
      authorSourceCounts.set(key, (authorSourceCounts.get(key) || 0) + 1);
    });
  });

  // Autor-Modus: eine Quelle bekommt einen Eintrag PRO Autor:in MIT eigener
  // Überschrift, damit sie unter jeder solchen Sektion auffindbar ist. Hat
  // KEINE ihrer Autor:innen mehr als diese eine Quelle, bleibt es bei einem
  // einzigen Eintrag (einsortiert nach dem alphabetisch ersten Nachnamen).
  // Quellen ganz ohne Autor bleiben ebenfalls ein Eintrag.
  const expanded = [];
  sources.forEach((s) => {
    const sourceAuthors = s.authors || [];
    if (!sourceAuthors.length) {
      expanded.push({ ...s, __sortAuthor: null });
      return;
    }
    const headedAuthors = sourceAuthors.filter(
      (name) => (authorSourceCounts.get(normalizeAuthor(name)) || 0) > 1
    );
    if (headedAuthors.length) {
      headedAuthors.forEach((authorName) => {
        expanded.push({ ...s, __sortAuthor: authorName });
      });
    } else {
      const bySurname = [...sourceAuthors].sort((a, b) =>
        getSurname(a).toLowerCase().localeCompare(getSurname(b).toLowerCase())
      );
      expanded.push({ ...s, __sortAuthor: bySurname[0] });
    }
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
  prependAiIcon(summaryEl);
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

function renderSourceList(sources, options = {}) {
  currentSourceList = sources;
  const sorted = sortSources(sources);
  currentDisplayedSources = sorted;
  updateAlphabetJumpBar(sorted);
  updateImportedSourcesCount();
  const list = document.getElementById('source-list');
  list.innerHTML = '';
  let lastMonthYear = null;
  let lastAuthorKey = null;
  const authorCounts = new Map();
  if (currentSortMode === 'author') {
    sorted.forEach((s) => {
      if (!s.__sortAuthor) return;
      const key = normalizeAuthor(s.__sortAuthor);
      authorCounts.set(key, (authorCounts.get(key) || 0) + 1);
    });
  }
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

    let extraGapAfterAuthorGroup = false;
    if (currentSortMode === 'author' && !pendingDeletions.has(s.id)) {
      const key = s.__sortAuthor ? normalizeAuthor(s.__sortAuthor) : null;
      const isNewAuthor = key && key !== lastAuthorKey;
      if (isNewAuthor && (authorCounts.get(key) || 0) > 1) {
        list.appendChild(buildAuthorMarker(s.__sortAuthor));
      } else if (
        isNewAuthor &&
        lastAuthorKey &&
        (authorCounts.get(lastAuthorKey) || 0) > 1
      ) {
        // Dieser Autor hat nur eine Quelle (keine eigene Zwischenüberschrift),
        // steht aber direkt nach einem Autor MIT Zwischenüberschrift - ohne
        // zusätzlichen Abstand sähe es so aus, als gehöre die Quelle noch
        // zum vorherigen Autor.
        extraGapAfterAuthorGroup = true;
      }
      lastAuthorKey = key;
    }

    if (pendingDeletions.has(s.id)) {
      if (activeEditId === s.id) {
        appendTimelineRow(buildEditPanel(s, { pendingDeletion: true }));
      } else {
        appendTimelineRow(buildUndoRow(s));
      }
      return;
    }

    const li = document.createElement('li');
    li.className = 'source-row';
    if (s.url_reachable === false) {
      li.classList.add('source-row--unreachable');
    }
    if (extraGapAfterAuthorGroup) {
      li.classList.add('source-row--after-author-group');
    }
    li.dataset.sourceId = s.id;
    // Backlog #65: eindeutiges Sprungziel für die Alphabet-Leiste - anders
    // als data-source-id (mehrdeutig, wenn eine Quelle im Autor:innen-Modus
    // mehrfach expandiert erscheint) trifft der Index in der sortierten
    // Liste immer genau DIESE eine Zeile.
    li.dataset.rowIndex = String(rowIndex);

    const header = document.createElement('div');
    header.className = 'source-row-header';

    const citationUrl = s.listen_url || s.url;
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
          activeEditId = activeEditId === s.id ? null : s.id;
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
      editBtn.addEventListener('click', () => {
        activeEditId = activeEditId === s.id ? null : s.id;
        renderSourceList(currentSourceList, options);
      });
      actions.appendChild(editBtn);
    }

    header.appendChild(actions);
    li.appendChild(header);

    if (hasDetails && expandedSourceIds.has(s.id)) {
      li.appendChild(buildSourceDetails(s, citationUrl));
    }

    appendTimelineRow(li);

    if (activeEditId === s.id) {
      appendTimelineRow(buildEditPanel(s));
    }
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
  const res = await fetch('/api/authors', { headers: { 'X-Lang': getLang() } });
  const authorEntries = await res.json();
  const match = authorEntries.find((a) => normalizeAuthor(a.name) === normalizeAuthor(name));
  const ids = match ? match.source_ids : [];

  document.getElementById('source-filter-label').textContent = t(
    ids.length === 1 ? 'import.filteredByAuthor' : 'import.filteredByAuthorPlural'
  );
  document.getElementById('source-filter-name').textContent = match ? match.name : name;
  // Muss VOR renderSourceList() gesetzt werden - sortSources() liest den
  // Filter-Status, um die Autoren-Expansion in der gefilterten Ansicht zu
  // unterdrücken (siehe isFilterActive()).
  document.getElementById('source-filter-status').classList.remove('hidden');
  renderSourceList(allSources.filter((s) => ids.includes(s.id)));

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

function normalizeTerm(term) {
  return term.trim().toLowerCase();
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
function updateBrokenLinksButton() {
  const badge = document.getElementById('broken-links-count-badge');
  if (!badge) return;
  const count = allSources.filter((s) => s.url_reachable === false).length;
  badge.textContent = String(count);
  badge.classList.toggle('hidden', count === 0);
}

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
  document.getElementById('source-list').classList.toggle('timeline-mode', mode === 'date');
  renderSourceList(currentSourceList);
}

async function loadSources() {
  const res = await fetch('/api/sources', {
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
}

async function loadAuthors() {
  const res = await fetch('/api/authors', { headers: { 'X-Lang': getLang() } });
  allAuthors = await res.json();
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

// Plattform anhand der URL automatisch erkennen (siehe urlInput-Handler in
// buildRow weiter unten), statt sie manuell auswählen/eintippen zu müssen -
// das frühere Auswahl-Dropdown (Datalist) wurde deshalb wieder entfernt.
// Mastodon ist föderiert (beliebige Instanz-Domains) - "mastodon" im
// Hostnamen ist nur eine Best-effort-Heuristik, keine vollständige Erkennung.
const SOCIAL_PLATFORM_HOSTS = [
  { pattern: /(^|\.)linkedin\.com$/, platform: 'LinkedIn' },
  { pattern: /(^|\.)(twitter|x)\.com$/, platform: 'X (Twitter)' },
  { pattern: /(^|\.)instagram\.com$/, platform: 'Instagram' },
  { pattern: /(^|\.)(facebook|fb)\.com$/, platform: 'Facebook' },
  { pattern: /(^|\.)(youtube\.com|youtu\.be)$/, platform: 'YouTube' },
  { pattern: /mastodon/, platform: 'Mastodon' },
  { pattern: /(^|\.)bsky\.app$/, platform: 'Bluesky' },
  { pattern: /(^|\.)tiktok\.com$/, platform: 'TikTok' },
];

function detectSocialPlatform(url) {
  let hostname;
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return '';
  }
  const match = SOCIAL_PLATFORM_HOSTS.find(({ pattern }) => pattern.test(hostname));
  return match ? match.platform : '';
}

function buildSocialLinksField(initialLinks) {
  const wrapper = document.createElement('div');
  wrapper.className = 'social-links-field';

  const rows = document.createElement('div');
  rows.className = 'social-link-rows';
  wrapper.appendChild(rows);

  // Ohne Zeilen gibt es nichts zu entfernen - dann steht ein einzelner
  // "+"-Button für sich, um die erste Zeile anzulegen (analog zum
  // Mehrfach-Autoren-Feld bei Quellen, das dieselben Icons verwendet).
  const standaloneAddBtn = document.createElement('button');
  standaloneAddBtn.type = 'button';
  standaloneAddBtn.className = 'icon-button add-author-btn';
  standaloneAddBtn.innerHTML = PLUS_ICON;
  const addLabel = t('import.addSocialLink');
  standaloneAddBtn.title = addLabel;
  standaloneAddBtn.setAttribute('aria-label', addLabel);
  standaloneAddBtn.addEventListener('click', () => rows.appendChild(buildRow(null)));
  wrapper.appendChild(standaloneAddBtn);

  function refreshStandaloneButton() {
    standaloneAddBtn.classList.toggle('hidden', rows.children.length > 0);
  }

  function buildAddButton(insertNewRow) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button add-author-btn';
    btn.innerHTML = PLUS_ICON;
    btn.title = addLabel;
    btn.setAttribute('aria-label', addLabel);
    btn.addEventListener('click', () => insertNewRow(buildRow(null)));
    return btn;
  }

  function buildRemoveButton(row) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-button remove-author-btn';
    btn.innerHTML = REMOVE_ICON;
    const removeLabel = t('import.removeSocialLink');
    btn.title = removeLabel;
    btn.setAttribute('aria-label', removeLabel);
    btn.addEventListener('click', () => {
      row.remove();
      refreshStandaloneButton();
    });
    return btn;
  }

  function buildRow(link) {
    const row = document.createElement('div');
    row.className = 'social-link-row';

    const platformInput = document.createElement('input');
    platformInput.type = 'text';
    platformInput.className = 'social-platform-input';
    // Fix: kein list="..."-Dropdown mehr - die Plattform wird seit
    // detectSocialPlatform() automatisch anhand der URL erkannt (siehe
    // urlInput-Handler unten), eine manuelle Auswahl aus Vorschlägen ist
    // damit für die abgedeckten Plattformen redundant. Feld bleibt trotzdem
    // ein normales Textfeld für die manuelle Korrektur/Eingabe bei nicht
    // erkannten URLs.
    platformInput.setAttribute('autocomplete', 'off');
    platformInput.placeholder = t('import.socialPlatformPlaceholder');
    platformInput.value = (link && link.platform) || '';

    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.className = 'social-url-input';
    urlInput.placeholder = t('import.socialUrlPlaceholder');
    urlInput.value = (link && link.url) || '';
    urlInput.addEventListener('input', () => {
      // Nie ein bereits gefülltes Plattform-Feld überschreiben (z.B. von
      // Hand korrigierte Angabe) - gleiche Konvention wie bei KI-generierten
      // Feldern im Rest des Formulars.
      if (platformInput.value.trim()) return;
      const detected = detectSocialPlatform(urlInput.value.trim());
      if (detected) platformInput.value = detected;
    });

    row.appendChild(platformInput);
    row.appendChild(urlInput);
    row.appendChild(buildAddButton((newRow) => row.insertAdjacentElement('afterend', newRow)));
    row.appendChild(buildRemoveButton(row));
    return row;
  }

  (initialLinks && initialLinks.length ? initialLinks : []).forEach((link) => {
    rows.appendChild(buildRow(link));
  });
  refreshStandaloneButton();

  function getSocialLinkValues() {
    return [...rows.querySelectorAll('.social-link-row')]
      .map((row) => ({
        platform: row.querySelector('.social-platform-input').value.trim(),
        url: row.querySelector('.social-url-input').value.trim(),
      }))
      .filter((link) => link.platform && link.url);
  }

  return { wrapper, getSocialLinkValues };
}

async function generateAuthorBio(name, bioInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingBio');
  try {
    const res = await fetch(`/api/authors/${encodeURIComponent(name)}/generate-bio`, {
      method: 'POST',
      headers: devUserHeaders(),
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

// Für Co-Autor:innen, die gerade erst im Formular eingetragen wurden (siehe
// buildNewAuthorProfilePanel) - anders als generateAuthorBio gibt es noch
// keine registrierte Person mit indizierten Quellen, deshalb der eigene
// Endpunkt mit Name+aktuellem Quellentext statt Name-in-URL.
async function generateAuthorBioPreview(name, text, bioInput, statusEl, buttons) {
  buttons.forEach((b) => {
    b.disabled = true;
  });
  statusEl.textContent = t('import.generatingBio');
  try {
    const res = await fetch('/api/authors/generate-bio-preview', {
      method: 'POST',
      headers: devUserHeaders(),
      body: JSON.stringify({ name, text }),
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

  if (a.photo_url) {
    const img = document.createElement('img');
    img.src = a.photo_url;
    img.alt = a.name;
    img.className = 'author-photo';
    photoCol.appendChild(img);
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
          headers: devUserHeaders(),
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
        headers: devUserHeaders(),
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
      headers: devUserHeaders(),
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
        headers: devUserHeaders(),
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
    // Fix: das Anlege-Formular (#import-bereich) steht im Markup VOR der
    // Quelltyp-Leiste/Quellenliste - fällt es nach dem Import weg, rutscht
    // der bisherige Scroll-Inhalt ohne Gegenmaßnahme einfach nach oben
    // nach, sodass man plötzlich mitten in der Liste statt an den
    // "Neue Quelle anlegen"-Buttons landet. Zurück nach oben scrollen, damit
    // direkt die nächste Quelle angelegt werden kann.
    window.scrollTo({ top: 0, behavior: 'smooth' });
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
updateSourceManagementVisibility();
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
  activeEditId = deepLinkEditId;
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
  ensureSourceVisible(deepLinkSourceId);
  renderSourceList(currentSourceList);
  requestAnimationFrame(() => {
    const row = document.querySelector(`#source-list [data-source-id="${deepLinkSourceId}"]`);
    row?.scrollIntoView({ block: 'center' });
    row?.classList.add('source-highlight-flash');
    row?.addEventListener('animationend', () => row.classList.remove('source-highlight-flash'), { once: true });
  });
}

// Deep-Link aus der Konversationsansicht (Autor:innen-Links an Zitaten):
// /import.html?author=<name> filtert direkt auf die Texte dieser Person und
// zeigt ihr Profil (inkl. Vita) im Info-Panel an.
const deepLinkAuthor = new URLSearchParams(window.location.search).get('author');
if (deepLinkAuthor) {
  await filterByAuthor(deepLinkAuthor);
}
