from __future__ import annotations

from datetime import datetime, timedelta, timezone


def demo_imports() -> list[dict]:
    now = datetime.now(timezone.utc)
    base_events = [
        ("drive", "done", "Stránka nalezena v připojené složce Google Drive"),
        ("download", "done", "Záloha byla bezpečně stažena"),
        ("extract", "done", "Obraz stránky byl extrahován"),
    ]
    notes = [
        (1, "Architektura synchronizace poznámek", "done", "synced", 100, .96),
        (2, "Příprava prezentace pro klienta", "done", "synced", 100, .91),
        (3, "Nápady pro nový web", "review", "review", 82, .63),
        (4, "Seznam úkolů na tento týden", "processing", "ocr", 68, .88),
        (5, "Poznámky ze schůzky", "done", "synced", 100, .94),
        (6, "Nákupní seznam", "done", "synced", 100, .98),
        (7, "Nečitelný nadpis", "error", "ocr", 42, .31),
        (8, "Návrh databázového modelu", "done", "synced", 100, .89),
        (9, "Volné nápady", "queued", "queued", 8, None),
    ]
    result = []
    for index, title, status, stage, progress, confidence in notes:
        stamp = (now - timedelta(minutes=(index - 1) * 13)).isoformat(timespec="seconds")
        events = list(base_events)
        if stage not in {"queued"}:
            events.append(("ocr", "done" if stage != "ocr" else "error", "Rukopis rozpoznán" if stage != "ocr" else "OCR nedosáhlo minimální jistoty"))
        if stage == "synced":
            events.extend([
                ("markdown", "done", "Markdown vytvořen atomickým zápisem"),
                ("sync", "done", "Poznámka odeslána do LiveSync"),
            ])
        markdown = f"""---
created: {now.date().isoformat()}
tags:
  - rukopis
  - poznámky
---

# {title}

Toto je ukázka zpracovaného obsahu ručně psané stránky. Výsledná poznámka je obyčejný Markdown a po importu ji můžeš libovolně upravovat v Obsidianu.

## Úkoly

- [ ] Zkontrolovat výsledek
- [ ] Doplnit související odkazy

![[Attachments/Rukopis/page-{index:02d}.png]]
"""
        result.append({
            "source_id": f"demo-page-{index}", "page_number": index, "title": title,
            "notebook": "Ukázkový zápisník", "status": status, "stage": stage,
            "progress": progress, "ocr_confidence": confidence,
            "target_path": f"Inbox/{now.date().isoformat()} – {title}.md" if status == "done" else None,
            "image_path": f"/static/demo/page-{index:02d}.png",
            "raw_ocr": "Ukázkový surový přepis rukopisu. Některá slova mohou být rozpoznána nepřesně.",
            "markdown": markdown, "error": "Rukopis je příliš slabý nebo překrytý kresbou." if status == "error" else None,
            "source_checksum": f"demo-{index:02d}", "protected": status == "done" and index in {1, 2, 5},
            "updated_at": stamp, "events": events,
        })
    return result
