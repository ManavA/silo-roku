import json
import tempfile
from pathlib import Path
import unittest

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]


class SiloEbookAdapterTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as directory:
            return run_function(
                [ROOT / "source/adapters/SiloAdapter.brs", ROOT / "source/adapters/SiloEbookAdapter.brs"],
                name, list(args), root=Path(directory),
            )

    def test_profile_scoped_progress_request_uses_ordered_v2_contract(self):
        session = {"baseUrl": "https://fixture.example", "accessToken": "secret", "profileId": "reader"}
        params = {"contentId": "ebook:one", "fileId": "42", "location": "epubcfi(/6/4!/4/2)",
                  "progress": 0.25, "updatedAt": "2026-10-22T12:00:00.123Z"}
        request = self.call("BuildSiloEbookRequest", "ebook_save_progress", session, params)
        self.assertTrue(request["ok"])
        self.assertEqual(request["method"], "PUT")
        self.assertEqual(request["url"], "https://fixture.example/api/v2/ebooks/ebook%3Aone/progress")
        self.assertEqual(request["headers"]["X-Profile-Id"], "reader")
        self.assertEqual(json.loads(request["body"]), {
            "file_id": "42", "location": "epubcfi(/6/4!/4/2)",
            "progress": 0.25, "updated_at": "2026-10-22T12:00:00.123Z",
        })
        params["updatedAt"] = "2026-10-22T12:00:00Z"
        self.assertFalse(self.call("BuildSiloEbookRequest", "ebook_save_progress", session, params)["ok"])

    def test_progress_receipt_rejects_different_file_and_older_position(self):
        expected = {"contentId": "ebook:one", "fileId": "42", "location": "epubcfi(/6/4!/4/2)",
                    "updatedAt": "2026-10-22T12:00:00.123Z", "progress": 0.25}
        receipt = {"progress": {"content_id": "ebook:one", "file_id": "42",
                                "location": "epubcfi(/6/4!/4/2)", "progress": 0.25,
                                "updated_at": "2026-10-22T12:00:00.123Z"}}
        self.assertTrue(self.call("SiloEbookProgressReceipt", receipt, expected))
        receipt["progress"]["progress"] = 0.3
        self.assertFalse(self.call("SiloEbookProgressReceipt", receipt, expected))
        receipt["progress"]["progress"] = 0.25
        receipt["progress"]["file_id"] = "43"
        self.assertFalse(self.call("SiloEbookProgressReceipt", receipt, expected))
        receipt["progress"]["file_id"] = "42"
        receipt["progress"]["location"] = "epubcfi(/6/2!/4/2)"
        self.assertFalse(self.call("SiloEbookProgressReceipt", receipt, expected))

    def test_text_page_request_and_projection_are_bounded(self):
        session = {"baseUrl": "https://fixture.example", "accessToken": "secret", "profileId": "reader"}
        params = {"contentId": "ebook:one", "fileId": "42", "pageIndex": 1}
        request = self.call("BuildSiloEbookRequest", "ebook_text_page", session, params)
        self.assertTrue(request["ok"])
        self.assertEqual(request["url"], "https://fixture.example/api/v2/ebooks/ebook%3Aone/files/42/text-pages/1")
        self.assertEqual(request["headers"]["X-Profile-Id"], "reader")
        raw = {"revision": "a" * 64, "location": "silo-text-v1:" + "a" * 64 + ":0:2048",
               "text": "  A readable page\n", "page_index": 1, "total_pages": 3,
               "previous_page": 0, "next_page": 2}
        page = self.call("SiloEbookTextPage", raw, 1)
        self.assertTrue(page["ok"])
        self.assertEqual(page["data"]["text"], "  A readable page\n")
        raw["page_index"] = 2
        self.assertFalse(self.call("SiloEbookTextPage", raw, 1)["ok"])
        raw["page_index"] = 1
        raw["text"] = "x" * 17000
        self.assertFalse(self.call("SiloEbookTextPage", raw, 1)["ok"])

    def test_book_detail_selects_authorized_epub_file(self):
        raw = {"content_id": "ebook:one", "type": "ebook", "title": "Example",
               "versions": [{"file_id": "41", "container": "pdf"},
                            {"file_id": "42", "container": "epub"}]}
        result = self.call("SiloEbookDetail", raw, "ebook:one")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["fileId"], "42")
        raw["versions"][1]["container"] = "mobi"
        self.assertFalse(self.call("SiloEbookDetail", raw, "ebook:one")["ok"])
        raw["type"] = "movie"
        self.assertFalse(self.call("SiloEbookDetail", raw, "ebook:one")["ok"])


if __name__ == "__main__":
    unittest.main()
