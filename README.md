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
| Nutzer- & Rechtemanagement | Quellen anlegen, kuratieren, pflegen nur mit freigeschaltetem Nutzerkonto. Der Autor eines Chunks/einer Quelle wird mit dem Benutzerkonto verknüpft (statt freiem Textfeld). Freischaltung ist zeitlich begrenzt (z. B. 1 Jahr, Frist wird bei Freischaltung festgelegt) und darf nur durch Nutzer:innen mit einer besonderen technischen Rolle erfolgen. Bewertung/Gewichtung von Quellen: Konzept noch offen |
| Sprachdialog | STT für die Frage, TTS für die Antwort (z. B. ElevenLabs). Der Kern bleibt unverändert – Sprache ist nur eine Hülle. **Erst ganz zum Schluss**, sonst debuggt man zwei Dinge gleichzeitig |
| Kuratierte Aufbereitung | Interessante Takes, Zitate und Impulse ansprechend im Frontend darstellen |
| Design / UI-Politur | Nach dem funktionierenden Kern |

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
- **Frontend**: Erfassen und Abrufen sind bewusst getrennt. Startseite (`static/index.html` + `question.js`) zeigt nur die Frage-Antwort-Maske; ein runder Plus-Button oben rechts führt zur Inhaltspflege (`static/import.html` + `import.js`) mit Importformular und Liste der vorhandenen Quellen. Quellenangaben bei der Antwort werden als aufklappbare, im Fall einer URL klickbare Einträge unter der Antwort aufgelöst
- **Tests**: `pytest`-Suite (`tests/`) für Chunking, Vectorstore-Roundtrip und die API-Endpunkte (Embeddings/LLM dabei gemockt, damit Tests schnell und ohne API-Key laufen)

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

- Weitere Importarten (URL, PDF, YouTube) – laut Vorgabe bewusst nicht in dieser Session
- Manuelle Verifikation von `/api/ask` mit echtem `ANTHROPIC_API_KEY` (lokal nicht vorhanden, Nutzer muss eigenen Key eintragen)
- Design/UI-Politur (laut Backlog erst nach dem funktionierenden Kern)
