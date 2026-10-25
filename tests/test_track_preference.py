"""Compact scoped preferences resolved against actual native Roku inventories."""

from pathlib import Path
import re
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/TrackPreference.brs"
SCOPE = {"sourceId": "plex:fixture-server", "profileId": "fixture-owner"}


class TrackPreferenceTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "Native track preference policy is missing")
        self.assertRegex(POLICY.read_text(), r"(?i)function\s+" + re.escape(name) + r"\(")
        return run_function(POLICY, name, list(args))

    def preference(self, **changes):
        return {"schemaVersion": 1, **SCOPE, "subtitleMode": "auto", "subtitleLanguage": "eng",
                "subtitleName": "", "audioLanguage": "", "audioName": "", **changes}

    def subtitle(self, track_id="sub-en", language="eng", name="English", **changes):
        return {"TrackName": track_id, "Language": language, "Description": name, **changes}

    def audio(self, track_id="audio-en", language="eng", name="English", **changes):
        return {"Track": track_id, "Language": language, "Name": name, **changes}

    def test_default_record_is_compact_and_explicitly_auto_english(self):
        self.assertEqual(self.preference(), self.call("TrackPreferenceNormalize", None, SCOPE))
        raw = self.preference(token="synthetic-secret", subtitleTrack="https://synthetic.test/private",
                              headers={"Authorization": "synthetic-secret"})
        result = self.call("TrackPreferenceNormalize", raw, SCOPE)
        self.assertEqual(self.preference(), result)
        self.assertNotIn("synthetic-secret", str(result))
        self.assertNotIn("https://", str(result))

    def test_explicit_off_and_on_remain_distinct_from_auto(self):
        preference = self.call("TrackPreferenceSetMode", None, SCOPE, "off")
        self.assertEqual("off", preference["subtitleMode"])
        result = self.call("TrackPreferenceResolve", preference, SCOPE, "subtitle", [self.subtitle()])
        self.assertEqual({"kind": "subtitle", "trackId": "", "captionMode": "Off", "reason": "explicit_off"}, result)
        preference = self.call("TrackPreferenceSetMode", preference, SCOPE, "on")
        self.assertEqual("on", preference["subtitleMode"])
        self.assertEqual("On", self.call("TrackPreferenceResolve", preference, SCOPE, "subtitle", [self.subtitle()])["captionMode"])
        preference = self.call("TrackPreferenceSetMode", preference, SCOPE, "auto")
        self.assertEqual(self.preference(), preference)
        self.assertIsNone(self.call("TrackPreferenceSetMode", preference, SCOPE, "sometimes"))

    def test_remembered_native_choice_stores_language_and_name_without_runtime_id(self):
        track = self.subtitle("https://synthetic.test/sub.vtt?sig=fixture", "spa", "Spanish Full",
                              url="https://synthetic.test/private", token="synthetic-secret")
        record = self.call("TrackPreferenceRemember", None, SCOPE, "subtitle", track["TrackName"], [track])
        self.assertEqual(self.preference(subtitleMode="on", subtitleLanguage="spa", subtitleName="Spanish Full"), record)
        self.assertNotIn("https://", str(record))
        self.assertNotIn("synthetic-secret", str(record))
        off = self.call("TrackPreferenceSetMode", record, SCOPE, "off")
        on = self.call("TrackPreferenceSetMode", off, SCOPE, "on")
        result = self.call("TrackPreferenceResolve", on, SCOPE, "subtitle", [self.subtitle("fresh-id", "spa", "Spanish Full")])
        self.assertEqual("fresh-id", result["trackId"])
        self.assertEqual("explicit_name", result["reason"])

    def test_exact_name_language_then_english_fallback_uses_current_inventory(self):
        record = self.preference(subtitleMode="on", subtitleLanguage="spa", subtitleName="Spanish Main")
        tracks = [self.subtitle("wrong-language", "eng", "Spanish Main"),
                  self.subtitle("spanish-other", "spa", "Spanish Other"),
                  self.subtitle("spanish-main", "spa", " SPANISH MAIN ")]
        self.assertEqual("spanish-main", self.call("TrackPreferenceResolve", record, SCOPE, "subtitle", tracks)["trackId"])
        result = self.call("TrackPreferenceResolve", record, SCOPE, "subtitle", tracks[:2])
        self.assertEqual("spanish-other", result["trackId"])
        self.assertEqual("explicit_language", result["reason"])
        result = self.call("TrackPreferenceResolve", record, SCOPE, "subtitle", tracks[:1])
        self.assertEqual("wrong-language", result["trackId"])
        self.assertEqual("auto_english", result["reason"])

    def test_default_english_prefers_full_lane_over_sdh_forced_and_commentary(self):
        tracks = [self.subtitle("commentary", "eng", "English commentary"),
                  self.subtitle("sdh", "eng", "English SDH"),
                  self.subtitle("forced", "eng", "English Forced"),
                  self.subtitle("full", "eng", "English Full"),
                  self.subtitle("full-second", "eng", "English Full")]
        result = self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", tracks)
        self.assertEqual({"kind": "subtitle", "trackId": "full", "captionMode": "On", "reason": "auto_english"}, result)
        tracks = [self.subtitle("caption", "eng", "English", HasAccessibilityCaption=True), self.subtitle("full", "eng", "English")]
        self.assertEqual("full", self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", tracks)["trackId"])

    def test_remembered_subtitle_type_survives_changed_native_labels(self):
        cases = [("English SDH", "English CC", {}),
                 ("English CC", "English Captions", {"HasAccessibilityCaption": True}),
                 ("English Forced", "English Forced Signs", {})]
        for remembered_name, fresh_name, flags in cases:
            with self.subTest(remembered_name=remembered_name):
                old_track = self.subtitle("previous-title-id", "eng", remembered_name)
                record = self.call("TrackPreferenceRemember", None, SCOPE, "subtitle",
                                   old_track["TrackName"], [old_track])
                reloaded = self.call("TrackPreferenceNormalize", record, SCOPE)
                tracks = [self.subtitle("full", "eng", "English Full"),
                          self.subtitle("preferred-type", "eng", fresh_name, **flags)]
                result = self.call("TrackPreferenceResolve", reloaded, SCOPE, "subtitle", tracks)
                self.assertEqual("preferred-type", result["trackId"])
                self.assertEqual("explicit_language", result["reason"])

    def test_english_fallback_retains_remembered_subtitle_type(self):
        record = self.preference(subtitleMode="on", subtitleLanguage="spa", subtitleName="Spanish SDH")
        tracks = [self.subtitle("full", "eng", "English Full"),
                  self.subtitle("sdh", "eng", "English CC")]
        result = self.call("TrackPreferenceResolve", record, SCOPE, "subtitle", tracks)
        self.assertEqual("sdh", result["trackId"])
        self.assertEqual("auto_english", result["reason"])

    def test_english_aliases_match_whole_language_values_and_whole_label_tokens(self):
        for language in ("en", "eng", "English", " ENG "):
            with self.subTest(language=language):
                result = self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", [self.subtitle(language=language)])
                self.assertEqual("sub-en", result["trackId"])
        rejected = [self.subtitle("name-prefix", "und", "Englishman"), self.subtitle("language-prefix", "engineering", "Track"),
                    self.subtitle("conflicting-language", "fra", "English")]
        self.assertIsNone(self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", rejected))
        result = self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", [self.subtitle("label-only", "und", "English (SDH)")])
        self.assertEqual("label-only", result["trackId"])

    def test_default_audio_leaves_roku_automatic_selection_untouched(self):
        self.assertIsNone(self.call("TrackPreferenceResolve", None, SCOPE, "audio", [self.audio()]))
        record = self.preference(audioLanguage="jpn")
        self.assertIsNone(self.call("TrackPreferenceResolve", record, SCOPE, "audio", [self.audio()]))

    def test_valid_english_region_tags_are_english_but_explicit_language_stays_exact(self):
        for language in ("en-US", "eng-US", "en-GB"):
            with self.subTest(language=language):
                result = self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", [self.subtitle(language=language, name="Regional lane")])
                self.assertIsNotNone(result, "Regional English track was not selected")
                self.assertEqual("sub-en", result["trackId"])
        record = self.preference(audioLanguage="en-US")
        result = self.call("TrackPreferenceResolve", record, SCOPE, "audio", [self.audio("us", "eng-US", "Regional lane")])
        self.assertIsNotNone(result, "Two-letter and three-letter locale aliases should agree")
        self.assertEqual("us", result["trackId"])
        self.assertIsNone(self.call("TrackPreferenceResolve", record, SCOPE, "audio", [self.audio("gb", "en-GB", "Regional lane")]))

    def test_explicit_audio_uses_exact_name_then_language_without_prefix_matches(self):
        record = self.preference(audioLanguage="English", audioName="Main Stereo")
        tracks = [self.audio("commentary", "eng", "English Commentary"),
                  self.audio("main-surround", "eng", "Main Surround"),
                  self.audio("main-stereo", "en", " MAIN STEREO ")]
        self.assertEqual("main-stereo", self.call("TrackPreferenceResolve", record, SCOPE, "audio", tracks)["trackId"])
        self.assertEqual("main-surround", self.call("TrackPreferenceResolve", record, SCOPE, "audio", tracks[:2])["trackId"])
        record = self.preference(audioName="Main")
        self.assertIsNone(self.call("TrackPreferenceResolve", record, SCOPE, "audio", tracks))
        record = self.call("TrackPreferenceRemember", None, SCOPE, "audio", "main-stereo", tracks)
        self.assertEqual(self.preference(audioLanguage="eng", audioName="MAIN STEREO"), record)
        self.assertNotIn("main-stereo", str(record))
        record = self.call("TrackPreferenceRemember", record, SCOPE, "audio", "", tracks)
        self.assertEqual("", record["audioLanguage"])
        self.assertEqual("", record["audioName"])

    def test_missing_empty_or_malformed_inventory_defers_all_selection(self):
        inventories = [None, {}, "[]", [], [None], [{"TrackName": 7, "Language": "eng"}], [{"Description": "English"}]]
        for inventory in inventories:
            with self.subTest(inventory=inventory):
                self.assertIsNone(self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", inventory))
                self.assertIsNone(self.call("TrackPreferenceResolve", self.preference(subtitleMode="off"), SCOPE, "subtitle", inventory))
        self.assertIsNone(self.call("TrackPreferenceResolve", None, SCOPE, "video", [self.subtitle()]))

    def test_missing_subtitle_language_never_selects_an_arbitrary_foreign_lane(self):
        tracks = [self.subtitle("fr", "fra", "French")]
        self.assertIsNone(self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", tracks))
        self.assertIsNone(self.call("TrackPreferenceResolve", self.preference(subtitleMode="on"), SCOPE, "subtitle", tracks))

    def test_source_and_profile_switches_drop_other_scope_choices(self):
        record = self.preference(subtitleMode="off", audioLanguage="jpn")
        for changed in ({"sourceId": "plex:other", "profileId": SCOPE["profileId"]},
                        {"sourceId": SCOPE["sourceId"], "profileId": "other"}):
            with self.subTest(scope=changed):
                self.assertEqual(self.preference(**changed), self.call("TrackPreferenceNormalize", record, changed))
                result = self.call("TrackPreferenceResolve", record, changed, "subtitle", [self.subtitle()])
                self.assertEqual("On", result["captionMode"])
        owner_scope = {"sourceId": SCOPE["sourceId"], "profileId": ""}
        self.assertEqual(self.preference(**owner_scope), self.call("TrackPreferenceNormalize", None, owner_scope))
        silo = {"sourceId": "silo:https://synthetic.test", "profileId": "profile-1"}
        self.assertEqual(self.preference(**silo), self.call("TrackPreferenceNormalize", None, silo))

    def test_invalid_or_credential_bearing_scope_is_rejected(self):
        scopes = [None, {}, {"sourceId": "plex:fixture"}, {"sourceId": "plex:fixture", "profileId": None},
                  {"sourceId": "plex", "profileId": "owner"}, {"sourceId": "plex:fixture", "profileId": 2},
                  {"sourceId": "silo:https://user:password@synthetic.test", "profileId": "profile-1"},
                  {"sourceId": "silo:https://synthetic.test?token=fixture", "profileId": "profile-1"},
                  {"sourceId": "plex:" + "x" * 300, "profileId": "owner"}]
        for scope in scopes:
            with self.subTest(scope=scope):
                self.assertIsNone(self.call("TrackPreferenceNormalize", None, scope))

    def test_inventory_scans_only_first_sixty_four_entries(self):
        initial = [self.subtitle(str(i), "fra", "French") for i in range(63)]
        result = self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", initial + [self.subtitle("64")])
        self.assertEqual("64", result["trackId"])
        tracks = initial + [self.subtitle("64", "fra", "French"), self.subtitle("65")]
        self.assertIsNone(self.call("TrackPreferenceResolve", None, SCOPE, "subtitle", tracks))
        self.assertIsNone(self.call("TrackPreferenceRemember", None, SCOPE, "subtitle", "65", tracks))

    def test_unsafe_preference_names_and_unavailable_ids_never_enter_storage(self):
        raw = self.preference(subtitleMode="on", subtitleLanguage="https://synthetic.test?token=fixture",
                              subtitleName="https://synthetic.test/sub.vtt?token=fixture", audioName="Authorization: Bearer fixture")
        record = self.call("TrackPreferenceNormalize", raw, SCOPE)
        self.assertEqual("", record["subtitleLanguage"])
        self.assertEqual("", record["subtitleName"])
        self.assertEqual("", record["audioName"])
        self.assertIsNone(self.call("TrackPreferenceRemember", None, SCOPE, "subtitle", "not-available", [self.subtitle()]))
        record = self.call("TrackPreferenceRemember", None, SCOPE, "subtitle", "", [])
        self.assertEqual("off", record["subtitleMode"])
        self.assertEqual("", self.call("TrackPreferenceNormalize", self.preference(subtitleName="x" * 97), SCOPE)["subtitleName"])

    def test_off_preference_survives_actual_registry_json_round_trip(self):
        self.assertTrue(POLICY.is_file(), "Native track preference policy is missing")
        output = run_brightscript(POLICY, '''
scope = {sourceId:"plex:fixture-server",profileId:"fixture-owner"}
record = TrackPreferenceSetMode(invalid,scope,"off")
stored = FormatJson(record)
reloaded = TrackPreferenceNormalize(ParseJson(stored,"i"),scope)
selection = TrackPreferenceResolve(reloaded,scope,"subtitle",[{TrackName:"sub-en",Language:"eng",Description:"English"}])
print reloaded.subtitleMode
print selection.captionMode
print Len(stored) < 1024''')
        self.assertEqual("off\nOff\ntrue", output.strip())


if __name__ == "__main__":
    unittest.main()
