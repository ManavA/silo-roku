"""The Roku library options keep the two collection paths adjacent and named."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "components/SiloUILibrary.brs"


class LibraryOptionsTests(unittest.TestCase):
    def test_server_collections_are_next_to_personal_and_dispatch_at_index_two(self):
        source = LIBRARY.read_text()
        functions = "\n".join(re.search(r"sub " + name + r"\(.*?\nend sub", source, re.S)[0]
                              for name in ("LibraryOptions", "onLibraryOption"))
        functions += "\n" + re.search(r"function LibraryShuffleLabel\(.*?\nend function", source, re.S)[0]
        format_source = (ROOT / "source/core/SiloUIFormat.brs").read_text()
        functions += "\n" + re.search(r"function TextOr\(.*?\nend function", format_source, re.S)[0]
        helpers = '''
sub BrowsePagedChoices(title as String, choices as Object, handler as String)
 m.labels=choices
end sub
function BrowseChoiceIndex(event as Object) as Integer
 return m.index
end function
function BrowseCaptureContext() as Object
 return {}
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.called={action:action,purpose:purpose}
end sub
'''
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "options.brs"
            file.write_text(functions + helpers)
            out = run_brightscript([file], '''
m.provider="silo":m.libraryToken=3:m.index=2:m.librarySource="query":m.libraryCollection=""
LibraryOptions()
onLibraryOption(invalid)
print FormatJson({first:m.labels[0],personal:m.labels[1],server:m.labels[2],called:m.called})
''', root=Path(directory))
        self.assertEqual(json.loads(out.splitlines()[-1]), {
            "first": "Libraries", "personal": "Collections", "server": "Server collections",
            "called": {"action": "server_collections", "purpose": "lib_server_collections"},
        })

    def test_top_rated_sort_keeps_scope_and_cursor_and_stays_silo_only(self):
        scene = (ROOT / "components/SiloUIScene.brs").read_text()
        pill_move = re.search(r"function PillMove\(.*?\nend function", scene, re.S)[0]
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "sorts.brs"
            helper.write_text(pill_move + "\n" + '''
sub BuildPills(parent as Object, name as String, labels as Object, spacing as Integer, height as Integer, fontSize as Integer)
 m.builds=m.builds+1:m.labels=labels:m.pillGroups[name]={index:0,pills:labels}
end sub
sub PaintPills(name as String, focused as Boolean)
end sub
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.requests.Push({action:action,params:params,token:extra})
end sub
function TextOr(value as Dynamic) as String
 if type(value)="String" then return value
 return ""
end function
''')
            out = run_brightscript([LIBRARY, helper, ROOT/"components/SiloUIAccessibility.brs"], '''
m.top={appFocused:false}
m.provider="silo":m.librarySortProvider="":m.builds=0:m.libraryTabs={}:m.pillGroups={}:m.requests=[]
m.librarySorts=[{sort:"added_at",order:"desc"},{sort:"title",order:"asc"},{sort:"release_date",order:"desc"}]
m.labels=["Recently added","A–Z","Newest"]:m.pillGroups={libraryTabs:{index:0,pills:m.labels}}
m.libraryTitle={}:m.libraryRetryButtons=invalid:m.libraryToken=4:m.grid={}:m.libraryEmpty={}
m.libraryType="movie":m.libraryPerson="":m.libraryId="lib-1":m.librarySource="collection"
m.libraryCollection="collection-1":m.libraryGenre="Drama":m.libraryWatched="unwatched":m.libraryPrefix="A":m.libraryFormatFilter="hdr"
m.libraryCursor="old-page":m.zone="libraryTabs"
LibraryQuery(true)
LibraryKey("right"):LibraryKey("right"):LibraryKey("right")
selected=m.requests.Peek():labels=m.labels
LibraryQuery(true)
sameProvider={builds:m.builds,index:m.pillGroups.libraryTabs.index}
m.libraryCursor="rated-page-2"
LibraryQuery(false)
continuation=m.requests.Peek():count=m.requests.Count()
LibraryKey("right")
bounded=m.requests.Count()=count
m.libraryPerson="actor-1"
LibraryQuery(true)
person=m.requests.Peek()
m.provider="plex"
LibraryQuery(true)
print FormatJson({sameProvider:sameProvider,person:person,labels:labels,selected:selected,continuation:continuation,bounded:bounded,plexLabels:m.labels,plex:m.requests.Peek()})
''', root=Path(directory))
        actual = json.loads(out.splitlines()[-1])
        self.assertEqual(actual["labels"], ["Recently added", "A–Z", "Newest", "Top rated"])
        expected = {"type": "movie", "sort": "rating_imdb", "order": "desc", "limit": 60,
                    "libraryId": "lib-1", "source": "collection", "collectionId": "collection-1",
                    "genre": "Drama", "watched": "unwatched", "namePrefix": "A", "formatFilter": "hdr"}
        self.assertEqual(actual["selected"], {"action": "catalog_query", "params": expected, "token": 8})
        self.assertEqual(actual["continuation"], {"action": "catalog_query", "params": dict(expected, cursor="rated-page-2"), "token": 9})
        self.assertEqual(actual["sameProvider"], {"builds": 1, "index": 3})
        self.assertEqual(actual["person"], {"action": "person_items", "params": dict(expected, personid="actor-1"), "token": 10})
        self.assertTrue(actual["bounded"])
        self.assertEqual(actual["plexLabels"], ["Recently added", "A–Z", "Newest"])
        self.assertEqual(actual["plex"]["action"], "sections")

    def test_decade_and_rating_selection_keep_scope_through_paging_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "filters.brs"
            helper.write_text("""
sub BrowsePagedChoices(title as String, choices as Object, handler as String)
 m.choices=choices
end sub
function BrowseChoiceIndex(event as Object) as Integer
 return m.index
end function
function BrowseCaptureContext() as Object
 return {}
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.requests.Push(params)
end sub
function TextOr(value as Dynamic) as String
 if type(value)="String" then return value
 return ""
end function
""")
            scene = Path(directory) / "library.brs"
            source = LIBRARY.read_text()
            for name in ("BrowsePagedChoices", "BrowseChoiceIndex", "BrowseCaptureContext"):
                source = re.sub(r"(?:sub|function) " + name + r"\(.*?\nend (?:sub|function)", "", source, flags=re.S)
            scene.write_text(source)
            out = run_brightscript([scene, helper], """
m.provider="silo":m.librarySortProvider="silo":m.requests=[]
m.libraryTitle={}:m.libraryRetryButtons=invalid:m.libraryToken=4:m.grid={}:m.libraryEmpty={}
m.libraryType="movie":m.libraryPerson="":m.libraryId="lib-1":m.librarySource="query"
m.libraryCollection="":m.libraryGenre="Drama":m.libraryWatched="unwatched":m.libraryPrefix="":m.libraryFormatFilter="hdr"
m.librarySorts=[{sort:"title",order:"asc"}]:m.pillGroups={libraryTabs:{index:0}}
m.index=13:onLibraryOption(invalid)
decades=m.choices
m.index=4:onLibraryChoice(invalid)
m.index=14:onLibraryOption(invalid)
ratings=m.choices
m.index=2:onLibraryChoice(invalid)
selected=m.requests.Peek():title=m.libraryTitle.text
m.index=0:onLibraryChoice(invalid)
ratingCleared=m.requests.Peek()
m.index=2:onLibraryChoice(invalid)
m.libraryCursor="page-2":LibraryQuery(false)
continuation=m.requests.Peek()
m.browseChoiceKind="library":m.browseChoiceEntries=[{libraryId:"lib-2"}]
m.index=1:onLibraryChoice(invalid)
libraryChanged=m.requests.Peek()
m.index=9:onLibraryOption(invalid)
print FormatJson({decades:decades,ratings:ratings,selected:selected,title:title,ratingCleared:ratingCleared,continuation:continuation,libraryChanged:libraryChanged,cleared:m.requests.Peek()})
""", root=Path(directory))
        actual = json.loads(out.splitlines()[-1])
        self.assertEqual(actual["decades"][4], "1990s")
        self.assertEqual(actual["ratings"], ["Any rating", "IMDb 6+", "IMDb 7+", "IMDb 8+", "IMDb 9+"])
        for request in [actual["selected"], actual["continuation"]]:
            self.assertEqual(request["decade"], 1990)
            self.assertEqual(request["minimumrating"], 7)
            self.assertEqual(request["genre"], "Drama")
            self.assertEqual(request["libraryId"], "lib-1")
            self.assertEqual(request["formatFilter"], "hdr")
        self.assertEqual(actual["continuation"]["cursor"], "page-2")
        self.assertEqual(actual["libraryChanged"]["libraryId"], "lib-2")
        self.assertEqual(actual["libraryChanged"]["decade"], 1990)
        self.assertEqual(actual["libraryChanged"]["minimumrating"], 7)
        self.assertNotIn("cursor", actual["libraryChanged"])
        self.assertEqual(actual["ratingCleared"]["decade"], 1990)
        self.assertNotIn("minimumrating", actual["ratingCleared"])
        self.assertEqual(actual["title"], "Movies • Drama • 1990s • IMDb 7+")
        self.assertIn("1990s", actual["title"])
        self.assertIn("IMDb 7+", actual["title"])
        self.assertNotIn("decade", actual["cleared"])
        self.assertNotIn("minimumrating", actual["cleared"])

    def test_library_heading_names_active_collection(self):
        self.assertEqual(run_function(LIBRARY, "LibraryTitleText", ["movie", "Award winners"]),
                         "Movies • Award winners")
        self.assertEqual(run_function(LIBRARY, "LibraryTitleText", ["series", ""]),
                         "Shows • Options: filters and lists")

    def test_person_filmography_heading_survives_query_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "api.brs"
            helper.write_text('''
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.called=action
end sub
function TextOr(value as Dynamic) as String
 if type(value)="String" then return value
 return ""
end function
''')
            out = run_brightscript([LIBRARY, helper], '''
m.libraryTitle={text:"A. Performer"}:m.libraryPerson="actor-1":m.libraryType="video"
m.libraryRetryButtons=invalid:m.libraryToken=0:m.grid={content:invalid}:m.libraryEmpty={}
m.provider="silo":m.librarySortProvider="silo":m.librarySorts=[{sort:"title",order:"asc"}]:m.pillGroups={libraryTabs:{index:0}}
m.libraryId="":m.librarySource="person":m.libraryCollection="":m.libraryGenre="":m.libraryWatched="":m.libraryPrefix="":m.libraryCursor=""
LibraryQuery(true)
print FormatJson({title:m.libraryTitle.text,action:m.called})
''', root=Path(directory))
        self.assertEqual(json.loads(out.splitlines()[-1]), {"title": "A. Performer", "action": "person_items"})

    def test_format_shortcut_queries_full_video_library_and_restores_home_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "scene.brs"
            helper.write_text('''
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.called={action:action,params:params,purpose:purpose}
end sub
sub ShowView(view as String)
 m.view=view
end sub
sub SetZone(zone as String)
 m.zone=zone
end sub
function TextOr(value as Dynamic) as String
 if type(value)="String" then return value
 return ""
end function
''')
            out = run_brightscript([LIBRARY, helper], '''
m.provider="silo":m.librarySortProvider="silo":m.view="home":m.zone="rows":m.history=[]:m.rows={rowItemFocused:[3,2]}
m.libraryTitle={}:m.libraryRetryButtons=invalid:m.libraryToken=0:m.libraryType=""
m.grid={content:invalid}:m.libraryEmpty={}
m.librarySorts=[{sort:"added_at",order:"desc"}]:m.pillGroups={libraryTabs:{index:0}}
LibraryOpenFormat("4k_hdr")
print FormatJson({view:m.view,zone:m.zone,history:m.history,focus:m.streamingHomeFocus,title:m.libraryTitle.text,request:m.called})
''', root=Path(directory))
        actual = json.loads(out.splitlines()[-1])
        self.assertEqual(actual["history"], [{"view": "home", "zone": "rows"}])
        self.assertEqual(actual["focus"], [3, 2])
        self.assertEqual(actual["title"], "Videos • 4K HDR files")
        self.assertEqual(actual["request"]["action"], "catalog_query")
        self.assertEqual(actual["request"]["params"]["type"], "video")
        self.assertEqual(actual["request"]["params"]["formatFilter"], "4k_hdr")
