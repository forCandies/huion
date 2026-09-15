from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List


@dataclass(frozen=True)
class Page:
    notebook_id: str
    notebook_name: str
    page_id: str
    page_number: int
    image: bytes
    image_ext: str
    image_sha256: str


def _ext(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise ValueError("Stránka není podporovaný PNG nebo JPEG obrázek")


def read_backup(path: Path) -> List[Page]:
    """Read the iOS .huionnoteios ZIP format without rounding numeric IDs."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        descriptors = [name for name in names if PurePosixPath(name).name == "describe"]
        if len(descriptors) != 1:
            raise ValueError("Očekáván jeden soubor describe, nalezeno: %s" % len(descriptors))
        descriptor = descriptors[0]
        root = str(PurePosixPath(descriptor).parent)
        meta = json.loads(archive.read(descriptor), parse_float=str, parse_int=str)
        notebook_id = str(meta.get("identify") or PurePosixPath(root).name)
        notebook_name = str(meta.get("name") or notebook_id)
        pages = []
        for number, item in enumerate(meta.get("canvasArr") or [], 1):
            page_id = str(item.get("identify") or number)
            page_root = "%s/%s" % (root, item.get("subPath", "pages/%s" % page_id))
            clip = "%s/clip.jpg" % page_root
            if clip in names:
                image = archive.read(clip)
            else:
                content_name = "%s/content" % page_root
                content = json.loads(archive.read(content_name), parse_float=str, parse_int=str)
                images = content.get("images") or []
                if not images:
                    raise ValueError("Stránka %s neobsahuje obrázek" % page_id)
                image = archive.read("%s/%s" % (page_root, images[-1]["localPath"]))
            pages.append(Page(
                notebook_id, notebook_name, page_id, number, image, _ext(image),
                hashlib.sha256(image).hexdigest(),
            ))
        return pages
