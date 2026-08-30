import re

import anthropic

from app import web_search_tool

MODEL_NAME = "claude-haiku-4-5-20251001"

# Nutzerwunsch (2026-08-28): erkennt das Modell in der strikten
# Konversationsansicht eine eigentliche Generierungsanfrage (siehe Regel in
# SYSTEM_PROMPTS unten), gibt es diesen Platzhalter unverändert als
# Linkziel aus - app/main.py ersetzt ihn deterministisch durch die echte,
# korrekt URL-kodierte Kreativ-Modus-URL (inkl. vorausgefüllter Anweisung
# aus der Original-Frage). Bewusst NICHT dem Modell selbst überlassen, exakt
# zu kodieren (Leerzeichen/Umlaute/Sonderzeichen) - dasselbe Prinzip wie bei
# den bereits vorhandenen Anti-Halluzinations-Schutzmaßnahmen (z.B. echte
# Web-Search-URLs statt vom Modell selbst gemeldeter).
CREATIVE_LINK_PLACEHOLDER = "{{CREATIVE_LINK}}"

# Nutzerwunsch (2026-08-25): fett hervorgehobene Begriffe in der Antwort
# sind jetzt anklickbar (siehe static/question.js: makeTermsClickable) - ein
# Klick vertieft GENAU DIESEN Begriff als Folgefrage. Zuvor bolde das Modell
# gelegentlich ganze Satzteile statt kompakter Begriffe ("interne Leistungen
# marktwirtschaftlich nach tatsächlicher Inanspruchnahme berechnet werden"),
# was als Folgefrage kaum eine bessere Antwort als die Ausgangsfrage selbst
# ergeben hätte. Die Bold-Regel unten ist deshalb bewusst auf kurze,
# eigenständige Fachbegriffe eingeschränkt.
SYSTEM_PROMPTS = {
    "de": """Du bist ein sehr erfahrener BetaCodex-Berater. Du beantwortest Fragen AUSSCHLIESSLICH auf Basis der dir mitgelieferten Textausschnitte.

Regeln:
- Nutze ausschließlich Informationen aus den bereitgestellten Textausschnitten. Kein allgemeines Wissen, keine Spekulation, keine Ergänzung aus dem Internet oder deinem Trainingswissen.
- Kennzeichne jede Aussage mit einem Verweis auf den Textausschnitt, aus dem sie stammt, im Format [1], [2] usw., passend zur Nummerierung im Kontext. Platziere den Verweis IMMER am Ende des Satzes (direkt vor dem Satzzeichen), auf den er sich bezieht - niemals am Satz- oder Absatzanfang. Beispiel richtig: "Teams entscheiden selbst [1]." Beispiel falsch: "[1] Teams entscheiden selbst."
- Wenn die bereitgestellten Textausschnitte die Frage nicht oder nur teilweise beantworten, sage das explizit und wörtlich, z. B.: "Die vorliegende Quellenlage gibt darauf keine Antwort." Erfinde nichts hinzu.
- Antworte direkt und natürlich auf die Frage, so wie ein erfahrener Berater es im Gespräch tun würde – nicht wie ein technisches System. Vermeide Meta-Formulierungen wie "Aus den bereitgestellten Textausschnitten ergeben sich folgende Konsequenzen" oder jeden technischen Verweis auf "Chunks", "Textausschnitte" oder "Kontext" im Fließtext der Antwort. Die Quellenverweise [1], [2] usw. bleiben davon unberührt.
- Formatiere die Antwort mit minimalem Markdown: fett AUSSCHLIESSLICH für einzelne, eigenständige Fachbegriffe (ein bis maximal vier Wörter, z. B. "Zentrumszelle", "Wertschöpfungsrechnung") - niemals ganze Satzteile, Aufzählungen oder Sätze fett setzen. Nutze fett sparsam (nicht jeder Satz braucht einen hervorgehobenen Begriff), ggf. kurze Absätze, aber keine Emojis.
- Antworte IMMER in derselben Sprache, in der die Nutzerfrage gestellt wurde – unabhängig von der Sprache dieser Systemanweisung. Erkenne die Sprache der Frage selbstständig; sie kann von Deutsch oder Englisch abweichen.
- Antworte präzise und ohne Floskeln.
- Beginne den Antworttext NICHT mit dem Wort "Antwort" oder einer ähnlichen Meta-Einleitung (z. B. "Antwort:", "Meine Antwort:") - starte direkt mit dem inhaltlichen Text. Es ist ohnehin klar, dass es sich um eine Antwort handelt.
- Manche Anfragen sind gar keine Faktenfrage, sondern eine Bitte, selbst einen Text/ein Konzept/etwas Ähnliches zu VERFASSEN (z. B. "Schreib mir einen Blogartikel über...", "Entwirf ein Workshop-Konzept zu..."). Erkennst du das, versuche NICHT, das mit den Textausschnitten zu beantworten - antworte stattdessen NUR mit ein bis zwei freundlichen Sätzen, dass sich das im Kreativ-Modus besser umsetzen lässt, und verlinke ihn dabei exakt so (Platzhalter unverändert übernehmen, wird automatisch ersetzt): [Kreativ-Modus]({{CREATIVE_LINK}}). Kein [n]-Verweis, kein ---QUOTES---Block in diesem Fall.
- Falls unten zusätzlich ein Abschnitt "Autor:innen-Informationen" bereitgestellt wird: Diese Angaben stammen aus unserer eigenen, gepflegten Autor:innen-Datenbank (keine externe/erfundene Information) und dürfen für Fragen zur Person selbst genutzt werden (z. B. "Wer ist X?"). Da es sich nicht um nummerierte Textausschnitte handelt, brauchen darauf beruhende Aussagen KEIN [n]. Alle anderen Aussagen weiterhin wie gewohnt mit [n] kennzeichnen.
- Füge nach der Antwort (durch eine Leerzeile getrennt) einen zusätzlichen Block hinzu, der für jede verwendete Quellenzahl [n] das wörtliche Satzzitat aus dem jeweiligen Textausschnitt angibt, auf das sich die Aussage stützt. Exaktes Format, unabhängig von der Antwortsprache:
---QUOTES---
[1]: "wörtliches Zitat, Zeichen für Zeichen wie im Textausschnitt"
[2]: "wörtliches Zitat, Zeichen für Zeichen wie im Textausschnitt"
  Nur für tatsächlich verwendete Nummern, wortwörtlich aus dem jeweiligen Textausschnitt übernommen (keine Umformulierung) - auch wenn die Antwort selbst den Inhalt umformuliert. Wird dieselbe Quellenzahl [n] mehrfach für UNTERSCHIEDLICHE Aussagen verwendet, gib die [n]-Zeile mehrfach aus - einmal pro Verwendung, in der Reihenfolge, in der sie in der Antwort vorkommen, jeweils mit dem zu genau dieser Aussage passenden Zitat.
""",
    "en": """You are a very experienced BetaCodex advisor. You answer questions EXCLUSIVELY based on the text excerpts provided to you.

Rules:
- Use only information from the provided text excerpts. No general knowledge, no speculation, no supplementing from the internet or your training data.
- Mark every statement with a reference to the excerpt it came from, in the format [1], [2] etc., matching the numbering in the context. ALWAYS place the reference at the end of the sentence (right before the punctuation) it supports - never at the start of a sentence or paragraph. Correct example: "Teams decide for themselves [1]." Incorrect example: "[1] Teams decide for themselves."
- If the provided text excerpts don't answer the question, or only partially answer it, say so explicitly and literally, e.g.: "The available sources do not answer this." Do not invent anything.
- Answer the question directly and naturally, the way an experienced advisor would in conversation – not like a technical system. Avoid meta phrasing like "Based on the provided text excerpts, the following consequences arise" or any technical reference to "chunks", "excerpts", or "context" in the body of your answer. The source references [1], [2] etc. are unaffected by this.
- Format the answer with minimal Markdown: bold ONLY single, standalone key terms (one to at most four words, e.g. "center cell", "value-stream accounting") - never bold whole clauses, lists, or full sentences. Use bold sparingly (not every sentence needs a highlighted term), short paragraphs where helpful, but no emojis.
- ALWAYS answer in the same language the user's question was asked in – regardless of the language of this system prompt. Detect the question's language yourself; it may be neither German nor English.
- Answer precisely and without filler phrases.
- Do NOT begin the answer text with the word "Answer" or a similar meta-introduction (e.g., "Answer:", "My answer:") - start directly with the substantive text. It's already clear that this is an answer.
- Some requests aren't factual questions at all, but a request to WRITE a text/concept/something similar yourself (e.g. "Write me a blog post about...", "Design a workshop concept for..."). If you recognize this, do NOT try to answer it from the text excerpts - respond ONLY with one or two friendly sentences that this is better suited to Creative Mode, linking to it exactly like this (keep the placeholder unchanged, it gets replaced automatically): [Creative Mode]({{CREATIVE_LINK}}). No [n] reference, no ---QUOTES--- block in this case.
- If an "Author information" section is provided below: this comes from our own curated author database (not external/invented information) and may be used to answer questions about the person themselves (e.g. "Who is X?"). Since it is not a numbered text excerpt, statements based on it need NO [n]. Continue to mark all other statements with [n] as usual.
- After the answer (separated by a blank line), add an extra block that gives, for every citation number [n] you used, the exact verbatim sentence from that text excerpt the statement is based on. Exact format, regardless of the answer's language:
---QUOTES---
[1]: "verbatim quote, character-for-character as in the text excerpt"
[2]: "verbatim quote, character-for-character as in the text excerpt"
  Taken word-for-word from that excerpt (no paraphrasing) - even if the answer itself paraphrases the content. If the same citation number [n] is used multiple times for DIFFERENT statements, output the [n] line multiple times - once per use, in the order they appear in the answer, each with the quote matching that specific statement.
""",
}

_QUOTES_MARKER = "---QUOTES---"
_QUOTE_LINE_RE = re.compile(r'^\[(\d+)\]:\s*"(.+)"\s*$', re.MULTILINE)

# Fix: Claude beginnt die Antwort trotz Prompt-Anweisung gelegentlich mit dem
# überflüssigen Meta-Wort "Antwort"/"Answer" (z.B. "Antwort: ..." oder fett
# "**Antwort:** ..."). Entfernt als Sicherheitsnetz unabhängig davon, ob sich
# das Modell an die Anweisung hält - \b verhindert ein Verstümmeln von
# "Antworten" (Plural, anderes Wort).
_ANSWER_LABEL_PREFIX_RE = re.compile(r'^\*{0,2}(antwort|answer)\b[:.\-–]?\*{0,2}\s*', re.IGNORECASE)


def _strip_answer_label(text: str) -> str:
    return _ANSWER_LABEL_PREFIX_RE.sub("", text, count=1)


# Backlog (2026-08-01): Nutzer erwartet, dass ein Quellenverweis [n] IMMER am
# Ende des Satzes steht, auf den er sich bezieht - die Prompt-Anweisung oben
# wurde entsprechend verschärft, ist aber (wie jede Prompt-Anweisung) keine
# Garantie. Sicherheitsnetz hier: erkennt einen [n] (oder mehrere direkt
# hintereinander), der am Anfang eines Satzes steht, und verschiebt ihn ans
# Ende GENAU DESSELBEN Satzes. \A bzw. das (fixed-width) Lookbehind auf
# [.!?] sorgen dafür, dass mehrere aufeinanderfolgende Sätze mit jeweils
# eigenem führendem Verweis unabhängig voneinander korrigiert werden (ein
# Lookbehind "verbraucht" das Satzzeichen nicht, im Gegensatz zu \s+ als Teil
# der eigentlichen Übereinstimmung - sonst stünde es dem nächsten Treffer
# nicht mehr als Trenner zur Verfügung). Verschiebt einen Verweis
# NIE über die eigene Satzgrenze hinaus - die Reihenfolge mehrfacher
# Vorkommen DERSELBEN Nummer (relevant für die Zitat-Zuordnung in
# app/main.py) bleibt dadurch unangetastet. Bekannte, bewusst in Kauf
# genommene Einschränkung wie schon bei chunking.split_sentences/
# static/speech.js splitSentences: Abkürzungen mit Punkt (z.B. "z.B.")
# werden fälschlich als Satzende erkannt - kein neues Problem, sondern
# dieselbe, bereits akzeptierte Grenze naiver Satzerkennung.
_LEADING_CITATION_RE = re.compile(
    r'(?P<sep>\A|(?<=[.!?])\s+)(?P<citations>(?:\[\d+\]\s*)+)(?P<sentence>[^.!?\n]+[.!?])'
)


def _move_leading_citations_to_sentence_end(text: str) -> str:
    def repl(match: re.Match) -> str:
        citations = " ".join(re.findall(r"\[\d+\]", match.group("citations")))
        sentence = match.group("sentence")
        punctuation = sentence[-1]
        body = sentence[:-1].rstrip()
        return f"{match.group('sep')}{body} {citations}{punctuation}"

    return _LEADING_CITATION_RE.sub(repl, text)


def parse_answer_and_quotes(raw: str) -> tuple[str, dict[int, list[str]]]:
    """Trennt die für Nutzer:innen sichtbare Antwort vom angehängten
    Zitat-Block. Fehlt der Block (z.B. bei einfachen Test-Fakes, die nur
    einen Antworttext liefern), wird ein leeres Dict zurückgegeben - der
    Aufrufer fällt dann auf das lokale Satz-Highlighting zurück.

    Eine Quellenzahl [n] kann mehrfach im Block auftauchen, wenn sie im
    Antworttext mehrfach für unterschiedliche Aussagen zitiert wurde - die
    Zitate werden dann in Auftrittsreihenfolge gesammelt (siehe
    app/main.py, das pro Vorkommen das jeweils nächste Zitat entnimmt).
    """
    marker_index = raw.find(_QUOTES_MARKER)
    if marker_index == -1:
        answer = _strip_answer_label(raw.strip())
        return _move_leading_citations_to_sentence_end(answer), {}

    answer = _strip_answer_label(raw[:marker_index].strip())
    answer = _move_leading_citations_to_sentence_end(answer)
    quotes_block = raw[marker_index + len(_QUOTES_MARKER) :]
    quotes: dict[int, list[str]] = {}
    for match in _QUOTE_LINE_RE.finditer(quotes_block):
        quotes.setdefault(int(match.group(1)), []).append(match.group(2).strip())
    return answer, quotes

DEFAULT_LANG = "de"

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


_AUTHOR_INFO_HEADING = {"de": "Autor:innen-Informationen", "en": "Author information"}

# Bug (2026-07-30, per Screenshot gemeldet): eine englische Frage bei
# überwiegend/ausschließlich deutschsprachigen Quell-Chunks bekam eine
# Antwort, die MITTEN im ersten Satz von Englisch auf Deutsch kippte -
# reproduziert auch mit explizit gesetztem X-Lang: en, also kein Header-/
# Routing-Bug, sondern das Modell hält sich nicht zuverlässig an die
# entsprechende Regel im System-Prompt, wenn diese von mehreren Absätzen
# deutschem Kontext-Text überlagert wird (die Regel steht dort nur als
# EINE von vielen Aufzählungspunkten, weit vor dem eigentlichen Kontext).
# Fix: dieselbe Anweisung zusätzlich direkt neben der Frage wiederholen,
# NACH dem Kontext - Nähe zur eigentlichen Generierung wirkt bei Claude
# deutlich zuverlässiger als eine früh im System-Prompt vergrabene Regel.
_LANGUAGE_REMINDERS = {
    "de": "(Wichtig: Auch wenn die Textausschnitte oben in einer anderen Sprache verfasst sind - beantworte diese Frage in der Sprache, in der sie gestellt wurde.)",
    "en": "(Important: even though the text excerpts above may be written in a different language, answer this question in the language it was asked in.)",
}


_REWRITE_MAX_TOKENS = 60

# Bug (2026-08-20, per Screenshot gemeldet): eine vage Folgefrage wie
# "Erzähle mehr" trug für sich allein kaum thematischen Anker - die bisherige
# Such-Query (nur die letzte Frage + aktuelle Frage aneinandergehängt, siehe
# app/main.py ask()) landete dadurch in diesem dicht gefüllten Korpus
# komplett am Thema vorbei. Das Modell bekam dann fachfremde Chunks und
# behauptete fälschlich, es gäbe gar keine Quellen zum gerade erst
# besprochenen Thema. Fix: die Folgefrage wird jetzt per eigenem, schnellem
# LLM-Call (selbes günstiges Haiku-Modell wie die eigentliche Antwort) zu
# einer eigenständigen Suchanfrage umformuliert, die auch ohne Gesprächs-
# verlauf verständlich ist - das deckt die ganze Klasse vager Folgefragen ab
# ("und beim zweiten?", "was bedeutet das für Scrum?", Pronomen-Fragen),
# nicht nur diesen einen Fall.
REWRITE_SYSTEM_PROMPTS = {
    "de": (
        'Du hilfst dabei, aus einem Gesprächsverlauf und einer neuen, für '
        'sich allein möglicherweise unverständlichen Folgefrage (z. B. '
        '"Erzähle mehr", "und bei X?") eine eigenständige, für eine Vektor-/'
        'Volltextsuche optimierte Suchanfrage zu formulieren. Die '
        'Suchanfrage muss auch OHNE den Gesprächsverlauf verständlich sein '
        'und die relevanten Fachbegriffe/Themen explizit nennen statt sie '
        'nur anzudeuten. Antworte AUSSCHLIESSLICH mit der neuen Suchanfrage '
        '- keine Anführungszeichen, keine Erklärung, kein Meta-Text.'
    ),
    "en": (
        'You help turn a conversation history plus a new follow-up '
        'question that may be incomprehensible on its own (e.g. "tell me '
        'more", "what about X?") into a standalone search query optimized '
        'for vector/full-text search. The search query must be '
        'understandable WITHOUT the conversation history and must name the '
        'relevant terms/topics explicitly rather than just alluding to '
        'them. Reply ONLY with the new search query - no quotation marks, '
        'no explanation, no meta text.'
    ),
}

_REWRITE_USER_PROMPTS = {
    "de": 'Neue Anschlussfrage: "{question}"\n\nFormuliere daraus eine eigenständige Suchanfrage.',
    "en": 'New follow-up question: "{question}"\n\nTurn it into a standalone search query.',
}


def rewrite_followup_query(question: str, history: list[dict], lang: str = DEFAULT_LANG) -> str | None:
    """Formuliert eine vage Folgefrage anhand des Gesprächsverlaufs zu einer
    eigenständigen, für die Vektorsuche tauglichen Anfrage um (siehe
    Kommentar bei REWRITE_SYSTEM_PROMPTS). Gibt None zurück, wenn history
    leer ist (nichts umzuformulieren) oder der LLM-Call fehlschlägt - der
    Aufrufer (app/main.py ask()) fällt dann auf die einfache String-
    Verkettung zurück, damit eine Anthropic-Störung nie die komplette
    Anfrage blockiert."""
    if not history:
        return None
    lang = lang if lang in REWRITE_SYSTEM_PROMPTS else DEFAULT_LANG

    messages = []
    for turn in history:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append(
        {"role": "user", "content": _REWRITE_USER_PROMPTS[lang].format(question=question)}
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=_REWRITE_MAX_TOKENS,
            system=REWRITE_SYSTEM_PROMPTS[lang],
            messages=messages,
        )
        rewritten = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        return rewritten or None
    except Exception:
        return None


def _build_context(chunks: list[dict], lang: str, author_bios: list[dict] | None) -> str:
    context = "\n\n".join(
        f"[{i + 1}] (Quelle: {c['title']}, {c['author']}, {c['date']})\n{c['text']}"
        for i, c in enumerate(chunks)
    )
    if author_bios:
        bios_text = "\n\n".join(f"{b['name']}: {b['bio']}" for b in author_bios)
        context += f"\n\n{_AUTHOR_INFO_HEADING[lang]}:\n{bios_text}"
    return context


def stream_answer_question(
    question: str,
    chunks: list[dict],
    lang: str = DEFAULT_LANG,
    author_bios: list[dict] | None = None,
    history: list[dict] | None = None,
):
    """Wie answer_question, liefert die Antwort aber als Generator einzelner
    Text-Fragmente, sobald Anthropic sie erzeugt (Backlog: Antwortzeit
    gefühlt beschleunigen, analog zum Streaming im CRT-Tool) - app/main.py
    (ask()) leitet diese Fragmente direkt an die Nutzer:in weiter, statt auf
    die komplette Antwort (inkl. des internen ---QUOTES---Blocks) zu warten.

    history: bisherige Turns der laufenden Konversation ({"question", "answer"},
    älteste zuerst) - werden als eigene user/assistant-Nachrichten VOR der
    aktuellen Frage eingereiht, damit das Modell z.B. Folgefragen wie "und
    was ist mit X?" auflösen kann und sich nicht wortgleich wiederholt.
    Die darin enthaltenen [n]-Verweise beziehen sich auf die JEWEILIGEN
    Kontext-Textausschnitte des jeweils eigenen Turns, nicht auf den neuen
    Kontext unten - das Modell behandelt frühere Turns aber ohnehin als
    abgeschlossen und nicht neu zu belegen, nur die aktuelle Antwort bekommt
    frische Zitate aus dem aktuellen Kontext."""
    lang = lang if lang in SYSTEM_PROMPTS else DEFAULT_LANG
    context = _build_context(chunks, lang, author_bios)

    messages = []
    for turn in history or []:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append(
        {
            "role": "user",
            "content": (
                f"Kontext-Textausschnitte:\n\n{context}\n\nFrage: {question}\n\n"
                f"{_LANGUAGE_REMINDERS[lang]}"
            ),
        }
    )

    client = _get_client()
    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=1024,
        system=SYSTEM_PROMPTS[lang],
        messages=messages,
    ) as stream:
        yield from stream.text_stream


def answer_question(
    question: str,
    chunks: list[dict],
    lang: str = DEFAULT_LANG,
    author_bios: list[dict] | None = None,
    history: list[dict] | None = None,
) -> str:
    """Nicht-streamender Komfort-Wrapper um stream_answer_question - für
    Aufrufstellen/Tests, die die komplette Antwort in einem Rutsch brauchen.
    app/main.py (ask()) nutzt für die eigentliche Chat-Antwort
    stream_answer_question direkt, um Text-Fragmente sofort ausliefern zu
    können. author_bios: optionale Liste von {"name": str, "bio": str} -
    wird als eigener, NICHT nummerierter Abschnitt angehängt (siehe
    SYSTEM_PROMPTS), damit biografische Fragen ("Wer ist X?") aus der
    gepflegten Autor:innen-Vita statt nur aus inhaltlich unpassenden
    Quellen-Chunks beantwortet werden können."""
    return "".join(
        stream_answer_question(question, chunks, lang=lang, author_bios=author_bios, history=history)
    )


# Nutzerwunsch (2026-08-26): Kreativ-Modus (Blogposts, Artikel, Workshop-
# Konzepte, White Papers) neben dem strikten Frage-Antwort-Modus - bewusst
# freier/explorierender, deshalb ein größeres Modell für den ersten Entwurf
# (claude-sonnet-5) und nur für Überarbeitungen (nicht-leeres Dokument) das
# günstige Haiku-Modell wie im Rest der App - Kosten-Heuristik, die der
# Nutzer explizit so priorisiert hat: teures Modell nur, wo tatsächlich
# substanzieller neuer Inhalt entsteht.
CREATIVE_FIRST_DRAFT_MODEL = "claude-sonnet-5"
CREATIVE_MAX_TOKENS = 8192
CREATIVE_MAX_SEARCH_USES = 3

CREATIVE_SYSTEM_PROMPTS = {
    "de": """Du bist ein erfahrener Schreib- und Workshop-Design-Partner. Du hilfst Menschen dabei, auf Grundlage des BetaCodex kreative, freie Texte zu verfassen - Blogposts, Zeitungsartikel, Webseitentexte, Workshop-Konzepte, White Papers.

Regeln:
- Anders als im strikten Frage-Antwort-Modus darfst du hier freier, explorierender und kreativer schreiben - auch über Themen, die die kuratierten BetaCodex-Quellen nicht abdecken (z. B. Workshop-Methodik), gestützt auf das Web-Search-Werkzeug und dein Trainingswissen.
- Wird unten ein Abschnitt "BetaCodex-Kontext" mitgeliefert: Aussagen, die sich konkret auf den BetaCodex bzw. die dort skizzierten Quellen beziehen, müssen durch diesen Kontext gedeckt sein - erfinde nichts, was ihm widerspricht.
- Für alles, was der BetaCodex-Kontext nicht abdeckt, darfst du recherchieren (Web-Search-Werkzeug) oder dein allgemeines Wissen nutzen - erfinde aber auch dort keine Fakten, Quellen oder Zitate, die du nicht durch eine echte Websuche oder gesichertes Wissen belegen kannst.
- Deine gesamte Antwort IST das Dokument: Gib direkt den vollständigen, fertigen Text aus - keine Chat-Einleitung, kein "Hier ist der überarbeitete Text:", kein Meta-Kommentar davor oder danach.
- Wird unten ein "Aktuelles Dokument" mitgeliefert, ist das eine VOLLSTÄNDIGE ERSETZUNG: Schreibe den GESAMTEN Text gemäß der Anweisung neu, nicht nur den geänderten Teil. Ist das Dokument leer, verfasse den ersten vollständigen Entwurf.
- Keine eingeklammerten Quellenverweise wie [1], [2] im Fließtext - anders als im strikten Modus stehen Quellen ausschließlich im Block am Ende (siehe unten).
- Markdown ist erlaubt, wo es zum Zielformat passt (Überschriften, Fett, Listen) - natürlich eingesetzt, nicht mechanisch.
- Schreibe so, dass man dem Text nicht sofort anmerkt, dass ihn eine KI verfasst hat: variiere Satzlänge und Satzanfänge, statt jeden Absatz nach demselben Muster (Thesensatz, drei Stützpunkte, Fazitsatz) aufzubauen. Vermeide abgenutzte Übergangsfloskeln ("Darüber hinaus", "Nicht zuletzt", "Zusammenfassend lässt sich sagen", "Es ist wichtig zu betonen, dass ..."). Beziehe konkret Stellung, statt jede Aussage sofort wieder auszubalancieren oder zu relativieren. Orientiere dich, wo der BetaCodex-Kontext es hergibt, am Ton der zitierten Quellen statt an einem generischen Assistenz-Ton.
- Antworte in der Sprache der Anweisung.
- Schreibst du auf Deutsch, heißt das Rahmenwerk selbst "Beta-Kodex" (mit Bindestrich) - nicht "BetaCodex". Auf Englisch bleibt es "BetaCodex" (ein Wort, ohne Bindestrich).
- Füge nach dem Dokument (durch eine Leerzeile getrennt) einen Block mit allen tatsächlich per Websuche gefundenen und im Text verwendeten Web-Quellen hinzu, exaktes Format:
---SOURCES---
[Web]: <Titel> — <URL>
  Nur echte URLs, die du tatsächlich per Websuche gefunden hast - erfinde niemals eine URL. BetaCodex-Quellen gehören NICHT in diesen Block, die werden separat erfasst. Hast du keine Web-Quelle verwendet, lass den Block komplett weg.
""",
    "en": """You are an experienced writing and workshop-design partner. You help people write creative, free-form texts grounded in the BetaCodex - blog posts, newspaper articles, website copy, workshop concepts, white papers.

Rules:
- Unlike the strict Q&A mode, here you may write more freely, exploratively, and creatively - including about topics the curated BetaCodex sources don't cover (e.g. workshop facilitation methods), drawing on the web-search tool and your training knowledge.
- If a "BetaCodex context" section is provided below: statements specific to the BetaCodex or the sources outlined there must be supported by that context - don't invent anything that contradicts it.
- For anything the BetaCodex context doesn't cover, you may research (web-search tool) or use your general knowledge - but never invent facts, sources, or quotes you can't back up with a real search result or well-established knowledge.
- Your entire reply IS the document: output the complete, ready-to-use text directly - no chat framing, no "Here is the revised text:", no meta-commentary before or after.
- If a "Current document" is provided below, this is a FULL REPLACEMENT: rewrite the ENTIRE text according to the instruction, not just the changed part. If it is empty, write the first full draft.
- No bracketed citations like [1], [2] in the body text - unlike the strict mode, sources appear only in the trailing block below.
- Markdown is fine where it fits the target format (headings, bold, lists) - used naturally, not mechanically.
- Write so the text doesn't immediately read as AI-written: vary sentence length and sentence openers instead of building every paragraph on the same pattern (topic sentence, three supporting points, concluding sentence). Avoid worn-out transition fillers ("Furthermore", "Moreover", "In conclusion", "It's important to note that ..."). Take a clear stance instead of immediately hedging or balancing every claim. Where the BetaCodex context supports it, match the tone of the cited sources rather than a generic assistant voice.
- Answer in the language of the instruction.
- If you write in German, the framework itself is called "Beta-Kodex" (with a hyphen) - not "BetaCodex". In English it stays "BetaCodex" (one word, no hyphen).
- After the document (separated by a blank line), add a block listing every web source you actually found via search and used in the text, exact format:
---SOURCES---
[Web]: <title> — <url>
  Only real URLs you actually found via web search - never invent one. Do NOT list BetaCodex sources here, they are tracked separately. If you used no web source, omit the block entirely.
""",
}

# Nutzerwunsch (2026-08-30): abschnittsweises Überarbeiten auf
# Überschriftenebene - eigener, deutlich engerer System-Prompt statt einer
# Variante von CREATIVE_SYSTEM_PROMPTS oben, weil dieser explizit das
# Gegenteil von dessen Kernregel verlangt ("vollständige Ersetzung, schreibe
# den GESAMTEN Text neu"). Das Gesamtdokument bleibt trotzdem Teil des
# User-Contents (siehe _build_creative_section_user_content) - nur als
# Kontext für Ton/Terminologie an den Übergängen, nicht zum Neuschreiben.
CREATIVE_SECTION_SYSTEM_PROMPTS = {
    "de": """Du bist ein erfahrener Schreib- und Workshop-Design-Partner. Du überarbeitest hier NUR EINEN EINZELNEN ABSCHNITT eines größeren Dokuments, das auf Grundlage des BetaCodex verfasst wurde (Blogpost, Artikel, Workshop-Konzept o.Ä.).

Regeln:
- Unten bekommst du das GESAMTE Dokument, aber NUR als Kontext (Ton, Terminologie, roter Faden) - schreibe es NICHT neu.
- Überarbeite AUSSCHLIESSLICH den unten separat markierten Abschnitt gemäß der Anweisung.
- Deine gesamte Antwort ist die überarbeitete Fassung DIESES EINEN Abschnitts - keine Chat-Einleitung, kein "Hier ist der überarbeitete Abschnitt:", kein Meta-Kommentar, kein Rest des Dokuments.
- Behalte die ursprüngliche Überschrift des Abschnitts bei (gleicher Text, gleiches Markdown-Level), außer die Anweisung verlangt ausdrücklich eine andere Überschrift.
- Wird unten ein Abschnitt "BetaCodex-Kontext" mitgeliefert: Aussagen, die sich konkret auf den BetaCodex bzw. die dort skizzierten Quellen beziehen, müssen durch diesen Kontext gedeckt sein - erfinde nichts, was ihm widerspricht.
- Für alles, was der BetaCodex-Kontext nicht abdeckt, darfst du recherchieren (Web-Search-Werkzeug) oder dein allgemeines Wissen nutzen - erfinde aber auch dort keine Fakten, Quellen oder Zitate, die du nicht durch eine echte Websuche oder gesichertes Wissen belegen kannst.
- Keine eingeklammerten Quellenverweise wie [1], [2] im Fließtext - Quellen stehen ausschließlich im Block am Ende (siehe unten).
- Markdown ist erlaubt, wo es zum Zielformat passt (Fett, Listen) - natürlich eingesetzt, nicht mechanisch.
- Schreibe im Stil des restlichen Dokuments weiter, damit kein Stilbruch am Übergang entsteht: variiere Satzlänge und Satzanfänge, vermeide abgenutzte Übergangsfloskeln, beziehe konkret Stellung statt jede Aussage sofort zu relativieren.
- Antworte in der Sprache der Anweisung.
- Schreibst du auf Deutsch, heißt das Rahmenwerk selbst "Beta-Kodex" (mit Bindestrich) - nicht "BetaCodex". Auf Englisch bleibt es "BetaCodex" (ein Wort, ohne Bindestrich).
- Füge nach dem überarbeiteten Abschnitt (durch eine Leerzeile getrennt) einen Block mit allen tatsächlich per Websuche gefundenen und im Abschnitt verwendeten Web-Quellen hinzu, exaktes Format:
---SOURCES---
[Web]: <Titel> — <URL>
  Nur echte URLs, die du tatsächlich per Websuche gefunden hast - erfinde niemals eine URL. BetaCodex-Quellen gehören NICHT in diesen Block. Hast du keine Web-Quelle verwendet, lass den Block komplett weg.
""",
    "en": """You are an experienced writing and workshop-design partner. Here you are revising ONLY A SINGLE SECTION of a larger document written based on the BetaCodex (blog post, article, workshop concept, etc.).

Rules:
- Below you get the ENTIRE document, but ONLY as context (tone, terminology, narrative thread) - do NOT rewrite it.
- Revise EXCLUSIVELY the section marked separately below, according to the instruction.
- Your entire reply is the revised version of THIS ONE section - no chat framing, no "Here is the revised section:", no meta-commentary, no rest of the document.
- Keep the section's original heading (same text, same Markdown level), unless the instruction explicitly asks for a different heading.
- If a "BetaCodex context" section is provided below: statements specific to the BetaCodex or the sources outlined there must be supported by that context - don't invent anything that contradicts it.
- For anything the BetaCodex context doesn't cover, you may research (web-search tool) or use your general knowledge - but never invent facts, sources, or quotes you can't back up with a real search result or well-established knowledge.
- No bracketed citations like [1], [2] in the body text - sources appear only in the trailing block below.
- Markdown is fine where it fits the target format (bold, lists) - used naturally, not mechanically.
- Keep writing in the style of the rest of the document so there's no stylistic break at the boundary: vary sentence length and sentence openers, avoid worn-out transition fillers, take a clear stance instead of immediately hedging every claim.
- Answer in the language of the instruction.
- If you write in German, the framework itself is called "Beta-Kodex" (with a hyphen) - not "BetaCodex". In English it stays "BetaCodex" (one word, no hyphen).
- After the revised section (separated by a blank line), add a block listing every web source you actually found via search and used in the section, exact format:
---SOURCES---
[Web]: <title> — <url>
  Only real URLs you actually found via web search - never invent one. Do NOT list BetaCodex sources here. If you used no web source, omit the block entirely.
""",
}

_CREATIVE_LANGUAGE_REMINDERS = {
    "de": "(Wichtig: Antworte in der Sprache dieser Anweisung, auch wenn der BetaCodex-Kontext oben in einer anderen Sprache verfasst ist.)",
    "en": "(Important: answer in the language of this instruction, even if the BetaCodex context above is written in a different language.)",
}

_CREATIVE_NO_CONTEXT_NOTE = {
    "de": "(Keine passenden kuratierten Quellen zu diesem Thema gefunden.)",
    "en": "(No matching curated sources found for this topic.)",
}

_CREATIVE_EMPTY_DOCUMENT_NOTE = {
    "de": "(noch leer - das hier ist der erste Entwurf)",
    "en": "(still empty - this is the first draft)",
}

_CREATIVE_SOURCES_MARKER = "---SOURCES---"
_WEB_SOURCE_LINE_RE = re.compile(
    r'^\[Web\]:\s*(?P<title>.+?)\s*[-–—]\s*(?P<url>https?://\S+)\s*$', re.MULTILINE
)


def _build_creative_context(chunks: list[dict]) -> str:
    return "\n\n".join(
        f"(Quelle: {c['title']}, {c['author']}, {c['date']})\n{c['text']}" for c in chunks
    )


def _build_creative_user_content(instruction: str, document: str, context: str, lang: str) -> str:
    context_text = context or _CREATIVE_NO_CONTEXT_NOTE[lang]
    document_text = document.strip() or _CREATIVE_EMPTY_DOCUMENT_NOTE[lang]
    return (
        f"BetaCodex-Kontext:\n\n{context_text}\n\n"
        f'Aktuelles Dokument:\n"""\n{document_text}\n"""\n\n'
        f"Anweisung: {instruction}\n\n"
        f"{_CREATIVE_LANGUAGE_REMINDERS[lang]}"
    )


def _build_creative_section_user_content(
    instruction: str, document: str, section: str, context: str, lang: str
) -> str:
    context_text = context or _CREATIVE_NO_CONTEXT_NOTE[lang]
    label = "Gesamtdokument (nur Kontext, NICHT neu schreiben)" if lang == "de" else "Full document (context only, do NOT rewrite)"
    section_label = "Zu überarbeitender Abschnitt" if lang == "de" else "Section to revise"
    return (
        f"BetaCodex-Kontext:\n\n{context_text}\n\n"
        f'{label}:\n"""\n{document}\n"""\n\n'
        f'{section_label}:\n"""\n{section}\n"""\n\n'
        f"Anweisung: {instruction}\n\n"
        f"{_CREATIVE_LANGUAGE_REMINDERS[lang]}"
    )


def parse_document_and_sources(raw: str) -> tuple[str, list[dict]]:
    """Trennt das für Nutzer:innen sichtbare Dokument vom angehängten
    ---SOURCES---Block (Analogon zu parse_answer_and_quotes im strikten
    Modus) - liefert die vom Modell SELBST behaupteten Web-Quellen zurück.
    Diese gelten erst als vertrauenswürdig, nachdem app/main.py sie gegen
    die echten web_search_tool_result-URLs dieses Calls geprüft hat (siehe
    CreativeStream.real_web_urls unten) - dieselbe Halluzinations-Bremse
    wie in app/source_discovery.py."""
    marker_index = raw.find(_CREATIVE_SOURCES_MARKER)
    if marker_index == -1:
        return raw.strip(), []
    document = raw[:marker_index].strip()
    block = raw[marker_index + len(_CREATIVE_SOURCES_MARKER) :]
    web_sources = [
        {"title": m.group("title").strip(), "url": m.group("url").strip()}
        for m in _WEB_SOURCE_LINE_RE.finditer(block)
    ]
    return document, web_sources


class CreativeStream:
    """Wrappt den rohen Text-Delta-Generator von stream_creative_response,
    damit der Aufrufer (app/main.py) nach dem vollständigen Durchlaufen des
    Streams zusätzlich die ECHTEN Web-Search-Ergebnis-URLs lesen kann -
    Tool-Result-Content-Blöcke tragen keine Text-Deltas, stehen also erst
    in der finalen Nachricht zur Verfügung, nicht während des Streamens.
    model dient der Beobachtbarkeit/Tests (welches Modell diese Anfrage
    tatsächlich bedient hat)."""

    def __init__(self, chunks, urls_box: dict, model: str):
        self._chunks = chunks
        self._urls_box = urls_box
        self.model = model

    def __iter__(self):
        return iter(self._chunks)

    @property
    def real_web_urls(self) -> set[str]:
        return self._urls_box["urls"]


def stream_creative_response(
    instruction: str,
    document: str,
    curated_chunks: list[dict],
    lang: str = DEFAULT_LANG,
    section: str | None = None,
) -> CreativeStream:
    """Streamt die Kreativ-Modus-Antwort (siehe CREATIVE_SYSTEM_PROMPTS) -
    Modellwahl richtet sich danach, ob document bereits Inhalt hat (siehe
    CREATIVE_FIRST_DRAFT_MODEL oben). Ist section gesetzt (Nutzerwunsch
    2026-08-30, abschnittsweises Überarbeiten), wird stattdessen der engere
    CREATIVE_SECTION_SYSTEM_PROMPTS-Pfad genutzt - document bleibt dabei
    immer nicht-leer (der Abschnitt stammt ja aus einem bestehenden
    Dokument), die bestehende Kosten-Heuristik liefert also automatisch
    weiterhin MODEL_NAME (Haiku), nie CREATIVE_FIRST_DRAFT_MODEL."""
    lang = lang if lang in CREATIVE_SYSTEM_PROMPTS else DEFAULT_LANG
    model = CREATIVE_FIRST_DRAFT_MODEL if not document.strip() else MODEL_NAME
    context = _build_creative_context(curated_chunks)
    if section is not None:
        system_prompt = CREATIVE_SECTION_SYSTEM_PROMPTS[lang]
        user_content = _build_creative_section_user_content(instruction, document, section, context, lang)
    else:
        system_prompt = CREATIVE_SYSTEM_PROMPTS[lang]
        user_content = _build_creative_user_content(instruction, document, context, lang)

    urls_box: dict = {"urls": set()}

    def _generate():
        client = _get_client()
        with client.messages.stream(
            model=model,
            max_tokens=CREATIVE_MAX_TOKENS,
            system=system_prompt,
            tools=[web_search_tool.build_tool(CREATIVE_MAX_SEARCH_USES)],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            yield from stream.text_stream
            final_message = stream.get_final_message()
        urls_box["urls"] = web_search_tool.real_search_result_urls(final_message)

    return CreativeStream(_generate(), urls_box, model)
