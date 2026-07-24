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
    loadSources();
  } catch (err) {
    status.textContent = 'Fehler: ' + err.message;
  }
});

loadSources();
