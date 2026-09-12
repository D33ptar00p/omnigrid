"""Resolve OpenStreetMap `wikidata` tags to photographs.

Only three GB plants carry a `wikimedia_commons` tag directly, but 451 carry a
Wikidata id, and Wikidata records an image (property P18) for many of them. The
image itself lives on Wikimedia Commons under a free licence, and Commons serves
a thumbnail from a stable URL built from the filename.

Both the link and the picture are published facts about the plant, so this adds
no inference -- but the *licence* of each photograph belongs to its author, not
to us, so the author and licence are fetched alongside and shown with the image.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import requests

SOURCE_ID = "wikidata"
API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = "omnigrid/0.1 (open energy map; +https://github.com/omnigrid/omnigrid)"

#: Wikidata property for "image".
P_IMAGE = "P18"
BATCH = 50


@dataclass(frozen=True, slots=True)
class Image:
    qid: str
    filename: str
    #: Commons thumbnail, stable and cacheable.
    thumb_url: str
    full_url: str
    artist: str | None = None
    licence: str | None = None
    credit_url: str | None = None

    def to_json(self) -> dict[str, str | None]:
        return {
            "thumb": self.thumb_url, "full": self.full_url,
            "artist": self.artist, "licence": self.licence,
            "credit_url": self.credit_url,
        }


def thumb_url(filename: str, width: int = 640) -> str:
    return (f"https://commons.wikimedia.org/wiki/Special:FilePath/"
            f"{quote(filename.replace(' ', '_'))}?width={width}")


def _batched(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_images(qids: list[str], *, pause: float = 0.2) -> dict[str, Image]:
    """Look up P18 for each Wikidata id, then the photo's author and licence."""
    session = requests.Session()
    session.headers["User-Agent"] = UA

    files: dict[str, str] = {}
    for batch in _batched(sorted(set(qids)), BATCH):
        r = session.get(API, params={
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "claims", "format": "json",
        }, timeout=60)
        r.raise_for_status()
        for qid, entity in r.json().get("entities", {}).items():
            claims = entity.get("claims", {}).get(P_IMAGE) or []
            if claims:
                value = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(value, str):
                    files[qid] = value
        time.sleep(pause)

    # Attribution for each photograph: the licence is the photographer's, not ours.
    meta: dict[str, dict[str, str]] = {}
    names = sorted(set(files.values()))
    for batch in _batched(names, BATCH):
        r = session.get(COMMONS_API, params={
            "action": "query", "titles": "|".join(f"File:{n}" for n in batch),
            "prop": "imageinfo", "iiprop": "extmetadata|url", "format": "json",
        }, timeout=60)
        r.raise_for_status()
        for page in r.json().get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            extra = info.get("extmetadata", {})
            title = page.get("title", "").removeprefix("File:")
            meta[title] = {
                "artist": _plain(extra.get("Artist", {}).get("value")),
                "licence": extra.get("LicenseShortName", {}).get("value"),
                "credit_url": info.get("descriptionurl"),
            }
        time.sleep(pause)

    out: dict[str, Image] = {}
    for qid, filename in files.items():
        m = meta.get(filename, {})
        out[qid] = Image(
            qid=qid, filename=filename,
            thumb_url=thumb_url(filename), full_url=thumb_url(filename, 1600),
            artist=m.get("artist"), licence=m.get("licence"),
            credit_url=m.get("credit_url"),
        )
    return out


def _plain(html: str | None) -> str | None:
    """Commons returns the artist as a fragment of HTML."""
    if not html:
        return None
    import re
    text = re.sub(r"<[^>]+>", "", html)
    return " ".join(text.split()) or None


def load_cache(path: Path) -> dict[str, Image]:
    if not path.exists():
        return {}
    return {
        qid: Image(qid=qid, **data)
        for qid, data in json.loads(path.read_text()).items()
    }


def save_cache(path: Path, images: dict[str, Image]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        qid: {"filename": i.filename, "thumb_url": i.thumb_url, "full_url": i.full_url,
              "artist": i.artist, "licence": i.licence, "credit_url": i.credit_url}
        for qid, i in images.items()
    }, indent=1))
