import os
import tempfile
import unittest
import json
import zipfile
from pathlib import Path


class ConfigurationTests(unittest.TestCase):
    def test_allowed_emails_are_normalized(self):
        os.environ["ALLOWED_EMAILS"] = " A@Example.com, b@example.com ,,"
        from app.config import Settings
        value = Settings.from_env().allowed_emails
        self.assertEqual(value, frozenset({"a@example.com", "b@example.com"}))

    def test_database_prevents_duplicate_source_page(self):
        from app.db import Database
        from app.demo import demo_imports
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user = db.upsert_user("test@example.com", "Test")
            db.seed_demo(user["id"], demo_imports()[:1])
            db.seed_demo(user["id"], demo_imports()[:1])
            count = db.one("SELECT count(*) value FROM imports WHERE user_id=?", (user["id"],))["value"]
            self.assertEqual(count, 1)

    def test_connection_secrets_are_encrypted_and_round_trip(self):
        from app.secrets import SecretStore
        store = SecretStore("unit-test-key")
        encrypted = store.seal({"refresh_token": "top-secret"})
        self.assertNotIn("top-secret", encrypted)
        self.assertEqual(store.open(encrypted)["refresh_token"], "top-secret")

    def test_backup_parser_keeps_stable_page_id(self):
        from app.huion import read_backup
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "sample.huionnoteios.zip"
            meta = {"identify": 12345678901234567890, "name": "Test", "canvasArr": [{"identify": 98765432109876543210, "subPath": "pages/p1"}]}
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("book/describe", json.dumps(meta))
                archive.writestr("book/pages/p1/clip.jpg", b"\xff\xd8\xfftest")
            pages = read_backup(archive_path)
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0].page_id, "98765432109876543210")
            self.assertEqual(pages[0].image_ext, ".jpg")

    def test_ai_result_normalizes_tasks_and_tags(self):
        from app.ai import AIResult
        result = AIResult.from_dict({
            "title": "  Porada  ", "summary": "Souhrn", "cleaned_text": "Text",
            "tasks": [{"text": " Zavolat Janě ", "due": "2026-09-20"}, {"text": "", "due": None}],
            "tags": ["Projekt Alfa", "projekt-alfa", " Porada "],
        })
        self.assertEqual(result.title, "Porada")
        self.assertEqual(result.tasks, [{"text": "Zavolat Janě", "due": "2026-09-20"}])
        self.assertEqual(result.tags, ["projekt-alfa", "porada"])


if __name__ == "__main__":
    unittest.main()
