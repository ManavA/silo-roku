"""Exercise real core policy flows with Roku's native boxed numeric Type names."""

from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICIES = [ROOT / "source/core" / name for name in (
    "HomeRowsPolicy.brs", "BrowseUpdatePolicy.brs", "BrowseScreenPolicy.brs",
    "SearchPolicy.brs", "EpisodeNeighbors.brs", "ExtrasPolicy.brs")]

FACADE = '''
' Only Type() names change; policy values, arithmetic and state are unchanged.
function CoreFixtureType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.numericAlias
    if kind = "LongInteger" or kind = "roLongInteger" then return "roLongInteger"
    if kind = "Double" or kind = "roDouble" then return "roDouble"
    return kind
end function
function CoreFixtureCall(alias as String, name as String, args as Object) as Dynamic
    m.numericAlias = alias
    if name = "rows" then return CoreFixtureRows()
    if name = "update" then return CoreFixtureUpdate(false)
    if name = "update_restore" then return CoreFixtureUpdate(true)
    if name = "screen" then return CoreFixtureScreen(false)
    if name = "screen_restore" then return CoreFixtureScreen(true)
    if name = "index_types" then return CoreFixtureIndexTypes()
    if name = "search" then return CoreFixtureSearch()
    if name = "episode" then return CoreFixtureEpisode()
    if name = "extras" then return CoreFixtureExtras()
    if name = "EnScope" then return EnScope(args[0])
    if name = "ExScopeMatches" then return ExScopeMatches(args[0],args[1])
    if name = "SearchIndexCard" then return SearchIndexCard(args[0],"plex:fixture")
    if name = "EnCard" then return EnCard(args[0],args[1],"episode")
    if name = "ExNativeItem" then return ExNativeItem(args[0],"plex:fixture")
    return invalid
end function
function CoreFixtureRows() as Object
    plan = HomeRowsPlan([{rowId:"a",rowTitle:"Continue"},{rowId:"a",rowTitle:"Continue"},
        {rowId:"b",rowTitle:"Recent"},{rowId:"b",rowTitle:"Recent"}])
    return {flat:HomeRowsIndexAt(plan,[1,1]),position:HomeRowsPositionFor(plan,2),
        fractional:HomeRowsIndexAt(plan,[0,0.5]),string:HomeRowsIndexAt(plan,[0,"1"]),
        negative:HomeRowsPositionFor(plan,-1),overflow:HomeRowsIndexAt(plan,[1,2])}
end function
function CoreFixtureItems() as Object
    return [{itemId:"101",title:"First"},{itemId:"102",title:"Second"},{itemId:"103",title:"Third"}]
end function
function CoreFixtureUpdate(restore as Boolean) as Object
    scope = {provider:"plex",sourceId:"plex:fixture",profileId:"owner",generation:7,route:"home",listKind:"home"}
    items = CoreFixtureItems()
    first = BrowseUpdatePlan(invalid,items,scope,1,"catalog","enter")
    if restore then return BrowseUpdatePlan(first.state,items,scope,2,"catalog","restore")
    return BrowseUpdatePlan(first.state,[items[2],items[0],items[1]],scope,1,"catalog","refresh")
end function
function CoreFixtureScreen(restore as Boolean) as Object
    items = CoreFixtureItems()
    model = {scopeKey:"route-7",presentation:"grid",items:items,selectedIndex:1}
    first = BrowseScreenPlan(invalid,model,1,"content",false)
    if restore
        model.selectedIndex = 2
        return BrowseScreenPlan(first.state,model,0,"content",true)
    end if
    model.items = [items[2],items[0],items[1]]
    return BrowseScreenPlan(first.state,model,1,"content",false)
end function
function CoreFixtureIndexTypes() as Object
    plan = HomeRowsPlan([{rowId:"a"},{rowId:"a"}])
    return {flat:HomeRowsIndexAt(plan,[0,1]),position:HomeRowsPositionFor(plan,1),
        update:BrowseUpdateIndex(1),screen:BrowseScreenIndex(1),
        fractionalUpdate:BrowseUpdateIndex(1.5),fractionalScreen:BrowseScreenIndex(1.5)}
end function
function CoreFixtureSearch() as Object
    source = "plex:fixture"
    first = {provider:"plex",sourceId:source,itemId:"101",title:"Moon",type:"movie",year:2005,resumeMs:4000}
    second = {provider:"plex",sourceId:source,itemId:"102",title:"Moon",type:"movie",year:2026,resumeMs:60000}
    index = SearchIndexAdd(invalid,[first,second],source)
    return {index:index,ranked:SearchLocalMatches(index,"moon",source)}
end function
function CoreFixtureEpisodeItem(id as String, number as Integer) as Object
    return {provider:"plex",sourceId:"plex:fixture",itemId:id,type:"episode",seriesItemId:"100",
        parentItemId:"110",seasonItemId:"110",seasonNumber:1,episodeNumber:number,durationMs:120000,resumeMs:4000}
end function
function CoreFixtureEpisode() as Object
    scope = {provider:"plex",sourceId:"plex:fixture",profileId:"owner",generation:7,lookupId:"lookup-1",anchorItemId:"101"}
    anchor = CoreFixtureEpisodeItem("101",1)
    following = CoreFixtureEpisodeItem("102",2)
    state = EpisodeNeighborsStart(anchor,scope)
    request = EpisodeNeighborsRequest(state)
    if request = invalid then return EpisodeNeighborsOutcome(state)
    response = {ok:true,data:{items:[anchor,following],offset:0,pageSize:48,rawCount:2,hasMore:false,nextOffset:-1}}
    state = EpisodeNeighborsResult(state,request,response)
    request = EpisodeNeighborsRequest(state)
    if request = invalid then return EpisodeNeighborsOutcome(state)
    version = {sourceId:scope.sourceId,itemId:"102",mediaId:"901",partId:"902",versionId:"plex:fixture:102:901:902"}
    state = EpisodeNeighborsResult(state,request,{ok:true,data:{item:following,versions:[version]}})
    outcome = EpisodeNeighborsOutcome(state)
    outcome["matches"] = EpisodeNeighborsProofMatches(outcome.proof,anchor,following,scope)
    return outcome
end function
function CoreFixtureExtras() as Object
    scope = {sourceId:"plex:fixture",profileId:"owner",generation:7}
    extra = {provider:"plex",sourceId:scope.sourceId,itemId:"501",type:"movie",extraType:"trailer",
        title:"Trailer",durationMs:90000,resumeMs:4000}
    playlist = BuildExtrasPlaylist({item:{sourceId:scope.sourceId,itemId:"101"},extras:[extra]},scope,scope)
    if not playlist.ok then return {playlist:playlist,selected:invalid,resolved:invalid}
    selected = ExtrasPlaylistItem(playlist,0,scope)
    version = {sourceId:scope.sourceId,itemId:"501",versionId:"video-version",videoCodec:"h264",
        mediaIndex:2,partIndex:1,partKey:"/library/parts/3501/file.mp4"}
    resolved = ResolveExtraPlayback(playlist,0,{item:extra,versions:[version]},scope)
    return {playlist:playlist,selected:selected,resolved:resolved}
end function
'''


class CoreNativeAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="silo-core-native-type-")
        cls.script = Path(cls.directory.name) / "policy.brs"
        # The facade replaces only the type accessor in temporary policy copies.
        source = "\n".join(re.sub(r"\btype\(", "CoreFixtureType(", path.read_text(), flags=re.I)
                           for path in POLICIES)
        cls.script.write_text(source + FACADE)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def call(self, name, *args, alias="roInteger"):
        return run_function(self.script, "CoreFixtureCall", [alias, name, list(args)], root=Path(self.directory.name))

    def test_native_row_tuple_maps_to_flat_identity_and_restored_position(self):
        self.assertEqual({"flat": 3, "position": [1, 0], "fractional": -1, "string": -1,
                          "negative": [-1, -1], "overflow": -1}, self.call("rows"))

    def test_native_browse_update_follows_focused_identity_after_reorder(self):
        result = self.call("update")
        self.assertEqual(2, result["index"])
        self.assertTrue(result["matched"])
        self.assertEqual("102", result["items"][result["index"]]["itemId"])
        self.assertEqual("keep", result["focusTarget"])

    def test_native_browse_update_restore_keeps_saved_index_and_focus_owner(self):
        result = self.call("update_restore")
        self.assertEqual(2, result["index"])
        self.assertEqual("catalog", result["focusTarget"])

    def test_native_browse_screen_follows_focused_identity_after_reorder(self):
        result = self.call("screen")
        self.assertEqual(2, result["index"])
        self.assertEqual("102", result["items"][result["index"]]["key"])
        self.assertEqual("keep", result["focusTarget"])

    def test_native_browse_screen_restore_keeps_saved_index(self):
        self.assertEqual(2, self.call("screen_restore")["index"])

    def test_integer_only_row_and_browse_indices_retain_their_numeric_restriction(self):
        for alias in ("roLongInteger", "roDouble"):
            with self.subTest(alias=alias):
                self.assertEqual({"flat": -1, "position": [-1, -1], "update": 0, "screen": 0,
                                  "fractionalUpdate": 0, "fractionalScreen": 0}, self.call("index_types", alias=alias))

    def test_native_search_keeps_year_resume_and_year_ranking(self):
        result = self.call("search")
        self.assertEqual([2005, 2026], [card["year"] for card in result["index"]])
        self.assertEqual([4000, 60000], [card["resumeMs"] for card in result["index"]])
        self.assertEqual(["102", "101"], [card["itemId"] for card in result["ranked"]])

    def test_search_numeric_families_and_resume_bounds_are_preserved(self):
        raw = {"provider": "plex", "sourceId": "plex:fixture", "itemId": "101", "title": "Moon",
               "type": "movie", "year": 2026, "resumeMs": 60000}
        long_card = self.call("SearchIndexCard", raw, alias="roLongInteger")
        self.assertNotIn("year", long_card)
        self.assertNotIn("resumeMs", long_card)
        double_card = self.call("SearchIndexCard", raw, alias="roDouble")
        self.assertNotIn("year", double_card)
        self.assertEqual(60000, double_card["resumeMs"])
        for resume in (-1, 86400001, "60000"):
            self.assertNotIn("resumeMs", self.call("SearchIndexCard", dict(raw, resumeMs=resume)))

    def test_native_episode_normalization_inventory_and_proof_remain_usable(self):
        for alias in ("roInteger", "roLongInteger", "roDouble"):
            with self.subTest(alias=alias):
                result = self.call("episode", alias=alias)
                self.assertEqual("known", result["status"])
                self.assertEqual("102", result["candidate"]["itemId"])
                self.assertEqual((1, 2, 120000, 4000), tuple(result["candidate"][key]
                                 for key in ("seasonNumber", "episodeNumber", "durationMs", "resumeMs")))
                self.assertTrue(result["matches"])

    def test_native_extras_normalization_selection_and_playback_begin_on_own_timeline(self):
        for alias in ("roInteger", "roLongInteger", "roDouble"):
            with self.subTest(alias=alias):
                result = self.call("extras", alias=alias)
                self.assertTrue(result["playlist"]["ok"])
                self.assertEqual(90000, result["playlist"]["items"][0]["durationMs"])
                self.assertEqual(0, result["playlist"]["items"][0]["resumeMs"])
                self.assertTrue(result["selected"]["ok"])
                self.assertTrue(result["resolved"]["ok"])
                self.assertEqual((0, 0, 1), tuple(result["resolved"]["params"][key]
                                 for key in ("startPositionMs", "versionIndex", "partIndex")))

    def test_native_aliases_preserve_episode_and_extras_generation_guards(self):
        scope = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner", "generation": 7,
                 "lookupId": "lookup-1"}
        for generation in (-1, 7.5, "7", 2147483648):
            with self.subTest(generation=generation):
                malformed = dict(scope, generation=generation)
                self.assertIsNone(self.call("EnScope", malformed))
                self.assertFalse(self.call("ExScopeMatches", malformed, malformed))

    def test_native_normalization_keeps_invalid_media_positions_bounded(self):
        scope = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner"}
        episode = {"provider": "plex", "sourceId": "plex:fixture", "itemId": "101", "type": "episode",
                   "seasonNumber": 1, "episodeNumber": 2, "resumeMs": -1, "durationMs": 86400001}
        card = self.call("EnCard", episode, scope)
        self.assertEqual((0, 0), (card["resumeMs"], card["durationMs"]))
        extra = {"provider": "plex", "sourceId": "plex:fixture", "itemId": "501", "type": "movie",
                 "extraType": "trailer", "durationMs": -1}
        self.assertEqual(0, self.call("ExNativeItem", extra)["durationMs"])


if __name__ == "__main__":
    unittest.main()
