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
- Fett hervorgehobene Fachbegriffe in einer Antwort sind anklickbar – ein
  Klick vertieft genau diesen Begriff als Folgefrage, im Kontext der
  laufenden Konversation.
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

### Explore-Modus (Netzwerk-Ansicht)

- Schlagworte und Autor:innen der gesamten Quellensammlung als
  interaktives, animiertes Netzwerk statt einer reinen Liste – öffentlich
  zugänglich wie die Konversationsansicht.
- Automatische thematische Clusterbildung (Community-Erkennung) statt
  eines manuell gepflegten Vokabulars; Knotengröße spiegelt die Anzahl
  zugehöriger Quellen.
- Klick auf einen Knoten hebt ihn samt aller direkt verbundenen Nachbarn
  hervor (der Rest dimmt ab) und zentriert ihn im Bild; erneuter Klick
  setzt die Ansicht zurück. "Öffnen in neuem Tab"-Icons an den
  hervorgehobenen Knoten springen direkt zur gefilterten Quellenliste.
- Freitextsuche hebt passende Knoten hervor, ganz ohne Neuaufbau der
  Simulation.
- Ein Schlagwort, das namensgleich mit einer registrierten Autorin/einem
  Autor ist (z. B. wird jemand in einem fremden Text thematisch erwähnt),
  bekommt keinen eigenen Knoten – die Verbindung geht direkt zum
  bestehenden Autor:innen-Knoten. Ein Klick darauf zeigt sowohl eigene
  Texte als auch Texte, die die Person nur erwähnen (als solche markiert).
- Beim Laden zeigt sich zuerst kurz das komplette, bereits eingeschwungene
  Netzwerk, dann zoomt die Ansicht sanft auf die Standardstufe – kein
  sichtbares "Zittern" der Simulation mehr.
- Autor:innen- und Schlagwort-Knoten lassen sich über zwei Icons neben der
  Suchzeile unabhängig voneinander aus-/einblenden. Blendet man alle
  Schlagworte aus, werden Autor:innen mit mindestens einem gemeinsamen
  (jetzt ausgeblendeten) Begriff direkt miteinander verbunden, statt ohne
  Kanten dazustehen.

### Kreativ-Modus

- Eigener Modus (Stift-Icon im Header) für kreatives Schreiben auf
  Grundlage des BetaCodex – Blogposts, Artikel, Webseitentexte,
  Workshop-Konzepte, White Papers – bewusst freier als die strikte
  Konversationsansicht: neben den kuratierten Quellen darf hier auch
  allgemeines Internet- und Modellwissen einfließen (z. B. für
  Workshop-Methodik, die kuratiert nicht abgedeckt ist).
- Persistentes Dokument statt Chat-Verlauf: eine Anweisung ersetzt jeweils
  das gesamte Dokument (kein Diff, kein Abschnitts-Editing – das ist
  bewusst ein späterer Ausbauschritt), sichtbar als Live-Stream Wort für
  Wort.
- Kosten-bewusste Modellwahl: der erste Entwurf (leeres Dokument) nutzt
  ein größeres Modell (Claude Sonnet), jede Überarbeitung eines
  bestehenden Dokuments das günstigere Haiku-Modell wie im Rest der App.
- Formatierungs-Toolbar (Fett, Kursiv, Überschrift, Liste) direkt über dem
  Dokumentfeld, dazu ein Bearbeiten/Vorschau-Umschalter, der die fertig
  formatierte Ansicht ohne sichtbare Markdown-Syntax zeigt.
- Quellen erscheinen getrennt nach Herkunft: kuratierte BetaCodex-Quellen
  (mit Autor:in statt URL beschriftet) und tatsächlich per Websuche
  gefundene Web-Quellen – jede Web-URL wird hart gegen die echten
  Suchergebnisse geprüft, erfundene Quellen werden verworfen.
- Eigenes, strengeres Rate-Limit als die Konversationsansicht (Sonnet +
  Websuche kosten pro Anfrage deutlich mehr als eine Haiku-Antwort).

### Quellen pflegen (Quellen-Pfleger:innen)

- Import per Copy/Paste, URL/Blogpost, PDF-Upload, YouTube-Link oder
  Audio-/Podcast-Datei (automatische Transkription, mit den bereits
  eingetragenen Autor:innen-Namen als Vokabular-Hinweis gegen
  wiederkehrende Fehlschreibungen prominenter Namen) – für jeden Typ gibt
  es einen manuellen Fallback, falls die automatische Extraktion
  scheitert.
- Größere Verarbeitungsschritte (z. B. Audio-Transkription) laufen im
  Hintergrund; ein Status-Icon zeigt den Fortschritt, mehrere Importe
  lassen sich parallel anstoßen.
- Volltextsuche über den gesamten Quellenbestand, Autor:innen-Verzeichnis
  mit Profilen (Foto, Vita, Website, Social Links, zweisprachig gepflegt).
  Profilfotos werden lokal in zwei Auflösungen zwischengespeichert, damit
  extern gehostete Bilder (z. B. LinkedIn-Links mit eingebautem
  Ablaufdatum) nicht nach einigen Wochen wieder "kaputtgehen". Ein kleiner,
  unauffälliger Bildquellennachweis unter dem Foto nennt automatisch die
  Domain der externen Foto-URL. Beim Eintragen eines Social-Media-Links
  genügt die URL - die Plattform (LinkedIn, X, Instagram, ...) wird
  automatisch erkannt, unbekannte Plattformen fallen auf die Domain zurück.
- KI-gestützte Zusammenfassung + Begriffs-Querverweise beim Import,
  jederzeit nachträglich auslösbar. Eine von Hand überarbeitete
  Zusammenfassung wird automatisch in die jeweils andere Sprache
  übersetzt und danach nicht mehr von einer erneuten KI-Generierung
  überschrieben.
- Bearbeiten inline in der Quellenliste; Löschen ist ein Papierkorb mit
  Rückholfrist statt eines endgültigen Vorgangs.
- Relevanz-Score pro Quelle (1–10) für die spätere Sortierung/Gewichtung.
- Wöchentliche Hintergrund-Prüfung aller Quellen-Links; ein Warn-Badge am
  "Quellen"-Menüpunkt macht auf defekte Links aufmerksam (von jeder Seite
  aus sichtbar), ein Filter-Button in der Quellenübersicht zeigt gezielt
  die betroffenen Quellen.
- Website-Wissensquellen: freigegebene externe Websites (z. B. Blogs von
  Expert:innen) werden wöchentlich im Hintergrund gecrawlt und fließen als
  automatischer Fallback in Antworten ein, wenn die kuratierten Quellen zum
  Thema nichts hergeben – dezent im Chat gekennzeichnet, mit
  Schnell-Ausschließen-Button für einzelne, erkennbar unpassende Seiten
  direkt aus der Konversationsansicht. Für neue Websites ohne verlässliche
  URL-Struktur wählt eine KI-gestützte Positivselektion gezielt einzelne
  Artikel statt automatisch alles unterhalb der URL zu übernehmen.

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

### System-Voraussetzungen (Produktion)

Über `requirements.txt` (per `pip`) hinaus braucht der Server folgendes
System-Paket, das bei einem frischen Server-Aufsetzen leicht vergessen
wird (Vorfall 2026-08-03: fehlte auf Produktion, dadurch schlugen alle
Audio-Transkriptionen über 25 MB fehl, siehe `split_audio_file` in
`app/extraction.py`):

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

Fehlt `ffmpeg`/`ffprobe` beim Start, schreibt die App eine deutliche
Warnung in die Logs (`journalctl --user -u betacodex-blue`/`-green`).

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
| v0.57.2 | Fix: Platzhaltertext im leeren Frage-Eingabefeld der Konversationsansicht einladender formuliert - "Konversation starten"/"Start a conversation" wird zu "Reden wir über den Beta-Kodex"/"Let's talk about the BetaCodex" (der Platzhalter für Folgefragen bleibt unverändert) |
| v0.57.1 | Vier kleine Fixes/Ergänzungen: (1) Cursor-Fokus springt beim Hinzufügen eines Social-Media-Links in der Autor:innen-Vita automatisch in die neue URL-Zeile. (2) Explore-Netzwerk erklärt in einer dezenten Legende rechts unter dem Netzwerk (gleiche Optik wie der Bildquellennachweis), was ein Punkt/eine Linie bedeutet - wechselt mit den Autor:innen-/Schlagworte-Toggle-Buttons. (3) Das Quellen-Vorschläge-Panel lässt sich jetzt per eigenem "x" schließen, zusätzlich zum bestehenden Glühbirnen-Toggle. (4) Vier weitere von Dependabot gemeldete chromadb-CVEs analysiert und dokumentiert - betreffen wie die bereits bekannte CVE-2026-45829 ausschließlich den nicht genutzten HTTP-Server-Modus |
| v0.57.0 | Neu: "Kreativ-Modus" (Stift-Icon im Header) - freieres Schreiben auf Grundlage des BetaCodex (Blogposts, Artikel, Workshop-Konzepte, White Papers) statt strikter Quellenbindung: erster Entwurf mit Claude Sonnet, Überarbeitungen mit dem günstigeren Haiku-Modell wie im Rest der App; kombiniert kuratierte BetaCodex-Quellen mit Claudes Web-Search-Werkzeug für Themen, die kuratiert nicht abgedeckt sind (jede Web-Quelle hart gegen echte Suchergebnisse geprüft, BetaCodex-Quellen deterministisch aus dem tatsächlich verwendeten Kontext, nie vom Modell selbst gemeldet). Persistentes Dokument statt Chat-Verlauf (Ganzdokument-Ersatz pro Anweisung), Formatierungs-Toolbar + Bearbeiten/Vorschau-Umschalter, eigenes strengeres Rate-Limit. Systemprompt hält das Modell außerdem explizit zu einem weniger "KI-typischen" Schreibstil an (variierte Satzlänge, keine Floskel-Übergänge, klare Positionen statt ständigem Relativieren) und zur korrekten deutschen Schreibweise "Beta-Kodex" (mit Bindestrich) |
| v0.56.1 | Neu: kein separates Plattform-Feld mehr beim Eintragen eines Social-Media-Links in der Autor:innen-Vita - nur noch die URL eingeben, die Plattform wird beim Speichern automatisch ermittelt (bekannte Plattformen liefern ihren Namen, alles andere fällt auf die Domain zurück statt den Link zu verwerfen) |
| v0.56.0 | Neu: kleiner, unauffälliger Bildquellennachweis rechtsbündig unter dem Autor:innen-Foto in der Vita-Ansicht ("Foto: example.com"), automatisch aus der Domain der externen Foto-URL abgeleitet - ohne Navigationspfad und ohne "www."-Präfix. Bekannte CDN-Domains großer Plattformen (media.licdn.com, rgstatic.net, googleusercontent.com, media-amazon.com, gravatar.com, wp.com) werden dabei auf den erkennbaren Plattformnamen abgebildet (z. B. "Foto: LinkedIn") |
| v0.55.0 | Neu: Autor:innen/Schlagworte im Explore-Netzwerk lassen sich über zwei Toggle-Icons neben der Suchzeile unabhängig voneinander aus-/einblenden (Standard: beide an), rein clientseitig aus den schon geladenen Graph-Daten neu gerendert. Da es bisher keine direkten Autor-Autor-Kanten gab, verbindet `deriveAuthorOnlyEdges()` beim Ausblenden aller Schlagworte Autor:innen stattdessen über gemeinsame (jetzt ausgeblendete) Begriffe (Gewicht = Anzahl geteilter Begriffe) - bereits vorhandene direkte Autor-Autor-Kanten bleiben dabei erhalten. Sind beide Schalter aus, bleibt das Netzwerk bewusst leer |
| v0.54.1 | Fix: "Sicherheitsprüfung fehlgeschlagen" bei rasch aufeinanderfolgenden Fragen - Cloudflare-Turnstile-Tokens werden nach jedem Versuch asynchron im Hintergrund neu ausgestellt, eine Folgefrage kurz danach fragte das neue Token teils vor Abschluss dieser Verifikation ab und bekam einen leeren String. Trat durch die neuen anklickbaren Begriffe (v0.54.0) deutlich häufiger auf, da diese Folgefragen schneller auslösen als manuelles Tippen. `getToken()` wartet jetzt kurz (bis zu ~3s) auf ein frisches Token, bevor aufgegeben wird |
| v0.54.0 | Neu: fett hervorgehobene Fachbegriffe in einer Antwort sind jetzt anklickbar - ein Klick stellt automatisch eine Folgefrage ("Erzähl mir mehr über {Begriff}."), eingebettet in den bestehenden, verlaufsbewussten Frage-Mechanismus, sodass die Vertiefung im Kontext der laufenden Konversation bleibt. Dazu die Bold-Regel im Systemprompt verschärft: fett jetzt ausschließlich für kompakte Fachbegriffe (1-4 Wörter) statt ganzer Satzteile, damit eine Folgefrage dazu auch eine sinnvoll vertiefte Antwort liefert |
| v0.53.2 | Fix: ein Audio-Upload mit mindestens einer/einem eingetragenen Autor:in scheiterte auf Produktion mit "Prompt is not supported for diarization models" - der seit v0.52.0 gesetzte Vokabular-Hinweis (OpenAIs "prompt"-Parameter) wurde unverändert auch an `gpt-4o-transcribe-diarize` durchgereicht, obwohl dieses Modell den Parameter grundsätzlich ablehnt (anders als `whisper-1`, wo er weiterhin genutzt wird) |
| v0.53.1 | Fix: die Schreibweise "Niels Pfläging" in bestehenden KI-Zusammenfassungen/Schlagworten wich von der registrierten Autor:innen-Schreibweise "Niels Pflaeging" ab, wodurch der neue Keyword-Autor:innen-Merge im Explore-Netzwerk (v0.53.0) für ihn nicht griff. Läuft als einmalige, idempotente Korrektur bei jedem Server-Start statt als manuelles Einmal-Skript, kommt damit automatisch über den normalen Deploy auf allen Umgebungen an; ändert bewusst nur Zusammenfassungen/Schlagworte, roher Quellentext/Titel bleiben unangetastet |
| v0.53.0 | Neu: Im Explore-Netzwerk bekommt ein Schlagwort, das namensgleich mit einer registrierten Autorin/einem Autor ist (z. B. wird jemand in einem fremden Text nur thematisch erwähnt), keinen eigenen Knoten mehr - die Verbindung geht direkt zum bestehenden Autor:innen-Knoten; ein Klick darauf zeigt jetzt sowohl eigene Texte als auch Texte, die die Person nur erwähnen (mit "erwähnt"-Badge unterschieden). Fix: die anfängliche Einschwingphase des Kraft-Graphen wirkte bei ~300 Knoten wie ein Grafikfehler ("Zittern") - die Simulation wird jetzt synchron vorgerechnet, dann zoomt die Ansicht bewusst von der Gesamtübersicht auf die Standardstufe. Fix (Testinfrastruktur): die Testsuite brauchte zuletzt bis zu 20+ Minuten statt ~1 Minute, teils ganz ohne Ende - Ursache war ein struktureller Leak in `app/vectorstore.py` (jeder Test erzeugte einen komplett neuen nativen ChromaDB-Client, dessen Rust-Bindings einen eigenen, nie geschlossenen Thread-Pool starten) zusammen mit 5 Hintergrund-Threads, die seit v0.49.7 bei jeder Testclient-Instanziierung statt nur einmal pro Session starten - bei ~350 Tests kamen so über 2000 nie freigegebene Betriebssystem-Threads zusammen. Client-Erzeugung von Collection-Erzeugung entkoppelt, Testsuite nutzt jetzt einen session-weit geteilten Client statt eines neuen pro Test (Produktionsverhalten unverändert); läuft wieder in ~37 Sekunden bei 790/790 grünen Tests |
| v0.52.1 | Fix: die Vokabular-Hinweise für die Audio-Transkription liegen jetzt separat gepflegt in `app/transcription_hints.json` statt fest in `main.py` - dort ergänzt um Niels Pflaeging/Silke Hermann als Namensbeispiele; Dubletten mit den quellenspezifischen Autor:innen werden beim Zusammenführen automatisch entfernt. Dazu: uneinheitliche Schreibweisen von "Beta-Kodex"/"BetaCodex" in bereits vorhandenen KI-Zusammenfassungen und Schlagworten einmalig auf allen drei Umgebungen normalisiert (Deutsch: "Beta-Kodex", Englisch: "BetaCodex") |
| v0.52.0 | Neu: eine von Hand überarbeitete Quellen-Zusammenfassung wird automatisch in die jeweils andere Sprache übersetzt und ist danach vor künftigen KI-Neugenerierungen geschützt (das KI-Icon erscheint nur noch bei tatsächlich unveränderten KI-Zusammenfassungen). Fix: das Explore-Netzwerk blieb beim Umschalten der Oberflächensprache bisher deutsch - Backend und Frontend laden die Knoten-Beschriftungen jetzt sprachabhängig neu. Neu: bei der Audio-Transkription werden die für eine Quelle bereits eingetragenen Autor:innen-Namen (z. B. Niels Pflaeging, Silke Hermann) als Vokabular-Hinweis an Whisper/GPT-4o-Transcribe übergeben, um wiederkehrende Fehlschreibungen prominenter Namen zu reduzieren. Fix (Testinfrastruktur): ein zweiter, dem Anthropic-Vorfall aus v0.51.0 entsprechender Kostenschutz - ein ungemockter echter OpenAI-Client in Tests konnte über die eingebaute Wiederholungslogik (bis zu 30+90 Sekunden Wartezeit) die Testsuite spürbar verlangsamen |
| v0.51.0 | Neu: "Explore"-Modus (Netzwerk-Icon im Header) - Schlagworte und Autor:innen der gesamten Quellensammlung als interaktives, thematisch geclustertes Netzwerk (D3.js, automatische Community-Erkennung). Klick auf einen Knoten hebt ihn samt direkter Nachbarn hervor und zentriert ihn, "Öffnen in neuem Tab"-Icons springen von dort zur gefilterten Quellenliste; erneuter Klick setzt zurück. Dazu: lokaler Foto-Cache für Autor:innen-Profilbilder (behebt wiederkehrend "kaputte" Fotos durch abgelaufene externe Links, z. B. LinkedIn-CDN-URLs mit eingebautem Ablaufdatum) in zwei Auflösungen (Vita: groß, Explore-Netzwerk: klein), inkl. täglichem Selbstheilungs-Worker. Fix: Autor:innen-Namen werden im KI-generierten Schlagwort-Highlighting der Quellen-Zusammenfassungen nicht mehr hervorgehoben (Namensabgleich war zu fehleranfällig). Fix: der tägliche Quellen-Vorschlags-Worker löste in der Testsuite bei praktisch jedem Test eine echte, kostenpflichtige Websuche aus - jetzt sauber gemockt, zusätzlich ein generelles Sicherheitsnetz gegen unbeabsichtigte echte Anthropic-API-Aufrufe in Tests |
| v0.50.2 | Fix: Quellen-Vorschläge zeigten teils auf nicht existierende Seiten - das Modell füllt das `submit_candidates`-Tool als eigenen, von der eigentlichen Websuche entkoppelten Aufruf und konnte dabei plausibel klingende, aber nie tatsächlich gefundene URLs erfinden. Jeder Kandidat wird jetzt hart gegen die echten Suchergebnis-URLs desselben Websuche-Calls geprüft (`web_search_tool_result`-Block) - nicht verifizierbare Kandidaten fallen lautlos raus, statt eine tote Quelle vorzuschlagen |
| v0.50.1 | Fix: der tägliche Nachschub-Lauf für Quellen-Vorschläge fand mit nur 2 befragten Autor:innen pro Tag viel weniger, als sich durch Annehmen/Ablehnen leeren ließ - `SOURCE_SUGGESTION_AUTHORS_PER_RUN` auf 6 erhöht, damit der Vorrat spürbar schneller in Richtung des Ziels (100) wächst; Produktions-Vorrat einmalig manuell auf 68 aufgefüllt. Dazu Header-Feinschliff: mehr Abstand zwischen Nutzername und Trennlinie im mobilen Header, und der Nutzername blendet sich jetzt synchron mit dem Marken-Namen aus/ein, wenn der Sticky-Header beim Scrollen kollabiert/expandiert |
| v0.50.0 | Neu: proaktive Quellen-Vorschläge aus dem offenen Web (Glühbirnen-Icon neben der Quellenliste) - ein Hintergrund-Worker sucht täglich per Claudes Web-Search-Tool nach neuen, thematisch/autorenmäßig passenden Text-Quellen (autor:innen- und themenbasiert gemischt, Alfie-Kohn-Monopolisierung durch Durchmischung verhindert) und hält einen Vorrat von bis zu 100 Vorschlägen bereit; die Liste zeigt davon immer bis zu 5 gleichzeitig und rückt beim Annehmen/Ablehnen sofort aus dem Vorrat nach (keine Wartezeit auf eine neue Websuche), mit Fade-Out/Fade-In-Übergängen. "Annehmen" öffnet das bestehende URL-Import-Formular vorausgefüllt statt selbst eine Quelle anzulegen - Review/Speichern laufen 1:1 wie beim manuellen Import. Dazu: neuer Sticky-Header (Titel blendet sich beim Herunterscrollen elegant zum Punkt aus, Icon-Leiste bleibt oben sichtbar), sowie ein Fix für die Autor:innen-Vita-Zweispaltenansicht (Suche/Import-Formular/Jobs/Website-Verwaltung landeten dort fälschlich neben statt oberhalb der Spalten) |
| v0.49.9 | Fix: fehlgeschlagene Imports, die auch "Erneut versuchen" nicht retten kann (z. B. weil die zugrunde liegende Datei/URL nie erreichbar war), blieben ohne Abbruchmöglichkeit für immer in der Jobs-Warteschlange hängen - neuer zweistufig bestätigter "Abbrechen"-Button ruft dafür das bestehende Lösch-Endpoint auf. Dabei zwei weitere kleine Bugs behoben: fehlender Abstand zwischen "Erneut versuchen" und "Abbrechen", sowie eine Race Condition, bei der der 3-Sekunden-Poll-Takt der Jobs-Liste den "Sicher?"-Bestätigungsstatus vor dem zweiten Klick zurücksetzen konnte |
| v0.49.8 | Fix: eine weich gelöschte Quelle mit zuvor fehlgeschlagener Verarbeitung (`processing_status: error`) blieb für immer im Import-Jobs-Badge/der Fehler-Warteschlange sichtbar, da `delete_source()` bewusst nur `deleted_at` setzt und `/api/import-jobs` das bisher nicht mitprüfte |
| v0.49.7 | Zwei Fixes: (1) Alle Hintergrund-Threads/Aufräumarbeiten (URL-Check, Web-Crawl-Sweep, Zusammenfassungs-Nachzug, Bootstrap-Admin) starten jetzt über einen echten FastAPI-`lifespan`-Hook statt unbedingt beim bloßen Modul-Import - verhindert reale Seiteneffekte (Netzwerk-/API-Aufrufe auf echte Daten) durch ein simples `python3 -c "from app import main"` oder den Test-Suite-Import, mutmaßliche Ursache eines realen Datenverlusts auf Dev. (2) `add_source()` prüft jetzt sofort, ob eine angegebene `pdf_upload_id` noch existiert - fehlte die hochgeladene Datei bereits (z. B. veralteter Wert), wurde bisher klaglos eine zum Scheitern verurteilte Quelle angelegt, die später mit der irreführenden Meldung "Texterkennung fehlgeschlagen" abbrach, obwohl die KI-Texterkennung nie aufgerufen wurde; echte KI-Texterkennungsfehler werden zusätzlich jetzt geloggt statt lautlos zu verschwinden |
| v0.49.6 | Fix: Highlight-Text konnte vom Chunk-Text abweichen, wenn das LLM sein "wörtliches" Zitat leicht anders formatiert wiedergibt (z. B. geschütztes Leerzeichen \xa0 aus gecrawltem Text wird zu normalem Leerzeichen) - der exakte String-Vergleich im Frontend fand das Zitat dann nicht mehr; `_find_quote_span()` liefert jetzt die tatsächliche Textspanne aus dem Chunk statt des Modelltexts. Zusätzlich vier neue Tests für `findHighlightRange` (bisher ungetestet) sowie ein Test für korrekte Occurrence-Zuordnung bei verschachtelten Zitatnummern |
| v0.49.5 | Fix: Quellen-Highlighting verschwand teils dauerhaft, wenn eine Antwort denselben Chunk mit identischem Zitat mehrfach referenzierte (seit v0.49.3 durch die treffsichereren Folgefrage-Antworten häufiger) - der Auf-/Zuklapp-Zustand der Quellen-Karten lag redundant in einer Variable je Zitat-Button statt zentral, wodurch er bei geteilten Karten aus dem Takt geriet; `makeCitationsClickable` hatte zuvor keine Testabdeckung, jetzt zwei Regressionstests |
| v0.49.4 | Test-Fix: drei CI-Tests warteten nach einem simulierten langsamen Hintergrund-Import mit einem festen `time.sleep(0.5)` statt zu pollen - auf einem langsameren CI-Runner reichte das nicht, wodurch v0.49.3 fälschlich am CI-Gate scheiterte, ohne den eigentlichen Deploy-Fix zu betreffen (siehe v0.49.3) |
| v0.49.3 | Fix: vage Folgefragen ("Erzähle mehr") lieferten teils "keine Quellen"-Antworten zu Themen, die gerade erst korrekt beantwortet wurden - die Such-Query für Folgefragen wird jetzt per eigenem LLM-Call zu einer eigenständigen, themenspezifischen Suchanfrage umformuliert statt nur Frage-Text zu verketten |
| v0.49.2 | Fix: Cloudflare Turnstile sprang beim Laden der Konversationsseite kurz sichtbar auf/zu (Eingabezeile bzw. die zentrierte Startansicht verschob sich) - Platzbedarf wird jetzt nur noch reserviert, wenn wirklich eine sichtbare Challenge nötig ist |
| v0.49.1 | Sicherheits-Fix: pypdf auf 6.16.1 (behebt zwei Dependabot-Meldungen zu Speicher-/Laufzeit-Erschöpfung bei präparierten PDFs, CVE-2026-71870/CVE-2026-71852) |
| v0.49 | Backlog: Website-Wissensquellen als automatischer Fallback bei dünner Quellenlage (Negativ-/Positivselektion, wöchentlicher Hintergrund-Crawl, dezente Kennzeichnung im Chat, Schnell-Ausschließen-Button für Pfleger:innen); Lorem-Ipsum-Platzhaltertexte werden beim Website-Import erkannt und ausgeschlossen; fehlende Autor:innen/Datum werden in der Konversationsansicht nicht mehr als Platzhaltertext angezeigt |
| v0.48 | Backlog #202: Konversationsverlauf wird an /api/ask mitgeschickt (vermeidet Wiederholungen bei Folgefragen); Mobile-Popover als echtes Akkordeon statt Overlay; Mikrofon-Icon-Sprung beim Laden der Konversationsseite behoben |
| v0.47 | Backlog: serverseitige Duplikat-Prüfung beim Anlegen von Quellen per URL; URL-/Datei-Popover im Quellenverzeichnis auf Mobile über volle Zeilenbreite statt Icon-Spalte |
| v0.46 | Wöchentliche Link-Prüfung + Warn-Badge am "Quellen"-Menüpunkt mit Filter für defekte Quellen |
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
