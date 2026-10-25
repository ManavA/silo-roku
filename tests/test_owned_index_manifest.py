"""Pure quota/coverage lifecycle for disposable, scoped Plex inventory shards."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
PAGE_POLICY = ROOT / "source/core/OwnedIndexPolicy.brs"
POLICY = ROOT / "source/core/OwnedIndexManifestPolicy.brs"
NOW = 1791882000
SCOPE = {"provider": "plex", "sourceId": "plex:fixture-server", "profileId": "",
         "accountId": "fixture-account", "sessionRevision": 3, "inventoryRunId": "run-1"}


def job(library="10", offset=0):
    return {"provider": "plex", "sourceId": SCOPE["sourceId"], "profileId": "",
            "inventoryRunId": "run-1", "libraryId": library, "offset": offset,
            "limit": 48, "requestId": offset + 1}


def shard(library="10", offset=0, raw_count=48, terminal=False, item_id=None,
          external=True, created_at=NOW):
    records = []
    if item_id is not None:
        records.append({"itemId": item_id, "type": "movie", "title": "Synthetic title",
                        "year": 2020, "tmdbId": "123" if external else "",
                        "imdbId": "", "tvdbId": ""})
    page = {"offset": offset, "pageSize": 48, "rawCount": raw_count,
            "totalSize": offset + raw_count, "totalKnown": False,
            "hasMore": not terminal, "nextOffset": -1 if terminal else offset + raw_count,
            "pageTerminal": terminal, "externalIdsComplete": external or not records,
            "records": records}
    if terminal and raw_count == 48:
        page["totalKnown"] = True
    data = {"schema": 1, **SCOPE, "libraryId": library, "createdAt": created_at,
            "expiresAt": created_at + 3600, **page}
    body = json.dumps(data, separators=(",", ":"))
    uri = f"cachefs:/owned-run-1-{library}-{offset}.json"
    return body, uri, len(body.encode("utf-8"))


def empty_manifest():
    return {"schema": 1, **SCOPE, "createdAt": NOW, "expiresAt": NOW + 3600,
            "totalBytes": 0, "shardCount": 0, "libraries": [], "shards": [],
            "sourceInventoryComplete": False, "authoritativeAbsence": False}


def synthetic_manifest(count=1, bytes_per_shard=1000, ids_per_shard=1, id_length=5):
    """Valid metadata, synthesized without large shard bodies or disk operations."""
    result = empty_manifest()
    for index in range(count):
        item_ids = [f"{index * 48 + item:0{id_length}d}" for item in range(ids_per_shard)]
        result["shards"].append({"libraryId": "10", "offset": index * 48,
                                 "rawCount": 48, "nextOffset": (index + 1) * 48,
                                 "terminal": False, "identityComplete": True,
                                 "recordCount": len(item_ids), "itemIds": item_ids,
                                 "uri": f"cachefs:/owned-run-1-10-{index * 48}.json",
                                 "bytes": bytes_per_shard, "createdAt": NOW,
                                 "expiresAt": NOW + 3600})
    result["shardCount"] = count
    result["totalBytes"] = count * bytes_per_shard
    if count:
        result["libraries"] = [{"libraryId": "10", "rawOffset": (count - 1) * 48,
                                 "nextOffset": count * 48, "terminal": False,
                                 "identityComplete": True, "coverageValid": True,
                                 "rawCount": count * 48, "recordCount": count * ids_per_shard}]
    return result


class OwnedIndexManifestTests(unittest.TestCase):
    def call(self, function, arguments):
        self.assertTrue(POLICY.is_file(), "owned inventory manifest policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-manifest-") as directory:
            return run_function([PAGE_POLICY, POLICY], function, arguments, root=Path(directory))

    def create(self):
        result = self.call("OwnedIndexManifestCreate", [SCOPE, NOW])
        self.assertTrue(result["ok"])
        return result["manifest"]

    def append(self, manifest, library="10", offset=0, raw_count=48,
               terminal=False, item_id="100", external=True, created_at=NOW):
        body, uri, size = shard(library, offset, raw_count, terminal, item_id, external, created_at)
        return self.call("OwnedIndexManifestAppend",
                         [manifest, job(library, offset), body, uri, size, created_at])

    def test_create_is_compact_scoped_and_has_no_source_absence_claim(self):
        manifest = self.create()
        self.assertEqual(empty_manifest(), manifest)
        self.assertTrue(self.call("OwnedIndexManifestValidate", [manifest, SCOPE, NOW])["ok"])
        self.assertEqual("cachefs:/owned-manifest-run-1.json",
                         self.call("OwnedIndexManifestUri", ["run-1"]))
        self.assertEqual("", self.call("OwnedIndexManifestUri", ["../outside"]))

    def test_scope_rejects_missing_private_url_and_unsupported_fields(self):
        for patch in ({"token": "synthetic-private"}, {"baseUrl": "https://private.example.test"},
                      {"provider": "silo"}, {"sourceId": "https://private.example.test"},
                      {"profileId": None}, {"accountId": ""}, {"sessionRevision": -1},
                      {"sessionRevision": "3"}, {"inventoryRunId": "../unsafe"}):
            with self.subTest(patch=patch):
                self.assertFalse(self.call("OwnedIndexManifestCreate", [{**SCOPE, **patch}, NOW])["ok"])
        missing = copy.deepcopy(SCOPE)
        missing.pop("profileId")
        self.assertFalse(self.call("OwnedIndexManifestCreate", [missing, NOW])["ok"])
        self.assertFalse(self.call("OwnedIndexManifestCreate", [SCOPE, 0])["ok"])

    def test_append_keeps_raw_offsets_including_filtered_slots_and_immutable_input(self):
        manifest = self.create()
        before = copy.deepcopy(manifest)
        result = self.append(manifest)
        self.assertTrue(result["ok"])
        self.assertEqual(before, manifest)
        updated = result["manifest"]
        self.assertEqual(1, updated["shardCount"])
        self.assertEqual(48, updated["libraries"][0]["rawCount"])
        self.assertEqual(1, updated["libraries"][0]["recordCount"])
        self.assertEqual(48, updated["libraries"][0]["nextOffset"])
        self.assertEqual(["100"], updated["shards"][0]["itemIds"])
        self.assertNotIn("title", json.dumps(updated))
        self.assertNotIn("records", json.dumps(updated))
        self.assertTrue(self.call("OwnedIndexManifestValidate", [updated, SCOPE, NOW])["ok"])

    def test_partial_and_terminal_libraries_never_prove_whole_source_absence(self):
        manifest = self.append(self.create())["manifest"]
        coverage = self.call("OwnedIndexManifestCoverage", [manifest, SCOPE, NOW])
        self.assertTrue(coverage["ok"])
        self.assertFalse(coverage["libraries"][0]["terminal"])
        self.assertFalse(coverage["sourceInventoryComplete"])
        self.assertFalse(coverage["authoritativeAbsence"])
        result = self.append(manifest, offset=48, raw_count=1, terminal=True,
                             item_id="101", external=False)
        self.assertTrue(result["ok"])
        coverage = self.call("OwnedIndexManifestCoverage", [result["manifest"], SCOPE, NOW])
        self.assertTrue(coverage["libraries"][0]["terminal"])
        self.assertFalse(coverage["libraries"][0]["identityComplete"])
        self.assertEqual(49, coverage["libraries"][0]["rawCount"])
        self.assertFalse(coverage["sourceInventoryComplete"])
        self.assertFalse(coverage["authoritativeAbsence"])

    def test_append_rejects_gap_overlap_duplicates_and_pages_after_terminal(self):
        manifest = self.append(self.create())["manifest"]
        for offset in (0, 1, 47, 49, 96):
            with self.subTest(offset=offset):
                self.assertFalse(self.append(manifest, offset=offset, item_id="200")["ok"])
        self.assertFalse(self.append(manifest, offset=48, item_id="100")["ok"])
        self.assertFalse(self.append(manifest, library="11", item_id="100")["ok"])
        self.assertFalse(self.append(self.create(), offset=48)["ok"])
        terminal = self.append(manifest, offset=48, raw_count=0, terminal=True, item_id=None)["manifest"]
        self.assertFalse(self.append(terminal, offset=48, item_id="200")["ok"])

    def test_append_validates_actual_body_path_bytes_scope_and_record_counts(self):
        manifest = self.create()
        body, uri, size = shard(item_id="100")
        changes = [([manifest, job(), body, uri, size + 1, NOW]),
                   ([manifest, job(), body, "cachefs:/owned-other-10-0.json", size, NOW]),
                   ([manifest, job(), body, uri + ".part", size, NOW]),
                   ([manifest, job(), "{}", uri, 2, NOW])]
        for patch in ({"accountId": "other"}, {"sourceId": "plex:other"},
                      {"profileId": "other"}, {"sessionRevision": 4},
                      {"inventoryRunId": "run-2"}, {"rawCount": 0},
                      {"token": "synthetic-private"}, {"createdAt": NOW - 1,
                                                          "expiresAt": NOW + 3599}):
            bad = {**json.loads(body), **patch}
            bad_body = json.dumps(bad, separators=(",", ":"))
            changes.append([manifest, job(), bad_body, uri, len(bad_body.encode()), NOW])
        for arguments in changes:
            with self.subTest(change=arguments[2:5]):
                result = self.call("OwnedIndexManifestAppend", arguments)
                self.assertFalse(result["ok"])
                self.assertNotIn("manifest", result)
                self.assertNotIn("synthetic-private", json.dumps(result))

    def test_quota_caps_shard_count_and_all_bytes_before_accepting(self):
        manifest = synthetic_manifest(200)
        self.assertTrue(self.call("OwnedIndexManifestValidate", [manifest, SCOPE, NOW])["ok"])
        quota = self.call("OwnedIndexManifestQuota", [manifest, 65536])
        self.assertTrue(quota["ok"])
        self.assertFalse(quota["canWrite"])
        self.assertEqual(0, quota["remainingShards"])
        self.assertFalse(self.append(manifest, offset=9600, item_id="20000")["ok"])
        oversized = synthetic_manifest(64, 65536)
        self.assertFalse(self.call("OwnedIndexManifestValidate", [oversized, SCOPE, NOW])["ok"])
        valid = synthetic_manifest(63, 65536)
        self.assertTrue(self.call("OwnedIndexManifestValidate", [valid, SCOPE, NOW])["ok"])
        self.assertFalse(self.call("OwnedIndexManifestQuota", [valid, 65536])["canWrite"])
        self.assertFalse(self.call("OwnedIndexManifestQuota", [empty_manifest(), 65537])["ok"])

    def test_metadata_has_its_own_bounded_read_size(self):
        manifest = synthetic_manifest(24, ids_per_shard=48, id_length=128)
        self.assertGreater(len(json.dumps(manifest).encode()), 131072)
        self.assertFalse(self.call("OwnedIndexManifestValidate", [manifest, SCOPE, NOW])["ok"])

    def test_append_rejects_mistyped_numeric_metadata_without_runtime_errors(self):
        body, uri, _ = shard(item_id="100")
        manifest = self.create()
        for field in ("createdAt", "expiresAt", "offset", "rawCount", "totalSize", "nextOffset"):
            changed = json.loads(body)
            changed[field] = str(changed[field])
            bad_body = json.dumps(changed, separators=(",", ":"))
            with self.subTest(field=field):
                result = self.call("OwnedIndexManifestAppend",
                                   [manifest, job(), bad_body, uri, len(bad_body.encode()), NOW])
                self.assertFalse(result["ok"])

    def test_validate_rejects_forged_scope_counts_flags_duplicates_and_paths(self):
        good = self.append(self.create())["manifest"]
        mutations = []
        for key, value in (("totalBytes", 0), ("shardCount", 2), ("token", "synthetic-private"),
                           ("sourceInventoryComplete", True), ("authoritativeAbsence", True),
                           ("expiresAt", NOW + 7200)):
            changed = copy.deepcopy(good)
            changed[key] = value
            mutations.append(changed)
        for field, value in (("bytes", 65537), ("uri", "cachefs:/../private.json"),
                             ("recordCount", 2), ("offset", 1), ("itemIds", ["100", "100"]),
                             ("url", "https://private.example.test")):
            changed = copy.deepcopy(good)
            changed["shards"][0][field] = value
            mutations.append(changed)
        for field, value in (("rawCount", 1), ("recordCount", 2), ("nextOffset", 1),
                             ("terminal", True), ("identityComplete", False)):
            changed = copy.deepcopy(good)
            changed["libraries"][0][field] = value
            mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed):
                self.assertFalse(self.call("OwnedIndexManifestValidate", [changed, SCOPE, NOW])["ok"])
        for patch in ({"sourceId": "plex:other"}, {"profileId": "other"},
                      {"accountId": "other"}, {"sessionRevision": 4}, {"inventoryRunId": "other"}):
            self.assertFalse(self.call("OwnedIndexManifestValidate", [good, {**SCOPE, **patch}, NOW])["ok"])

    def test_case_folded_native_keys_preserve_explicit_scope_and_empty_profile(self):
        lower_scope = {key.lower(): value for key, value in SCOPE.items()}
        result = self.call("OwnedIndexManifestCreate", [lower_scope, NOW])
        self.assertTrue(result["ok"])
        manifest = {key.lower(): value for key, value in result["manifest"].items()}
        self.assertTrue(self.call("OwnedIndexManifestValidate", [manifest, lower_scope, NOW])["ok"])

    def test_eviction_invalidates_only_affected_library_and_releases_bytes(self):
        manifest = self.append(self.create())["manifest"]
        manifest = self.append(manifest, offset=48, raw_count=1, terminal=True, item_id="101")["manifest"]
        manifest = self.append(manifest, library="11", raw_count=1, terminal=True, item_id="200")["manifest"]
        deleted = manifest["shards"][0]
        result = self.call("OwnedIndexManifestEvict", [manifest, [deleted["uri"]], NOW])
        self.assertTrue(result["ok"])
        evicted = result["manifest"]
        self.assertEqual(2, evicted["shardCount"])
        self.assertEqual(manifest["totalBytes"] - deleted["bytes"], evicted["totalBytes"])
        libraries = {value["libraryId"]: value for value in evicted["libraries"]}
        self.assertFalse(libraries["10"]["coverageValid"])
        self.assertFalse(libraries["10"]["terminal"])
        self.assertFalse(libraries["10"]["identityComplete"])
        self.assertTrue(libraries["11"]["coverageValid"])
        self.assertTrue(libraries["11"]["terminal"])
        self.assertTrue(self.call("OwnedIndexManifestValidate", [evicted, SCOPE, NOW])["ok"])
        self.assertFalse(self.append(evicted, offset=49, item_id="102")["ok"])
        self.assertFalse(self.call("OwnedIndexManifestEvict", [manifest, ["tmp:/private"], NOW])["ok"])

    def test_expiry_drops_references_and_invalidates_coverage_at_exact_boundary(self):
        manifest = self.append(self.create(), raw_count=1, terminal=True)["manifest"]
        self.assertFalse(self.call("OwnedIndexManifestValidate", [manifest, SCOPE, NOW + 3600])["ok"])
        coverage = self.call("OwnedIndexManifestCoverage", [manifest, SCOPE, NOW + 3600])
        self.assertFalse(coverage["ok"])
        self.assertEqual([], coverage["libraries"])
        expired = self.call("OwnedIndexManifestExpire", [manifest, NOW + 3600])
        self.assertTrue(expired["ok"])
        self.assertEqual([], expired["manifest"]["shards"])
        self.assertEqual(0, expired["manifest"]["totalBytes"])
        self.assertFalse(expired["manifest"]["libraries"][0]["coverageValid"])
        self.assertFalse(expired["manifest"]["libraries"][0]["terminal"])
        self.assertFalse(self.append(expired["manifest"], item_id="200", created_at=NOW + 3600)["ok"])

    def test_sign_out_purge_returns_only_validated_owned_prefix_paths_even_after_expiry(self):
        manifest = self.append(self.create())["manifest"]
        uri = manifest["shards"][0]["uri"]
        self.assertEqual([uri, uri + ".part", "cachefs:/owned-manifest-run-1.json",
                          "cachefs:/owned-manifest-run-1.json.part"],
                         self.call("OwnedIndexManifestPurgePlan", [manifest]))
        for unsafe in ("tmp:/private", "cachefs:/other.json", "cachefs:/owned-run-2-10-0.json",
                       "cachefs:/owned-run-1-../outside-0.json", "https://private.example.test"):
            changed = copy.deepcopy(manifest)
            changed["shards"][0]["uri"] = unsafe
            with self.subTest(unsafe=unsafe):
                self.assertEqual([], self.call("OwnedIndexManifestPurgePlan", [changed]))
        self.assertEqual([], self.call("OwnedIndexManifestPurgePlan", [{"shards": [{"uri": uri}]}]))


if __name__ == "__main__":
    unittest.main()
