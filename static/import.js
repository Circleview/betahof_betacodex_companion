import { initI18n, t, getLang } from '/i18n.js';
import { initAuth, onAuthChange } from '/auth.js';
import { CONVERSATION_STORAGE_KEY, CONVERSATION_ID_STORAGE_KEY, consumeConversationHandoffToken } from '/conversation-handoff.js';
import { buildMarkupToolbar, jsonHeaders, buildAuthorFields } from '/source-edit.js';
import {
  allSources,
  clearSourceFilter,
  closeSearchBar,
  currentSourceList,
  ensureSourceVisible,
  filterByAuthor,
  filterByBrokenLinks,
  filterByTerm,
  fullTextReady,
  isFilterActive,
  loadSources,
  renderSourceList,
  searchSources,
  setSortMode,
  sortSources,
} from '/import-list.js';
import { loadAuthors } from '/import-authors.js';
import { hasPflegerRole, state } from '/import-state.js';
import { fetchImportJobs, startJobsPolling, stopJobsPolling } from '/import-jobs.js';
import { initWebAllowlist, loadSourceSuggestions, loadWebAllowlist } from '/import-web.js';
import { initTermMerge } from '/import-terms.js';

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

const webAllowlistBereich = document.getElementById('web-allowlist-bereich');

const sourceSuggestionsBereich = document.getElementById('source-suggestions-bereich');

let pendingUploadId = null;
let pendingUploadType = null; // 'pdf' | 'audio' (EPUB: null, kein Staging)
// Idee ff895248: Token der in /api/extract-url vorgemerkten Web-Bilder; gilt nur für die URL der Vorschau.
let pendingImageToken = null;

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
  pendingImageToken = null;
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
  pendingImageToken = null;
  fillForm({});
  showForm();
});

document.getElementById('import-cancel-button').addEventListener('click', hideForm);

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
  state.searchBarOpen = !state.searchBarOpen;
  document.getElementById('search-bar').classList.toggle('hidden', !state.searchBarOpen);
  renderSourceList(currentSourceList);
  if (state.searchBarOpen) {
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

initTermMerge();

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
    pendingImageToken = null;
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
    pendingImageToken = data.image_token || null;
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

// URL im Formular geändert: die vorgemerkten Bilder gehören zur alten URL.
document.getElementById('url').addEventListener('input', () => {
  pendingImageToken = null;
});

const AUDIO_UPLOAD_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.mp4', '.mpeg', '.mpga', '.webm'];
const AUDIO_UPLOAD_MAX_BYTES = 25 * 1024 * 1024;
// Spiegel von REQUEST_BODY_LIMITS in app/main.py - vorab prüfen, statt
// erst nach dem Hochladen abgelehnt zu werden.
const UPLOAD_MAX_BYTES = 200 * 1024 * 1024;

function isAudioUploadFile(file) {
  if (file.type && file.type.startsWith('audio/')) return true;
  const name = file.name.toLowerCase();
  return AUDIO_UPLOAD_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function isEpubUploadFile(file) {
  return file.type === 'application/epub+zip' || file.name.toLowerCase().endsWith('.epub');
}

document.getElementById('popover-upload').addEventListener('click', async () => {
  const fileInput = document.getElementById('popover-file');
  const status = document.getElementById('upload-status');
  const file = fileInput.files[0];
  if (!file) {
    status.textContent = t('import.pleaseChooseFile');
    return;
  }
  if (file.size > UPLOAD_MAX_BYTES) {
    status.textContent = t('import.uploadTooLarge');
    return;
  }
  const isEpub = isEpubUploadFile(file);
  const isAudio = !isEpub && isAudioUploadFile(file);
  status.textContent = isAudio && file.size > AUDIO_UPLOAD_MAX_BYTES
    ? t('import.uploadingExtractingLargeAudio')
    : t('import.uploadingExtracting');
  try {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(isEpub ? '/api/extract-epub-upload' : isAudio ? '/api/extract-audio-upload' : '/api/extract-pdf-upload', {
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
    pendingUploadType = isEpub ? null : isAudio ? 'audio' : 'pdf';
    pendingImageToken = null;
    if (!data.extracted && isEpub) {
      pendingUploadId = null;
      status.textContent = t('import.epubNoText');
      return;
    }
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
    // Bücher (EPUB) sind urheberrechtlich geschützt: restricted vorbelegt.
    fillForm({ title: data.title, authors: data.authors, date: data.date, text: data.text, restricted: isEpub });
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

initWebAllowlist({ openUrlPopoverWithUrl });

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
    image_token: pendingImageToken,
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
    pendingImageToken = null;
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
const handoff = await consumeConversationHandoffToken();
if (handoff && handoff.history.length) {
  try {
    sessionStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(handoff.history));
    // Dieselbe Chat-ID mitnehmen, sonst zerfiele das Gespräch im Fragen-Log.
    if (handoff.conversationId) sessionStorage.setItem(CONVERSATION_ID_STORAGE_KEY, handoff.conversationId);
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
  state.activeEditId = deepLinkEditId;
  // Fix (2026-09-22): im Autor:innen-Modus reicht die Quellen-ID allein
  // nicht mehr (siehe isActiveEditRow) - welche der ggf. mehreren Zeilen
  // (eine pro Autor:in) gemeint ist, wird hier über dieselbe Sortierung wie
  // die eigentliche Liste bestimmt: die im aktuellen Sortiermodus ZUERST
  // gerenderte Zeile dieser Quelle.
  const deepLinkRow = sortSources(allSources).find((s) => s.id === deepLinkEditId);
  state.activeEditAuthorKey = deepLinkRow ? deepLinkRow.__sortAuthor || null : null;
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
