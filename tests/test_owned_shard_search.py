"""Retained bounded cached-search job policy and synthetic inventory data."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/OwnedShardSearchPolicy.brs"
INDEX = ROOT / "source/core/OwnedIndexPolicy.brs"
MANIFEST = ROOT / "source/core/OwnedIndexManifestPolicy.brs"
RANKING = ROOT / "source/core/SearchPolicy.brs"
NOW = 1791882000
JOB = {"query": "moon", "sourceId": "plex:fixture-server", "profileId": "",
       "requestId": 7, "manifestUri": "cachefs:/owned-manifest-run-1.json"}
SESSION = {"sourceId": JOB["sourceId"], "profileId": "", "accountId": "fixture-account",
           "baseUrl": "https://server.example.test", "token": "synthetic-private-token",
           "accountToken": "synthetic-private-account", "clientId": "fixture-client"}


def record(item_id="100", title="Moon", year=2026):
    return {"itemId": item_id, "title": title, "type": "movie", "year": year,
            "tmdbId": item_id, "imdbId": "", "tvdbId": ""}


def inventory(pages=None):
    pages = [[record()]] if pages is None else pages
    scope = {"provider": "plex", "sourceId": JOB["sourceId"], "profileId": "",
             "accountId": SESSION["accountId"], "sessionRevision": 3, "inventoryRunId": "run-1"}
    files, shards = {}, []
    offset, total = 0, sum(len(page) for page in pages)
    for page in pages:
        raw_count = len(page)
        terminal = offset + raw_count == total
        data = {"schema": 1, **scope, "libraryId": "10", "createdAt": NOW,
                "expiresAt": NOW + 3600, "offset": offset, "pageSize": 48,
                "rawCount": raw_count, "totalSize": total, "totalKnown": True,
                "hasMore": not terminal, "nextOffset": -1 if terminal else offset + raw_count,
                "pageTerminal": terminal, "externalIdsComplete": True, "records": page}
        body = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        uri = f"cachefs:/owned-run-1-10-{offset}.json"
        files[uri] = body
        shards.append({"libraryId": "10", "offset": offset, "rawCount": raw_count,
                       "nextOffset": data["nextOffset"], "terminal": terminal,
                       "identityComplete": True, "recordCount": len(page),
                       "itemIds": [entry["itemId"] for entry in page], "uri": uri,
                       "bytes": len(body.encode()), "createdAt": NOW, "expiresAt": NOW + 3600})
        offset += raw_count
    last = shards[-1]
    manifest = {"schema": 1, **scope, "createdAt": NOW, "expiresAt": NOW + 3600,
                "totalBytes": sum(entry["bytes"] for entry in shards), "shardCount": len(shards),
                "libraries": [{"libraryId": "10", "rawOffset": last["offset"],
                               "nextOffset": last["nextOffset"], "terminal": last["terminal"],
                               "identityComplete": True, "coverageValid": True,
                               "rawCount": total, "recordCount": total}],
                "shards": shards, "sourceInventoryComplete": False, "authoritativeAbsence": False}
    files[JOB["manifestUri"]] = json.dumps(manifest, separators=(",", ":"))
    return manifest, files


class OwnedShardSearchTests(unittest.TestCase):
    def call(self, function, arguments):
        self.assertTrue(POLICY.is_file(), "bounded owned shard search policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-search-policy-") as directory:
            return run_function([INDEX, RANKING, POLICY], function, arguments, root=Path(directory))


    def test_job_is_bounded_scope_and_exact_cache_manifest_uri_without_credentials(self):
        self.assertTrue(self.call("OwnedShardSearchValidJob", [JOB]))
        for patch in ({"query": "x" * 121}, {"query": "m"}, {"query": "---"}, {"query": "  m "}, {"query": "moon\n"},
                      {"query": None}, {"sourceId": "silo:other"}, {"sourceId": ""},
                      {"profileId": None}, {"requestId": -1}, {"accountId": "private"},
                      {"token": "private"}, {"manifest": {}},
                      {"manifestUri": "tmp:/owned-manifest-run-1.json"},
                      {"manifestUri": "cachefs:/owned-manifest-../run.json"},
                      {"manifestUri": "cachefs:/owned-manifest-run-1.json.part"}):
            with self.subTest(patch=patch):
                self.assertFalse(self.call("OwnedShardSearchValidJob", [{**JOB, **patch}]))


    def test_rank_ties_keep_first_hundred_after_four_digit_arrival_counts(self):
        self.assertTrue(POLICY.is_file(), "bounded owned shard search policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-search-rank-") as directory:
            temporary = Path(directory)
            fixture = temporary / "ranking.brs"
            fixture.write_text('''
function RunShardRankingFixture() as Object
    state = OwnedShardSearchState("moon","plex:fixture-server")
    for page = 0 to 24
        records = []
        for slot = 1 to 48
            id = (page * 48 + slot).ToStr()
            records.Push({itemId:id,title:"Moon",type:"movie",year:2026,tmdbId:id,imdbId:"",tvdbId:""})
        end for
        state = OwnedShardSearchAccumulate(state,records)
    end for
    return OwnedShardSearchResults(state)
end function
''')
            outcome = run_function([INDEX, RANKING, POLICY, fixture], "RunShardRankingFixture", [], root=temporary)
        self.assertEqual([str(index) for index in range(1, 101)], [item["itemId"] for item in outcome["items"]])


if __name__ == "__main__":
    unittest.main()
