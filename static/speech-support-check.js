// Backlog #49: synchrone Vorab-Prüfung, ob der Browser Spracheingabe/-ausgabe
// unterstützt - bewusst als klassisches, blockierendes <script> (kein
// type="module", kein defer/async) direkt im <head> eingebunden, NICHT als
// Teil von speech.js/question.js (die erst als deferred Module am Ende des
// <body> laufen, siehe dortige <script>-Tags). Dadurch steht die Klasse
// html.speech-supported schon fest, BEVOR der Parser das Mikrofon-Icon
// überhaupt erreicht/rendert - style.css kann so von Anfang an den
// richtigen End-Zustand zeigen. Ohne das: entweder ein sichtbarer
// Layout-Sprung, sobald question.js später den Button einblendet, oder
// (bei permanent reserviertem Platz) eine dauerhafte Lücke auf Browsern
// ohne Unterstützung. Prüfung 1:1 identisch zu speech.js:getRecognitionCtor
// + der supported-Berechnung - beide Stellen bewusst getrennt, da diese
// Datei synchron/blockierend sein muss und speech.js es nicht sein darf
// (würde sonst den gesamten Seitenaufbau verzögern).
if ((window.SpeechRecognition || window.webkitSpeechRecognition) && window.speechSynthesis) {
  document.documentElement.classList.add('speech-supported');
}
