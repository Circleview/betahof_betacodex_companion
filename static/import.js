const importBereich = document.getElementById('import-bereich');
const urlPopover = document.getElementById('url-popover');

function showForm() {
  importBereich.classList.remove('hidden');
  urlPopover.classList.add('hidden');
}

function fillForm({ title = '', author = '', date = '', url = '', text = '' }) {
  document.getElementById('title').value = title;
  document.getElementById('author').value = author;
  document.getElementById('date').value = date;
  document.getElementById('url').value = url;
  document.getElementById('text').value = text;
}

document.getElementById('typ-text').addEventListener('click', () => {
  fillForm({});
  showForm();
});

document.getElementById('typ-url').addEventListener('click', () => {
  importBereich.classList.add('hidden');
  urlPopover.classList.toggle('hidden');
  document.getElementById('popover-status').textContent = '';
});

document.getElementById('popover-load').addEventListener('click', async () => {
  const url = document.getElementById('popover-url').value.trim();
  const status = document.getElementById('popover-status');
  if (!url) {
    status.textContent = 'Bitte eine URL eintragen.';
    return;
  }
  status.textContent = 'Lade und extrahiere...';
  try {
    const res = await fetch('/api/extract-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      throw new Error('Fehler bei der Extraktion');
    }
    const data = await res.json();
    if (!data.extracted) {
      status.textContent = 'Automatische Extraktion fehlgeschlagen. Bitte Text manuell einfügen.';
      fillForm({ url });
      showForm();
      return;
    }
    fillForm({ title: data.title, author: data.author, date: data.date, url, text: data.text });
    showForm();
  } catch (err) {
    status.textContent = 'Fehler: ' + err.message;
  }
});

async function loadSources() {
  const res = await fetch('/api/sources');
  const sources = await res.json();
  const list = document.getElementById('source-list');
  list.innerHTML = '';
  sources.forEach((s) => {
    const li = document.createElement('li');
    li.textContent = `${s.title} – ${s.author || 'unbekannt'} (${s.date || 'ohne Datum'}) [${s.chunk_count} Chunks]`;
    list.appendChild(li);
  });
}

document.getElementById('source-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    title: document.getElementById('title').value,
    author: document.getElementById('author').value || null,
    date: document.getElementById('date').value || null,
    url: document.getElementById('url').value || null,
    text: document.getElementById('text').value,
  };
  const status = document.getElementById('import-status');
  status.textContent = 'Importiere...';
  try {
    const res = await fetch('/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Fehler beim Import');
    }
    const data = await res.json();
    status.textContent = `Importiert: "${data.title}" (${data.chunk_count} Chunks)`;
    document.getElementById('source-form').reset();
    importBereich.classList.add('hidden');
    loadSources();
  } catch (err) {
    status.textContent = 'Fehler: ' + err.message;
  }
});

loadSources();
