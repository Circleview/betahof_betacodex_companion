// Nutzerwunsch (2026-08-30): Konversations-Übergabe vom Embed-Widget (siehe
// embed.html: #embed-expand-button) sowie vom bestehenden "Quelle
// ansehen/bearbeiten"-Link (question.js: appendViewSourceLink/
// appendEditSourceLink) in einen neu geöffneten Tab - sessionStorage ist
// pro Tab und zusätzlich pro Top-Level-Browsing-Context partitioniert, ein
// neuer Tab bekäme also so oder so leeren Storage, selbst same-origin
// (siehe app/conversation_handoff.py für die Server-Gegenstelle). Eigenes,
// von question.js UND import.js gemeinsam genutztes Modul, damit der
// sessionStorage-Schlüssel nur an einer Stelle definiert ist.
export const CONVERSATION_STORAGE_KEY = 'conversationHistory';

// Holt ein kurzlebiges Einmal-Token für die übergebene Konversation - null
// bei leerer Historie oder fehlgeschlagenem Request (Aufrufer entscheidet
// selbst über den Fallback, z.B. trotzdem ohne Token navigieren).
export async function createConversationHandoffToken(history) {
  if (!history || history.length === 0) return null;
  try {
    const res = await fetch('/api/conversation-handoff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ history }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.token || null;
  } catch (err) {
    return null;
  }
}

// Liest ein ?handoff=-Token aus der aktuellen URL und entfernt NUR dieses
// eine Token wieder aus der Adresszeile (Muster wie auth.js beim ?auth=-
// Parameter) - andere, gleichzeitig vorhandene Parameter (z.B. ?edit=<id>
// beim "Quelle bearbeiten"-Link, siehe question.js:appendEditSourceLink)
// bleiben dabei erhalten. Bug (2026-08-31, per Screenshot gemeldet): eine
// frühere Fassung hat hier pauschal die gesamte Query-Zeile
// (window.location.pathname ohne Suffix) ersetzt - dadurch verschwand z.B.
// ?edit=<id> beim "Quelle bearbeiten"-Klick aus der Konversationsansicht,
// noch bevor import.js es weiter unten lesen konnte (deepLinkEditId blieb
// dadurch immer leer). Liefert null, wenn kein Token vorhanden war oder der
// Abruf fehlschlägt (z.B. abgelaufen/bereits verwendet).
export async function consumeConversationHandoffToken() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('handoff');
  if (!token) return null;
  params.delete('handoff');
  const query = params.toString();
  history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : ''));
  try {
    const res = await fetch(`/api/conversation-handoff/${encodeURIComponent(token)}`);
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data.history) ? data.history : null;
  } catch (err) {
    return null;
  }
}
