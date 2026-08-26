// Gemeinsamer NDJSON-Zeilen-Leser für streamende POST-Endpoints (/api/ask,
// /api/creative) - liest den Response-Body inkrementell, ruft
// handlers[event.type](event) für jede ankommende Zeile auf (ausgenommen
// "error", das wirft, und "done", das den Stream beendet und dessen Event
// zurückgegeben wird). Wirft, falls der Stream ohne "done"-Event endet
// (z.B. abgebrochene Verbindung) - dieselbe Konvention wie zuvor direkt in
// question.js:readAskStream.
export async function readNdjsonStream(
  response,
  handlers,
  noDoneEventMessage = 'Stream ended without a done event.'
) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let doneEvent = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === 'error') {
        throw new Error(event.message);
      } else if (event.type === 'done') {
        doneEvent = event;
      } else {
        handlers[event.type]?.(event);
      }
    }
  }

  if (!doneEvent) throw new Error(noDoneEventMessage);
  return doneEvent;
}
