"""Retained exact cached Services job validation policy."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/OwnedServiceMatchPolicy.brs"
INDEX = ROOT / "source/core/OwnedIndexPolicy.brs"
MANIFEST = ROOT / "source/core/OwnedIndexManifestPolicy.brs"
SEARCH = ROOT / "source/core/OwnedShardSearchPolicy.brs"
RANKING = ROOT / "source/core/SearchPolicy.brs"
from tests.test_owned_shard_search import inventory, record, SESSION, NOW


def candidate(tmdb="100", imdb="", tvdb="", kind="movie"):
    identity = tmdb or ("imdb:" + imdb if imdb else "tvdb:" + tvdb)
    return {"catalogId": "metadata:" + kind + ":" + identity, "type": kind,
            "tmdbId": tmdb, "imdbId": imdb, "tvdbId": tvdb}


JOB = {"sourceId": SESSION["sourceId"], "profileId": "", "requestId": 7,
       "manifestUri": "cachefs:/owned-manifest-run-1.json", "candidates": [candidate()]}


class OwnedServiceMatchTests(unittest.TestCase):
    def call(self, function, *arguments):
        self.assertTrue(POLICY.is_file(), "exact owned service matching policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-service-policy-") as directory:
            return run_function([INDEX, MANIFEST, RANKING, SEARCH, POLICY], function, list(arguments),
                                root=Path(directory))


    def test_job_accepts_only_bounded_public_exact_identity_and_cache_path(self):
        self.assertTrue(self.call("OwnedServiceMatchValidJob", JOB))
        self.assertTrue(self.call("OwnedServiceMatchValidJob", {**JOB, "candidates": []}))
        for patch in ({"candidates": [candidate()] * 101}, {"candidates": None},
                      {"candidates": [candidate(), candidate()]},
                      {"candidates": [{**candidate(), "token": "private"}]},
                      {"candidates": [{**candidate(), "title": "Moon"}]},
                      {"candidates": [candidate(tmdb="", imdb="", tvdb="")]},
                      {"candidates": [candidate(kind="episode")]},
                      {"candidates": [candidate(tmdb="100?token=private")]},
                      {"candidates": [{**candidate(), "catalogId": "https://private.test"}]},
                      {"candidates": [{**candidate(), "Type": "show"}]},
                      {"accountId": "private"}, {"sessionRevision": 3}, {"token": "private"},
                      {"sourceId": "silo:other"}, {"profileId": None}, {"requestId": -1},
                      {"manifestUri": "tmp:/owned-manifest-run-1.json"},
                      {"manifestUri": "cachefs:/owned-manifest-../run.json"}):
            with self.subTest(patch=patch):
                self.assertFalse(self.call("OwnedServiceMatchValidJob", {**JOB, **patch}))


if __name__ == "__main__":
    unittest.main()
