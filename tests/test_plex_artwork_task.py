"""Fresh exact Plex identity owns optional public artwork; no provider IO escapes."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_function
from tests.test_silo_artwork_task import BOUNDARIES

ROOT = Path(__file__).resolve().parents[1]
SCOPE = {"provider": "plex", "sourceId": "plex:fixture-server", "profileId": "owner", "generation": 7, "requestId": "art-1"}
OWNER = {"scope": {key: SCOPE[key] for key in ("provider", "sourceId", "profileId", "generation")},
         "scopeKey": "route-7", "key": "501", "itemId": "501", "type": "movie", "tmdbId": "",
         "identityRequired": True, "nativeType": "movie", "artId": 1, "readyAtMs": 240}
PARAMS = {"type": "movie", "itemId": "501", "itemType": "movie"}
SESSION = {"sourceId": SCOPE["sourceId"], "profileId": "owner", "clientId": "synthetic-client",
           "baseUrl": "https://provider-private.example.test", "token": "synthetic-server-token",
           "accountToken": "synthetic-account-token", "accountId": "synthetic-account"}
MOVIE = {"ratingKey": "501", "type": "movie", "guid": "plex://movie/native-501",
         "Guid": [{"id": "tmdb://000141"}, {"id": "imdb://tt0133093"}]}
EPISODE = {"ratingKey": "501", "type": "episode", "grandparentRatingKey": "500",
           "guid": "tmdb://999", "Guid": [{"id": "tmdb://malformed-leaf-id"}]}
SHOW = {"ratingKey": "500", "type": "show", "guid": "plex://show/native-500", "Guid": [{"id": "tmdb://202"}]}
META = {"type": "movie", "tmdbId": "141", "posterPath": "/fixture.jpg", "backdropPath": "/fixture.png", "private": "synthetic"}


def wire(row):
    return json.dumps({"MediaContainer": {"size": 1, "Metadata": [row]}})


def case(*, episode=False, params=None, owner=None, scope=None, session=None, rows=None, responses=None, revision_at=0):
    selected_params = {**PARAMS, **({"type": "tv", "itemType": "episode"} if episode else {})}
    selected_owner = {**OWNER, **({"type": "tv", "nativeType": "episode"} if episode else {})}
    if params is not None:
        selected_params = params
    if owner is not None:
        selected_owner = owner
    if responses is None:
        selected_rows = rows if rows is not None else ([EPISODE, SHOW] if episode else [MOVIE])
        metadata = {**META, **({"type": "tv", "tmdbId": "202"} if episode else {})}
        responses = [{"body": wire(row), "elapsedMs": 500} for row in selected_rows]
        responses.append({"body": json.dumps(metadata), "elapsedMs": 500})
    return copy.deepcopy({"params": selected_params, "owner": selected_owner, "scope": SCOPE if scope is None else scope,
                          "session": SESSION if session is None else session, "responses": responses, "revisionAt": revision_at})


BATCH = '''
function RunPlexArtworkBatch(cases as Object) as Object
    output=[]
    for each entry in cases
        for each response in entry.responses
            if response.DoesExist("repeatBody")
                response["body"]=String(response.repeatBody,TaskValue(response,"repeatChar"," "))
            end if
        end for
        output.Push(RunPlexArtwork(entry.params,entry.owner,entry.scope,entry.session,entry.responses,entry.revisionAt))
    end for
    return output
end function
'''


class PlexArtworkTaskTests(unittest.TestCase):
    def run_cases(self, cases):
        with tempfile.TemporaryDirectory(prefix="plex-artwork-worker-") as directory:
            temporary = Path(directory)
            worker = temporary / "worker.brs"
            source = (ROOT / "components/ApiTask.brs").read_text()
            source = source.replace("function TaskDeviceSession(", "function UnusedDeviceSession(", 1)
            source = source.replace('CreateObject("roTimespan")', "ArtworkFixtureClock()")
            worker.write_text(source)
            http_source = (ROOT / "source/network/Http.brs").read_text()
            names = ("HttpErrorCode", "HttpErrorBodyLimit", "HttpErrorBodyWithinLimit", "HttpResponseBodyLimit", "HttpResponseBody", "HttpTimeoutMs")
            http = temporary / "http.brs"
            http.write_text("\n".join(re.search(r"(?ms)^function " + name + r"\(.*?^end function", http_source).group(0) for name in names))
            boundary = temporary / "fixture.brs"
            boundaries = BOUNDARIES.replace("RunSiloArtwork", "RunPlexArtwork")
            boundaries = boundaries.replace('session["appVersion"] = "0.1.0"',
                                            'session["appVersion"] = "0.1.0"\n    if provider="plex" then session["clientId"]=session.deviceId')
            boundary.write_text(boundaries + BATCH)
            files = [ROOT / "source/core/RuntimeIdentity.brs", ROOT / "source/auth/SessionPolicy.brs", ROOT / "source/adapters/PlexAdapter.brs",
                     ROOT / "source/adapters/SiloAdapter.brs", ROOT / "source/adapters/MetadataAdapter.brs", worker, http, boundary]
            return run_function(files, "RunPlexArtworkBatch", [cases], root=temporary)

    def test_movie_and_show_fresh_exact_guid_identity_then_header_free_public_dto(self):
        show = case(params={"type": "tv", "itemId": "500", "itemType": "show"},
                    owner={**OWNER, "type": "tv", "itemId": "500", "key": "500", "nativeType": "show"}, rows=[SHOW],
                    responses=[{"body": wire(SHOW), "elapsedMs": 500}, {"body": json.dumps({**META, "type": "tv", "tmdbId": "202"})}])
        stored_without_generated_fields = {key: value for key, value in SESSION.items() if key != "clientId"}
        scenarios = [case(), show, case(session=stored_without_generated_fields)]
        for result, kind, identifier in zip(self.run_cases(scenarios), ("movie", "tv", "movie"), ("141", "202", "141")):
            self.assertTrue(result["outcome"]["ok"])
            self.assertEqual(2, len(result["requests"]))
            self.assertTrue(result["requests"][0]["url"].endswith("?includeGuids=1"))
            self.assertEqual("synthetic-server-token", result["requests"][0]["headers"]["X-Plex-Token"])
            self.assertEqual({"Accept": "application/json", "X-Silo-Client": "roku/0.1.0"}, result["requests"][1]["headers"])
            self.assertEqual([3750, 3250], result["timeouts"])
            self.assertEqual([98304, 98304], [request["responseBodyLimit"] for request in result["requests"]])
            self.assertEqual({"type": kind, "tmdbId": identifier, "posterUri": "https://image.tmdb.org/t/p/w342/fixture.jpg",
                              "backdropUri": "https://image.tmdb.org/t/p/w780/fixture.png"}, result["outcome"]["data"])
            for private in ("synthetic", "ratingKey", "Guid", "itemId", "sourceId", "headers"):
                self.assertNotIn(private, json.dumps(result["outcome"]["data"]))

    def test_episode_uses_fresh_exact_parent_show_and_never_leaf_tmdb_identity(self):
        result = self.run_cases([case(episode=True)])[0]
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(["https://provider-private.example.test/library/metadata/501?includeGuids=1",
                          "https://provider-private.example.test/library/metadata/500?includeGuids=1",
                          "https://metadata.example/v1/enrich/tv/202"], [request["url"] for request in result["requests"]])
        self.assertEqual([3750, 3250, 2750], result["timeouts"])
        self.assertEqual([98304] * 3, [request["responseBodyLimit"] for request in result["requests"]])
        self.assertEqual("202", result["outcome"]["data"]["tmdbId"])
        self.assertNotIn("999", json.dumps(result["outcome"]))
        for request in result["requests"][:2]:
            self.assertEqual("synthetic-server-token", request["headers"]["X-Plex-Token"])
        self.assertNotIn("X-Plex-Token", result["requests"][2]["headers"])

    def test_existing_public_exact_movie_show_path_remains_one_header_free_read(self):
        scenarios = [case(params={"type": kind, "tmdbId": identifier},
                          responses=[{"body": json.dumps({**META, "type": kind, "tmdbId": identifier})}])
                     for kind, identifier in (("movie", "141"), ("tv", "202"))]
        for value in self.run_cases(scenarios):
            self.assertTrue(value["outcome"]["ok"])
            self.assertEqual(1, len(value["requests"]))
            self.assertNotIn("X-Plex-Token", value["requests"][0]["headers"])

    def test_guid_conflicts_bad_tmdb_aliases_and_overflow_never_become_a_public_identity(self):
        bad_rows = [
            {**MOVIE, "guid": "tmdb://142"},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}, {"id": "tmdb://142"}]},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}, {"id": "tmdb://0"}]},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}, {"id": "tmdb://oops"}]},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}, {"id": "tmdb://1234567890123"}]},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}, {"id": " tmdb://142"}]},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}] * 16},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}] * 15 + [{"id": "tmdb://142"}]},
            {**MOVIE, "Guid": "tmdb://141"},
            {**MOVIE, "Guid": [{"id": "tmdb://141"}, {"id": 142}]},
            {**MOVIE, "GuId": [{"id": "tmdb://142"}]},
            {**MOVIE, "Guid": [{"id": "tmdb://141", "ID": "tmdb://142"}]},
        ]
        for result in self.run_cases([case(rows=[row]) for row in bad_rows]):
            self.assertFalse(result["outcome"]["ok"])
            self.assertEqual(1, len(result["requests"]))
        valid = [{**MOVIE, "guid": "tmdb://141", "Guid": [{"id": "tmdb://000141"}]},
                 {**MOVIE, "guid": "tvdb://123", "Guid": [{"id": "tmdb://141"}]}]
        self.assertTrue(all(value["outcome"]["ok"] for value in self.run_cases([case(rows=[row]) for row in valid])))

    def test_only_one_exact_typed_leaf_and_numeric_parent_can_authorize_following_reads(self):
        bodies = ["null", "[]", "not-json", json.dumps({"MediaContainer": {"Metadata": []}}),
                  json.dumps({"MediaContainer": {"Metadata": [MOVIE, MOVIE]}}),
                  wire({**MOVIE, "ratingKey": "502"}), wire({**MOVIE, "ratingKey": 501}),
                  wire({**MOVIE, "type": "show"}), wire({**MOVIE, "Guid": []})]
        for result in self.run_cases([case(responses=[{"body": body}]) for body in bodies]):
            self.assertFalse(result["outcome"]["ok"])
            self.assertEqual(1, len(result["requests"]))
        invalid = [None, 500, "", "../500", "500?token=x", "5" * 21]
        for result in self.run_cases([case(episode=True, rows=[{**EPISODE, "grandparentRatingKey": parent}, SHOW]) for parent in invalid]):
            self.assertFalse(result["outcome"]["ok"])
            self.assertEqual(1, len(result["requests"]))
        for result in self.run_cases([case(episode=True, rows=[EPISODE, {**SHOW, **change}]) for change in
                                     ({"ratingKey": "499"}, {"ratingKey": 500}, {"type": "episode"}, {"Guid": []})]):
            self.assertFalse(result["outcome"]["ok"])
            self.assertEqual(2, len(result["requests"]))

    def test_invalid_private_owner_or_request_rejects_before_provider_io(self):
        changes = [{"identityRequired": 1}, {"tmdbId": "141"}, {"itemId": "502"}, {"nativeType": "episode"},
                   {"scopeKey": "route-6"}, {"key": "../501"}, {"artId": 0}, {"artId": 1.5},
                   {"scope": {**OWNER["scope"], "profileId": "other"}},
                   {"scope": {**OWNER["scope"], "generation": 8}}]
        scenarios = [case(owner={**OWNER, **change}) for change in changes]
        scenarios += [case(params={**PARAMS, "itemId": identifier}, owner={**OWNER, "itemId": identifier})
                      for identifier in ("", "abc", "501/502", "5" * 21)]
        scenarios += [case(params={**PARAMS, "tmdbId": "141"})]
        for result in self.run_cases(scenarios):
            self.assertFalse(result["outcome"]["ok"])
            self.assertEqual([], result["requests"])

    def test_every_read_rechecks_revision_and_exact_private_session_before_publication(self):
        scenarios = [case(episode=True, revision_at=2)]
        for stage in range(3):
            for mutation in ({"revisionChange": True}, {"sessionPatch": {"token": "changed-token"}},
                             {"sessionPatch": {"baseUrl": "https://other.example.test"}}):
                entry = case(episode=True)
                entry["responses"][stage].update(mutation)
                scenarios.append(entry)
        values = self.run_cases(scenarios)
        self.assertEqual([], values[0]["requests"])
        for value in values:
            self.assertEqual("session_changed", value["outcome"]["errorCode"])
            self.assertNotIn("data", value["outcome"])

    def test_all_receipts_keep_byte_cap_cumulative_budget_and_actual_boolean_success(self):
        scenarios = []
        expected = []
        for stage in range(3):
            for response in ({"repeatBody": 98305}, {"repeatBody": 49153, "repeatChar": "é"}, {"okOverride": 1}):
                entry = case(episode=True)
                entry["responses"][stage].update(response)
                scenarios.append(entry)
                expected.append((stage + 1, "response_too_large" if "repeatBody" in response else ""))
        entry = case(episode=True)
        entry["responses"][0]["elapsedMs"] = 2800
        scenarios.append(entry)
        expected.append((1, "lookup_budget"))
        entry = case(episode=True)
        entry["responses"][2]["elapsedMs"] = 3000
        scenarios.append(entry)
        expected.append((3, "lookup_budget"))
        for value, (reads, error) in zip(self.run_cases(scenarios), expected):
            self.assertFalse(value["outcome"]["ok"])
            self.assertEqual(reads, len(value["requests"]))
            if error:
                self.assertEqual(error, value["outcome"]["errorCode"])

    def test_auth_failure_or_public_identity_mismatch_never_publishes_or_retries(self):
        failures = [case(responses=[{"statusCode": 401, "body": "synthetic"}]),
                    case(episode=True, responses=[{"body": wire(EPISODE)}, {"statusCode": 404, "body": "synthetic"}]),
                    case(responses=[{"body": wire(MOVIE)}, {"body": json.dumps({**META, "tmdbId": "999"})}]),
                    case(responses=[{"body": wire(MOVIE)}, {"body": json.dumps({**META, "type": "tv"})}])]
        for result, count in zip(self.run_cases(failures), (1, 2, 2, 2)):
            self.assertFalse(result["outcome"]["ok"])
            self.assertEqual(count, len(result["requests"]))
