// Reine Gruppierungslogik des Fragen-Logs (ohne DOM, damit per node --test
// prüfbar - siehe tests/question-log-blocks.test.mjs). question-log.js
// rendert nur noch, was hier berechnet wird.
//
// Ein Block ist ein ganzer Chat: Schlüssel conversation_id, Einträge ohne ID
// (Altbestand, Kreativ, MCP, Feedback ohne ID) sind Einzelblöcke. Blockstart
// = frühester Zeitstempel des GANZEN Chats (ungefiltert), damit parallele
// Chats sich nie mischen und Filter die Reihenfolge nicht verschieben.

export const shortId = (cid) => cid.slice(0, 4);

// Stabile Blockfarbe aus der ID: 12 Farbtöne in 30°-Schritten.
export function conversationColor(cid) {
  let hash = 0;
  for (const ch of cid) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return `hsl(${(hash % 12) * 30} 65% 45%)`;
}

// entries: Liste aus /api/question-log; activeTypes: Set aktiver event_types;
// activeCid: nur diesen Chat zeigen (oder null).
// Ergebnis: Blöcke absteigend nach Start, je { key, conversationId, color,
// start, items: [{ entry, k, n }] } mit Einträgen aufsteigend; k/n zählt über
// den ganzen Chat, leere Blöcke (nach Typ-Filter) fehlen.
export function buildBlocks(entries, activeTypes, activeCid) {
  const groups = new Map();
  entries.forEach((entry, index) => {
    const cid = entry.conversation_id || null;
    const key = cid || `entry:${entry.id}`;
    if (!groups.has(key)) groups.set(key, { key, conversationId: cid, all: [] });
    groups.get(key).all.push({ entry, index, time: Date.parse(entry.timestamp) });
  });
  const blocks = [];
  groups.forEach((g) => {
    if (activeCid && g.conversationId !== activeCid) return;
    g.all.sort((a, b) => a.time - b.time || b.index - a.index);
    const n = g.all.length;
    const items = g.all
      .map(({ entry }, i) => ({ entry, k: i + 1, n }))
      .filter(({ entry }) => entry.event_types.some((et) => activeTypes.has(et)));
    if (!items.length) return;
    blocks.push({
      key: g.key,
      conversationId: g.conversationId,
      color: g.conversationId ? conversationColor(g.conversationId) : null,
      start: g.all[0].time,
      items,
    });
  });
  return blocks.sort((a, b) => b.start - a.start);
}

// Paging zählt Blöcke, nie Einträge: kein Block wird zerschnitten.
export const pageBlocks = (blocks, visibleCount) => blocks.slice(0, visibleCount);
