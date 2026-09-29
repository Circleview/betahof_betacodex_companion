# Wie BetaCodex Chat beim Beta-Kodex bleibt

[English version](HOW-IT-WORKS.md)

Erfahrungen aus dem Bau von [BetaCodex Chat](https://chat.betacodex.org) für alle
im Beta-Kodex-Netzwerk, die selbst KI-Werkzeuge bauen. Das Dokument beschreibt,
was im Code steckt, und vor allem, warum es so ist. Die Zahlen in der Tabelle am
Ende werden aus dem Code erzeugt, ein Test hält den Text aktuell (siehe
[Wie dieses Dokument aktuell bleibt](#wie-dieses-dokument-aktuell-bleibt)).

## 1. Nichts wurde trainiert

Das Sprachmodell kennt den Beta-Kodex nicht besser als jedes andere. Wir haben es
weder trainiert noch feinabgestimmt. Dass die Antworten beim Beta-Kodex bleiben,
liegt an drei Hebeln, die jede:r ohne Machine-Learning-Kenntnisse nachbauen kann:

1. **Kuratierte Quellen.** Das Modell sieht nur Texte, die Quellen-Pfleger:innen
   importiert haben. Die Qualität der Antworten hängt direkt an dieser Auswahl.
2. **Die Suche.** Zu jeder Frage werden wenige passende Textausschnitte gesucht.
   Nur diese bekommt das Modell zu sehen. Was die Suche nicht findet, kann das
   Modell nicht verwenden.
3. **Die Anweisungen.** Der System-Prompt verpflichtet das Modell, nur aus diesen
   Ausschnitten zu antworten und jede Aussage zu belegen. Code prüft und
   korrigiert danach, was das Modell trotzdem falsch macht.

Dieses Muster heißt RAG (Retrieval-Augmented Generation). Die Grundlagen stehen
in der [README](../README.md#wie-es-funktioniert-rag). Hier geht es um die
Details, die in der Praxis den Unterschied gemacht haben.

## 2. Die Quellen

- **Import:** URL, PDF, YouTube, Audio oder eingefügter Text
  (`app/extraction.py`). Der Text wird in überlappende Abschnitte zerlegt
  (`app/chunking.py`), die an Satzgrenzen enden. Jeder Abschnitt trägt Titel,
  Autor:innen, Datum und URL mit. Nur deshalb kann jede Antwort ihre Quelle nennen.
- **Embeddings lokal:** Ein mehrsprachiges Modell (`app/embeddings.py`) läuft auf
  dem eigenen Server. Die Suche kostet dadurch nichts pro Anfrage und funktioniert
  über Sprachgrenzen: Eine englische Frage findet deutsche Texte.
- **Zusammenfassungen und Schlagworte** erzeugt beim Import eine KI
  (`app/summarization.py`), auf Deutsch und Englisch. Pfleger:innen können sie von
  Hand überschreiben. Die Schlagworte sind später für die Suche wichtig (Abschnitt 3).
- **Relevanzscore 1–10** je Quelle: Kernquellen rutschen in der Suche etwas nach
  vorn, Randquellen etwas nach hinten. Score 5 ändert nichts.
- **Freigegebene Websites** (`app/web_allowlist.py`, `app/web_crawler.py`):
  Pfleger:innen können ganze Websites oder Blogs freigeben, zum Beispiel flipping-points.org. Sie
  werden wöchentlich indiziert und in jeder Suche mit durchsucht.
- **Die öffentliche Quellenliste** liegt unter
  [`docs/sources/`](sources/QUELLEN.md), auch als JSON und ohne Volltexte.

## 3. Konversationsmodus: nur belegte Antworten

### Die Suche

Ablauf pro Frage (`app/main.py`, Funktion `ask`):

1. **Folgefragen umformulieren.** „Erzähl mehr“ oder „und bei Scrum?“ sind für eine
   Suche wertlos. Ein schneller Modell-Aufruf formuliert daraus mit dem
   Gesprächsverlauf eine eigenständige Suchanfrage (`rewrite_followup_query` in
   `app/llm.py`). Vorher landete die Suche bei vagen Folgefragen komplett neben dem
   Thema, und das Modell behauptete, es gebe keine Quellen.
2. **Vektorsuche mit Reserve.** Es werden mehr Kandidaten geholt als gebraucht,
   aus den kuratierten Quellen und den freigegebenen Websites zugleich.
3. **Neu sortieren** nach Ähnlichkeit, gewichtet mit dem Relevanzscore. Doppelte
   Texte belegen nur einen Platz.
4. **Genannte Autor:innen.** Steht ein bekannter Name in der Frage, wird zusätzlich
   in jeder Quelle dieser Person gesucht, und ihre Treffer bekommen einen Vorteil.
   Einen deutlich größeren bekommen sie, wenn auch ein Schlagwort der Quelle in der
   Frage vorkommt. Auslöser war eine Frage nach einem Autor und einem seiner
   Fachbegriffe: Die passende Quelle verlor gegen lange Podcast-Transkripte
   derselben Person zu ganz anderen Themen.
5. **Hybrid-Suche.** Begriffe in Anführungszeichen und bekannte Schlagworte der
   Sammlung (auch gebeugt, etwa „Zellstrukturen“) bekommen garantiert einen
   Ausschnitt, der sie wörtlich enthält.

Warum Schritt 5 nötig war: Reine Vektorsuche erfasst Bedeutung, aber schlecht
seltene Eigennamen und Fachbegriffe. Bei „Was ist {Schlagwort}?“ enthielt nur in
56 % der Fälle überhaupt ein Ausschnitt den gefragten Begriff (82 Schlagworte, u. a.
Doppelmanagement, NUMMI, John Seddon). Mit der Hybrid-Suche waren es 100 % der
Stichprobe. Gemessen wird ohne Modellkosten mit `tools/retrieval_eval.py`.

### Die Anweisungen

Die System-Prompts stehen in `app/llm.py` (`SYSTEM_PROMPTS`, Deutsch und Englisch).
Die wichtigsten Regeln:

- Ausschließlich Informationen aus den mitgelieferten Ausschnitten. Kein
  Trainingswissen, keine Spekulation.
- Jede Aussage bekommt einen Verweis `[1]`, `[2]` am Satzende.
- Nach der Antwort folgt ein Block mit dem **wörtlichen Zitat** je Verweis. Der Code
  sucht dieses Zitat im Originaltext und hebt es in der Quellenansicht hervor. So
  können Leser:innen jede Aussage in Sekunden prüfen.
- Geben die Ausschnitte nur einen Teil her, antwortet das Modell mit diesem Teil und
  nennt die Lücke am Ende. Nur wenn gar nichts passt, kommt ein fest vorgegebener
  Absage-Satz.
- Bittet jemand um einen Text („Schreib mir einen Blogpost …“), verweist die
  Antwort auf den Kreativ-Modus, statt aus Ausschnitten einen Blogpost zu basteln.

### Was wir über Prompts gelernt haben

- **Nähe schlägt Position.** Regeln weit oben im System-Prompt wurden bei langem
  Kontext ignoriert: Englische Fragen bekamen deutsche Antworten, und das Modell
  sagte zu oft ab, obwohl es Teilantworten gab. Dieselbe Regel noch einmal direkt
  **nach** der Frage (`_LANGUAGE_REMINDERS`, `_PARTIAL_ANSWER_REMINDERS`) wirkte
  zuverlässig.
- **Richtig-/Falsch-Beispiele** im Prompt helfen mehr als abstrakte Regeln.
- **Einem Prompt nie allein vertrauen.** Wo ein Fehler sichtbar wäre, korrigiert
  Code nach: Ein vorangestelltes „Antwort:“ wird entfernt, Verweise am Satzanfang
  wandern ans Satzende, ein Absage-Satz vor einer echten Antwort fällt weg. Den
  Link in den Kreativ-Modus baut der Code, nicht das Modell.
- **Den festen Absage-Satz als Signal nutzen.** Er wird im Fragen-Log gezählt.
  So sehen die Pfleger:innen, zu welchen Themen Quellen fehlen. Nutzer:innen sehen
  statt des knappen Satzes eine freundliche Erklärung mit Tipps.

## 4. Kreativ-Modus: frei schreiben, beim Beta-Kodex belegt

Der Kreativ-Modus schreibt Blogposts, Artikel, Workshop-Konzepte. Er ist
**absichtlich lockerer** als der Konversationsmodus, denn ein Workshop-Konzept
braucht auch Moderationswissen, das in keiner Beta-Quelle steht. Die Grenze
verläuft so (`CREATIVE_SYSTEM_PROMPTS` in `app/llm.py`):

- Zur Anweisung werden passende Ausschnitte aus den kuratierten Quellen gesucht,
  mit derselben Hybrid-Suche wie oben, und als „BetaCodex-Kontext“ mitgegeben.
- **Aussagen über den Beta-Kodex müssen durch diesen Kontext gedeckt sein.** Für
  alles andere darf das Modell sein Wissen und die Websuche nutzen, aber keine
  Fakten, Quellen oder Zitate erfinden.
- **Web-Quellen werden gegengeprüft.** Das Modell listet am Ende, welche Webseiten
  es verwendet hat. Angezeigt werden nur URLs, die in genau diesem Aufruf wirklich
  als Suchtreffer zurückkamen (`app/web_search_tool.py`). Erfundene Links fallen so
  heraus.
- **Beta-Quellen listet der Code**, nicht das Modell: Angezeigt wird genau das, was
  als Kontext mitgegeben wurde.
- **Stil:** Eine Stilrichtlinie (`app/prompts/humanizer.md`) beschreibt typische
  KI-Muster, die der Text vermeiden soll, etwa Floskeln, Dreierlisten oder
  „nicht X, sondern Y“. Sie ist lang und bei jeder Anfrage gleich. Deshalb wird sie
  per Prompt-Caching zwischengespeichert und kostet bei Folgeanfragen wenig.
- **Tempo:** Beim ersten Entwurf schreibt das Modell sofort los und recherchiert
  erst danach. Die Wartezeit bis zum ersten Wort sank damit bei recherchelastigen
  Anfragen von rund 18 auf 2–5 Sekunden. Der Preis: Der Einstieg entsteht ohne
  Recherche.
- **Aufräumen:** Ankündigungen wie „Ich recherchiere …“ schneidet der Code bei
  Überarbeitungen heraus (`clean_section_revision`).

Ehrlich gesagt: Der Kreativ-Modus garantiert nicht, dass jeder Satz aus Beta-Quellen
stammt. Er garantiert, dass Beta-Aussagen belegt sind und Web-Quellen echt. Wer
strikt belegte Antworten braucht, nutzt den Konversationsmodus.

## 5. Messen statt raten

- `tools/retrieval_eval.py` misst die Trefferquote der Suche ohne Modellkosten. Vor
  und nach jeder Änderung an Suche, Chunking oder Sortierung laufen lassen.
- Daumen hoch/runter unter jeder Antwort landet im Fragen-Log, zusammen mit
  anonymisierten Erstfragen und Absagen. Dort sieht man, welche Fragen gestellt
  werden und wo Quellen fehlen.
- Die Kostenübersicht zeigt, was welcher Modus kostet. Diese Zahlen bestimmen die
  Modellwahl (Abschnitt 6).

## 6. Entscheidungen und Verworfenes

- **Günstiges Modell, wo es reicht.** Antworten, Umformulierungen und
  Überarbeitungen laufen auf dem kleinen Modell. Nur der erste Kreativ-Entwurf, wo
  wirklich neuer Text entsteht, läuft auf dem größeren. Ein größeres Modell für den
  Konversationsmodus haben wir verworfen. Die Verbesserungen kamen aus Suche und
  Prompt.
- **Textqualität vor Tempo im Kreativ-Modus.** Verworfen: weniger Websuchen, ein
  Schalter für die Websuche in der Oberfläche, das kleine Modell für den ersten
  Entwurf.
- **Schwellwerte scheitern an dichten Sammlungen.** Die freigegebenen Websites
  wurden anfangs nur durchsucht, wenn die kuratierten Treffer „schwach“ waren. In
  einer thematisch dichten Sammlung ist aber fast immer irgendein Treffer nah
  genug. Der Fallback griff praktisch nie. Jetzt läuft die Suche immer mit, und die
  Treffer konkurrieren in der Sortierung.
- **Keine Abstimmung über Quellen.** Welche Quellen stärker zählen, entscheiden die
  Pfleger:innen über den Relevanzscore, nicht Nutzer:innen per Voting.

## 7. Selbst nachbauen oder mitnutzen

Ein Minimum, das schon gut trägt:

1. Sorgfältig ausgewählte Quellen, zerlegt in Abschnitte mit Herkunftsangaben.
2. Ein mehrsprachiges Embedding-Modell und eine Vektordatenbank (bei uns ChromaDB).
3. Ein strikter Prompt: nur aus Ausschnitten, jede Aussage mit Verweis und
   wörtlichem Zitat, fester Absage-Satz.
4. Früh ein Messskript für die Suche, bevor man am Prompt dreht.

Danach lohnen sich in dieser Reihenfolge: Hybrid-Suche für Fachbegriffe,
Umformulierung von Folgefragen, Code-Sicherheitsnetze für Prompt-Regeln.

BetaCodex Chat lässt sich auch direkt aus Claude und anderen MCP-Clients nutzen,
für Fragen mit Belegen und zum Schreiben (`app/mcp_server.py`). Zugänge vergeben
die Admins. Der Code steht in diesem Repository. Fragen und Erfahrungsaustausch
sind willkommen.

## Wo im Code

| Thema | Datei |
|---|---|
| Prompts, Erinnerungen, Kreativ-Modus | `app/llm.py` |
| Stilrichtlinie Kreativ-Modus | `app/prompts/humanizer.md` |
| Suche, Sortierung, Hybrid-Suche, Sicherheitsnetze | `app/main.py` |
| Vektordatenbank | `app/vectorstore.py` |
| Zerlegen in Abschnitte | `app/chunking.py` |
| Zusammenfassungen, Schlagworte | `app/summarization.py` |
| Web-Quellen-Prüfung | `app/web_search_tool.py` |
| Messskript Suche | `tools/retrieval_eval.py` |

## Stellschrauben

<!-- BEGIN generiert: scripts/how_it_works.py -->
| Stellschraube | Wert | Fundstelle |
|---|---|---|
| Modell für Antworten, Folgefragen-Umformulierung, Überarbeitungen | `claude-haiku-4-5-20251001` | `app/llm.py: MODEL_NAME` |
| Modell für den ersten Kreativ-Entwurf | `claude-sonnet-5` | `app/llm.py: CREATIVE_FIRST_DRAFT_MODEL` |
| Modell für Zusammenfassungen und Schlagworte beim Import | `claude-haiku-4-5-20251001` | `app/summarization.py: MODEL_NAME` |
| Embedding-Modell (lokal) | `intfloat/multilingual-e5-base` | `app/embeddings.py: MODEL_NAME` |
| Zeichen pro Textabschnitt (Chunk) | `900` | `app/chunking.py: CHUNK_SIZE` |
| Überlappung zwischen Chunks (Zeichen) | `130` | `app/chunking.py: CHUNK_OVERLAP` |
| Textausschnitte pro Antwort (Konversation) | `5` | `app/models.py: QuestionIn.top_k` |
| So viele Kandidaten mehr werden vor dem Neusortieren geholt | `3` | `app/main.py: RELEVANCE_OVERFETCH_MULTIPLIER` |
| Max. Einfluss des Relevanzscores (1–10) auf die Distanz | `0.15` | `app/main.py: RELEVANCE_MAX_ADJUSTMENT` |
| Distanz-Faktor für Quellen einer genannten Autor:in | `0.5` | `app/main.py: AUTHOR_MENTION_DISTANCE_FACTOR` |
| … wenn zusätzlich ein Schlagwort der Quelle in der Frage steht | `0.05` | `app/main.py: AUTHOR_MENTION_KEYWORD_MATCH_FACTOR` |
| Begriffe pro Frage mit garantiertem Ausschnitt (Hybrid-Suche) | `3` | `app/main.py: LEXICAL_MAX_TERMS` |
| Frühere Gesprächsrunden im Prompt | `3` | `app/main.py: ASK_HISTORY_MAX_TURNS` |
| Textausschnitte als Beta-Kontext im Kreativ-Modus | `6` | `app/main.py: CREATIVE_TOP_K` |
| Max. Websuchen pro Kreativ-Anfrage | `3` | `app/llm.py: CREATIVE_MAX_SEARCH_USES` |
| Kreativ-Anfragen pro IP | `6/10 min` | `app/main.py: CREATIVE_RATE_LIMIT_*` |

Diese Tabelle wird aus dem Code erzeugt. Ändern sich Prompts oder Parameter, schlägt `tests/test_how_it_works_doc.py` fehl, bis der Text oben geprüft und `python scripts/how_it_works.py --write` gelaufen ist.

<!-- fingerprint: aa60384c772d -->
<!-- END generiert -->

## Wie dieses Dokument aktuell bleibt

Ein Test (`tests/test_how_it_works_doc.py`) vergleicht die Tabelle oben und einen
Fingerabdruck über alle Prompts, die Stilrichtlinie, die Modelle und die
Suchparameter mit dem Code. Ändert sich etwas davon, schlägt der Test fehl, und
ohne grüne Tests gibt es kein Deployment. Wer die Änderung macht, prüft dann
diesen Text und die englische Fassung und schreibt den Block mit
`python scripts/how_it_works.py --write` neu. Der Test prüft außerdem, dass alle
genannten Dateien existieren.
