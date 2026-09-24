# BetaCodex Chat

Ein KI-Wissensassistent, der Fragen zum BetaCodex ausschließlich auf Basis
kuratierter, geprüfter Quellen beantwortet – mit lückenloser Quellenangabe
bis zur Originalstelle.

Live unter **https://chat.betacodex.org**.

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
stellen zu können. Der BetaCodex Chat schließt diese Lücke: eine
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
- Jede Antwort lässt sich per Icon in die Zwischenablage kopieren
  (formatiert und als Klartext, ohne die `[n]`-Verweise).
- Antwortet in der Sprache, in der gefragt wurde – Oberfläche und
  Antworten gibt es auf Deutsch und Englisch, unabhängig voneinander.
- Spam-/Bot-Schutz (Rate-Limiting + Cloudflare Turnstile), ohne dass
  anonymes Fragenstellen dafür ein Login bräuchte.
- Erkennt eine Bitte, selbst einen Text/ein Konzept zu verfassen statt
  eine Faktenfrage – verweist dann freundlich mit vorausgefüllter
  Anweisung auf den Kreativ-Modus, statt einen Zitat-Versuch zu erzwingen.

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
- Persistentes Dokument statt Chat-Verlauf: eine Anweisung im Hauptfeld
  ersetzt jeweils das gesamte Dokument, sichtbar als Live-Stream Wort für
  Wort.
- Abschnittsweises Überarbeiten (Vorschau-Modus, Überschriftenebene): ein
  Stift-Icon direkt neben jedem Abschnitt klappt einen Bereich darunter auf
  (kein Popover, gleiche Bedienung auf Desktop und Mobil) mit Anweisungsfeld
  (inkl. Spracheingabe) und Absenden-Button – überarbeitet wird dann NUR
  dieser eine Abschnitt, der Rest des Dokuments bleibt unangetastet. Das
  Gesamtdokument geht dabei weiterhin als Kontext mit (Ton/Terminologie an
  den Übergängen), nur die Antwort selbst bleibt auf den Abschnitt
  beschränkt. Ein aufgeklappter Bereich schließt einen zuvor geöffneten
  automatisch, eine noch nicht abgeschickte Anweisung bleibt beim Zuklappen
  für die Dauer der Sitzung erhalten.
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
- Der erzeugte Text erscheint nach dem Erzeugen zuerst in der Vorschau;
  "Bearbeiten" und die Abschnitts-Stifte blinken dabei einmal auf. Text und
  Quellenliste bleiben wie die Konversation im Tab erhalten (sessionStorage,
  überlebt Reload/Seitenwechsel); das Icon neben der Überschrift beginnt
  bewusst neu (zweistufige Bestätigung statt Browser-Popup).
- "Text kopieren" legt den Text samt Formatierung (HTML + Markdown-Klartext)
  in die Zwischenablage, ein kurz eingezeichneter grüner Haken bestätigt es.
- Der erste Text erscheint schnell, auch bei recherchelastigen Anfragen: das
  Modell schreibt sofort los und recherchiert erst danach (vorher bis zu
  ~18 s Wartezeit durch mehrere Suchrunden vor dem ersten Wort).
- Dasselbe Werk (Titel + Autor:innen) erscheint in der Quellenliste nur
  einmal, auch wenn es als mehrere Quellen-Datensätze vorliegt.
- Daumen-hoch/-runter unter dem erzeugten Text (in Bearbeiten- wie
  Vorschau-Ansicht, gleiche Komponente wie in der Konversation, Zustand
  bleibt über Reload erhalten). Das Feedback landet mit Anweisung und
  erzeugtem Text im Fragen-Log (Badge "Kreativ-Modus", der Link öffnet die
  Anweisung im Kreativ-Modus).
- Fragen-Log (Quellen-Pfleger:innen): lädt schnell auch bei vielen Einträgen -
  die Liste kommt schlank ohne Antworttexte (jede Antwort erst beim
  Aufklappen), gerendert werden seitenweise 30 Einträge (Nachladen beim
  Scrollen), die Filter wirken trotzdem immer auf den gesamten Bestand.
  Einträge werden nach zwei Jahren automatisch gelöscht (täglicher
  Hintergrund-Job), das Feedback-API kürzt überlange Texte auf 2.000 Zeichen
  Frage/Anweisung bzw. 20.000 Zeichen Antwort/Text.

### MCP-Zugang zum Kreativ-Modus

Der Kreativ-Modus lässt sich auch aus MCP-fähigen Programmen wie Claude
Code nutzen – für einen kleinen, eingeladenen Kreis mit der Rolle
„MCP-Nutzung“.

- Zwei Werkzeuge: `create_text` (neuen Text erzeugen) und `revise_text`
  (bestehenden Text nach einer Anweisung überarbeiten), jeweils auf
  Deutsch oder Englisch und mit abschaltbarer Websuche (Standard: an).
  Ergebnis ist Markdown mit Quellenliste – dieselbe Logik wie in der
  Oberfläche.
- Persönliche Schlüssel auf der Seite „MCP-Zugänge“ (Link im
  Login-Menü): beliebig viele je Konto (z. B. „Laptop“, „Claude Code“),
  einzeln widerrufbar, nur einmal im Klartext sichtbar und nur als Hash
  gespeichert. Wird einem Konto die Rolle entzogen, funktioniert keiner
  seiner Schlüssel mehr.
- Limits je Schlüssel: 30 Aufrufe pro Tag und 5 € pro Monat als
  Voreinstellung, von User-Admins je Schlüssel änderbar.
- Kostenmessung: jeder Kreativ-Aufruf (Oberfläche und MCP) wird mit
  Tokens, Websuchen und Kosten in USD und EUR protokolliert. User-Admins
  sehen die Monatsübersicht je Kanal und Konto und exportieren sie als
  CSV – Grundlage für ein späteres Bezahlmodell (z. B. Monats-Kontingent).
- MCP-Aufrufe erscheinen anonym (Badge „MCP“) im Fragen-Log.

Einrichtung in Claude Code (Schlüssel auf der Seite „MCP-Zugänge“
anlegen, der fertige Befehl wird dort angezeigt):

```bash
claude mcp add --transport http betacodex https://chat.betacodex.org/mcp \
  --header "Authorization: Bearer <dein-schlüssel>"
```

Andere MCP-Clients brauchen dieselben zwei Angaben: die Adresse
`https://chat.betacodex.org/mcp` (Streamable HTTP) und den Header
`Authorization: Bearer <dein-schlüssel>`.

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
- Schlagwort-Ansicht als dritte Sortierung neben Autor:in und Datum: alle
  Schlagworte der gewählten Sprache alphabetisch mit Sprungleiste,
  aufklappbar mit den zugehörigen Quellen, ein Balken zeigt, wie viele
  Quellen ein Begriff verbindet. Quellen-Pfleger:innen können Schlagworte
  dort direkt umbenennen oder (mit Rückfrage) aus allen Quellen löschen –
  protokolliert im Änderungs-Log und pro Quelle rückgängig machbar. Die
  Quellen eines Schlagworts lassen sich dort direkt aufklappen und
  bearbeiten.
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
  Quellenpflege ist `quellen_pfleger` vorbehalten, `mcp_nutzer` erlaubt den
  MCP-Zugang zum Kreativ-Modus, `user_admin` verwaltet Einladungen,
  `system_admin` darf alles. Ein Konto kann mehrere Rollen haben – sie
  werden in der Nutzerverwaltung einzeln per Häkchen vergeben und
  entzogen (Admin-Rollen nur durch System-Admins).
- Jede Änderung an einer Quelle landet diff-basiert in einem
  Änderungs-Log (mit Rückgängig-Funktion) – sichtbar für alle
  Quellen-Pfleger:innen, nicht nur für die handelnde Person.
- Anonymisierte Erstfragen neuer Konversationen werden separat
  protokolliert und helfen dabei, Lücken im Quellenbestand zu erkennen.

### Einbettbar

Die Konversationsansicht lässt sich als schlankes Widget in fremde
Webseiten einbetten (`/embed.html`, eigene, striktere
Content-Security-Policy). Ein kleines rotes Icon oben rechts öffnet den
vollständigen Companion in einem neuen Tab - läuft im Embed bereits eine
Konversation, wird sie dort nahtlos fortgesetzt (kurzlebiges,
einmal abrufbares Server-Handoff statt dauerhafter Speicherung, da
`sessionStorage` pro Tab/Browsing-Context isoliert ist). Dieselbe
Übergabe greift auch beim "Quelle ansehen/bearbeiten"-Link einer
Zitatangabe, der ebenfalls in einem neuen Tab landet.

Das Widget ist unabhängig von einer aktiven Early-Access-Sperre nutzbar -
anonyme Besucher:innen können im Embed direkt fragen, ohne das
Early-Access-Passwort zu kennen. Nur das "Vollständig öffnen"-Icon landet
für sie weiterhin auf der Early-Access-Gate-Seite, da der vollständige
Companion (`/`, `/import.html`) davon unberührt bleibt.

Das generierte `<iframe>`-Snippet passt sich dynamisch zur
Einbettungsumgebung an: die Breite füllt per CSS den verfügbaren Platz bis
zu einer einstellbaren max-width, die Höhe wird per `postMessage` vom Embed
selbst gemeldet (wächst z. B. mit jeder neuen Chat-Nachricht) und vom
kleinen Inline-Skript im Snippet übernommen. Startet standardmäßig auf
Englisch (nicht anhand der Browser-Sprache geraten, da Drittseiten-
Besucher:innen sprachlich nicht zwangsläufig dazu passen) - der
Sprachumschalter bleibt bedienbar.

---

## Wie es funktioniert (RAG)

BetaCodex Chat ist ein **RAG-System** (Retrieval-Augmented
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

**Diagramme:** `docs/diagrams/` enthält drei interaktive HTML-Diagramme
(erzeugt mit dem Archify-Skill) plus ihre JSON-Spezifikationen: der
RAG-Antwortfluss (`rag-flow.*`), die Produktions-Architektur
(`architecture.*`) und der CI/CD-Deploy-Ablauf (`deploy-flow.*`). Bei
architekturell relevanten Änderungen (neue Komponenten, geänderter
Anfrage-/Deploy-Fluss) die passende `.json`-Spezifikation entsprechend
anpassen und über `node ~/.agents/skills/archify/bin/archify.mjs deliver
<type> <spec.json> <output.html> --quality showcase --json` neu ausliefern.

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

### Zwei Instanzen: Dev, Produktion

- **Dev** (`Beta-Kodex - Wissenspartner/`, Port 8000): der aktive
  Arbeitsstand, kann jederzeit kurzzeitig instabil sein
  (Server-Neustarts während der Entwicklung).
- **Produktion** (https://chat.betacodex.org, Hetzner Cloud, CX23,
  Falkenstein, DSGVO-konform): ein einzelner Server mit zwei kompletten
  App-Instanzen ("Blue"/"Green") unter einem eigenen Systembenutzer
  `betacodex`, dahinter Caddy als Reverse Proxy mit automatischem
  Let's-Encrypt-TLS. Beide Instanzen teilen sich `data/` und `.env` per
  Symlink auf ein gemeinsames `shared/`-Verzeichnis; nur der Code
  unterscheidet sich zwischen den beiden Slots. Deployment läuft
  vollautomatisch per GitHub Actions (`.github/workflows/deploy.yml`),
  ausgelöst durch einen Tag-Push: `pytest -q` + `node --check`, bei Erfolg
  SSH zum Server, `deploy.sh <tag>` deployt auf die gerade inaktive Farbe,
  wartet auf einen Health-Check (`/api/version`), schaltet Caddy erst
  danach um und stoppt die alte Farbe – Zero-Downtime, mit automatischem
  Rollback (alte Farbe bleibt live), falls die neue Version nicht startet.
  Unterschiede zu Dev: `ENVIRONMENT` bleibt hier ungesetzt (nicht
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
| v0.73.0 | Konversation: Kopieren-Icon neben den Daumen je Antwort (gleicher Abstand wie zwischen Geschwindigkeit und Daumen) - legt die Antwort formatiert (HTML) und als Klartext (Markdown) in die Zwischenablage, ohne Zitat-Marker `[n]`, kurzer grüner Haken als Bestätigung |
| v0.72.0 | Schlagwort-Ansicht: Quellen lassen sich direkt unter dem Schlagwort aufklappen (Kurzbeschreibung) und bearbeiten - dieselben Zeilen und dasselbe Bearbeiten-Formular wie in der Quellenliste, aufgeklappte Schlagworte bleiben beim Speichern offen. Sicherheit: der SSRF-Schutz prüft jetzt auch jedes Weiterleitungsziel (eigener Redirect-Handler); normale Webseiten laufen dafür nicht mehr über trafilaturas eigenes Networking, sondern über denselben geschützten Abruf - gilt für Quellen-Import und Autor:innen-Fotos |
| v0.71.4 | Schlagwort-Ansicht mobil: nur die Quellenzahl statt "12 Quellen" (voller Text bleibt für Screenreader), Stift und Mülleimer immer nebeneinander rechts neben dem Begriff und vertikal mittig. Quellenliste: Text von Zeilen mit defektem Link steht wieder bündig mit den übrigen Zeilen, nur die Warn-Tönung ragt in den Rand |
| v0.71.3 | Sicherheit: SSRF-Schutz auch beim Abruf von Autor:innen-Fotos (dieselbe Prüfung wie beim Quellen-Import - keine privaten/internen Adressen, nur http/https). Schlagwort-Ansicht: Klick auf eine Quelle springt direkt in die ungefilterte Autor:innen-Ansicht zur Quelle, Quellen-Links wieder in Akzentfarbe; mobil schmalerer Balken (relativ zur Zeile), Silbentrennung und Stift/Mülleimer als Gruppe unter dem Begriff. Explore-Netzwerk wieder in der Breite der Inhaltsspalte (nimmt die volle Bildschirmbreite aus v0.70.0 zurück, die das Scrollen neben dem Diagramm verhinderte) |
| v0.71.2 | Schlagwort-Ansicht barrierefrei: Aufklappen per Disclosure-Button (aria-expanded/aria-controls) statt `<details>`/`<summary>`, damit Stift und Mülleimer nicht mehr in einem `<summary>` stecken (Chrome-Issue). Quellenanzahl in fester, rechtsbündiger Spalte - Balken und Zahlen stehen ruhig übereinander. Schlagwort-Vorschläge in allen Schlagwort-Feldern per Tastatur bedienbar (Pfeiltasten wählen, Enter übernimmt, Escape schließt zuerst nur die Liste). Fix: Vorschlagsliste öffnet sich nicht mehr nachträglich, wenn das Feld während des Ladens schon verlassen wurde |
| v0.71.1 | Quellenübersicht mobil aufgeräumt: Globus-Icon (Website-Wissensquellen) samt Panel und der Defekte-Links-Filter sind auf dem Smartphone ausgeblendet (Schreibtisch-Pflege). Die Sortierung nach Autor:in und Schlagwort bleibt mobil sichtbar - bei Platzmangel fallen zuerst der Datums-Button und "Ähnliche Schlagworte" weg, die ganze Sortier-Leiste erst zuletzt. Der Trennstrich vor der Sortierung erscheint nur noch, wenn links davon Quellen-Pfleger:innen-Icons stehen |
| v0.71.0 | Schlagwort-Ansicht in der Quellenübersicht: dritter Sortier-Button (Tag-Icon wie im Explore-Modus) neben Autor:in/Datum zeigt statt der Quellen alle Schlagworte der gewählten Sprache - alphabetisch mit eigener Sprungleiste, seitenweise nachgeladen, pro Begriff aufklappbar mit den zugehörigen Quellen (Direktlink zur Quelle, Filter-Link auf die Quellenliste) und einem Balken proportional zur Quellenanzahl. Quellen-Pfleger:innen können Schlagworte per Stift umbenennen (Enter speichert, erfasst alle Schreibweisen) oder per Mülleimer zweistufig löschen - über die bestehenden Zusammenführen-/Lösch-Endpunkte, damit im Änderungs-Log und pro Quelle rückgängig machbar |
| v0.70.1 | Fix: echte Root-Cause der seit Tagen bekannten CI-Test-Flakiness gefunden - `done_event.set()` in `_finish_synchronous_import` feuert bewusst VOR der Zusammenfassungs-/Schlagwort-Generierung (Produktionsabsicht: die Antwort soll nicht auf die langsame KI-Zusammenfassung warten), `add_source()` kehrt also zurück, während der Hintergrund-Thread noch weiterläuft - Tests, die direkt danach `sources.json`/`terms.json` lasen oder überschrieben, rasten mit genau diesem Thread (nicht, wie zuvor angenommen, mit einem Thread aus einem VORHERIGEN Test). Die Test-`client`-Fixture wartet jetzt nach jedem HTTP-Aufruf automatisch auf währenddessen neu gestartete Hintergrund-Threads, mit gezieltem Opt-out für die drei Tests, die das asynchrone Zwischenverhalten selbst prüfen |
| v0.70.0 | Explore-Netzwerk: die Legende erklärt jetzt auch, was die Knoten-Farben bedeuten (automatisch erkannte Gruppe eng verwandter Autor:innen/Schlagworte per Louvain-Algorithmus, keine von Hand vergebenen Themen-Labels). Das Diagramm selbst geht jetzt über die volle Bildschirmbreite statt in der 980px-Spalte zu stecken (bricht per CSS aus der site-weiten Spalte aus, zentriert sich zum Viewport), gedeckelt auf 1600px auf Ultrawide-Monitoren, damit Kanten zwischen verwandten Knoten nicht unnötig lang werden - Header/Suchfeld/Legende bleiben bewusst in der schmalen Spalte |
| v0.69.3 | Fix: `[n]`-Zitatverweise zeigen sich während des Streamings nicht mehr als Text mit der rohen, vom Modell vergebenen Nummer (wich von der später fortlaufend neu nummerierten, klickbaren Version ab, wirkte wie ein kurzzeitiger Zahlenwechsel) - während des Streamings werden sie gar nicht erst angezeigt. Fix: eine Quelle mit erkanntem defektem Link wird jetzt nirgendwo mehr verlinkt (Konversationsmodus, Kreativ-Modus-Quellenliste, Quellenverwaltung) - Chunks/Zusammenfassung/Titel bleiben unverändert sichtbar, nur der klickbare Link fällt weg. Fix: der Warn-Hintergrund einer Quelle mit defektem Link bleedete bisher nur nach links aus dem Container-Innenabstand heraus, jetzt symmetrisch auf beiden Seiten. Fix: die Kreativ-Modus-Hinweisbox blieb in einer Zwischenbreite (zwei unabhängig gesetzte Breakpoints liefen auseinander) in der schmalen Spalten-Variante hängen - nutzt jetzt eine Container Query auf den tatsächlichen Umbruchpunkt des Layouts selbst statt eines separat gepflegten Viewport-Breakpoints. Neu: Trennstrich vor den web-bezogenen Werkzeugen in der Quellenverwaltung-Werkzeugleiste; reicht der Platz nicht für alle Icons, wird gestaffelt zuerst die Trennlinie, dann die Sortierung, zuletzt das Icon "Ähnliche Schlagworte" eingespart - die Suche bleibt dabei immer sichtbar. Fix: ein Scroll-Event ohne tatsächliche Bewegung wurde vom einklappenden Header fälschlich als "nach oben gescrollt" gewertet und konnte dadurch kurz aufflackern, besonders in einer zuvor kaum genutzten Zwischenbreite (641-899px), seit dort die Seite überhaupt erst scrollt (v0.68.1) |
| v0.69.2 | Fix: der DNS-Mock aus v0.69.1 patchte versehentlich `socket.getaddrinfo` GLOBAL (ein einziges, geteiltes Modul-Objekt im ganzen Prozess) statt nur die eigene SSRF-Prüfung - dadurch nutzte auch die ECHTE interne DNS-Auflösung von `urllib.request.urlopen()` die gefälschte IP, wodurch Tests mit frei erfundenen Domains (z.B. "cdn.example.org") einen echten, an falschem Host-Header/SNI hängenden Verbindungsversuch auslösten (CI-Lauf dadurch spürbar verlangsamt bzw. hängend). `app/extraction.py` hat jetzt eine eigene, separat mockbare `_getaddrinfo`-Referenz statt `socket.getaddrinfo` direkt zu nutzen |
| v0.69.1 | Fix: der SSRF-Schutz aus v0.69.0 löste in der Testsuite (`tests/test_api.py`) bei jedem `add_source()`-Aufruf mit URL eine echte DNS-Auflösung aus, was in CI die Laufzeit spürbar erhöhte und einen bereits bekannten, zeitkritischen Nebenlauf-Fehler wahrscheinlicher machte (2 zufällig fehlschlagende Tests bei einem Deploy-Versuch). DNS-Auflösung wird jetzt wie andere externe Aufrufe in der `client`-Fixture gemockt - keine echten Netzwerkanfragen mehr in der Suite |
| v0.69.0 | Sicherheit: SSRF-Schutz beim Quellen-Import per URL (Security-Review 2026-09-23) - vor jedem echten Seitenabruf (PDF/Audio-Download, generischer Webseiten-Fetch) werden jetzt alle per DNS aufgelösten IPs des Hostnamens gegen private/interne Adressbereiche geprüft (Cloud-Metadata-Endpunkte, localhost, internes Netz); eine unsichere URL degradiert still zu "nicht extrahierbar", genau wie jeder andere Abruf-Fehlschlag |
| v0.68.2 | Fix: CI-Testsuite war zufällig flaky (unterschiedliche, an `terms.json`/`sources.json` hängende Tests scheiterten bei Reruns) - Ursache war ein beim Import gestarteter Hintergrund-Thread (`_finish_synchronous_import`), der die Datei-Pfade erst beim tatsächlichen Zugriff dynamisch liest; verpasste er sein Warte-Fenster, konnte er unbemerkt in die Dateien eines bereits laufenden, späteren Tests schreiben. Der Test-Teardown wartet jetzt bis zu 15s pro Hintergrund-Thread und lässt den Test laut fehlschlagen, falls danach noch einer lebt, statt ihn still weiterlaufen zu lassen (bewusst kein Warten ohne Zeitlimit, damit ein echter Bug die Suite nicht für immer blockiert) |
| v0.68.1 | Fix: Konversationsmodus scrollte in einer "Zwischengröße" (641-899px Breite, weder Mobile- noch Desktop-Grid-Breakpoint) nicht zuverlässig - `#chat-column` nutzte dort noch die alte feste 70vh-Box mit intern scrollendem `#chat-messages` (verschachtelter Scroll-Container). Jetzt dieselbe Wachsen-mit-Antworttext-Mechanik wie bei Mobile/Desktop (Box wächst, Seite scrollt, Eingabefeld sticky), der äußere Rahmen der Box bleibt dabei erhalten |
| v0.68.0 | Konversationsmodus: Quellen-Titel (Seitenleiste "Verwendete Quellen" und Zitat-Karten-Überschrift) bekommen jetzt direkt neben sich das etablierte "öffnet extern"-Icon statt nur einer dezenten Unterstreichung; eine aufgeklappte Zitat-Karte lässt sich jetzt über ein "×" oben rechts wieder schließen (gleiches Muster wie an anderen Stellen der App). Fix: der Stift zum Bearbeiten des Zielschlagworts im "Ähnliche Schlagworte"-Panel war auf Desktop unsichtbar (betraf eine geteilte Hover-Ausblendregel für Icon-Buttons). Aufräumen nach Impeccable-Design-Review: dicke einseitige Akzent-/Warnrahmen (bekanntes KI-generiert-Muster) durch dünne durchgehende Rahmen bzw. das bereits vorhandene Warn-Icon ersetzt. Sicherheit: die beim Quellen-Anlegen übergebene Upload-ID (PDF/Audio) wird jetzt als echte UUID validiert, bevor sie in einen Datei-/Glob-Pfad einfließt - schließt eine Pfad-Traversal- bzw. Glob-Wildcard-Lücke |
| v0.67.1 | Ähnliche-Schlagworte-Panel: jede Gruppe zeigt jetzt ein DE/EN-Badge, da sich Schreibweisen zwischen den Sprachen mitunter ähneln, ohne gleich zu sein. Jede Variante hat außerdem ein eigenes "×" (immer sichtbar, nur dezent gedimmt - bewusst nicht erst bei Hover eingeblendet, damit es auch auf Touch-Geräten erreichbar ist), um einzelne, nicht passende Schlagworte aus einer Gruppe zu entfernen, ohne gleich die ganze Gruppe ignorieren zu müssen |
| v0.67.0 | Neu: Panel "Ähnliche Schlagworte" in der Quellenverwaltung (eigenes Icon in der Werkzeugleiste) - eine KI-Analyse (Claude Sonnet) prüft die vorhandenen Schlagworte je Sprache auf inhaltliche Nähe (z. B. "hierarchiefreie Organisationen" vs. "hierarchielose Organisation") und schlägt Gruppen mit einem Zielschlagwort vor; jede Gruppe muss einzeln bestätigt werden (Zusammenführen, Ignorieren, oder Alle Schlagworte löschen mit Zweistufen-Bestätigung), automatisches Sofort-Zusammenführen gibt es bewusst nicht. Ein Klick auf eine der Varianten tauscht sie mit dem vorgeschlagenen Zielschlagwort. Die Analyse läuft in alphabetisch sortierten Häppchen und streamt Treffer laufend (gleiches NDJSON-Muster wie `/api/ask`), damit die ersten Vorschläge deutlich früher zur Bearbeitung erscheinen statt erst nach dem kompletten Durchlauf über oft 1000+ Begriffe. Beide Aktionen (Zusammenführen/Löschen) protokollieren jede betroffene Quelle im bestehenden Änderungs-Log und sind darüber einzeln rückgängig machbar. Dazu: die automatische KI-Generierung neuer Schlagworte (Import und "Zusammenfassung neu generieren") bekommt jetzt die bereits etablierten Begriffe der Sammlung als Kontext, damit sie einen passenden vorhandenen Begriff bevorzugt, statt eine neue Formulierung fürs selbe Thema zu erfinden |
| v0.66.0 | Import: eine Quelle gilt in der Fortschrittsanzeige jetzt bis zum Abschluss der Zusammenfassungs-/Schlagwort-Generierung als "in Arbeit" (eigener Schritt "Zusammenfassung & Schlagworte werden erstellt"), statt schon vorher auf "fertig" zu springen. Schlagworte werden beim manuellen Bearbeiten jetzt wie in einem modernen Tagging-System vorgeschlagen (`/api/terms`, gefiltert nach der aktuell eingestellten Sprache - `terms.json` unterscheidet dafür jetzt zwischen DE/EN, bestehende Begriffe einmalig migriert) - funktioniert auch für einen Begriff MITTEN in der kommagetrennten Liste, nicht nur für den zuletzt getippten. Konversationsmodus: jedes `[n]`-Zitat im Antworttext bekommt jetzt eine eigene, fortlaufende Anzeige-Nummer (statt sich bei mehrfacher Zitation derselben Quelle zu wiederholen), pro Antwort wieder bei 1 beginnend. Fix: eine Quelle mit mehreren Autor:innen öffnete im Autor:innen-Modus beim Bearbeiten alle ihre Zeilen (eine pro Autor:in) gleichzeitig als Formular statt nur der angeklickten - `activeEditId` berücksichtigt jetzt zusätzlich, unter welcher Autor:in-Überschrift die konkrete Zeile steht |
| v0.65.0 | Kreativ-Modus: Daumen-Feedback unter dem erzeugten Text (Bearbeiten- und Vorschau-Ansicht, gemeinsame Komponente `static/answer-feedback.js` mit der Konversation, Zustand bleibt über Reload erhalten); das Feedback landet mit Anweisung und erzeugtem Text im Fragen-Log (`mode: "creative"`, Badge "Kreativ-Modus", Link öffnet die Anweisung im Kreativ-Modus). Fragen-Log: schlanke Liste ohne Antworttexte (Antwort erst beim Aufklappen, `GET /api/question-log?include_answers=false` + `GET /api/question-log/{id}`), seitenweises Rendern per Sentinel/IntersectionObserver (30 Einträge, Filter wirken auf den gesamten Bestand), automatische Löschung von Einträgen nach zwei Jahren (täglicher Hintergrund-Job, Datenschutzerklärung angepasst), Feedback-Texte werden auf 2.000 (Frage/Anweisung) bzw. 20.000 Zeichen (Antwort/Text) gekürzt |
| v0.64.2 | Fix: Alphabet-Sprungleiste in der Quellenübersicht braucht mobil (375-430 px Breite) nur noch zwei statt drei Zeilen - Buchstabenabstand und -breite minimal reduziert |
| v0.64.1 | Explore-Icon im Header: Verbindungen zwischen den Knoten jetzt als gepunktete Linien (drei Punkte je Verbindung, kleinere Knoten). Aufräumen nach Ponytail-Audit: gemeinsames `app/jsonstore.py` ersetzt 13 fast identische JSON-Laden/Speichern-Paare (Schreiben jetzt überall atomar mit eindeutigem Temp-Dateinamen, Lese-Verhalten je Modul unverändert), tote CSS-Regeln, ungenutzte i18n-Schlüssel und Funktionen entfernt, `devUserHeaders()` in `jsonHeaders()` umbenannt |
| v0.64.0 | Kreativ-Modus: erster Text erscheint deutlich schneller (System-Prompt-Regel "sofort losschreiben, dann recherchieren" statt bis zu drei Suchrunden vor dem ersten Wort, gemessen ~18 s → ~2-5 s); erzeugter Text zuerst in der Vorschau, "Bearbeiten" und Abschnitts-Stifte blinken einmal auf; Text UND Quellenliste bleiben per sessionStorage über Reload/Seitenwechsel erhalten; neuer "Neu anfangen"-Button neben der Überschrift (zweistufige Bestätigung statt `confirm()`-Popup); neuer "Text kopieren"-Button (HTML + Markdown-Klartext) mit animiertem grünem Haken; dasselbe Werk (Titel+Autor:innen) erscheint nur einmal in der Quellenliste (Eintrag mit Link gewinnt). Feedback-Formular im Footer: nach dem Absenden ist nach 60 s Cooldown (kleiner Rückwärts-Timer) erneut Feedback möglich |
| v0.63.7 | Drei Fixes aus derselben Nutzer-Review des Ackoff-Falls: (1) Zitat-Highlighting fand die vom Modell im ---QUOTES---Block wörtlich zitierte Textstelle nicht, wenn die Quelle (gecrawlt/PDF) typografische Anführungszeichen/Apostrophe (’‘“”) nutzte, das Modell aber gerade ('/"") - `_find_quote_span()` bildet beide Varianten jetzt auf dieselbe Zeichenklasse ab; bei mehrfach zitierter Quelle konnte das zuvor zum Highlight der JEWEILS ANDEREN Textstelle führen. (2) "Automatically switched to English"-Hinweis erschien fälschlich bei einer durchgehend deutschen Antwort, wenn diese ein langes wörtliches fremdsprachiges Zitat enthielt - `detectTextLanguage()` blendet Text in Anführungszeichen jetzt vor der Spracherkennung aus. (3) Eine Frage, die z. B. sowohl "erste Frage" als auch "keine Antwort gefunden" war, erschien im Fragen-Log als zwei separate, identisch aussehende Einträge - `event_type` ist jetzt `event_types` (Liste), passende Ereignisse werden in denselben Eintrag zusammengeführt (`question_log.add_event_type`/Text-Abgleich bei Feedback) statt dupliziert; Filter zeigen einen Eintrag, sobald mindestens eines seiner Labels aktiv ist |
| v0.63.6 | Fix: `authors.find_mentioned()` erkannte eine Autor:in bisher nur, wenn der VOLLE registrierte Name wörtlich in der Frage vorkam - dadurch wurde der Autor:innen-Boost (gezielte Suche in den Quellen dieser Person, siehe `AUTHOR_MENTION_DISTANCE_FACTOR`) weder bei reiner Nachnamen-Nennung ("Texte von Ackoff") noch bei Tippfehlern im Vornamen ("Russel" statt "Russell") ausgelöst, obwohl die Quellen der Person real vorhanden waren. Erkennt jetzt zusätzlich den Nachnamen allein (Wortgrenze) sowie Tippfehler-nahe Schreibweisen des Nachnamens (`difflib.get_close_matches`, Cutoff 0.8, erst ab 4 Zeichen Nachnamenlänge) - reiner Vorname allein bleibt bewusst außen vor (zu mehrdeutig) |
| v0.63.5 | Fix: fett gesetzte Zwischenüberschriften ohne "#"-Markdown-Syntax (nur eine eigene fett gesetzte Zeile, z. B. "**§1 Titel**" gefolgt von Fließtext) wurden fälschlich zu klickbaren, roten Schlagwort-Links - `makeTermsClickable()` erkennt jetzt strukturell, ob ein `<strong>` seine Zeile komplett für sich allein einnimmt (davor/danach nur Zeilenumbruch oder Absatzgrenze) und behandelt es dann wie eine echte Überschrift (schwarz, nicht klickbar); echte Inline-Fachbegriffe bleiben unverändert klickbar/rot |
| v0.63.4 | Fix: eine Überschrift, die das Modell zusätzlich fett markierte ("## **Titel**"), wurde fälschlich zum klickbaren, roten Schlagwort-Link statt schwarzer, nicht-klickbarer Überschrift zu bleiben - Ursache war ein verschachteltes `<strong>` durch die bisherige Verarbeitungsreihenfolge (erst Fett-Ersetzung, dann Überschriften-Erkennung) in `renderMarkdown()` |
| v0.63.3 | Fix: klickbare Schlagwort-Begriffe in Antworten (Folgefragen-Links auf fett hervorgehobene Begriffe, `.term-followup`) waren nur beim Hover im Akzent-Rot eingefärbt - jetzt dauerhaft im App-üblichen Rot sichtbar, fett kommt weiterhin vom umschließenden `<strong>` |
| v0.63.2 | Fix: der "Absenden"-Button im Feedback-Popover im Footer war auf dem Desktop unnötig breit (full-width) - jetzt rechtsbündig direkt unter der Textbox |
| v0.63.1 | Fix: Links auf den Rechtstext-Seiten (Datenschutz/Impressum) fielen auf die Browser-Standardfarbe (Blau) zurück statt die App-Akzentfarbe zu nutzen - jetzt konsistent zum Rest der App. Fix: E-Mail-Adresse im Impressum (DE+EN) als HTML-Entities statt Klartext kodiert, für Menschen identisch lesbar, aber ohne literales "@" im rohen Quelltext, das einfache Spam-Bot-Scraper erkennen könnten |
| v0.63.0 | Neu (Livegang-Vorbereitung): automatische Sprachumschaltung im Konversations- und Kreativ-Modus (Haupt-Website + Embed) anhand der tatsächlichen Antwort/des erzeugten Dokuments, mit kurzem Hinweis im Chat bzw. über der Kreativ-Textbox (30s Auto-Hide); Standard-Sprache jetzt überall Englisch; responsives Embed-iframe (Breite/Höhe passen sich der Einbettungsumgebung an, Mobil-Erkennung bleibt korrekt); Rename "BetaCodex Companion" → "BetaCodex Chat" überall im Code/Header/Mails/Manifest; eigene Impressum-Seite (DE+EN) statt externem Link; Early-Access-Sperre per Feature-Toggle deaktivierbar (Code bleibt für Reaktivierung erhalten); Look-and-Feel (Button-Rundung/-Padding) an betacodex.org/home angeglichen; Datenschutzerklärung an tatsächliche Funktionen angeglichen (u. a. Speicherung von erster Frage/unbeantworteten Fragen/Feedback korrekt dokumentiert) plus laienverständliche "In Kürze"-Zusammenfassung; vollständiger Navigations-Header auch auf den vier Rechtstext-Seiten; Fragen-Log: Einträge einzeln löschbar, Antwort zur ersten Frage wird jetzt mitgespeichert |
| v0.62.2 | Fix: Konsolen-Warnung "[Cloudflare Turnstile] Unable to find onload callback 'onTurnstileLoad'" auf allen Seiten mit Cloudflare-Turnstile-Einbindung (`index.html`, `import.html`, `explore.html`, `creative.html`, `embed.html`, `question-log.html`, `changelog.html`) entfernt - der `?onload=onTurnstileLoad`-Query-Parameter im `<script>`-Tag verlangte, dass der Callback schon existiert, wenn Cloudflares async geladenes SDK fertig ist, was das als ES-Modul deferred ausgeführte `turnstile.js` nicht immer schaffte. Rein kosmetisch (ein bereits vorhandener Fallback hielt die Funktion intakt), aber verwirrend in der Konsole. `turnstile.js` prüft jetzt direkt (per kurzem Polling) auf `window.turnstile`, ohne noch auf einen Callback angewiesen zu sein - `?onload=` und das jetzt überflüssige `defer` sind aus allen sieben `<script>`-Tags entfernt |
| v0.62.1 | Fix (intern, keine Verhaltensänderung): zwei mechanische Code-Duplikate entfernt (ponytail-Audit) - `tests/test_frontend_js.py` nutzt jetzt einen gemeinsamen `_run_node()`-Helfer statt 36 identischer `subprocess.run`/`json.loads`-Stellen, `app/main.py` bündelt die fünf wortgleichen Sleep-Loop-Hintergrund-Worker (URL-Gesundheits-Check, Quellenvorschlag-Suche, Zusammenfassungs-Nachzug, Autor:innen-Foto-Cache, Web-Allowlist-Crawl) in einer generischen `_run_periodic()`. Takt, Fehlerbehandlung und alle `_..._once()`-Funktionen unverändert, 952/952 Tests weiterhin grün |
| v0.62.0 | Neu: das Embed-Widget (`/embed.html`) ist jetzt auch nutzbar, ohne die Early-Access-Sperre aufzuheben - bisher fing die Early-Access-Middleware das Widget selbst sowie all seine JS-/API-Abhängigkeiten (u. a. `/api/ask`, `/api/turnstile-config`, `/api/auth/whoami`) ab, obwohl `EMBED_ENABLED` und `EARLY_ACCESS_PASSWORD` technisch unabhängige Schalter sind - beide waren bisher faktisch dennoch aneinander gekoppelt. Das "Vollständig öffnen"-Icon führt für anonyme Embed-Besucher:innen bewusst weiterhin zur Early-Access-Gate-Seite, da der vollständige Companion selbst nicht mitfreigegeben wird |
| v0.61.7 | Fix: Tippfehler in der v0.61.6-Überschrift für Nutzer:innen ohne Quellen-Pfleger:innen-Rolle - "Zugrundliegende" → "Zugrundeliegende Quellen" |
| v0.61.6 | Fix: die Quellenverwaltung zeigte für Nutzer:innen ohne Quellen-Pfleger:innen-Rolle irreführend "Quellen verwalten" als Überschrift, obwohl sie dort nichts verwalten können, nur die bereits importierten Quellen einsehen - zeigt für sie jetzt "Zugrundliegende Quellen" ("Underlying sources") |
| v0.61.5 | Fix: in der Konversationsansicht konnte dieselbe Quelle mehrfach in der Sidebar erscheinen, wenn zwei verschiedene `[n]`-Verweise auf unterschiedliche Chunks derselben Quelle zeigten (identisch aussehende Einträge, dedupliziert wurde bisher nach chunk_id statt nach source_id). Fix: der automatische Link-Check meldet gelegentlich einen tatsächlich funktionierenden Link fälschlich als nicht erreichbar - Quellen-Pfleger:innen können den Link jetzt im Bearbeiten-Panel nach eigener manueller Prüfung selbst als geprüft markieren (setzt den Status zurück bis zur nächsten automatischen Prüfung, im Änderungs-Log protokolliert und dort rückgängig machbar). Fix: nahm man einen Quellenvorschlag an, während man tief in der Vorschlagsliste gescrollt war, blieb das sich öffnende Import-Formular im mobilen Akkordeon-Modus außerhalb des sichtbaren Bereichs - scrollt jetzt automatisch dorthin |
| v0.61.4 | Fix: der Abstand zwischen den Daumen-hoch/-runter-Icons pro Antwort war zu gering (`gap: 0.15rem`) - auf `0.5rem` erhöht |
| v0.61.3 | Fix: Zeilen mit einem `[n]`-Quellenverweis hatten in der Konversationsansicht sichtbar mehr Abstand zur vorherigen Zeile als Zeilen ohne Verweis, innerhalb desselben Absatzes - `vertical-align: super` beim Zitat-Button lässt Browser die Zeilenbox der gesamten Zeile anhand der hochgestellten Position berechnen. Ersetzt durch `position: relative` mit negativem `top`-Versatz und `line-height: 0` - verschiebt die Zahl weiterhin optisch nach oben, ohne die Zeilenbox zu beeinflussen |
| v0.61.2 | Fix: der Klick auf eine Frage im Fragen-Log löste weiterhin keine Antwort aus (v0.61.1 behob nur einen Teilaspekt) - der `?q=`-Auto-Submit stand im Code VOR der Registrierung des questionForm-submit-Handlers. requestSubmit() löste das "submit"-Event dadurch ohne registrierten Handler (der e.preventDefault() aufruft) aus - die native Browser-Formular-Absendung griff (ein echter Seiten-Reload, da das Formular kein eigenes action/method hat), was exakt zum gemeldeten Bild-Flackern, der verschwindenden Frage und der nie ankommenden Antwort passt. Der Aufruf steht jetzt nach der Handler-Registrierung |
| v0.61.1 | Fix: der Klick auf eine Frage im Fragen-Log (öffnet den Konversationsmodus in einem neuen Tab und stellt die Frage automatisch, `?q=`-Parameter) zeigte zwar die Frage an, das Absenden schlug aber fehl - das automatische Absenden feuerte quasi sofort beim Laden, oft bevor das extern nachladende Cloudflare-Turnstile-Widget bereit war, wodurch mit leerem Captcha-Token gesendet und vom Server abgelehnt wurde. Wartet jetzt auf dieselbe Bereitschafts-Zusage wie der normale Versand (mit 5s-Obergrenze) |
| v0.61.0 | Neu: das Fragen-Log kennt jetzt zwei weitere Ereignistypen neben der ersten Frage jeder Konversation - "Keine Antwort gefunden" (automatisch geloggt, wenn der Companion laut eigener Systemanweisung nicht/nur teilweise antworten konnte, inkl. Frage und Antwort) und "Feedback" (Daumen-hoch/-runter je Antwort im Konversationsmodus, mit kurzer Bestätigungsanimation, die dauerhaft als grüner Haken stehen bleibt - ein zweites Feedback zur selben Antwort ist danach nicht mehr möglich). Das Fragen-Log selbst hat eine sticky, rechtsbündige Filterleiste nach Ereignistyp bekommen, jede protokollierte Frage ist ein Link, der den Konversationsmodus in einem neuen Tab mit genau dieser Frage automatisch startet (zum Nachvollziehen gemeldeter Fälle und Testen von Quellenverbesserungen), die vollständige Antwort steht dabei standardmäßig eingeklappt |
| v0.60.6 | Fix: das Explore-Netzwerk (`/explore.html`) stürzte auf Mobilgeräten beim Navigieren/Klicken im Netzwerk ab - `loading="lazy"` auf den SVG-Autor:innen-Fotos wird von praktisch keinem Browser unterstützt, alle (potenziell hochauflösenden) Fotos wurden dadurch entgegen der ursprünglichen Absicht sofort und gleichzeitig dekodiert, was auf speicherknappen Geräten den Tab abstürzen lassen konnte - die Foto-URLs werden jetzt in kleinen, zeitversetzten Gruppen gesetzt. Fix: wechselte man aus dem Embed-Snippet über das "Vollständig öffnen"-Icon in den vollständigen Companion, startete der neue Tab immer in der geraten/gespeicherten statt der im Embed gewählten Sprache - wird jetzt als `?lang=`-Parameter mitgegeben und im neuen Tab übernommen |
| v0.60.5 | Fix: eine Frage nach einer registrierten Autor:in zu einem konkreten Thema ("Erzähle mir etwas über Andreas Schlegel und Zeitorientierung") fand keine Antwort, obwohl eine passende eigene Quelle existierte - sie lag rein embedding-mäßig weiter vom Anfrageembedding entfernt als andere, thematisch unpassende Quellen derselben Person, ein einheitlicher Autor:innen-Rabatt änderte daran nichts. Die Autor:innen-gefilterte Suche läuft jetzt pro Quelle statt gemeinsam über alle Chunks, und stimmt ein kuratiertes Schlagwort (`key_terms_de`/`key_terms_en`) einer Quelle wörtlich mit der Frage überein, bekommt sie einen deutlich stärkeren Rabatt als die reine Namens-Erwähnung |
| v0.60.4 | Fix: in der Quellenliste bekamen nur Autor:innen mit mehr als einer Quelle eine eigene Zwischenüberschrift, alle anderen erschienen ohne - jede Autor:in bekommt jetzt unabhängig von der Quellenanzahl ihre eigene Überschrift, dadurch nicht mehr nötige Sonderlogik entfernt |
| v0.60.3 | Fix: die Quellenverwaltung lud bei jedem Seitenaufruf den kompletten Volltext aller Quellen mit (mehrere MB, nur für die client-seitige Volltextsuche nötig), wodurch die Liste erst nach spürbarer Verzögerung erschien - die sichtbare Liste lädt jetzt zuerst, der Volltext wird danach im Hintergrund nachgeladen (Bearbeiten-Formular/Deep-Link warten darauf, damit nie mit leerem Text gespeichert werden kann). Dazu serverseitig `encode zstd gzip` in der Caddy-Konfiguration aktiviert - alle Antworten (HTML/JS/CSS/JSON) werden jetzt komprimiert ausgeliefert, was insbesondere die Quellenliste zusätzlich beschleunigt |
| v0.60.2 | Fix: die Konversation im Embed-Widget (`/embed.html`) war fest auf Deutsch verdrahtet, obwohl der Companion nicht weiß, in welcher Sprache die einbettende Seite läuft - der bereits im Header vorhandene DE/EN-Sprachumschalter erscheint jetzt auch im Embed, oben rechts direkt links neben dem "Vollständig öffnen"-Icon |
| v0.60.1 | Fix: der sticky Header flackerte auf dem Handy beim Scrollen mit aufliegendem Finger (kurze Auf-/Ab-Ticks lösten sofortiges Ein-/Ausblenden in schneller Folge aus) - das Wiedereinblenden bekommt jetzt eine kurze, durch jeden Abwärts-Tick abbrechbare Verzögerung, das Ausblenden bleibt sofort. Fix: ein per Konversations-Handoff eingelöstes Token löschte beim Aufräumen der Adresszeile versehentlich die GESAMTE Query-Zeile statt nur sich selbst - dadurch verschwand z.B. `?edit=<id>` beim "Quelle bearbeiten"-Link aus der Konversationsansicht mit, die Quellenübersicht öffnete sich dann ohne die eigentlich verlinkte Quelle. Fix: Tracking-Parameter (`utm_*`, `fbclid`, `gclid`, ...) in importierten URLs führten zu Duplikaten, da dieselbe geteilte Seite je nach Anhang wie eine andere URL wirkte - werden jetzt vor Duplikat-Prüfung und Speicherung entfernt (kuratierte Liste, funktionale Parameter bleiben erhalten). Fix: nach erfolgreichem Quellen-Import wurde nicht mehr zu den Quelltyp-Icons zurückgescrollt, die auf einem langen Formularinhalt aus dem Sichtbereich gerutscht waren. Dazu zwei größere Ergänzungen im selben Zug: zitierte Quellen erscheinen jetzt auch mobil (unterhalb der Eingabe, mit Trennlinie), und Fragen nach den Arbeiten einer registrierten Autor:in ("Erzähle mir etwas über die Arbeiten von X") finden jetzt zuverlässig deren eigene Quellen, auch wenn die reine Themen-Vektorsuche sie verfehlt hätte |
| v0.60.0 | Neu: "Vollständig öffnen"-Icon im Embed-Widget (`/embed.html`, oben rechts, klein und rot) - öffnet den vollständigen Companion in einem neuen Tab und führt eine bereits laufende Konversation dort nahtlos fort. Da `sessionStorage` bewusst pro Tab gilt und zusätzlich pro Top-Level-Browsing-Context partitioniert ist, geht das über ein kurzlebiges, einmal abrufbares Server-Handoff (`POST`/`GET /api/conversation-handoff`, Token verfällt nach 5 Minuten oder direkt nach dem ersten Abruf - kein dauerhafter Konversations-Speicher). Dieselbe Lösung behebt nebenbei einen zweiten, bereits bestehenden Fall: der "Quelle ansehen/bearbeiten"-Link einer Zitatangabe öffnet ebenfalls einen neuen Tab (`/import.html`) und ließ die Konversation bisher dort zurück - ein Klick auf den "Konversation"-Link im gemeinsamen Header führt sie im selben Tab jetzt automatisch fort. Gilt unverändert auch außerhalb des Embeds |
| v0.59.0 | Neu: abschnittsweises Überarbeiten im Kreativ-Modus (Überschriftenebene) - statt jede Anweisung das gesamte Dokument neu schreiben zu lassen, klappt ein Stift-Icon neben jedem Abschnitt in der Vorschau einen Bereich direkt darunter auf (kein Popover, identische Bedienung auf Desktop/Mobil inkl. rundem Absenden-Button und Spracheingabe wie in der Konversationsansicht) - überarbeitet wird dann nur dieser eine Abschnitt, das Gesamtdokument bleibt als Kontext erhalten (Ton/Terminologie an den Übergängen), der Rest des Dokuments unangetastet. Nur ein Bereich gleichzeitig geöffnet, eine noch nicht abgeschickte Anweisung übersteht das Zuklappen für die Dauer der Sitzung |
| v0.58.0 | Vier Fixes rund um die Einbetten-Funktion (`/embed.html`), die beim Reaktivieren der zuvor bewusst ausgetoggelten Funktion auffielen: (1) drei Tests zum `EMBED_ENABLED`-Feature-Flag hingen von einer unkontrollierten Ambient-Umgebungsvariable statt expliziter Testisolation ab. (2) Der "auf Mobile ausgeblendet"-Effekt für den Einbetten-Link im Footer griff faktisch nicht - eine spätere, unbedingte CSS-Regel gleicher Spezifität überschrieb die Media-Query-Regel. (3) Das seit v0.57.5 gefixte "Mikrofon-Icon springt beim Laden"-Problem war nur in `index.html` behoben, `embed.html` (eigenständige, nicht per Template geteilte Kopie derselben Eingabezeile) blieb auf dem alten, fehlerhaften Stand - jetzt nachgezogen, plus Regressionstest über beide Dateien. (4) Ein per Markdown-Link erzeugter Link in einer Konversationsantwort (z. B. der Verweis auf den Kreativ-Modus) blieb ungestylter Standard-Browser-Link - neue generelle Styling-Regel deckt auch künftige Links ab. Dazu: Konversations-Platzhalter vereinfacht ("Stelle eine Frage"/"Ask a question"), Footer-Reihenfolge geändert und der Beta-Hof-Beratungslink daraus vollständig entfernt |
| v0.57.5 | Die Konversationsansicht erkennt jetzt, wenn eine Anfrage eigentlich eine Bitte ist, selbst einen Text/ein Konzept zu verfassen (z. B. "Schreib mir einen Blogartikel über...") statt eine Faktenfrage - statt eines Zitat-Versuchs antwortet sie dann kurz und freundlich mit einem Link auf den Kreativ-Modus, der die ursprüngliche Frage direkt als Anweisung vorausfüllt. Die Ziel-URL wird dabei serverseitig deterministisch und korrekt URL-kodiert erzeugt, nicht vom Modell selbst. Dazu unterstützt die Chat-Antwort-Darstellung jetzt erstmals `[Text](URL)`-Markdown-Links |
| v0.57.4 | Explore-Suche zoomt/schwenkt jetzt automatisch so, dass die gefundenen Knoten im sichtbaren Fenster erscheinen (bisher wurden Nicht-Treffer nur abgedunkelt, ein Treffer außerhalb des aktuellen Ausschnitts blieb unsichtbar) - debounced (400ms) gegen ruckartige Kameraschwenke beim Tippen, greift erst ab drei eingegebenen Zeichen (bei 1-2 Zeichen sind Treffer meist noch zu unspezifisch), leere Suche zoomt symmetrisch zurück auf die Standardansicht |
| v0.57.3 | Neu: Spracheingabe (Mikrofon-Button, Live-Transkript) auch für das Anweisungsfeld im Kreativ-Modus, wie im Konversationsmodus inklusive automatischem Absenden nach Sprechende - Button bleibt oben an der Textbox ausgerichtet, auch wenn diese durch Diktat-Text mitwächst. Fix: flakigen Test `test_get_author_photo_serves_cached_file` behoben - pollte nicht auf den Hintergrund-Thread des Foto-Cachings, sondern verließ sich auf ein festes `time.sleep(0.1)`, das auf einem ausgelasteten Runner gelegentlich nicht reichte |
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
