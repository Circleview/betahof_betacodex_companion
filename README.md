# BetaCodex Companion

Ein KI-Wissensassistent, der Fragen zum BetaCodex ausschließlich auf Basis
kuratierter, geprüfter Quellen beantwortet – mit lückenloser Quellenangabe
bis zur Originalstelle.

Live unter **https://companion.betahof.com**.

---

## Was ist der BetaCodex?

Der BetaCodex ist eine Sammlung von zwölf einander ergänzenden, nicht
einzeln herausgreifbaren Prinzipien für eine zeitgemäße
Unternehmensführung – ein Gegenentwurf zur klassischen, tayloristischen
Managementpraxis. Er entstand 2008 aus der Forschungsinitiative *Beyond
Budgeting Round Table* (BBRT) und beruht auf der Erkenntnis, dass
Unternehmen soziologische Systeme sind, keine mechanischen Strukturen. Zu
den Prinzipien zählen unter anderem Teamautonomie, Föderalisierung,
Leadership als Selbstorganisation, Transparenz, Marktorientierung und
bedingtes Arbeitseinkommen – sie wirken nur im Zusammenspiel, nicht als
einzeln umsetzbare Rezepte. Das Wissen steht seit 2008 unter einer
Open-Source-Lizenz frei zur Verfügung; mehr dazu unter
[betacodex.org](https://betacodex.org).

---

## Hintergrund

BetaCodex-Wissen ist umfangreich und über viele Quellen verteilt –
Blogposts, Bücher, Vorträge, Podcasts. Wer sich hineinarbeiten will, sucht
sich bisher mühsam durch verschiedene Kanäle, statt eine Frage einfach
stellen zu können. Der BetaCodex Companion schließt diese Lücke: eine
Chat-Oberfläche im Stil von Google NotebookLM, die ausschließlich aus
einem kuratierten, geprüften Quellenbestand antwortet – nie aus
allgemeinem Internet- oder Modellwissen.

Das ist bewusst kein allgemeiner Chatbot: Vieles, was im Internet zu
Management und Organisation kursiert, ist mit dem Erkenntnisstand des
BetaCodex-Netzwerks nicht vereinbar. Genau diese Vermischung soll das
System verhindern – findet sich in den Quellen keine Antwort, sagt der
Assistent das offen, statt zu spekulieren.

---

## Was der Assistent kann

### Fragen & Antworten

- Chat-Oberfläche, Antworten erscheinen als Stream Wort für Wort statt
  nach langem Warten auf einmal.
- Jede Aussage trägt einen klickbaren Verweis (`[1]`, `[2]` …) auf die
  tatsächlich verwendete Textstelle – ein Klick springt zur passierten
  Original-Quelle und hebt die exakte Textpassage hervor, bei
  Video/Audio-Quellen inklusive Zeitstempel.
- Eine "Verwendete Quellen"-Sidebar baut sich über die gesamte
  Konversation auf, nicht nur pro Antwort.
- Antwortet in der Sprache, in der gefragt wurde – Oberfläche und
  Antworten gibt es auf Deutsch und Englisch, unabhängig voneinander.
- Spam-/Bot-Schutz (Rate-Limiting + Cloudflare Turnstile), ohne dass
  anonymes Fragenstellen dafür ein Login bräuchte.

### Sprachein- und -ausgabe

- Fragen lassen sich per Mikrofon diktieren, mit Live-Transkript: der
  erkannte Text erscheint schon während des Sprechens im Eingabefeld,
  nicht erst danach.
- Die Antwort wird bei einer per Mikrofon gestellten Frage automatisch
  vorgelesen (Google-Cloud-Text-to-Speech-Stimme) – wie in einem echten
  Gespräch. Vorlesetempo ist frei wählbar (1x–2x), die Stimme bleibt dabei
  unverändert in der Tonhöhe.

### Quellen pflegen (Quellen-Pfleger:innen)

- Import per Copy/Paste, URL/Blogpost, PDF-Upload, YouTube-Link oder
  Audio-/Podcast-Datei (automatische Transkription) – für jeden Typ gibt
  es einen manuellen Fallback, falls die automatische Extraktion
  scheitert.
- Größere Verarbeitungsschritte (z. B. Audio-Transkription) laufen im
  Hintergrund; ein Status-Icon zeigt den Fortschritt, mehrere Importe
  lassen sich parallel anstoßen.
- Volltextsuche über den gesamten Quellenbestand, Autor:innen-Verzeichnis
  mit Profilen (Foto, Vita, Website, Social Links, zweisprachig gepflegt).
- KI-gestützte Zusammenfassung + Begriffs-Querverweise beim Import,
  jederzeit nachträglich auslösbar.
- Bearbeiten inline in der Quellenliste; Löschen ist ein Papierkorb mit
  Rückholfrist statt eines endgültigen Vorgangs.
- Relevanz-Score pro Quelle (1–10) für die spätere Sortierung/Gewichtung.

### Nachvollziehbarkeit & Rechte

- Echtes, einladungsbasiertes Login-System (Magic Link, kein Passwort)
  mit abgestuften Rollen: anonymes Fragenstellen bleibt für alle offen,
  Quellenpflege ist `quellen_pfleger` vorbehalten, `user_admin` verwaltet
  Einladungen, `system_admin` darf alles.
- Jede Änderung an einer Quelle landet diff-basiert in einem
  Änderungs-Log (mit Rückgängig-Funktion) – sichtbar für alle
  Quellen-Pfleger:innen, nicht nur für die handelnde Person.
- Anonymisierte Erstfragen neuer Konversationen werden separat
  protokolliert und helfen dabei, Lücken im Quellenbestand zu erkennen.

### Einbettbar

Die Konversationsansicht lässt sich als schlankes Widget in fremde
Webseiten einbetten (`/embed.html`, eigene, striktere
Content-Security-Policy).

---

## Wie es funktioniert (RAG)

BetaCodex Companion ist ein **RAG-System** (Retrieval-Augmented
Generation) – ein Chatbot, der Fragen ausschließlich auf Basis der
eigenen, kuratierten Quellen beantwortet, nicht aus dem allgemeinen Wissen
des Sprachmodells. Jede Antwort ist mit Belegstellen aus den echten
Quellen zitiert. Das ist der zentrale Unterschied zu einem gewöhnlichen
Chatbot: Statt "irgendwas Plausibles" zu generieren, muss das Modell seine
Antwort auf konkrete, nachprüfbare Textstellen stützen.

Es gibt zwei getrennte Abläufe: Import (Quellen ins System bringen) und
Fragen stellen (den Chat nutzen).

**Phase A – Import**
1. **Text holen** – URL, PDF, YouTube-Video oder Audiodatei werden
   angegeben; `app/extraction.py` holt sich den reinen Text daraus
   (Webseiten-Scraping, PDF-Textextraktion, YouTube-Transkript, oder bei
   Audio: Transkription über OpenAI).
2. **Zerlegen (Chunking)** – Der Text wird in kleine, satzgrenzen-bewusste
   Abschnitte von je ~900 Zeichen zerlegt (`app/chunking.py`), mit etwas
   Überlappung zwischen den Stücken, damit an den Schnittstellen kein Sinn
   verloren geht. Jeder Chunk erhält zusätzlich **Metadaten zur Herkunft**
   (Quell-ID, Titel, Autor, Datum, URL, ggf. Zeitstempel/Seitenzahl).
3. **Embedding erzeugen** – Für jeden Chunk wird ein Embedding berechnet
   (siehe Kasten unten) und zusammen mit dem Original-Text in **ChromaDB**
   gespeichert, einer spezialisierten Datenbank für genau solche Vektoren.

**Phase B – Frage stellen**
1. Eine Frage wird gestellt, z. B. "Was ist ein Flip?".
2. Die Frage wird **genauso** in ein Embedding umgewandelt wie vorher die
   Chunks.
3. ChromaDB durchsucht alle gespeicherten Chunk-Embeddings und findet die,
   die dem Frage-Embedding am ähnlichsten sind – das ist die eigentliche
   Suche (Retrieval).
4. Die relevantesten Chunks (roher Text, keine Zusammenfassung) werden
   zusammen mit der Frage an das Sprachmodell geschickt, mit der
   Anweisung: Nur auf Basis dieser Textstellen antworten und sie zitieren.
5. Das Modell generiert die Antwort, die als Stream Wort für Wort im Chat
   erscheint, mit `[1]`, `[2]` usw. als klickbare Verweise auf die
   tatsächlich verwendeten Chunks.

Der Quellennachweis ist keine Zusatzfunktion, sondern fällt aus dieser
Architektur zwangsläufig ab – vorausgesetzt, die Metadaten werden von
Anfang an konsequent mitgeführt.

Wichtig: Der KI-Anteil steckt an zwei unterschiedlichen Stellen – dem
lokalen Embedding-Modell (Suche) und der Anthropic-API (Textgenerierung).
Das sind zwei separate Systeme mit unterschiedlichen Aufgaben.

### Was ist ein Embedding?

Ein Embedding ist eine Liste von Zahlen (bei uns 768 Stück), die die
**Bedeutung** eines Textstücks als Punkt in einem hochdimensionalen Raum
darstellt. Die Kernidee: Texte mit ähnlicher Bedeutung landen nah
beieinander, egal wie unterschiedlich die Formulierung ist.

Ein einfaches Bild: Stell dir eine Landkarte vor, auf der nicht
geografische Nähe, sondern *inhaltliche* Nähe die Position bestimmt.
"Führung ohne Weisungsbefugnis" und "Leadership without formal authority"
würden auf dieser Karte fast am selben Ort landen – trotz komplett
unterschiedlicher Wörter und sogar unterschiedlicher Sprache. "Führung"
und "Kartoffelsalat" wären hingegen weit auseinander.

Konkret bei uns:
- Das Modell heißt `intfloat/multilingual-e5-base` und läuft **lokal** auf
  dem Server (kein API-Call, keine Kosten pro Anfrage) – trainiert auf
  vielen Sprachen gleichzeitig, deshalb funktioniert die Suche auch über
  Sprachgrenzen hinweg (deutsche Quelle, englische Frage).
- "Ähnlich" wird mathematisch über den **Winkel zwischen zwei Vektoren**
  gemessen (Kosinus-Ähnlichkeit) – je kleiner der Winkel, desto ähnlicher
  die Bedeutung.
- Das Embedding-Modell "versteht" nichts im menschlichen Sinn – es hat
  beim Training gelernt, welche Wortkombinationen in ähnlichen Kontexten
  auftauchen, und bildet das auf Zahlen ab. Genau diese Zahlen sind es,
  die ChromaDB blitzschnell vergleichen kann, ganz ohne dass jemals ein
  Sprachmodell den kompletten Quellenbestand "lesen" müsste.

---

## Für Entwickler:innen

**Backend:** FastAPI (Python), Vektordatenbank Chroma (persistent, lokal
unter `data/chroma/`), Embeddings lokal über `sentence-transformers`
(`intfloat/multilingual-e5-base`), Antwortgenerierung über die Anthropic
API (`claude-haiku-4-5-20251001`) mit striktem quellenbasiertem
System-Prompt und Chunk-Referenzen; `/api/ask` antwortet als
NDJSON-Stream. Auth ist ein selbstgebautes Magic-Link-System
(`app/auth.py`, `app/users.py`, `app/mail.py`) mit drei Rollen
(`quellen_pfleger`, `user_admin`, `system_admin`) plus anonymem
Lesezugriff; Sessions laufen über signierte Cookies. Schreibende Endpunkte
sind gegen Bots über Rate-Limiting (`app/ratelimit.py`) und Cloudflare
Turnstile (`app/captcha.py`) abgesichert, dazu eine pfadabhängige
Content-Security-Policy (eigene, schlankere Variante für das eingebettete
`/embed.html`). Änderungen an Quellen werden diff-basiert in einem
Audit-Log protokolliert (`app/audit.py`, mit Revert-Endpunkt), erste
Konversationsfragen anonymisiert in einem separaten Log
(`app/question_log.py`) – beides nur für Quellen-Pfleger:innen/
System-Admins einsehbar. Rechenintensive Hintergrund-Jobs
(Audio-Transkription) laufen über einen begrenzten Worker-Pool
(`AUDIO_TRANSCRIPTION_WORKER_COUNT = 3`) statt unbegrenzt parallel.
Sprachein-/-ausgabe läuft über einen serverseitigen Proxy zu Google Cloud
Speech-to-Text/Text-to-Speech, damit der API-Key nie im Frontend landet.

**Frontend:** bewusst framework-los (Vanilla HTML/CSS/JS, ES-Module),
mobile-first, mit gemeinsamen Komponenten für Header/Footer
(`header.js`/`footer.js` + `init-*.js`, auf allen Seiten eingebunden) und
einem eigenen i18n-Modul für die zweisprachige Oberfläche
(`static/i18n/{de,en}.json`). Design orientiert sich an betacodex.org
(Systemfont-Stack, Terrakotta-Akzent, ruhiger Dark-Mode-Support).

**Tests:** `pytest`-Suite (aktuell 487 Tests, Embeddings/LLM/externe APIs
dabei gemockt) plus Node-basierte Tests für Frontend-Logik
(`tests/test_frontend_js.py`, führt Ausschnitte aus `static/*.js` direkt
in Node aus). Ein Pre-Commit-Hook verhindert versehentliche
`.env`-Commits.

### Lokal starten

```bash
cd "Beta-Kodex - Wissenspartner"
source venv/bin/activate          # oder: ./venv/bin/python -m ...
cp .env.example .env              # ANTHROPIC_API_KEY eintragen
git config core.hooksPath scripts/git-hooks   # einmalig: Secret-Schutz aktivieren
uvicorn app.main:app --reload
```

Danach `http://127.0.0.1:8000/` im Browser öffnen. Ohne gültigen
`ANTHROPIC_API_KEY` in `.env` funktioniert der Import (Chunking/Embedding/
Ablage in Chroma), aber `/api/ask` schlägt beim eigentlichen LLM-Aufruf
fehl.

### Drei parallele Instanzen: Dev, Stabil, Produktion

- **Dev** (`Beta-Kodex - Wissenspartner/`, Port 8000): der aktive
  Arbeitsstand, kann jederzeit kurzzeitig instabil sein
  (Server-Neustarts während der Entwicklung).
- **Stabil** (`Beta-Kodex - Wissenspartner (stabil)/`, Port 8001): ein
  separates [Git Worktree](https://git-scm.com/docs/git-worktree), das auf
  dem jeweils letzten getaggten Stand steht (siehe Versionshistorie unten
  für den aktuellen Tag), mit eigenem venv und eigener `.env`-Kopie:
  ```bash
  cd "Beta-Kodex - Wissenspartner (stabil)"
  git fetch origin --tags
  git checkout v0.45.0       # jeweils aktueller Tag
  ./venv/bin/pip install -r requirements.txt   # falls sich Abhängigkeiten geändert haben
  # Server neu starten
  ```
- **Produktion** (https://companion.betahof.com, Hetzner Cloud, CX23,
  Falkenstein, DSGVO-konform): ein einzelner Server mit zwei kompletten
  App-Instanzen ("Blue"/"Green") unter einem eigenen Systembenutzer
  `betacodex`, dahinter Caddy als Reverse Proxy mit automatischem
  Let's-Encrypt-TLS. Beide Instanzen teilen sich `data/` und `.env` per
  Symlink auf ein gemeinsames `shared/`-Verzeichnis; nur der Code
  unterscheidet sich zwischen den beiden Slots. Deployment läuft
  vollautomatisch per GitHub Actions (`.github/workflows/deploy.yml`),
  ausgelöst durch denselben Tag-Push, mit dem auch Stabil aktualisiert
  wird: `pytest -q` + `node --check`, bei Erfolg SSH zum Server,
  `deploy.sh <tag>` deployt auf die gerade inaktive Farbe, wartet auf
  einen Health-Check (`/api/version`), schaltet Caddy erst danach um und
  stoppt die alte Farbe – Zero-Downtime, mit automatischem Rollback (alte
  Farbe bleibt live), falls die neue Version nicht startet. Unterschiede
  zu Dev/Stabil: `ENVIRONMENT` bleibt hier ungesetzt (nicht
  `"development"`), dadurch sind Cookies `Secure` und der
  `X-Robots-Tag` (verhindert sonst die Suchmaschinen-Indexierung)
  entfällt; ein eigenes `EARLY_ACCESS_PASSWORD` sperrt die Seite vorerst
  für einen sanften Start, Turnstile läuft mit einem echten, bei
  Cloudflare registrierten Schlüsselpaar.

### Schutz vor versehentlichem Secret-Commit

`.env` ist in `.gitignore` und wird dadurch nicht getrackt. Zusätzlich
blockt ein Pre-Commit-Hook (`scripts/git-hooks/pre-commit`) jeden Commit,
der eine `.env`-artige Datei enthält (z. B. bei `git add -f` aus
Versehen). Der Hook ist Teil des Repos, muss aber **nach jedem frischen
Clone einmalig aktiviert werden**:

```bash
git config core.hooksPath scripts/git-hooks
```

### Tests ausführen

```bash
./venv/bin/pytest -v
```

---

## Versionshistorie

Kurzüberblick über die wichtigsten Ausbaustufen (neueste zuerst). Reine
Fix-Batches zwischen zwei Ausbaustufen (z. B. `v0.16.1`–`v0.16.5`) sind hier
nicht einzeln aufgeführt – Details dazu stehen in den jeweiligen
Commit-/Tag-Nachrichten in Git.

| Version | Wesentliche Änderungen |
|---|---|
| v0.45 | Backlog #190: Live-Transkript während Spracheingabe |
| v0.44 | Backlog #183/#184: Login-Bereich mobil als Aufklapp-Bereich statt Popover, dynamisch wachsendes Frage-Eingabefeld (inkl. Zittern-Fix) |
| v0.43 | Backlog #96/#115: GitHub-Actions-Workflow für Tests + Zero-Downtime Blue-Green-Deployment, Produktiv-Livegang auf Hetzner |
| v0.42 | Anonymisiertes Fragen-Log für Quellen-Admins + gemeinsame Navigations-Kopfzeile auf allen Seiten |
| v0.41 | Einbettbares Embed-Snippet für die Konversationsansicht (Backlog #75, hinter Feature-Flag) |
| v0.40 | Relevanz-Score für Quellen (1-10) |
| v0.39 | Änderungs-Log mit Rückgängig-Funktion + weiches Löschen |
| v0.38 | Klickbare Begriffs-Links + gezielte Begriffs-Ableitung aus der Zusammenfassung |
| v0.37 | Early-Access-Passwort für die Produktivumgebung |
| v0.36 | Streaming-Antworten für /api/ask |
| v0.35 | Vorbereitung für den Livegang: noindex, Datenschutzerklärung, gepinnte Abhängigkeiten, Backup-Skript |
| v0.34 | Sprachdialog: STT für Fragen, TTS für Antworten (Backlog #49) |
| v0.33 | Quellen-Admins mit Namen + Audit-Log ihrer Änderungen (Backlog #98) |
| v0.32 | Volltextsuche im Quellenverzeichnis (Backlog #94) |
| v0.31 | Fix: Audio-Import scheiterte bei Episoden über 23 Minuten (Diarisierungs-Zeitlimit) |
| v0.30 | Social-Media-Plattform wird automatisch anhand der URL erkannt |
| v0.29 | Großer/langsamer Import blockiert nicht mehr - eigene Warteschlange wie bei Audio/PDF |
| v0.28 | Fix: Scroll-Position nach Import + Anzahl importierter Quellen in Überschrift |
| v0.27 | Fix: Cmd/Strg+F durchsucht jetzt alle geladenen Quellen, nicht nur die aktuelle Seite |
| v0.26 | Fix: PDF-Extraktion crasht nicht mehr bei beschädigter Xref-Tabelle im CreationDate |
| v0.25 | KI-Vita-Vorschlag für neue Co-Autor:innen, PDF-OCR-Hintergrundjob, diverse Fixes |
| v0.24 | Backlog #58: Website-Grundlagen-Audit Teil 2 (PWA, Fehlerseiten, CSP, A11y, OG-Tags) |
| v0.23 | Backlog #65 + diverse Fixes: Alphabet-Sprungleiste, bilinguale Vita, Popover/Scroll/Retry-Fixes |
| v0.22 | Backlog #85: Feedback-Popover statt reinem GitHub-Issues-Link |
| v0.21 | Backlog #57: Infinite Scroll für die Quellenliste (je 20) |
| v0.20 | Backlog #86: Autorenprofil-Panel beim Import neuer Autor:innen |
| v0.19 | Zweistufiger Audio-Import mit Hintergrund-Verarbeitung + Status-Icon |
| v0.18 | Zitat-Qualität: Satzgrenzen-bewusstes Chunking, lokales Satz-Highlighting, KI-Zitat mit Verifikation gegen Halluzination, Re-Indizierung bestehender Quellen |
| v0.17 | Autor:innen-Profile (Foto, Vita, Website, Social Links) inkl. Umbenennen-Funktion |
| v0.16 | Echtes Login-System (Magic-Link, ausschließlich per Einladung) + zentrierter Chat-Startzustand |
| v0.15 | Spam-/Bot-Schutz, YouTube-Import als Fließtext, YouTube-Duplikat-Erkennung |
| v0.14 | Konversationsansicht: Quellen-Sidebar, Bearbeiten-Zugriff direkt aus dem Chat, Sprach-Politur |
| v0.13 | Mehrfach-Autoren pro Quelle |
| v0.12 | Mobile-First-Überarbeitung + Website-Grundlagen-Fixes |
| v0.11 | Frage-Antwort-Bereich zu Chat-Dialog umgebaut |
| v0.10 | PDF-Öffnen, Timeline-/Broken-Link-Fixes, sofortiger URL-Recheck |
| v0.9 | Zweisprachige (DE/EN) KI-Zusammenfassungen, Timeline-Fix, Autor-Sekundärsortierung |
| v0.7 | Markdown-Formatierung beim Import, Icon-Feinschliff, Footer |
| v0.6 | KI-Zusammenfassung beim Import läuft im Hintergrund |
| v0.5 | Magic-Button für nachträgliche KI-Zusammenfassung + Lösch-Widerruf-Fix |
| v0.4 | Bearbeiten-Panel-Bugfixes, Lösch-UX, Grid-Layout, Label-Klarstellungen |
| v0.3 | Admin-Volltextzugriff, Markdown-Editor, Audio-Import, natürlichere Antworten |
| v0.2 | Rollen, i18n (DE/EN), KI-Zusammenfassungen, PDF-/YouTube-Import, Löschen mit Undo |
| v0.1 | Vertikaler Durchstich: Text-Import, Frage-Antwort mit Quellenangabe |

Die aktuell laufende Version steht im Footer der Anwendung selbst
(`GET /api/version`, per `git describe --tags` ermittelt – kein manuelles
Versions-File zu pflegen).

### Ausgangspunkt (v0.1) im Detail

Der allererste, vertikale Durchstich lief mit folgendem Funktionsumfang:

- **Import** über ein Textfeld (Copy/Paste) mit Feldern für Titel, Autor, Datum, URL (`POST /api/sources`)
- **Chunking** mit `tiktoken` (cl100k_base), 900 Tokens pro Chunk, 130 Tokens Überlappung (`app/chunking.py`); jeder Chunk trägt Quell-ID, Titel, Autor, Datum, URL, Position als Metadaten
- **Lokales Embedding-Modell**: `intfloat/multilingual-e5-base` (sentence-transformers), läuft komplett offline/lokal (`app/embeddings.py`)
- **Vektordatenbank**: Chroma, persistent unter `data/chroma/` (`app/vectorstore.py`)
- **Retrieval**: Top-k-Suche zur Nutzerfrage (Standard k=5)
- **Antwortgenerierung**: Anthropic API, Modell `claude-haiku-4-5-20251001`, mit striktem System-Prompt – antwortet ausschließlich aus den gelieferten Chunks, referenziert sie als `[1]`, `[2]` usw. und sagt explizit, wenn die Quellenlage eine Frage nicht hergibt (`app/llm.py`)
- **Frontend**: Erfassen und Abrufen sind bewusst getrennt. Startseite (`static/index.html` + `question.js`) zeigt nur die Frage-Antwort-Maske; ein runder Plus-Button oben rechts führt zur Inhaltspflege (`static/import.html` + `import.js`). Dort erst die Quelltyp-Auswahl (zwei Kreis-Buttons: Text / URL), dann das jeweilige Formular. Quellenangaben bei der Antwort werden als aufklappbare, im Fall einer URL klickbare Einträge unter der Antwort aufgelöst
- **URL-Import (Blogposts/Artikel)**: Klick auf den URL-Button öffnet ein an den Button angedocktes Popover für die URL-Eingabe (`POST /api/extract-url`, `app/extraction.py`, `trafilatura`). Titel, Autor, Erscheinungsdatum und Text werden automatisch extrahiert und in das bestehende Formular übernommen; von dort läuft der Import wie beim Text-Einfügen weiter (`POST /api/sources`). Schlägt die Extraktion ganz fehl, wird das im Popover angezeigt und auf manuelle Texteingabe verwiesen (Fallback)
- **Quellen bearbeiten**: Klick auf das Stift-Icon einer Quelle öffnet ein Akkordeon direkt unter dem jeweiligen Listeneintrag (`PUT /api/sources/{id}`) – Bearbeitung passiert inline in der Liste, ohne Sprung zu einem separaten Formular. Titel/Autor/Datum/URL/Text werden neu gespeichert, die Chunks in Chroma komplett neu erzeugt und die Autor:innen-Registry entsprechend nachgeführt
- **Autor:innen-Verzeichnis** (`app/authors.py`, `GET /api/authors`): wird bei jedem Import/Update automatisch mitgeführt, normalisiert Groß-/Kleinschreibung und Leerzeichen, behält aber die zuerst gesehene Schreibweise als Anzeigename, alphabetisch sortiert
- **Rollen/Rechte (Test-Stand)**: vier Rollen – kein Login/keine Rolle (Assistant-Mode: Fragen stellen, Quellen lesen, immer offen), `quellen_pfleger` (darf Quellen anlegen/bearbeiten), `user_admin`, `system_admin`. Da es noch kein echtes Login gab, ließ sich die aktive Test-Rolle über einen Dropdown manuell umschalten (`X-Dev-User`-Header) – rein für die Entwicklung, kein Sicherheitsmechanismus
- **Design**: An `betacodex.org` angelehnt (Systemfont-Stack mit Inter zuerst, Textfarbe `#232323`, Akzent-Terrakotta `#B22F1C`, großzügiger Weißraum, ruhige Buttons/Inputs, einfaches Dark-Mode-Pendant über `prefers-color-scheme`)
- **Tests**: `pytest`-Suite (`tests/`) für Chunking, Vectorstore-Roundtrip, URL-Extraktion (gemocktes `trafilatura`), Autor:innen-Registry und alle API-Endpunkte (Embeddings/LLM dabei gemockt, damit Tests schnell und ohne API-Key laufen)
- **Inhalt**: Die 9 Artikel aus dem [betahof.de-Magazin](https://www.betahof.de/magazin/) wurden über die URL-Import-Pipeline eingespeist

---

Diese Datei wird bei jeder größeren Richtungsentscheidung mitgepflegt.
