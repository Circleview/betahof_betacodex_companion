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
