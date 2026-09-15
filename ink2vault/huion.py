from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, List


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


def _read_pages(meta: dict, root_name: str, read: Callable[[str], bytes], exists: Callable[[str], bool]) -> List[Page]:
    notebook_id = str(meta.get("identify") or root_name)
    notebook_name = str(meta.get("name") or notebook_id)
    pages = []
    for number, item in enumerate(meta.get("canvasArr") or [], 1):
        page_id = str(item.get("identify") or number)
        page_root = str(item.get("subPath") or "pages/%s" % page_id).strip("/")
        clip = "%s/clip.jpg" % page_root
        if exists(clip):
            image = read(clip)
        else:
            content_name = "%s/content" % page_root
            content = json.loads(read(content_name), parse_float=str, parse_int=str)
            images = content.get("images") or []
            if not images:
                raise ValueError("Stránka %s neobsahuje obrázek" % page_id)
            image = read("%s/%s" % (page_root, images[-1]["localPath"]))
        pages.append(Page(
            notebook_id, notebook_name, page_id, number, image, _ext(image),
            hashlib.sha256(image).hexdigest(),
        ))
    return pages


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
        prefix = "%s/" % root if root not in ("", ".") else ""
        return _read_pages(
            meta,
            PurePosixPath(root).name,
            lambda name: archive.read(prefix + name),
            lambda name: prefix + name in names,
        )


def read_notebook(path: Path) -> List[Page]:
    """Read a live notebook directory from the Huion Note macOS sandbox."""
    meta = json.loads((path / "describe").read_text(encoding="utf-8"), parse_float=str, parse_int=str)
    return _read_pages(
        meta,
        path.name,
        lambda name: (path / name).read_bytes(),
        lambda name: (path / name).is_file(),
    )


def read_source(path: Path) -> List[Page]:
    return read_notebook(path) if path.is_dir() else read_backup(path)
