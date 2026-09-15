import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ink2vault.ai import AIResult, process_image
from ink2vault.cli import main, parser
from ink2vault.config import Config
from ink2vault.huion import Page, read_backup, read_notebook
from ink2vault.pipeline import Pipeline, find_sources, markdown
from ink2vault.state import State


JPEG = b"\xff\xd8\xff" + b"test-image"


def make_backup(path: Path, image: bytes = JPEG) -> None:
    meta = {
        "identify": 12345678901234567890,
        "name": "Můj sešit",
        "canvasArr": [{"identify": 98765432109876543210, "subPath": "pages/p1"}],
    }
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr("book/describe", json.dumps(meta))
        archive.writestr("book/pages/p1/clip.jpg", image)


def make_live_notebook(path: Path, image: bytes = JPEG) -> None:
    path.mkdir(parents=True)
    meta = {
        "identify": 12345678901234567890,
        "name": "Živý sešit",
        "canvasArr": [{"identify": 98765432109876543210, "subPath": "pages/p1"}],
    }
    (path / "describe").write_text(json.dumps(meta), encoding="utf-8")
    page = path / "pages/p1"
    page.mkdir(parents=True)
    (page / "clip.jpg").write_bytes(image)


class LocalPipelineTests(unittest.TestCase):
    def test_cli_without_arguments_opens_menu(self):
        with patch("builtins.input", return_value="0"):
            self.assertEqual(main([]), 0)

    def test_cli_import_command_is_available(self):
        args = parser().parse_args(["import"])
        self.assertEqual(args.command, "import")

    def test_claude_structured_output_is_parsed(self):
        response = {
            "structured_output": {
                "title": "Nákup", "summary": "Seznam", "cleaned_text": "Mléko",
                "tasks": [{"text": "Koupit mléko", "due": None}], "tags": ["Domácnost"],
            }
        }
        completed = type("Completed", (), {
            "returncode": 0, "stdout": json.dumps(response), "stderr": "",
        })()
        with patch("ink2vault.ai.subprocess.run", return_value=completed) as run:
            result = process_image(Path("/tmp/page.jpg"), "Sešit", 1, "sonnet")
        self.assertEqual(result.title, "Nákup")
        self.assertEqual(result.tasks[0]["text"], "Koupit mléko")
        command = run.call_args.args[0]
        self.assertIn("--json-schema", command)
        self.assertIn("Read", command)

    def test_backup_parser_keeps_stable_page_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.huionnoteios"
            make_backup(path)
            pages = read_backup(path)
        self.assertEqual(pages[0].page_id, "98765432109876543210")
        self.assertEqual(pages[0].notebook_name, "Můj sešit")

    def test_extensionless_icloud_archive_is_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "Test-123456"
            make_backup(archive)
            sources = list(find_sources(root))
            pages = read_backup(sources[0])
        self.assertEqual(sources, [archive])
        self.assertEqual(len(pages), 1)

    def test_live_icloud_notebook_is_discovered_and_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notebook = root / "newData" / "book-id"
            make_live_notebook(notebook)
            sources = list(find_sources(root / "newData"))
            pages = read_notebook(sources[0])
        self.assertEqual(sources, [notebook])
        self.assertEqual(pages[0].page_id, "98765432109876543210")
        self.assertEqual(pages[0].notebook_name, "Živý sešit")

    def test_ai_result_normalizes_tasks_and_tags(self):
        result = AIResult.from_dict({
            "title": " Porada ", "summary": "Souhrn", "cleaned_text": "Text",
            "tasks": [{"text": " Zavolat Janě ", "due": "2026-09-20"}, {"text": "", "due": None}],
            "tags": ["Projekt Alfa", "projekt-alfa", " Porada "],
        })
        self.assertEqual(result.tasks, [{"text": "Zavolat Janě", "due": "2026-09-20"}])
        self.assertEqual(result.tags, ["projekt-alfa", "porada"])

    def test_markdown_contains_summary_tasks_and_attachment(self):
        page = Page("book", "Sešit", "page", 1, JPEG, ".jpg", "hash")
        result = AIResult("Plán", "Krátké shrnutí", "Čistý text", [{"text": "Zavolat", "due": None}], ["projekt"])
        value = markdown("Rukopis", page, result, "Attachments/page.jpg", "book:page")
        self.assertIn("## Shrnutí\n\nKrátké shrnutí", value)
        self.assertIn("- [ ] Zavolat", value)
        self.assertIn("![[Attachments/page.jpg]]", value)

    def test_second_scan_never_overwrites_edited_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, vault = root / "source", root / "vault"
            source.mkdir(); vault.mkdir()
            make_backup(source / "backup.huionnoteios")
            config = Config(str(source), str(vault))
            pipeline = Pipeline(config, State(root / "state.sqlite3"))
            ai_result = AIResult("Moje poznámka", "Shrnutí", "Obsah", [], ["test"])
            with patch("ink2vault.pipeline.process_image", return_value=ai_result):
                self.assertEqual(pipeline.scan(), 1)
                note = next((vault / config.note_folder).glob("*.md"))
                note.write_text("MOJE RUČNÍ ÚPRAVA", encoding="utf-8")
                self.assertEqual(pipeline.scan(), 0)
            self.assertEqual(note.read_text(encoding="utf-8"), "MOJE RUČNÍ ÚPRAVA")

    def test_scan_recovers_note_written_before_state_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, vault = root / "source", root / "vault"
            source.mkdir(); vault.mkdir()
            backup = source / "backup.huionnoteios"
            make_backup(backup)
            config = Config(str(source), str(vault))
            state = State(root / "state.sqlite3")
            page = read_backup(backup)[0]
            source_id = "%s:%s" % (page.notebook_id, page.page_id)
            state.begin(source_id, str(backup), page.notebook_name, page.page_number, page.image_sha256)
            state.reserve(source_id, "Inbox/Rukopis/recovered.md")
            recovered = vault / "Inbox/Rukopis/recovered.md"
            recovered.parent.mkdir(parents=True)
            recovered.write_text("už zapsáno", encoding="utf-8")

            with patch("ink2vault.pipeline.process_image") as ai:
                self.assertEqual(Pipeline(config, state).scan(), 0)
            ai.assert_not_called()
            self.assertEqual(state.get(source_id)["status"], "done")

    def test_state_resets_errors_without_forgetting_done_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.begin("done", "a", "Sešit", 1, "hash-a")
            state.done("done", "note.md")
            state.begin("error", "b", "Sešit", 2, "hash-b")
            state.fail("error", "chyba")

            self.assertEqual(state.reset_errors(), 1)
            self.assertIsNotNone(state.get("done"))
            self.assertIsNone(state.get("error"))

    def test_state_reset_all_forgets_every_page(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.begin("page", "a", "Sešit", 1, "hash")
            state.done("page", "note.md")

            self.assertEqual(state.reset_all(), 1)
            self.assertIsNone(state.get("page"))


if __name__ == "__main__":
    unittest.main()
