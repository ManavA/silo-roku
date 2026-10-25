"""Plex discovery must fit the registry while preserving usable server choices."""

import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "components/ApiTask.brs"]

# The standalone interpreter has no device registry. Keep only that boundary
# replaced; decoding, session merging, budgeting and public results are app code.
REGISTRY_BOUNDARY = '''
function SaveSession(provider as String, session as Object, revision as Integer) as Boolean
    m.attemptedSession = session
    if m.failWrite then return false
    return Len(FormatJson(session)) <= 14000 and revision = m.registryRevision
end function

function SessionRevision(provider as String) as Integer
    return m.registryRevision
end function

function ReplaceSession(provider as String, session as Object, revision as Integer) as Boolean
    return SaveSession(provider, session, revision)
end function

function HttpRequest(request as Object, timeoutMs = 9000 as Integer) as Object
    if Instr(1,request.url,"/api/v2/resources") > 0
        m.resourceFetches = m.resourceFetches + 1
        return {ok:true,body:m.resourcesResponse}
    end if
    return {ok:true, body:FormatJson({"MediaContainer":{"machineIdentifier":m.selectedMachineId}})}
end function

function FinishPlexDiscovery(resources as String, session as Object, failWrite as Boolean, currentRevision as Integer) as Object
    m.attemptedSession = invalid
    m.failWrite = failWrite
    m.registryRevision = currentRevision
    m.resourcesResponse = resources
    m.resourceFetches = 0
    decoded = DecodePlexResponse("resources", resources, {})
    result = TaskFinishPlex("resources", decoded, session, 0)
    characters = 0
    if m.attemptedSession <> invalid then characters = Len(FormatJson(m.attemptedSession))
    return {outcome:result, savedSession:m.attemptedSession, savedCharacters:characters}
end function

function FinishPlexThenSelect(resources as String, session as Object, failWrite as Boolean) as Object
    discovery = FinishPlexDiscovery(resources, session, false, 0)
    if discovery.outcome.ok <> true then return discovery
    selectedSession = discovery.savedSession
    m.selectedMachineId = "fixture-server-0"
    m.failWrite = failWrite
    m.attemptedSession = invalid
    result = TaskSelectPlexServer(selectedSession, {"machineId":m.selectedMachineId}, 0)
    return {outcome:result, savedSession:m.attemptedSession, savedCharacters:Len(FormatJson(m.attemptedSession))}
end function

function FinishPlexThenSelectId(resources as String, session as Object, machineId as String, freshResources = "" as String) as Object
    discovery = FinishPlexDiscovery(resources, session, false, 0)
    if discovery.outcome.ok <> true then return discovery
    m.selectedMachineId = machineId
    if freshResources <> "" then m.resourcesResponse = freshResources
    m.attemptedSession = invalid
    result = TaskSelectPlexServer(discovery.savedSession, {machineId:machineId}, 0)
    return {outcome:result, resourceFetches:m.resourceFetches, savedSession:m.attemptedSession}
end function
'''


class PlexResourceBudgetTests(unittest.TestCase):
    def resource(self, index, connections=None, token="synthetic-server-token"):
        if connections is None:
            connections = [{"uri": f"https://server-{index}.example.test:32400",
                            "local": False, "relay": False}]
        return {"clientIdentifier": f"fixture-server-{index}",
                "name": f"Fixture Server {index}", "provides": "server",
                "accessToken": token, "owned": True, "connections": connections}

    def finish(self, resources, session=None, *, fail_write=False, revision=0, select=False, select_id=None, refreshed_resources=None):
        if session is None:
            session = {"clientId": "fixture-client", "accountToken": "synthetic-account-token"}
        with tempfile.TemporaryDirectory(prefix="silo-resource-boundary-") as directory:
            boundary = Path(directory) / "registry.brs"
            boundary.write_text(REGISTRY_BOUNDARY)
            function = "FinishPlexThenSelectId" if select_id is not None else ("FinishPlexThenSelect" if select else "FinishPlexDiscovery")
            arguments = [json.dumps(resources), session, fail_write]
            if select_id is not None:
                arguments = [json.dumps(resources), session, select_id]
                if refreshed_resources is not None:
                    arguments.append(json.dumps(refreshed_resources))
            elif not select:
                arguments.append(revision)
            return run_function([*FILES, boundary], function, arguments)

    def large_resources(self):
        resources = []
        for server in range(10):
            connections = []
            for connection in range(12):
                host = "a" * 48 + "." + "b" * 48 + f".s{server}c{connection}.example.test"
                connections.append({"uri": "https://" + host + ":32400",
                                    "local": False, "relay": False})
            resources.append(self.resource(server, connections))
        return resources

    def test_large_discovery_keeps_one_connection_per_server_before_alternatives(self):
        result = self.finish(self.large_resources())
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(10, len(result["outcome"]["data"]["servers"]))
        candidates = result["savedSession"]["candidateServers"]
        self.assertEqual(10, len(candidates))
        self.assertTrue(all(server["connections"] for server in candidates))
        self.assertLessEqual(result["savedCharacters"], 14000)
        self.assertLess(sum(len(server["connections"]) for server in candidates), 120)

    def test_owned_server_survives_ten_earlier_shared_servers(self):
        resources = []
        for index in range(10):
            shared = self.resource(index)
            shared["owned"] = False
            resources.append(shared)
        resources.append(self.resource(10))
        result = self.finish(resources)
        self.assertTrue(result["outcome"]["ok"])
        visible = result["outcome"]["data"]["servers"]
        self.assertEqual(11, len(visible))
        self.assertEqual("fixture-server-10", visible[0]["machineId"])
        self.assertEqual("fixture-server-10", result["savedSession"]["candidateServers"][0]["machineId"])

    def test_all_twenty_four_bounded_choices_remain_visible(self):
        result = self.finish([self.resource(index) for index in range(24)])
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(24, len(result["outcome"]["data"]["servers"]))
        self.assertEqual(10, len(result["savedSession"]["candidateServers"]))

    def test_public_server_name_is_bounded_before_crossing_task_boundary(self):
        result = self.finish([self.resource(0) | {"name": "N" * 4000}])
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(128, len(result["outcome"]["data"]["servers"][0]["name"]))

    def test_uncached_shared_choice_refetches_resources_only_when_selected(self):
        resources = []
        for index in range(10):
            shared = self.resource(index)
            shared["owned"] = False
            resources.append(shared)
        resources.append(self.resource(10))
        result = self.finish(resources, select_id="fixture-server-9")
        self.assertEqual("connected", result["outcome"]["data"]["state"])
        self.assertEqual("plex:fixture-server-9", result["outcome"]["data"]["sourceId"])
        self.assertEqual(1, result["resourceFetches"])
        self.assertEqual([], result["savedSession"]["candidateServers"])

    def test_uncached_choice_survives_owned_resources_added_before_selection(self):
        initial = [self.resource(index) | {"owned": False} for index in range(11)]
        refreshed = [self.resource(index + 100) for index in range(24)]
        refreshed.append(initial[-1])
        result = self.finish(initial, select_id="fixture-server-10", refreshed_resources=refreshed)
        self.assertEqual("connected", result["outcome"]["data"]["state"])
        self.assertEqual("plex:fixture-server-10", result["outcome"]["data"]["sourceId"])
        self.assertEqual(1, result["resourceFetches"])

    def test_removed_uncached_choice_cannot_save_an_old_server_route(self):
        initial = [self.resource(index) | {"owned": False} for index in range(11)]
        result = self.finish(initial, select_id="fixture-server-10", refreshed_resources=[self.resource(99)])
        self.assertEqual("server_not_found", result["outcome"]["errorCode"])
        self.assertIsNone(result["savedSession"])
        self.assertEqual(1, result["resourceFetches"])

    def test_selection_discards_discovery_candidates_before_saving_connected_session(self):
        result = self.finish(self.large_resources(), select=True)
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual("connected", result["outcome"]["data"]["state"])
        self.assertEqual("plex:fixture-server-0", result["outcome"]["data"]["sourceId"])
        self.assertEqual([], result["savedSession"]["candidateServers"])
        self.assertEqual("synthetic-server-token", result["savedSession"]["token"])
        self.assertEqual("synthetic-account-token", result["savedSession"]["accountToken"])
        self.assertLessEqual(result["savedCharacters"], 14000)

    def test_verified_selection_write_failure_reports_storage_error(self):
        result = self.finish([self.resource(0)], select=True, fail_write=True)
        self.assertEqual("storage_error", result["outcome"]["errorCode"])

    def test_preferred_local_https_connection_survives_remote_alternatives(self):
        connections = [
            {"uri": "https://relay.example.test", "local": False, "relay": True},
            {"uri": "https://remote.example.test", "local": False, "relay": False},
            {"uri": "http://192.168.1.20:32400", "local": True, "relay": False},
            {"uri": "https://local.example.test", "local": True, "relay": False},
        ]
        result = self.finish([self.resource(1, connections)])
        saved = result["savedSession"]["candidateServers"][0]
        self.assertEqual("https://local.example.test", saved["connections"][0]["baseUrl"])
        self.assertEqual(4, len(saved["connections"]))

    def test_uncached_server_prefers_local_https_over_provider_order_relay(self):
        resources = [self.resource(index) for index in range(11)]
        resources[10] = self.resource(10, [
            {"uri": "https://relay.example.test", "local": False, "relay": True},
            {"uri": "https://local.example.test", "local": True, "relay": False},
        ])
        result = self.finish(resources, select_id="fixture-server-10")
        self.assertEqual("connected", result["outcome"]["data"]["state"])
        self.assertEqual("https://local.example.test", result["savedSession"]["baseUrl"])
        self.assertTrue(result["savedSession"]["local"])
        self.assertEqual(1, result["resourceFetches"])

    def test_unfit_server_does_not_hide_a_later_usable_server(self):
        result = self.finish([self.resource(1, token="synthetic-" + "x" * 14000),
                              self.resource(2)])
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(["fixture-server-2"],
                         [server["machineId"] for server in result["outcome"]["data"]["servers"]])
        self.assertEqual("synthetic-server-token",
                         result["savedSession"]["candidateServers"][0]["token"])

    def test_budget_includes_existing_credentials_and_replaces_old_candidates(self):
        session = {"clientId": "fixture-client", "accountToken": "synthetic-account-token",
                   "accountName": "x" * 12000,
                   "candidateServers": [{"discarded": "x" * 20000}]}
        result = self.finish([self.resource(1), self.resource(2)], session)
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(2, len(result["savedSession"]["candidateServers"]))
        self.assertLessEqual(result["savedCharacters"], 14000)
        self.assertEqual(session["accountToken"], result["savedSession"]["accountToken"])

    def test_no_candidate_fits_returns_an_actionable_resource_storage_error(self):
        result = self.finish([self.resource(1, token="synthetic-" + "x" * 14000)])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("resource_storage_full", result["outcome"]["errorCode"])
        self.assertIsNone(result["savedSession"])

    def test_empty_account_server_list_remains_a_successful_empty_result(self):
        result = self.finish([])
        self.assertEqual({"ok": True, "data": {"servers": []}}, result["outcome"])

    def test_public_result_contains_no_tokens_or_connections(self):
        result = self.finish([self.resource(1)])
        public = json.dumps(result["outcome"])
        self.assertNotIn("synthetic-", public)
        self.assertNotIn("example.test", public)
        self.assertNotIn("connections", public)

    def test_same_revision_write_failure_reports_storage_error(self):
        result = self.finish([self.resource(1)], fail_write=True)
        self.assertEqual("storage_error", result["outcome"]["errorCode"])

    def test_changed_revision_still_reports_session_changed(self):
        result = self.finish([self.resource(1)], revision=1)
        self.assertEqual("session_changed", result["outcome"]["errorCode"])


if __name__ == "__main__":
    unittest.main()
