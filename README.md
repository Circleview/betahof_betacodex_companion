# BetaCodex Wissensassistent

Ein RAG-basierter Frage-Antwort-Assistent, der ausschließlich auf kuratierten Quellen zum BetaCodex und den zugehörigen Sozialtechnologien und Forschungszweigen arbeitet.

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
| Podcasts als Quelle | Audio über URL ziehen, per Whisper transkribieren – ein Zwischenschritt mehr |
| Wissensgraph / Landkarte | Automatische Vernetzung der Inhalte aus den vorhandenen Embedding-Ähnlichkeiten; Darstellung per D3 oder Cytoscape. **Wichtig:** Schwellenwert für Kanten einbauen (Regler), sonst wird das Netz zum Wollknäuel |
| Nutzer- & Rechtemanagement | Quellen anlegen, kuratieren, pflegen nur mit freigeschaltetem Nutzerkonto. Der Autor eines Chunks/einer Quelle wird mit dem Benutzerkonto verknüpft (statt freiem Textfeld). Freischaltung ist zeitlich begrenzt (z. B. 1 Jahr, Frist wird bei Freischaltung festgelegt) und darf nur durch Nutzer:innen mit einer besonderen technischen Rolle erfolgen |
| Community Voting (Bedeutungsrang von Quellen) | Nutzer:innen mit der Rolle "Quellen-Pfleger:in" können jede Quelle einmal bewerten (Vote schiebt den Rang der Quelle einen Schritt hoch/runter). Ein Vote pro Nutzer:in und Quelle, änderbar. Die eigene Bewertung ist für die/den Nutzer:in sichtbar, der Durchschnitt aller Bewertungen ("Community Voting") für alle |
| Versionshistorie / Audit-Log | Hinzufügen und nachträgliches Bearbeiten von Quellen wird protokolliert: Zeitstempel, änderndes Nutzerkonto, saubere Historie der vorgenommenen Änderungen. Setzt das Nutzerkonto-Konzept voraus (siehe oben) |
| Autor:innen-Verzeichnis: Empfehlungen & Graph | Das bestehende Autor:innen-Verzeichnis (`app/authors.py`, `/api/authors`) soll später für Leseempfehlungen ähnlicher Autor:innen und für den Aufbau des Wissensgraphen (s. o.) genutzt werden |
| Podcasts als Quelle | Audio über URL ziehen, per Whisper transkribieren – ein Zwischenschritt mehr |
| Wissensgraph / Landkarte | Automatische Vernetzung der Inhalte aus den vorhandenen Embedding-Ähnlichkeiten; Darstellung per D3 oder Cytoscape. **Wichtig:** Schwellenwert für Kanten einbauen (Regler), sonst wird das Netz zum Wollknäuel |
| Sprachdialog | STT für die Frage, TTS für die Antwort (z. B. ElevenLabs). Der Kern bleibt unverändert – Sprache ist nur eine Hülle. **Erst ganz zum Schluss**, sonst debuggt man zwei Dinge gleichzeitig |
| Kuratierte Aufbereitung | Interessante Takes, Zitate und Impulse ansprechend im Frontend darstellen |

---

## 8. Arbeitsprinzipien

1. Erst der vertikale Durchstich, dann Breite.
2. Metadaten von Anfang an mitschleppen – nachträglich ist es teuer.
3. Gemischte Testquellen (PDF, Blog, YouTube) früh einspeisen, um Formatprobleme sofort zu sehen.
4. Nach jedem Schritt prüfen: Bedient sich das System wirklich der richtigen Quellen?
5. Diese Datei bei jeder Richtungsentscheidung mitpflegen.

---

## 9. Status: Schritt 0 (Durchstich) – umgesetzt (v0.1)

Der vertikale Durchstich läuft. Umgesetzt wurde:

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

### Noch offen / nicht Teil dieses Schritts

- Weitere Importarten (PDF, YouTube) – Text und URL (Blogposts/Artikel) sind umgesetzt
- Design/UI-Politur (laut Backlog erst nach dem funktionierenden Kern)
- Nutzer-/Rechtemanagement (siehe Backlog, Abschnitt 7)
