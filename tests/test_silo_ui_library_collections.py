"""Collection selection keeps personal and server-owned scopes distinct."""

import unittest
from pathlib import Path
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "components/SiloUILibrary.brs"


class LibraryCollectionChoiceTests(unittest.TestCase):
    def choice(self, kind, entry):
        return run_function(LIBRARY, "LibraryCollectionChoice", [kind, entry])

    def test_personal_collection_sets_user_source_without_stale_library(self):
        self.assertEqual(self.choice("collection", {"id": "personal-1", "source": "user_collection"}),
                         {"source": "user_collection", "collectionId": "personal-1", "libraryId": ""})

    def test_server_collection_keeps_owning_library_scope(self):
        self.assertEqual(self.choice("server_collection", {"id": "admin-1", "source": "library_collection", "libraryId": "12"}),
                         {"source": "library_collection", "collectionId": "admin-1", "libraryId": "12"})

    def test_unknown_or_empty_selection_clears_collection_scope(self):
        empty = {"source": "query", "collectionId": "", "libraryId": ""}
        self.assertEqual(self.choice("collection", None), empty)
        self.assertEqual(self.choice("server_collection", {"id": "admin-1", "libraryId": ""}), empty)
        self.assertEqual(self.choice("server_collection", {"id": "admin-1", "libraryId": "12", "source": "user_collection"}), empty)
