// Fix: Layout-Sprung beim Laden mit bestehender Konversation. Die Klasse
// "chat-started" (schaltet vom zentrierten Startzustand auf die volle
// Chat-Ansicht mit Sidebar/Nachrichtenverlauf um, siehe style.css) wird
// von restoreConversationHistory() in question.js gesetzt - das läuft aber
// erst NACH den asynchronen await initI18n()/initAuth()-Aufrufen als
// deferred Module am Ende von <body>. Bis dahin ist die Seite schon
// gezeichnet (zentrierter, schmaler Startzustand), und der Sprung auf die
// volle Breite passiert sichtbar nachträglich (gemessen: ~260px).
// Deshalb hier dieselbe Prüfung bereits synchron/blockierend, direkt nach
// dem öffnenden <body>-Tag platziert (nicht im <head> - document.body
// existiert dort noch nicht). sessionStorage-Zugriff ist synchron, daher
// ohne Verzögerung möglich. CONVERSATION_STORAGE_KEY 1:1 identisch zu
// question.js - beide bewusst getrennt gehalten (gleiche Begründung wie
// bei speech-support-check.js: diese Datei muss synchron laufen,
// question.js darf es nicht).
try {
  const raw = sessionStorage.getItem('conversationHistory');
  const history = raw ? JSON.parse(raw) : [];
  if (Array.isArray(history) && history.length > 0) {
    document.body.classList.add('chat-started');
  }
} catch (err) {
  // sessionStorage evtl. deaktiviert (privates Fenster u.ä.) - dann bleibt
  // der zentrierte Startzustand wie bisher, question.js übernimmt normal.
}
