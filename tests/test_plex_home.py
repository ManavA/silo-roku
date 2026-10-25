"""Bounded provider Home behavior; rendering and focus still need a Roku."""

import json
from pathlib import Path
import re
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "source/adapters/PlexAdapter.brs"
FIXTURES = ROOT / "tests/fixtures/plex"
SCOPE = {"provider": "plex", "sourceId": "plex:server-a", "profileId": "owner", "generation": 4}


class PlexHomeTests(unittest.TestCase):

    def decode(self, action, payload, **params):
        return run_function(ADAPTER, "DecodePlexResponse", [action, json.dumps(payload),
                            {"sourceId": SCOPE["sourceId"], **params}])

    def result(self, action, data=None, ok=True, **scope):
        return {**SCOPE, **scope, "action": action, "ok": ok, "data": data or {}}


    def item(self, item_id, **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": str(item_id),
                "type": "movie", "title": "Fixture film", **changes}

    def row(self, row_id, item_id, **changes):
        return {"id": row_id, "sourceId": SCOPE["sourceId"], "title": "Fixture shelf",
                "items": [self.item(item_id)], **changes}

    def test_fast_lanes_have_fixed_row_identity_and_titles(self):
        payload = json.loads((FIXTURES / "continue.json").read_text())
        for action, row_id, title in (("home_continue", "home.continue", "Continue watching"),
                                      ("home_on_deck", "home.ondeck", "On deck")):
            with self.subTest(action=action):
                data = self.decode(action, payload)["data"]
                self.assertIn("rows", data, "Home history loses its row identity")
                self.assertEqual(row_id, data["rows"][0]["id"])
                self.assertEqual(title, data["rows"][0]["title"])
                self.assertEqual(data["items"], data["rows"][0]["items"])

    def test_section_hubs_keep_native_shelves_and_omit_duplicate_history(self):
        payload = json.loads((FIXTURES / "section_hubs.json").read_text())
        data = self.decode("section_hubs", payload, sectionId="1")["data"]
        self.assertIn("rows", data, "Section hubs are flattened before reaching Home")
        self.assertEqual(["plex.1.movie.recentlyadded", "plex.1.movie.toprated"],
                         [row["id"] for row in data["rows"]])
        self.assertEqual(["Recently added", "Top rated"], [row["title"] for row in data["rows"]])
        self.assertEqual(["301", "401"], [row["items"][0]["itemId"] for row in data["rows"]])
        self.assertTrue(all(item["sourceId"] == SCOPE["sourceId"]
                            for row in data["rows"] for item in row["items"]))

    def test_section_decoder_bounds_shelves_cards_and_drops_unsafe_row_ids(self):
        hubs = [{"hubIdentifier": "https://private.test/?token=secret", "title": "Shelf",
                 "type": "movie", "Metadata": [{"ratingKey": str(100 + i), "type": "movie", "title": "Film"}
                                                 for i in range(30)]}]
        hubs += [{"hubIdentifier": "native." + str(i), "title": "Shelf", "type": "movie",
                  "Metadata": [{"ratingKey": str(500 + i), "type": "movie", "title": "Film"}]}
                 for i in range(20)]
        data = self.decode("section_hubs", {"MediaContainer": {"Hub": hubs}}, sectionId="1")["data"]
        self.assertIn("rows", data, "Bounded section shelves are missing")
        self.assertEqual(2, len(data["rows"]))
        self.assertEqual(6, len(data["rows"][0]["items"]))
        self.assertLessEqual(len(data["items"]), 12)
        self.assertNotIn("secret", str(data))

    def test_history_exclusion_uses_provider_identity_instead_of_shelf_title(self):
        payload = {"MediaContainer": {"Hub": [{"hubIdentifier": "movie.recentlyadded",
                   "title": "Continue the adventure", "type": "movie",
                   "Metadata": [{"ratingKey": "301", "type": "movie", "title": "Fixture film"}]}]}}
        data = self.decode("section_hubs", payload, sectionId="1")["data"]
        self.assertEqual(["plex.1.movie.recentlyadded"], [row["id"] for row in data["rows"]])


if __name__ == "__main__":
    unittest.main()
