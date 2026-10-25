"""Browse shuffle names its structural scope and confirms ignored selections."""
import json
import re
import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class LibraryShuffleScopeTests(unittest.TestCase):
    def run_flow(self, setup, action):
        with tempfile.TemporaryDirectory() as tmp:
            source = (ROOT / "components/SiloUILibrary.brs").read_text()
            source = re.sub(r"sub BrowseDialog\(.*?\nend sub", "", source, count=1, flags=re.S)
            module = Path(tmp) / "library.brs"
            module.write_text(source + '''
sub BrowseDialog(title as String, labels as Object, handler as String)
    node = {buttonSelected:0,isSameNode:function(other)
        return other.id = 1
    end function,id:1}
    m.top.dialog = node:m.browseDialog = node
    m.labels = labels:m.title = title
    BrowseBindDialog(node,handler)
end sub
sub ShuffleBegin(kind as String, id as String)
    m.calls.Push({kind:kind,id:id})
end sub
''')
            result = run_brightscript([module, ROOT / "components/SiloUIDialogs.brs", ROOT / "source/core/SiloUIFormat.brs"], '''
    m.provider="silo":m.sourceId="silo:test":m.profileId="p":m.generation=1
    m.view="library":m.libraryToken=1:m.browseViewToken=1:m.top={}:m.calls=[]:m.browseDialog={}
    LibraryResetFilters():m.libraryId="7"
''' + setup + '''
    LibraryShuffle()
    before=m.calls.Count()
''' + action + '''
    print FormatJson({before:before,calls:m.calls,message:m.browseDialog.message})
''', root=Path(tmp))
            return json.loads(result)

    def test_filtered_library_waits_for_confirmation_and_preserves_captured_scope(self):
        result = self.run_flow('m.libraryGenre="Drama"', '''
    m.libraryId="changed"
    event={getRoSGNode:function()
        return {id:1}
    end function}
    onLibraryShuffleConfirm(event)
    onLibraryShuffleConfirm(event)
''')
        self.assertEqual(result["before"], 0)
        self.assertEqual(result["calls"], [{"kind": "library", "id": "7"}])
        self.assertIn("filters", result["message"])
        self.assertIn("person", result["message"])
        self.assertIn("list", result["message"])

    def test_unfiltered_structural_scopes_start_directly(self):
        cases = [
            ("", {"kind": "library", "id": "7"}),
            ('m.libraryCollection="u1":m.librarySource="user_collection"', {"kind": "user_collection", "id": "u1"}),
            ('m.libraryCollection="c1":m.librarySource="library_collection"', {"kind": "library_collection", "id": "c1"}),
        ]
        for setup, expected in cases:
            with self.subTest(setup=setup):
                result = self.run_flow(setup, "")
                self.assertEqual(result["before"], 1)
                self.assertEqual(result["calls"], [expected])

    def test_each_ignored_filter_or_source_requires_confirmation(self):
        selections = [
            'm.libraryPerson="actor"', 'm.libraryGenre="Drama"',
            'm.libraryWatched="unwatched"', 'm.libraryPrefix="A"',
            'm.libraryFormatFilter="4k"', 'm.libraryDecade=1990',
            'm.libraryMinimumRating=8', 'm.librarySource="watchlist"',
            'm.librarySource="favorites"', 'm.librarySource="history"',
            'm.librarySource="person"',
        ]
        for setup in selections:
            with self.subTest(setup=setup):
                result = self.run_flow(setup, "")
                self.assertEqual(result["calls"], [])
                self.assertIn("do not apply", result["message"])

    def test_cancel_or_stale_dialog_cannot_start_shuffle(self):
        for change in ['m.browseDialog.buttonSelected=1', 'm.libraryToken=2', 'm.profileId="other"', 'm.generation=2', 'm.sourceId="other"']:
            with self.subTest(change=change):
                result = self.run_flow('m.libraryGenre="Drama"', change + '''
    event={getRoSGNode:function()
        return {id:1}
    end function}
    onLibraryShuffleConfirm(event)
''')
                self.assertEqual(result["calls"], [])

    def test_filtered_collections_confirm_the_exact_collection(self):
        for kind in ["user_collection", "library_collection"]:
            with self.subTest(kind=kind):
                result = self.run_flow(f'm.librarySource="{kind}":m.libraryCollection="c1":m.libraryGenre="Drama"', '''
    event={getRoSGNode:function()
        return {id:1}
    end function}
    onLibraryShuffleConfirm(event)
''')
                self.assertEqual(result["before"], 0)
                self.assertEqual(result["calls"], [{"kind": kind, "id": "c1"}])
