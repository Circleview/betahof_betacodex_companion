// Import-Jobs der Quellenseite: Jobs-Ring, Jobs-Liste, Abfrage/Polling.
// Aus import.js herausgezogen (Idee 313ad93d, reiner Code-Umzug).
import { t } from '/i18n.js';
import { jsonHeaders } from '/source-edit.js';
import { loadSources } from '/import-list.js';
import { hasPflegerRole } from '/import-state.js';
import { pollWebAllowlistStatus } from '/import-web.js';

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

export async function fetchImportJobs() {
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

export function startJobsPolling() {
  if (jobsPollTimer) return;
  pollBackgroundImportStatus();
  // Erstes und bisher einziges Polling im Projekt (siehe README/Kommentar
  // hier bewusst) - kein Vorbild für generelle Live-Aktualisierungen,
  // sondern gezielt für den Import-Warteschlangen-Status (Audio/PDF-
  // Verarbeitung + Website-Indizierung).
  jobsPollTimer = setInterval(pollBackgroundImportStatus, 3000);
}

export function stopJobsPolling() {
  if (jobsPollTimer) {
    clearInterval(jobsPollTimer);
    jobsPollTimer = null;
  }
  document.getElementById('typ-jobs').classList.add('hidden');
  document.getElementById('jobs-popover').classList.add('hidden');
  document.getElementById('jobs-bar').classList.add('hidden');
}
