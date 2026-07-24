import json

import trafilatura


def extract_from_url(url: str) -> dict:
    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception:
        downloaded = None

    if not downloaded:
        return {"title": "", "author": "", "date": "", "text": "", "extracted": False}

    metadata_json = trafilatura.extract(
        downloaded,
        url=url,
        output_format="json",
        with_metadata=True,
        favor_precision=True,
    )
    if not metadata_json:
        return {"title": "", "author": "", "date": "", "text": "", "extracted": False}

    data = json.loads(metadata_json)
    text = (data.get("text") or "").strip()
    return {
        "title": data.get("title") or "",
        "author": data.get("author") or "",
        "date": data.get("date") or "",
        "text": text,
        "extracted": bool(text),
    }
