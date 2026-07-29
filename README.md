# BetaCodex Wissensassistent

Ein RAG-basierter Frage-Antwort-Assistent, der ausschließlich auf kuratierten Quellen zum BetaCodex und den zugehörigen Sozialtechnologien und Forschungszweigen arbeitet.

---

## Aktueller Stand

### Für Nutzer:innen

Aus dem ursprünglichen Durchstich (Text rein, Antwort mit Quellenangabe raus)
ist inzwischen ein vollwertiger Wissenspartner geworden. Man stellt seine
Frage im Chat und bekommt eine Antwort, die ausschließlich auf den
kuratierten BetaCodex-Quellen beruht – jede Aussage ist bis zur
Original-Quelle zurückverfolgbar, inklusive Zeitstempel bei Video/Audio.
Wer mag, diktiert die Frage per Mikrofon und lässt sich die Antwort
vorlesen; Oberfläche und Antworten gibt es auf Deutsch und Englisch.

Wer Quellen einpflegt (Blogposts, PDFs, YouTube-Videos, Podcasts/Audio-
Dateien), tut das über eine eigene Import-Oberfläche mit Volltextsuche,
Autor:innen-Verzeichnis samt Profilen und einem Papierkorb statt
endgültigem Löschen. Größere Verarbeitungsschritte (z. B. Audio-
Transkription) laufen im Hintergrund, ein Status-Icon zeigt den
Fortschritt. Über ein echtes, einladungsbasiertes Login-System gibt es
abgestufte Rechte: anonymes Fragenstellen bleibt für alle offen, das
Pflegen von Quellen ist Quellen-Pfleger:innen vorbehalten. Änderungen an
Quellen landen nachvollziehbar in einem Änderungs-Log (mit
Rückgängig-Funktion), anonymisierte Erstfragen neuer Konversationen helfen
dabei, Lücken im Quellenbestand zu erkennen. Die Konversationsansicht lässt
sich außerdem als Widget in fremde Webseiten einbetten.

Das Projekt ist bewusst kein allgemeiner Chatbot: Findet sich in den
Quellen keine Antwort, sagt der Assistent das offen, statt zu spekulieren.

### Für Entwickler:innen

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
Konversationsfragen anonymisiert in einem separaten Log (`app/
question_log.py`) – beides nur für Quellen-Pfleger:innen/System-Admins
einsehbar. Rechenintensive Hintergrund-Jobs (Audio-Transkription) laufen
über einen begrenzten Worker-Pool (`AUDIO_TRANSCRIPTION_WORKER_COUNT = 3`)
statt unbegrenzt parallel. Sprachein-/-ausgabe läuft über einen
serverseitigen Proxy zu Google Cloud Speech-to-Text/Text-to-Speech, damit
der API-Key nie im Frontend landet.

**Frontend:** bewusst framework-los (Vanilla HTML/CSS/JS, ES-Module),
mobile-first, mit gemeinsamen Komponenten für Header/Footer
(`header.js`/`footer.js` + `init-*.js`, auf allen Seiten eingebunden) und
einem eigenen i18n-Modul für die zweisprachige Oberfläche (`static/i18n/
{de,en}.json`). Design orientiert sich an betacodex.org (Systemfont-Stack,
Terrakotta-Akzent, ruhiger Dark-Mode-Support).

**Betrieb & Tests:** zwei parallele Git-Worktrees, Dev (Port 8000, aktiver
Arbeitsstand) und Stabil (Port 8001, jeweils letzter getaggter Release,
siehe Abschnitt 9), Versionierung per `git describe --tags` ohne manuelles
Versions-File. Testsuite mit `pytest` (aktuell 444 Tests, Embeddings/LLM/
externe APIs dabei gemockt), ein Pre-Commit-Hook verhindert versehentliche
`.env`-Commits.

---

## 1. Ziel des Projekts

Ein Online-Experte / Chatbot, der Fragen zum BetaCodex beantwortet – aber **nur** auf Basis kuratierter, geprüfter Wissensquellen. Vorbild in der Bedienlogik ist Google NotebookLM: Quellen werden hinzugefügt, und die KI antwortet ausschließlich aus diesen Quellen.

**Kernanforderungen:**

- Antworten stammen ausschließlich aus den importierten Quellen – kein beliebiges Internet- oder Modellwissen.
- Jede Antwort weist ihre Herkunft aus (Titel, Autor, Datum, Link, bei Videos mit Zeitstempel), damit Nutzer in die Originalquelle eintauchen können.
- Wenn die Quellenlage eine Frage nicht hergibt, sagt das System das offen, statt zu spekulieren.
- Unterschiedliche Quellformate (Web, Text, PDF, Video) werden über eine einheitliche Import-Oberfläche eingespeist.

**Explizites Nicht-Ziel:** Ein allgemeiner Chatbot. Vieles, was im Internet zum Thema steht, ist mit dem Erkenntnisstand des BetaCodex-Netzwerks nicht vereinbar. Genau diese Vermischung soll das System verhindern.

---

## 2. Funktionsprinzip (RAG)

Retrieval Augmented Generation, in zwei Phasen:

**Phase A – Ingestion (Import)**
1. Quelle wird über URL, Upload oder Texteingabe hinzugefügt.
2. Reiner Text wird extrahiert (bei Video: Transkript).
3. Text wird in Abschnitte ("Chunks") zerlegt.
4. Jeder Chunk erhält **Metadaten zur Herkunft** (Quell-ID, Titel, Autor, Datum, URL, ggf. Zeitstempel/Seitenzahl).
5. Chunks werden als Embeddings in einer Vektordatenbank abgelegt.

**Phase B – Retrieval & Antwort**
1. Nutzerfrage wird ebenfalls als Embedding dargestellt.
2. Die inhaltlich ähnlichsten Chunks werden gesucht (Top-k).
3. Nur diese Chunks gehen zusammen mit der Frage und einem strikten System-Prompt an das Sprachmodell.
4. Das Modell antwortet ausschließlich auf dieser Basis und referenziert die verwendeten Chunks.
5. Das Frontend löst die Referenzen zu klickbaren Quellenangaben auf.

Der Quellennachweis ist keine Zusatzfunktion, sondern fällt aus dieser Architektur zwangsläufig ab – vorausgesetzt, die Metadaten werden von Anfang an konsequent mitgeführt.

---

## 3. Vorgehen: vertikaler Durchstich zuerst

Nicht in die Breite bauen, sondern einmal komplett von vorne bis hinten – schlicht, aber funktionierend.

### Schritt 0 – Der Durchstich
Eine einzige Importart (Text einfügen), ein Textfeld für Fragen, eine Antwort mit Quellenangabe. Wenn das sauber läuft, ist das Fundament bewiesen; alles Weitere ist Erweiterung.

### Meilenstein 1 – Import (in dieser Reihenfolge)
1. **Text einfügen** – Copy/Paste in ein Textfeld (+ Felder für Titel/Autor/Quelle)
2. **Blogpost / Artikel per URL** – Seite laden, Artikeltext extrahieren, Navigation und Werbung verwerfen
3. **PDF-Upload** – Präsentationen, Papers, Artikel
4. **YouTube-Link** – Transkript automatisch über die URL ziehen, möglichst mit Zeitstempeln

Für jeden Typ gilt: **Manueller Fallback.** Nicht jede Seite gibt ihren Inhalt her. Es muss immer möglich sein, Text von Hand einzufügen und die Metadaten manuell zu setzen.

Zieldimension zum Start: 50 Quellen für den Durchstich, später 300–500. Das ist technisch entspannt und läuft lokal auf einem MacBook problemlos.

### Meilenstein 2 – Ausgabe
Reduzierte Maske: Frage stellen, Antwort erhalten, Quellen sehen, Quellen anklicken. Erst danach Design und Kür.

---

## 4. Technische Bausteine

| Baustein | Vorschlag | Anmerkung |
|---|---|---|
| Sprache | Python 3.11+ | |
| Backend | FastAPI | überlebt den späteren Umzug auf einen Server |
| Vektordatenbank | Chroma | läuft lokal mit, kein separater Dienst nötig |
| Textextraktion Web | trafilatura | schneidet Menüs/Werbung weg |
| PDF | pypdf / pdfplumber | |
| YouTube | youtube-transcript-api | Transkript inkl. Zeitstempel |
| Embeddings | lokales Modell (z. B. multilingual-e5 / jina-v3) | deutschsprachig stark, bleibt lokal, kostenlos |
| Generierung | Anthropic API (Claude) | siehe Abschnitt 5 |
| Frontend | minimales HTML/JS | bewusst schlicht im Durchstich |

**Chunking-Startwerte:** ca. 800–1000 Tokens pro Chunk, 100–150 Tokens Überlappung. Später anhand echter Fragen nachjustieren.

**Datenmodell (minimal):**
- `Source`: id, titel, autor, datum, typ, url, importiert_am, roher_text
- `Chunk`: id, source_id, text, position, ggf. zeitstempel/seite, embedding

---

## 5. API vs. Self-Hosting

**Entscheidung: API.**

- **API (gewählt):** Die Frage geht an den Anbieter, dort läuft das Modell, die Antwort kommt zurück. Abrechnung nach Nutzung, keine eigene Hardware, immer aktuelle Modellqualität. Die Inhalte selbst liegen weiterhin lokal – ausgelagert wird nur die Denkarbeit.
- **Self-Hosting (verworfen):** Volle Kontrolle und Datenschutz, aber teure GPU-Hardware (schnell mehrere hundert Euro pro Monat) und meist geringere Textqualität.

Begründung: Es kommt auf Sprachqualität und einen schlanken Start an. Die Embeddings laufen ohnehin lokal, damit bleibt der Quellenbestand im Haus.

---

## 6. Späteres Deployment (Deutschland)

- **Server:** kleiner vServer bei Hetzner (Rechenzentren in Deutschland, DSGVO-konform), ca. **5–15 € / Monat**
- **Speicher:** bei diesen Textmengen praktisch vernachlässigbar
- **Modellnutzung:** nutzungsabhängig; im Testbetrieb wenige Euro, skaliert mit Nutzerzahl und Antwortlänge

---

## 7. Backlog (bewusst später)

| Thema | Beschreibung |
|---|---|
| Wissensgraph / Landkarte | Automatische Vernetzung der Inhalte aus den vorhandenen Embedding-Ähnlichkeiten; Darstellung per D3 oder Cytoscape. **Wichtig:** Schwellenwert für Kanten einbauen (Regler), sonst wird das Netz zum Wollknäuel |
| Nutzer- & Rechtemanagement: zeitliche Befristung | Freischaltung von Nutzerkonten mit der Rolle "Quellen-Pfleger:in" zeitlich begrenzen (z. B. 1 Jahr, Frist wird bei Freischaltung festgelegt). Das Nutzerkonto-/Rollenmodell selbst existiert bereits (siehe Versionshistorie) |
| Community Voting (Bedeutungsrang von Quellen) | Nutzer:innen mit der Rolle "Quellen-Pfleger:in" können jede Quelle einmal bewerten (Vote schiebt den Rang der Quelle einen Schritt hoch/runter). Ein Vote pro Nutzer:in und Quelle, änderbar. Die eigene Bewertung ist für die/den Nutzer:in sichtbar, der Durchschnitt aller Bewertungen ("Community Voting") für alle |
| Autor:innen-Verzeichnis: Empfehlungen & Graph | Das bestehende Autor:innen-Verzeichnis (`app/authors.py`, `/api/authors`) soll später für Leseempfehlungen ähnlicher Autor:innen und für den Aufbau des Wissensgraphen (s. o.) genutzt werden |
| Kuratierte Aufbereitung | Interessante Takes, Zitate und Impulse ansprechend im Frontend darstellen |
| Verlinkte Quellen in Dokumenten auswerten | Viele importierte Dokumente verlinken selbst weitere Quellen. Diese Links extrahieren und als Vorschläge für neue Quellen im Index nutzen (automatische Erweiterung des Quellen-Netzwerks) |
| Neue Rolle "Content Creator" | KI-gestützte Textgenerierung für Social Media/Blog-Beiträge auf Basis der vorhandenen Quellen |
| CI/CD-Pipeline | Automatisierte Tests + Zero-Downtime-Deployment (ggf. Blue-Green) |
| Produktiv-Deployment | Server-Umzug, eigenes Hosting jenseits von Dev/Stabil, CI/CD-Anbindung |

---

## 8. Arbeitsprinzipien

1. Erst der vertikale Durchstich, dann Breite.
2. Metadaten von Anfang an mitschleppen – nachträglich ist es teuer.
3. Gemischte Testquellen (PDF, Blog, YouTube) früh einspeisen, um Formatprobleme sofort zu sehen.
4. Nach jedem Schritt prüfen: Bedient sich das System wirklich der richtigen Quellen?
5. Diese Datei bei jeder Richtungsentscheidung mitpflegen.

---

## 9. Versionshistorie

Kurzüberblick über die wichtigsten Ausbaustufen (neueste zuerst). Reine
Fix-Batches zwischen zwei Ausbaustufen (z. B. `v0.16.1`–`v0.16.5`) sind hier
nicht einzeln aufgeführt – Details dazu stehen in den jeweiligen
Commit-/Tag-Nachrichten in Git.

| Version | Wesentliche Änderungen |
|---|---|
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

Der vertikale Durchstich lief mit folgendem Funktionsumfang:

- **Import** über ein Textfeld (Copy/Paste) mit Feldern für Titel, Autor, Datum, URL (`POST /api/sources`)
- **Chunking** mit `tiktoken` (cl100k_base), 900 Tokens pro Chunk, 130 Tokens Überlappung (`app/chunking.py`); jeder Chunk trägt Quell-ID, Titel, Autor, Datum, URL, Position als Metadaten
- **Lokales Embedding-Modell**: `intfloat/multilingual-e5-base` (sentence-transformers), läuft komplett offline/lokal (`app/embeddings.py`)
- **Vektordatenbank**: Chroma, persistent unter `data/chroma/` (`app/vectorstore.py`)
- **Retrieval**: Top-k-Suche zur Nutzerfrage (Standard k=5)
- **Antwortgenerierung**: Anthropic API, Modell `claude-haiku-4-5-20251001`, mit striktem System-Prompt – antwortet ausschließlich aus den gelieferten Chunks, referenziert sie als `[1]`, `[2]` usw. und sagt explizit, wenn die Quellenlage eine Frage nicht hergibt (`app/llm.py`)
- **Frontend**: Erfassen und Abrufen sind bewusst getrennt. Startseite (`static/index.html` + `question.js`) zeigt nur die Frage-Antwort-Maske; ein runder Plus-Button oben rechts führt zur Inhaltspflege (`static/import.html` + `import.js`). Dort erst die Quelltyp-Auswahl (zwei Kreis-Buttons: Text / URL), dann das jeweilige Formular. Quellenangaben bei der Antwort werden als aufklappbare, im Fall einer URL klickbare Einträge unter der Antwort aufgelöst
- **URL-Import (Meilenstein 1.2, Blogposts/Artikel)**: Klick auf den URL-Button öffnet ein an den Button angedocktes Popover für die URL-Eingabe (`POST /api/extract-url`, `app/extraction.py`, `trafilatura`). Titel, Autor, Erscheinungsdatum und Text werden automatisch extrahiert und in das bestehende Formular übernommen; von dort läuft der Import wie beim Text-Einfügen weiter (`POST /api/sources`). Erscheinungsdatum (`date`) und Speicherdatum (`imported_at`) werden als getrennte Felder abgelegt. Fehlt Autor/Datum nach der Extraktion (z. B. bei Wikipedia ohne Autorenangabe), bleiben die Felder leer und lassen sich vor dem Import manuell nachtragen. Schlägt die Extraktion ganz fehl, wird das im Popover angezeigt und auf manuelle Texteingabe verwiesen (Fallback)
- **Quellen bearbeiten**: Klick auf das Stift-Icon einer Quelle öffnet ein Akkordeon direkt unter dem jeweiligen Listeneintrag (`PUT /api/sources/{id}`) – Bearbeitung passiert inline in der Liste, ohne Sprung zu einem separaten Formular. Titel/Autor/Datum/URL/Text werden neu gespeichert, die Chunks in Chroma komplett neu erzeugt (alte gelöscht, neue eingefügt) und die Autor:innen-Registry entsprechend nachgeführt. Validierung (z. B. leerer Text) läuft **vor** dem Löschen der alten Chunks, damit ein fehlgeschlagenes Update nichts zerstört. Das Stift-Icon ist auf Desktop nur bei Hover/Fokus sichtbar, auf Touch-Geräten (kein Hover) immer
- **Autor:innen-Verzeichnis** (`app/authors.py`, `GET /api/authors`): wird bei jedem Import/Update automatisch mitgeführt, normalisiert Groß-/Kleinschreibung und Leerzeichen, behält aber die zuerst gesehene Schreibweise als Anzeigename, alphabetisch sortiert. In der Quellenliste sind Autor:innen anklickbar und filtern auf ihre Quellen (Registry-Daten, nicht String-Vergleich – robust gegenüber Schreibvarianten). Das Autor-Feld beim Anlegen/Bearbeiten ist ein Freitextfeld mit nativem HTML5-Datalist-Vorschlag aus den bereits bekannten Autor:innen, damit sich Schreibweisen nicht unnötig auffächern. Vorgesehen als Grundlage für spätere Leseempfehlungen und den Wissensgraphen (Backlog)
- **Rollen/Rechte (Test-Stand)** (`app/users.py`, `GET /api/dev/users`): vier Rollen – kein Login/keine Rolle (Assistant-Mode: Fragen stellen, Quellen lesen, immer offen), `quellen_pfleger` (darf Quellen anlegen/bearbeiten), `user_admin` (verwaltet künftig die Freischaltung von Quellen-Pfleger:innen), `system_admin` (steht über allen Rollen, darf alles). Da es noch kein echtes Login gibt, lässt sich die aktive Test-Rolle über einen Dropdown oben rechts in der Inhaltspflege manuell umschalten (`X-Dev-User`-Header, in `localStorage` gemerkt) – rein für die Entwicklung, kein Sicherheitsmechanismus. Geschützt sind `POST/PUT /api/sources` und `POST /api/extract-url`; Lesen/Fragen bleibt für alle offen
- **Design**: An `betacodex.org` angelehnt (Systemfont-Stack mit Inter zuerst, Textfarbe `#232323`, Akzent-Terrakotta `#B22F1C`, großzügiger Weißraum, ruhige Buttons/Inputs, einfaches Dark-Mode-Pendant über `prefers-color-scheme`). Bewusst kein externer Font-Download (Google Fonts blockierte in einer Testumgebung das Laden) – Systemfonts sehen dem Original sehr nahe
- **Tests**: `pytest`-Suite (`tests/`) für Chunking, Vectorstore-Roundtrip (inkl. gezieltes Löschen), URL-Extraktion (gemocktes `trafilatura`), Autor:innen-Registry und alle API-Endpunkte (Embeddings/LLM dabei gemockt, damit Tests schnell und ohne API-Key laufen)
- **Inhalt**: Die 9 Artikel aus dem [betahof.de-Magazin](https://www.betahof.de/magazin/) wurden über die URL-Import-Pipeline eingespeist (automatisiert, ohne Autor-Metadaten von der Seite – bei Bedarf über die Bearbeiten-Funktion nachtragen)

**Abweichung von Abschnitt 4:** Lokal war nur Python 3.9.6 installiert (keine 3.11+-Variante verfügbar), das Projekt läuft damit einwandfrei – bei Bedarf später auf 3.11+ umziehen.

### Starten

```bash
cd "Beta-Kodex - Wissenspartner"
source venv/bin/activate          # oder: ./venv/bin/python -m ...
cp .env.example .env              # ANTHROPIC_API_KEY eintragen
git config core.hooksPath scripts/git-hooks   # einmalig: Secret-Schutz aktivieren (siehe unten)
uvicorn app.main:app --reload
```

Danach `http://127.0.0.1:8000/` im Browser öffnen. Ohne gültigen `ANTHROPIC_API_KEY` in `.env` funktioniert der Import (Chunking/Embedding/Ablage in Chroma), aber `/api/ask` schlägt beim eigentlichen LLM-Aufruf fehl.

### Zwei parallele Instanzen: Dev und Stabil

Damit während laufender Weiterentwicklung immer eine funktionierende Version zum Testen bereitsteht, gibt es zwei Instanzen nebeneinander:

- **Dev** (`Beta-Kodex - Wissenspartner/`, Port 8000): der aktive Arbeitsstand, kann jederzeit kurzzeitig instabil sein (Server-Neustarts während der Entwicklung).
- **Stabil** (`Beta-Kodex - Wissenspartner (stabil)/`, Port 8001): ein separates [Git Worktree](https://git-scm.com/docs/git-worktree), das auf dem jeweils letzten getaggten Stand steht (siehe Versionshistorie, Abschnitt 9, für den aktuellen Tag), mit eigenem venv und eigener `.env`-Kopie. Wird nur bei erreichten, getesteten Meilensteinen aktualisiert:
  ```bash
  cd "Beta-Kodex - Wissenspartner (stabil)"
  git fetch origin --tags
  git checkout v0.18         # jeweils aktueller Tag
  ./venv/bin/pip install -r requirements.txt   # falls sich Abhängigkeiten geändert haben
  # Server neu starten
  ```

`http://127.0.0.1:8001/` ist damit die Adresse zum Testen, unabhängig davon, woran gerade auf Port 8000 gearbeitet wird.

### Schutz vor versehentlichem Secret-Commit

`.env` ist in `.gitignore` und wird dadurch nicht getrackt. Zusätzlich blockt ein Pre-Commit-Hook (`scripts/git-hooks/pre-commit`) jeden Commit, der eine `.env`-artige Datei enthält (z. B. bei `git add -f` aus Versehen). Der Hook ist Teil des Repos, muss aber **nach jedem frischen Clone einmalig aktiviert werden**:

```bash
git config core.hooksPath scripts/git-hooks
```

(In diesem Arbeitsverzeichnis ist das bereits erledigt.)

### Tests ausführen

```bash
./venv/bin/pytest -v
```

### Noch offen (siehe Backlog, Abschnitt 7)

PDF-/YouTube-Import, Design/UI-Politur und echtes Nutzer-/Rechtemanagement
sind inzwischen umgesetzt (siehe Versionshistorie, Abschnitt 9) - offen sind
weiterhin die in Abschnitt 7 gelisteten Backlog-Themen.
