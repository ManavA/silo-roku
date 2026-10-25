"""Execute the bounded playback-to-Home overlay without Roku or provider IO."""

from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/ContinueOverlay.brs"
SCOPE = {"sourceId": "plex:server-a", "profileId": "owner", "generation": 10}


class ContinueOverlayTests(unittest.TestCase):
    def call(self, name, *arguments):
        self.assertTrue(POLICY.is_file(), "Continue Watching overlay is missing")
        self.assertTrue(re.search(r"(?i)function\s+" + re.escape(name) + r"\(", POLICY.read_text()),
                        "Continue Watching behavior is missing: " + name)
        return run_function(POLICY, name, list(arguments))

    def movie(self, item_id="101", **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": item_id,
                "title": "Fixture film", "type": "movie", "durationMs": 100000,
                "resumeMs": 10000, "watched": False, **changes}

    def episode(self, item_id="201", episode=1, **changes):
        return self.movie(item_id, type="episode", seriesItemId="200", parentItemId="210",
                          seasonNumber=1, episodeNumber=episode, **changes)

    def history(self, item):
        return {**item, "rowId": "home.continue", "rowTitle": "Continue watching"}

    def bind(self, state=None, **scope):
        return self.call("ContinueOverlayBind", state, {**SCOPE, **scope})

    def record(self, state=None, item=None, position=40000, duration=100000, started=True,
               finished=False, successor=None, **scope):
        if state is None:
            state = self.bind()
        return self.call("ContinueOverlayRecord", state, {**SCOPE, **scope}, item or self.movie(),
                         position, duration, started, finished, successor)

    def home(self, state, items, complete=False, **scope):
        return self.call("ContinueOverlayHome", state, {**SCOPE, **scope}, items, complete)

    def test_partial_play_promotes_the_owned_title_and_updates_cached_bookmark(self):
        state = self.record()
        items = [self.history(self.movie("102")), self.history(self.movie())]
        view = self.home(state, items)
        self.assertEqual(["101", "102"], [item["itemId"] for item in view["items"]])
        self.assertEqual(40000, view["items"][0]["resumeMs"])
        self.assertEqual("home.continue", view["items"][0]["rowId"])
        self.assertEqual("Continue watching", view["items"][0]["rowTitle"])
        cards = self.call("ContinueOverlayCards", state, SCOPE, [self.movie()])
        self.assertEqual(40000, cards[0]["resumeMs"])
        self.assertEqual(10000, items[1]["resumeMs"], "Applying an edit must not alter the provider snapshot")

    def test_completion_threshold_is_exactly_95_percent(self):
        history = [self.history(self.movie())]
        partial = self.home(self.record(position=94999), history)
        complete = self.home(self.record(position=95000), history)
        self.assertEqual(94999, partial["items"][0]["resumeMs"])
        self.assertEqual([], complete["items"])
        library = self.call("ContinueOverlayCards", complete["state"], SCOPE, [self.movie()])
        self.assertEqual(0, library[0]["resumeMs"])
        self.assertTrue(library[0]["watched"])

    def test_successful_natural_end_completes_even_without_a_duration(self):
        state = self.record(position=0, duration=0, finished=True)
        self.assertEqual([], self.home(state, [self.history(self.movie())])["items"])

    def test_failed_or_cancelled_start_never_replaces_a_previous_edit(self):
        state = self.record(position=50000)
        for finished in (False, True):
            self.assertEqual(state, self.record(state, position=0, started=False, finished=finished))

    def test_unknown_duration_keeps_a_successful_bookmark_without_claiming_completion(self):
        state = self.record(position=95000, duration=0)
        view = self.home(state, [self.history(self.movie())])
        self.assertEqual(95000, view["items"][0]["resumeMs"])
        self.assertFalse(view["items"][0]["watched"])

    def test_completed_episode_advances_only_to_a_verified_cached_successor(self):
        current = self.episode()
        successor = self.episode("202", 2, title="Next fixture")
        state = self.record(item=current, position=97000, successor=successor)
        view = self.home(state, [self.history(current), self.history(self.movie("102"))])
        self.assertEqual(["202", "102"], [item["itemId"] for item in view["items"]])
        self.assertEqual("Next fixture", view["items"][0]["title"])
        for changed in ({"sourceId": "plex:other"}, {"provider": "silo"}, {"episodeNumber": 4},
                        {"seriesItemId": "999"}, {"parentItemId": "999"}, {"seasonNumber": 2}):
            with self.subTest(changed=changed):
                rejected = self.record(item=current, position=97000, successor={**successor, **changed})
                self.assertEqual([], self.home(rejected, [self.history(current)])["items"])

    def test_playing_the_successor_does_not_duplicate_it_or_reinstate_the_predecessor(self):
        current, successor = self.episode(), self.episode("202", 2)
        advanced = self.record(item=current, position=97000, successor=successor)
        resumed = self.record(advanced, item=successor, position=40000)
        view = self.home(resumed, [self.history(current), self.history(successor)])
        self.assertEqual(["202"], [item["itemId"] for item in view["items"]])
        self.assertEqual(40000, view["items"][0]["resumeMs"])
        completed = self.record(advanced, item=successor, position=97000)
        self.assertEqual([], self.home(completed, [self.history(current), self.history(successor)])["items"])

    def test_scope_changes_clear_edits_and_stale_events_are_rejected(self):
        state = self.record()
        rebound = self.bind(state, generation=11)
        self.assertEqual(state["edits"], rebound["edits"])
        self.assertEqual(11, rebound["generation"])
        self.assertEqual([], self.bind(state, profileId="child")["edits"])
        self.assertEqual([], self.bind(state, sourceId="plex:other")["edits"])
        for changed in ({"generation": 9}, {"profileId": "child"}, {"sourceId": "plex:other"}):
            with self.subTest(changed=changed):
                self.assertEqual(state, self.record(state, position=70000, **changed))
                self.assertEqual([self.history(self.movie())], self.home(state, [self.history(self.movie())], **changed)["items"])
        self.assertEqual(rebound, self.record(rebound, position=80000), "An old generation cannot mutate a rebound overlay")

    def test_edits_contain_only_compact_owned_facts(self):
        unsafe = self.movie(url="https://private.example/stream", headers={"X-Plex-Token": "secret"},
                            thumbKey="https://private.example/art", summary="private", token="secret")
        state = self.record(item=unsafe)
        for value in ("secret", "private.example", "headers", "thumbKey", "summary"):
            self.assertNotIn(value, str(state))
        for invalid in (self.movie(sourceId="plex:other"), self.movie(itemId="../unsafe"),
                        self.movie(provider="silo"), self.movie(extraType="trailer"),
                        self.movie(type="show")):
            self.assertEqual([], self.record(item=invalid)["edits"])

    def test_recent_edits_replace_duplicates_and_keep_only_32(self):
        self.assertTrue(POLICY.is_file(), "Continue Watching overlay is missing")
        output = run_brightscript(POLICY, '''
scope = {sourceId:"plex:server-a",profileId:"owner",generation:10}
state = ContinueOverlayBind(invalid,scope)
for i = 1 to 36
    card = {provider:"plex",sourceId:"plex:server-a",itemId:i.ToStr(),title:"Fixture",type:"movie"}
    state = ContinueOverlayRecord(state,scope,card,40000,100000,true,false,invalid)
end for
card.itemId = "20"
state = ContinueOverlayRecord(state,scope,card,60000,100000,true,false,invalid)
print FormatJson([state.edits.Count(),state.edits[0].item.itemId,state.edits[0].item.resumeMs,state.edits[31].item.itemId])
''')
        self.assertEqual('[32,"20",60000,"5"]', output.strip())

    def test_partial_paints_and_back_do_not_age_an_edit(self):
        state = self.record(position=95000)
        for _ in range(5):
            view = self.home(state, [self.history(self.movie())])
            state = view["state"]
            self.assertEqual([], view["items"])
        self.assertEqual(0, state["edits"][0]["refreshes"])

    def test_three_complete_refreshes_expire_once_per_generation_after_paint(self):
        state = self.record(position=95000)
        for count, generation in enumerate((11, 12, 13), 1):
            state = self.bind(state, generation=generation)
            view = self.home(state, [self.history(self.movie())], complete=True, generation=generation)
            state = view["state"]
            self.assertEqual([], view["items"], "The third paint still receives the local edit, as in tvOS")
            self.assertEqual(0 if count == 3 else 1, len(state["edits"]))
            if count < 3:
                repeated = self.home(state, [self.history(self.movie())], complete=True, generation=generation)
                self.assertEqual(count, repeated["state"]["edits"][0]["refreshes"])
                state = repeated["state"]
        state = self.bind(state, generation=14)
        self.assertEqual(["101"], [item["itemId"] for item in self.home(state, [self.history(self.movie())], complete=True, generation=14)["items"]])

    def test_provider_agreement_retires_completion_and_verified_advance(self):
        complete = self.home(self.record(position=95000), [self.history(self.movie("102"))], complete=True)
        self.assertEqual([], complete["state"]["edits"])
        current, successor = self.episode(), self.episode("202", 2)
        state = self.record(item=current, position=97000, successor=successor)
        advanced = self.home(state, [self.history(successor)], complete=True)
        self.assertEqual([], advanced["state"]["edits"])

    def test_stale_bookmark_at_the_same_rank_does_not_retire_a_promotion(self):
        stale = self.home(self.record(), [self.history(self.movie())], complete=True)
        self.assertEqual(1, len(stale["state"]["edits"]))
        self.assertEqual(40000, stale["items"][0]["resumeMs"])
        state = self.bind(stale["state"], generation=11)
        agreed = self.home(state, [self.history(self.movie(resumeMs=40000))], complete=True, generation=11)
        self.assertEqual([], agreed["state"]["edits"])

    def test_history_removal_keeps_other_shelves_and_updates_their_watched_fields(self):
        history = self.history(self.movie())
        shelf = {**self.movie(), "rowId": "plex.1.recent", "rowTitle": "Recently added"}
        view = self.home(self.record(position=95000), [history, shelf])
        self.assertEqual(["plex.1.recent"], [item["rowId"] for item in view["items"]])
        self.assertTrue(view["items"][0]["watched"])
        self.assertEqual(0, view["items"][0]["resumeMs"])

    def test_silo_history_is_identified_by_section_type_and_keeps_row_identity(self):
        scope = {"sourceId": "silo:fixture-server", "profileId": "viewer", "generation": 2}
        item = self.movie(provider="silo", sourceId=scope["sourceId"], itemId="content-1")
        state = self.call("ContinueOverlayBind", None, scope)
        state = self.call("ContinueOverlayRecord", state, scope, item, 40000, 100000, True, False, None)
        source = {**item, "rowId": "sec1", "sectionType": "continue_watching", "rowTitle": "Localized history"}
        view = self.call("ContinueOverlayHome", state, scope, [source], False)
        self.assertEqual("sec1", view["items"][0]["rowId"])
        self.assertEqual("Localized history", view["items"][0]["rowTitle"])
        self.assertEqual(40000, view["items"][0]["resumeMs"])

    def test_foreign_cards_actions_and_global_discovery_are_never_modified(self):
        cards = [self.movie(sourceId="plex:other"), {"title": "Next page", "uiAction": "next_page"},
                 {"sourceId": "metadata", "itemId": "101", "type": "movie", "title": "Global"}]
        self.assertEqual(cards, self.call("ContinueOverlayCards", self.record(), SCOPE, cards))

    def test_acknowledged_unwatched_overrides_a_previous_completed_play(self):
        state = self.record(position=97000)
        reset = self.call("ContinueOverlayWatched", state, SCOPE, self.movie(resumeMs=0), False)
        card = self.call("ContinueOverlayCards", reset, SCOPE, [self.movie(watched=True)])[0]
        self.assertFalse(card["watched"])
        self.assertEqual(0, card["resumeMs"])
        view = self.home(reset, [self.history(self.movie(watched=True))])
        self.assertEqual(["101"], [item["itemId"] for item in view["items"]])
        self.assertFalse(view["items"][0]["watched"])
        self.assertEqual(state, self.call("ContinueOverlayWatched", state, {**SCOPE, "profileId": "child"}, self.movie(), False))

    def test_acknowledged_watched_completes_a_previously_partial_play(self):
        marked = self.call("ContinueOverlayWatched", self.record(), SCOPE, self.movie(), True)
        self.assertEqual([], self.home(marked, [self.history(self.movie())])["items"])

    def test_home_stays_bounded_when_32_promotions_join_a_full_catalog(self):
        self.assertTrue(POLICY.is_file(), "Continue Watching overlay is missing")
        output = run_brightscript(POLICY, '''
scope = {sourceId:"plex:server-a",profileId:"owner",generation:10}
state = ContinueOverlayBind(invalid,scope)
items = []
for i = 1 to 132
    card = {provider:"plex",sourceId:"plex:server-a",itemId:i.ToStr(),title:"Fixture",type:"movie",rowId:"plex.1.recent"}
    if i <= 32 then state = ContinueOverlayRecord(state,scope,card,40000,100000,true,false,invalid)
    if i > 32 then items.Push(card)
end for
view = ContinueOverlayHome(state,scope,items,false)
print FormatJson([view.items.Count(),view.items[0].itemId,view.items[31].itemId])
''')
        self.assertEqual('[100,"32","1"]', output.strip())


if __name__ == "__main__":
    unittest.main()
