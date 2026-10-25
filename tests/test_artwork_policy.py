"""Private artwork policy executes the actual BrightScript before any I/O."""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/ArtworkPolicy.brs"
FILES = [ROOT / "source/core/ServerUrlPolicy.brs", ROOT / "source/adapters/SiloAdapter.brs", POLICY]
JOB = {"provider": "silo", "sourceId": "silo:fixture-server", "profileId": "fixture-profile",
       "generation": 7, "route": "library", "itemId": "fixture-item", "kind": "poster", "requestId": 12}
SESSION = {"sourceId": JOB["sourceId"], "profileId": JOB["profileId"],
           "baseUrl": "https://server.example.test", "accessToken": "synthetic-private-access",
           "profileToken": "synthetic-private-profile", "deviceId": "fixture-device"}
FIXTURE = ROOT / "tests/fixtures/artwork/silo_detail_small.json"


class ArtworkPolicyTests(unittest.TestCase):
    def call(self, name, args):
        self.assertTrue(POLICY.is_file(), "Private artwork policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-artwork-policy-") as directory:
            return run_function(FILES, name, args, root=Path(directory))

    def test_scene_job_has_only_scope_native_identity_and_safe_request_identity(self):
        self.assertTrue(self.call("ArtworkValidJob", [JOB]))
        for change in ({"url": "https://cdn.example.test/private.jpg?signature=synthetic"},
                       {"headers": {"Authorization": "synthetic"}}, {"params": {}},
                       {"accessToken": "synthetic"}, {"thumbKey": "/library/metadata/1/thumb/2"}):
            self.assertFalse(self.call("ArtworkValidJob", [{**JOB, **change}]))

    def test_brightscript_scene_literal_job_retains_scope_through_validation(self):
        self.assertTrue(POLICY.is_file(), "Private artwork policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-artwork-literal-") as directory:
            temporary = Path(directory)
            helper = temporary / "literal.brs"
            helper.write_text('''function ArtworkLiteralFixture() as Dynamic
                job = {provider:"silo",sourceId:"silo:fixture-server",profileId:"fixture-profile",generation:7,route:"library",itemId:"fixture-item",kind:"poster",requestId:12}
                job.sourceId = "silo:fixture-server"
                return ArtworkValidJob(job)
                end function''')
            self.assertTrue(run_function([*FILES, helper], "ArtworkLiteralFixture", [], root=temporary))

    def test_unsafe_job_identity_cannot_become_a_tmp_filename(self):
        for change in ({"requestId": "../escape"}, {"requestId": -1}, {"requestId": 1.5},
                       {"requestId": "signed?token=synthetic"}, {"generation": -1},
                       {"itemId": "../private"}, {"itemId": "https://cdn.example.test/a.jpg"},
                       {"kind": "logo"}, {"sourceId": "plex:other"}, {"profileId": ""}):
            self.assertFalse(self.call("ArtworkValidJob", [{**JOB, **change}]))

    def test_plex_relative_thumb_is_validated_but_signed_or_absolute_thumb_is_rejected(self):
        job = {**JOB, "provider": "plex", "sourceId": "plex:fixture-server", "profileId": "",
               "itemId": "101", "thumbKey": "/library/metadata/101/thumb/1700000000"}
        self.assertTrue(self.call("ArtworkValidJob", [job]))
        for thumb in ("//evil.test/a.jpg", "/library/metadata/101/thumb/2?X-Plex-Token=synthetic",
                      "/library/metadata/101/thumb/../2", "https://evil.test/a.jpg", "/library/metadata/102/thumb/2"):
            self.assertFalse(self.call("ArtworkValidJob", [{**job, "thumbKey": thumb}]))

    def test_silo_detail_uses_small_tier_and_authentication_headers_on_selected_server(self):
        request = self.call("ArtworkDetailRequest", [JOB, SESSION])
        self.assertTrue(request["ok"])
        self.assertEqual("GET", request["method"])
        self.assertEqual("/api/v2/catalog/items/fixture-item", urlsplit(request["url"]).path)
        self.assertEqual({"image_size": ["small"]}, parse_qs(urlsplit(request["url"]).query))
        self.assertEqual("Bearer synthetic-private-access", request["headers"]["Authorization"])
        self.assertEqual(JOB["profileId"], request["headers"]["X-Profile-Id"])
        self.assertNotIn("synthetic-private", request["url"])

    def test_detail_request_requires_exact_selected_source_and_profile(self):
        for change in ({"sourceId": "silo:other"}, {"profileId": "other"}, {"accessToken": ""}):
            result = self.call("ArtworkDetailRequest", [JOB, {**SESSION, **change}])
            self.assertFalse(result["ok"])
            self.assertNotIn("url", result)

    def test_signed_silo_image_is_resolved_inside_policy_with_empty_download_headers(self):
        body = json.loads(FIXTURE.read_text())
        result = self.call("ArtworkSiloImageRequest", [JOB, json.dumps(body)])
        self.assertTrue(result["ok"])
        self.assertEqual(body["poster_url"], result["url"])
        self.assertEqual({}, result["headers"])
        self.assertEqual("GET", result["method"])
        backdrop = self.call("ArtworkSiloImageRequest", [{**JOB, "kind": "backdrop"}, json.dumps(body)])
        self.assertEqual(body["backdrop_url"], backdrop["url"])

    def test_signed_image_resolution_rejects_wrong_item_missing_image_and_unsafe_url(self):
        body = json.loads(FIXTURE.read_text())
        for change in ({"content_id": "other"}, {"poster_url": ""},
                       {"poster_url": "http://cdn.example.test/a.jpg"},
                       {"poster_url": "https://user:secret@cdn.example.test/a.jpg"},
                       {"poster_url": "https://cdn.example.test/a.jpg#secret"},
                       {"poster_url": "file:/private.jpg"}, {"poster_url": "https://cdn.example.test/a jpg"}):
            result = self.call("ArtworkSiloImageRequest", [JOB, json.dumps({**body, **change})])
            self.assertFalse(result["ok"])
            self.assertNotIn("url", result)

    def test_session_snapshot_invalidates_revision_credentials_server_account_and_profile(self):
        self.assertTrue(self.call("ArtworkSessionMatches", [JOB, SESSION, SESSION, 3, 3]))
        self.assertFalse(self.call("ArtworkSessionMatches", [JOB, SESSION, SESSION, 3, 4]))
        for field in ("sourceId", "profileId", "accessToken", "profileToken", "baseUrl", "accountId", "refreshToken"):
            current = {**SESSION, field: "changed"}
            self.assertFalse(self.call("ArtworkSessionMatches", [JOB, SESSION, current, 3, 3]))

    def test_ready_files_require_matching_mime_magic_and_low_encoded_size(self):
        for mime, magic, extension in (("image/jpeg", "ffd8ffe000104a4649460001", "jpg"),
                                       ("image/png", "89504e470d0a1a0a0000000d", "png"),
                                       ("image/webp", "524946460400000057454250", "webp")):
            result = self.call("ArtworkFilePlan", [JOB, mime, magic, 2048])
            self.assertTrue(result["ok"])
            self.assertEqual("tmp:/artwork-7-12." + extension, result["uri"])
        for mime, magic, size in (("image/jpeg", "89504e470d0a1a0a0000000d", 2048),
                                  ("", "ffd8ffe000104a4649460001", 2048),
                                  ("text/html", "3c68746d6c3e000000000000", 2048),
                                  ("image/jpeg", "ffd8ff", 3),
                                  ("image/jpeg", "ffd8ffe000104a4649460001", 262145)):
            self.assertFalse(self.call("ArtworkFilePlan", [JOB, mime, magic, size])["ok"])

    def test_result_exposes_only_scoped_local_uri_and_coarse_error(self):
        outcome = {"status": "ready", "uri": "tmp:/artwork-7-12.jpg", "errorCode": "",
                   "url": "https://cdn.example.test/a.jpg?signature=synthetic", "headers": {"token": "synthetic"}}
        result = self.call("ArtworkEnvelope", [JOB, outcome])
        self.assertEqual({"status", "uri", "errorCode", *JOB}, set(result))
        self.assertEqual("tmp:/artwork-7-12.jpg", result["uri"])
        self.assertNotIn("synthetic", json.dumps(result))
        unsafe = self.call("ArtworkEnvelope", [JOB, {**outcome, "uri": outcome["url"], "errorCode": "token=synthetic"}])
        self.assertEqual("", unsafe["uri"])
        self.assertEqual("unavailable", unsafe["status"])
        self.assertEqual("invalid_response", unsafe["errorCode"])


if __name__ == "__main__":
    unittest.main()
