"""Gemeinsame Bausteine für Claudes serverseitiges Web-Search-Tool
(web_search_20250305), genutzt sowohl von app/source_discovery.py (Hintergrund-
Suche nach neuen Quellen) als auch von app/llm.py (Kreativ-Modus). Enthält
insbesondere die Halluzinations-Bremse real_search_result_urls(): egal was ein
Modell selbst über gefundene Quellen behauptet, nur URLs, die tatsächlich als
echter Websuche-Treffer in DIESEM Call zurückkamen, gelten als real."""


def build_tool(max_uses: int) -> dict:
    return {"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}


def real_search_result_urls(message) -> set[str]:
    """Sammelt die URLs, die die Websuche in DIESEM Call tatsächlich
    gefunden hat (message.content enthält dafür eigene
    "web_search_tool_result"-Blöcke, unabhängig von etwaigen anderen
    Tool-Calls im selben Response)."""
    urls: set[str] = set()
    for block in message.content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        content = getattr(block, "content", None)
        if not isinstance(content, list):
            continue  # WebSearchToolResultError statt echter Trefferliste
        for item in content:
            url = getattr(item, "url", None)
            if url:
                urls.add(url)
    return urls
