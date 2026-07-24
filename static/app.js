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

document.getElementById('question-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = document.getElementById('question').value;
  const answerDiv = document.getElementById('answer');
  const sourcesList = document.getElementById('answer-sources');
  answerDiv.textContent = 'Suche Antwort...';
  sourcesList.innerHTML = '';
  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k: 5 }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Fehler bei der Anfrage');
    }
    const data = await res.json();
    answerDiv.textContent = data.answer;
    data.sources.forEach((s) => {
      const li = document.createElement('li');
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `${s.title} – ${s.author || 'unbekannt'} (${s.date || 'ohne Datum'})`;
      details.appendChild(summary);
      const p = document.createElement('p');
      p.textContent = s.text;
      details.appendChild(p);
      if (s.url) {
        const a = document.createElement('a');
        a.href = s.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = 'Quelle öffnen';
        details.appendChild(a);
      }
      li.appendChild(details);
      sourcesList.appendChild(li);
    });
  } catch (err) {
    answerDiv.textContent = 'Fehler: ' + err.message;
  }
});

loadSources();
