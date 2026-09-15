from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


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
    return ".img"


def read_backup(path: Path) -> list[Page]:
    """Read the iOS .huionnoteios ZIP format without rounding numeric IDs."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        descriptors = [name for name in names if PurePosixPath(name).name == "describe"]
        if len(descriptors) != 1:
            raise ValueError(f"Expected one describe file, found {len(descriptors)}")
        descriptor = descriptors[0]
        root = str(PurePosixPath(descriptor).parent)
        meta = json.loads(archive.read(descriptor), parse_float=str, parse_int=str)
        notebook_id = str(meta.get("identify") or PurePosixPath(root).name)
        notebook_name = str(meta.get("name") or notebook_id)
        pages = []
        for number, item in enumerate(meta.get("canvasArr") or [], 1):
            page_id = str(item.get("identify") or number)
            page_root = f"{root}/{item.get('subPath', f'pages/{page_id}')}"
            clip = f"{page_root}/clip.jpg"
            if clip in names:
                image = archive.read(clip)
            else:
                content = json.loads(archive.read(f"{page_root}/content"), parse_float=str, parse_int=str)
                images = content.get("images") or []
                if not images:
                    raise ValueError(f"Page {page_id} contains no image")
                image = archive.read(f"{page_root}/{images[-1]['localPath']}")
            pages.append(Page(notebook_id, notebook_name, page_id, number, image, _ext(image), hashlib.sha256(image).hexdigest()))
        return pages
