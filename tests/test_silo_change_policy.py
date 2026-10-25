"""Silo quality retains its lease; physical file changes retire the old lease."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/SiloChangePolicy.brs"
FILES = [ROOT / "source/core/ServerUrlPolicy.brs", ROOT / "source/core/ProgressDeliveryPolicy.brs",
         ROOT / "tests/fixtures/legacy_policy_values.brs", ROOT / "source/core/VideoOwnerPolicy.brs",
         ROOT / "source/core/SiloPlaybackPolicy.brs"]

TRACE = '''
function SiloChangeTrace(config as Object,events as Object) as Object
 state=SiloChangeCreate(config)
 trace=[{state:state,projection:SiloChangeProjection(state),busy:SiloChangeBusy(state),effects:[]}]
 for each event in events
  decision=SiloChangeReduce(state,event)
  state=decision.state
  trace.Push({state:state,projection:SiloChangeProjection(state),busy:SiloChangeBusy(state),
   effects:decision.effects,accepted:decision.accepted})
 end for
 return trace
end function
function SiloChangeCases(cases as Object) as Object
 results=[]
 for each item in cases
  m.scNumericAlias=item.alias
  results.Push(SiloChangeTrace(item.config,item.events))
 end for
 return results
end function
function ScFixtureType(value as Dynamic) as String
 kind=type(value)
 if kind="Integer" or kind="roInt" or kind="LongInteger" or kind="roLongInteger" or kind="Float" or kind="roFloat" or kind="Double" or kind="roDouble"
  if m.scNumericAlias<>invalid and m.scNumericAlias<>"" then return m.scNumericAlias
 end if
 return kind
end function
'''


def scope(generation=20, session=False, **changes):
    result = dict(provider="silo", sourceId="silo:https://synthetic.test", profileId="owner", generation=generation)
    if session:
        result["sessionId"] = "lease-old"
    result.update(changes)
    return result


def native(attempt="old", state="playing", position=2.4, **changes):
    result = dict(attemptId=attempt, mode="playback", state=state, clipId=7, position=999,
                  renderedPosition=position, renderedClipId=7, renderedEpoch=0, errorCode=0)
    result.update(changes)
    return result


def playback_context(file="file-one", session="lease-old", **changes):
    result = dict(schemaVersion=1, sourceId=scope()["sourceId"], profileId="owner", itemId="movie-1", fileId=file,
                  sessionRevision=3, installationId="install-1", sessionId=session, playbackAttemptId="provider-attempt-1",
                  planId="plan-0001", planAttemptId="plan-attempt-1", planAttemptKey="plan-key-1", attemptedPlanKeys=[],
                  attemptCount=0, allowAlternateVersions=False, qualityPreference="original",
                  selectedTracks={"audio": {"id": "audio-accepted"}}, availableQualities=[
                      dict(label="original", preservesSource=True), dict(label="720p", preservesSource=False, height=720)])
    result.update(changes)
    return result


def plan(file="file-one", session="lease-old", target=90000, offset=90000, **changes):
    result = dict(provider="silo", sourceId=scope()["sourceId"], itemId="movie-1", versionId=file,
                  sessionId=session, installationId="install-1", startPositionMs=target-offset,
                  originalResumeMs=target, relativeTimeline=True, timelineOffsetMs=offset, canSeekAnywhere=True,
                  streamFormat="hls", url="https://synthetic.test/private.m3u8", headers={"Authorization": "synthetic-only"},
                  siloPlayback=playback_context(file, session))
    result.update(changes)
    return result


def detail(**changes):
    result = dict(item=dict(sourceId=scope()["sourceId"], itemId="movie-1", durationMs=600000), versionsComplete=True,
                  versions=[dict(sourceId=scope()["sourceId"], itemId="movie-1", versionId="file-one", durationMs=600000, bitrate=1200, bitrateKbps=1200, resolution="1920x1080"),
                            dict(sourceId=scope()["sourceId"], itemId="movie-1", versionId="file-two", durationMs=500000, bitrate=800, bitrateKbps=800, resolution="1280x720")])
    result.update(changes)
    return result


def config(kind="quality", landed=True, paused=False, **changes):
    result = dict(scope=scope(), operationId="silo-change-1", clipId=7, inventoryRevision=1, changeKind=kind,
                  paused=paused, native=native(), detail=detail(),
                  session=dict(attemptId="old", scope=scope(19, session=True), plan=plan(),
                               item=detail()["item"], closed=False, started=True, landed=landed),
                  transport=dict(attemptId="old", clipId=7, ready=True, retired=False, phase="bar", cursorMs=-1,
                                 seekTargetMs=-1, controlPending="", rePausePending=False, desiredPaused=paused),
                  intentProof=dict(attemptId="old", versionId="file-one", clipId=7, audioSafe=True,
                                   providerAudioIntent=False, versionDefaults=True, subtitleMode="unchanged"))
    result.update(changes)
    return result


def select(kind="quality", **changes):
    result = dict(kind="select", scope=scope(), operationId="silo-change-1", attemptId="old", versionId="file-one",
                  clipId=7, inventoryRevision=1, handle="sc-1-1", stopId="stop-1", native=native(), landed=True, paused=False,
                  transport=deepcopy(config()["transport"]), intentProof=deepcopy(config()["intentProof"]))
    result.update(changes)
    return result


def stopped(attempt="old"):
    return dict(kind="native", status=native(attempt=attempt, state="stopped", clipId=-1))


def terminal(ok=True, **changes):
    result = dict(kind="terminal", scope=scope(19, session=True), stopId="stop-1", ok=ok)
    result.update(changes)
    return result


def bound(action="playback_replan", request="new"):
    return dict(kind="request_bound", scope=scope(), operationId="silo-change-1", requestKind=action, requestId=request)


def receipt(action="playback_replan", request="new", **changes):
    result = dict(scope(), requestId=request, action=action, ok=True)
    if action == "detail":
        result["data"] = detail()
    else:
        is_version = action == "playback_start"
        ctx = playback_context("file-two" if is_version else "file-one", "lease-new" if is_version else "lease-old",
                               playbackAttemptId="provider-new" if is_version else "provider-attempt-1",
                               planId="plan-0002", planAttemptKey="plan-key-2", attemptCount=0 if is_version else 1,
                               attemptedPlanKeys=[] if is_version else ["plan-key-1"],
                               qualityPreference="original" if is_version else "720p")
        result["plan"] = plan("file-two" if is_version else "file-one", "lease-new" if is_version else "lease-old",
                              target=92400, siloPlayback=ctx)
        result["data"] = {"playbackDetail": detail()}
    result.update(changes)
    return dict(kind="detail" if action == "detail" else "plan", scope=scope(), operationId="silo-change-1",
                requestId=request, result=result)


def installed(action="playback_replan"):
    return dict(kind="installed", scope=scope(), operationId="silo-change-1", requestId="new", attemptId="new",
                versionId="file-two" if action == "playback_start" else "file-one")


def quality_prefix():
    return [select(), stopped(), bound()]


def version_prefix():
    return [select("version"), bound("detail", "verify"), receipt("detail", "verify")]


class SiloChangePolicyTests(unittest.TestCase):
    def cases(self, cases, alias=False):
        self.assertTrue(POLICY.exists(), "Silo quality/version owner policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-silo-change-") as directory:
            helper = Path(directory) / "trace.brs"
            helper.write_text(TRACE)
            source = POLICY
            if alias:
                source = Path(directory) / "policy.brs"
                source.write_text(POLICY.read_text().replace("return type(value)", "return ScFixtureType(value)"))
            return run_function([*FILES, source, helper], "SiloChangeCases", [cases], root=Path(directory))

    def trace(self, events=(), context=None):
        return self.cases([dict(config=context or config(), events=list(events), alias="")])[0]

    def effects(self, trace, kind):
        return [effect for entry in trace for effect in entry["effects"] if effect["kind"] == kind]

    def test_quality_stops_native_once_replans_same_lease_and_pauses_only_after_rendered_landing(self):
        trace = self.trace([select(paused=True), select(), stopped(), bound(), receipt(), installed(),
                            dict(kind="native", status=native("new", position=2.4, clipId=8, renderedClipId=8, renderedEpoch=1), landed=True),
                            dict(kind="native", status=native("new", position=2.4, clipId=8, renderedClipId=8), landed=True)], config(paused=True))
        self.assertEqual(1, len(self.effects(trace, "native_stop")))
        self.assertEqual([], self.effects(trace, "close")); self.assertEqual([], self.effects(trace, "cleanup"))
        request = self.effects(trace, "request")[0]
        self.assertEqual("playback_replan", request["action"])
        self.assertEqual(("lease-old", 92400, "720p"), (request["params"]["sessionId"], request["params"]["positionMs"], request["params"]["qualityPreference"]))
        self.assertEqual(1, len(self.effects(trace, "install_same_lease")))
        self.assertEqual([], trace[-2]["effects"])
        self.assertEqual([{"kind": "pause", "attemptId": "new"}], trace[-1]["effects"])
        self.assertEqual(scope(19, session=True), trace[-1]["state"]["leaseScope"])
        self.assertEqual("done", trace[-1]["state"]["phase"])

    def test_versions_prove_fresh_file_before_close_and_wait_for_both_original_barriers(self):
        traces = self.cases([dict(config=config("version"), events=[*version_prefix(), *barriers, bound("playback_start"),
                                                                   receipt("playback_start"), installed("playback_start")], alias="")
                             for barriers in ([stopped(), terminal()], [terminal(), stopped()])])
        for trace in traces:
            self.assertTrue(self.effects(trace, "request"), "version choice must request fresh exact file proof")
            self.assertEqual("detail", self.effects(trace, "request")[0]["action"])
            self.assertEqual([], trace[2]["effects"])
            self.assertEqual(1, len(self.effects(trace, "close")))
            start = self.effects(trace, "request")[-1]
            self.assertEqual("playback_start", start["action"])
            self.assertEqual(("file-two", 92400), (start["params"]["fileId"], start["params"]["startPositionMs"]))
            self.assertNotIn("audioTrackId", start["params"]); self.assertNotIn("selectedTracks", start["params"])
            self.assertEqual(1, len(self.effects(trace, "install")))

    def test_unlanded_keeps_original_resume_and_stale_epoch_clip_or_optimistic_clock_cannot_move_target(self):
        contexts = [config(landed=False), config(), config(landed=False)]
        events = [[select(landed=False), stopped()],
                  [dict(kind="native", status=native(position=200, renderedEpoch=1), landed=True),
                   select(native=native(position=300, renderedClipId=8)), stopped()],
                  [dict(kind="native", status=native(position=200, renderedEpoch=1), landed=True),
                   select(native=native(position=200, renderedEpoch=1)), stopped()]]
        traces = self.cases([dict(config=c, events=e, alias="") for c, e in zip(contexts, events)])
        self.assertEqual([90000, 92400, 90000], [self.effects(t, "request")[0]["params"]["positionMs"] for t in traces])

    def test_exact_selection_scope_transport_and_proven_intent_are_required_before_any_stop(self):
        cases = []
        for changes in [dict(scope=scope(profileId="child")), dict(scope=scope(generation=21)), dict(attemptId="other"),
                        dict(versionId="file-two"), dict(clipId=8), dict(inventoryRevision=2), dict(operationId="other"), dict(handle="file-two")]:
            cases.append(dict(config=config(), events=[select(**changes)], alias=""))
        for field, value in [("seekTargetMs", 1000), ("cursorMs", 1000), ("controlPending", "pause"), ("rePausePending", True), ("ready", False)]:
            context = config(); context["transport"][field] = value
            cases.append(dict(config=context, events=[select()], alias=""))
            event = select(); event["transport"][field] = value
            cases.append(dict(config=config(), events=[event], alias=""))
        for changes in [dict(audioSafe=False), dict(attemptId="other")]:
            context = config(); context["intentProof"].update(changes)
            cases.append(dict(config=context, events=[select()], alias=""))
        for trace in self.cases(cases):
            self.assertTrue(all(not row["effects"] for row in trace))

    def test_owned_malformed_plan_retires_original_once_but_foreign_receipts_do_nothing(self):
        cases = []
        for changes in [dict(ok=1), dict(action="playback_start"), dict(plan=plan(session="foreign")),
                        dict(plan=plan(target=93000, siloPlayback=playback_context(qualityPreference="720p")))]:
            cases.append(dict(config=config(), events=[*quality_prefix(), receipt(**changes), receipt(**changes)], alias=""))
        foreign = receipt(); foreign["requestId"] = "foreign"
        cases.append(dict(config=config(), events=[*quality_prefix(), foreign], alias=""))
        traces = self.cases(cases)
        for trace in traces[:-1]:
            self.assertEqual([], self.effects(trace, "install_same_lease"))
            self.assertEqual(1, len(self.effects(trace, "retire")))
        self.assertEqual([], traces[-1][-1]["effects"])

    def test_cancelled_quality_never_deletes_a_returned_plan_or_installs_after_back(self):
        trace = self.trace([*quality_prefix(), dict(kind="cancel"), receipt(), receipt(), terminal()])
        self.assertEqual([], self.effects(trace, "install_same_lease")); self.assertEqual([], self.effects(trace, "cleanup"))
        self.assertEqual(1, len(self.effects(trace, "retire")))
        self.assertEqual(scope(19, session=True), self.effects(trace, "retire")[0]["scope"])
        self.assertTrue(trace[4]["busy"])
        self.assertFalse(trace[-1]["busy"])

    def test_cancelled_version_allocation_is_collected_without_progress_and_cleanup_requires_exact_receipt(self):
        events = [*version_prefix(), stopped(), terminal(), bound("playback_start"), dict(kind="cancel"), receipt("playback_start")]
        wrong = terminal(scope=scope(session=True, sessionId="lease-new"), stopId="foreign")
        right = terminal(scope=scope(session=True, sessionId="lease-new"), stopId="stop-1-late")
        trace = self.trace([*events, wrong, right], config("version"))
        self.assertEqual([], self.effects(trace, "install"))
        cleanup = self.effects(trace, "cleanup")
        self.assertEqual(1, len(cleanup)); self.assertFalse(cleanup[0]["persistProgress"])
        self.assertTrue(trace[-2]["busy"]); self.assertFalse(trace[-1]["busy"])

    def test_malformed_owned_version_receipt_still_collects_exact_raw_allocation_without_optional_context(self):
        events = [*version_prefix(), stopped(), terminal(), bound("playback_start")]
        raw = receipt("playback_start", ok="not-a-boolean")
        raw["result"]["plan"].pop("siloPlayback")
        cases = [dict(config=config("version"), events=[*events, raw, raw], alias="")]
        for field, value in [("provider", "plex"), ("sourceId", "silo:foreign"), ("itemId", "other"),
                             ("versionId", "file-one"), ("sessionId", "lease-old"), ("installationId", "other")]:
            changed = deepcopy(raw); changed["result"]["plan"][field] = value
            cases.append(dict(config=config("version"), events=[*events, changed], alias=""))
        traces = self.cases(cases)
        cleanup = self.effects(traces[0], "cleanup")
        self.assertEqual(1, len(cleanup), "mapped allocated file must be abandoned despite malformed completion envelope")
        self.assertFalse(cleanup[0]["persistProgress"])
        self.assertNotIn("url", cleanup[0]["plan"]); self.assertNotIn("headers", cleanup[0]["plan"])
        self.assertTrue(traces[0][-1]["busy"])
        self.assertTrue(all(not self.effects(trace, "cleanup") for trace in traces[1:]))

    def test_failed_worker_abandon_retains_original_stop_identity_for_idempotent_retry(self):
        failure = receipt("playback_start", ok=False)
        failure["result"]["plan"] = dict(provider="silo", sourceId=scope()["sourceId"], itemId="movie-1", versionId="file-two",
                                            sessionId="lease-new", installationId="install-1", stopId="worker-stop-1", persistProgress=False)
        trace = self.trace([*version_prefix(), stopped(), terminal(), bound("playback_start"), failure], config("version"))
        cleanup = self.effects(trace, "cleanup")
        self.assertEqual(1, len(cleanup))
        self.assertEqual("worker-stop-1", cleanup[0]["stopId"], "retry must retain the worker's original DELETE identity")
        retry = self.trace([*version_prefix(), stopped(), terminal(), bound("playback_start"), failure,
                            terminal(False, scope=scope(session=True, sessionId="lease-new"), stopId="worker-stop-1"),
                            dict(kind="retry_cleanup"),
                            terminal(scope=scope(session=True, sessionId="lease-new"), stopId="worker-stop-1")], config("version"))
        self.assertEqual(["worker-stop-1", "worker-stop-1"], [e["stopId"] for e in self.effects(retry, "cleanup")])
        self.assertFalse(retry[-1]["busy"])

    def test_bad_fresh_version_proof_does_not_close_and_failed_terminal_blocks_allocation(self):
        invalids = [detail(versionsComplete=False), detail(versions=[detail()["versions"][0]]),
                    detail(versions=[detail()["versions"][0], dict(versionId="file-two", durationMs=1000, bitrate=100)])]
        cases = [dict(config=config("version"), events=[select("version"), bound("detail", "verify"), receipt("detail", "verify", data=d)], alias="") for d in invalids]
        traces = self.cases(cases)
        for trace in traces:
            self.assertEqual([], self.effects(trace, "close"))
            self.assertEqual("failed", trace[-1]["state"]["phase"])
        trace = self.trace([*version_prefix(), stopped(), terminal(False), dict(kind="retry_cleanup"), terminal()], config("version"))
        self.assertEqual("blocked", trace[-3]["state"]["phase"])
        self.assertEqual(1, len(self.effects(trace, "retry_cleanup")))
        self.assertEqual(1, len([e for e in self.effects(trace, "request") if e["action"] == "playback_start"]))

    def test_public_projection_bounded_and_subtitle_off_is_explicit_without_auto_wire_selector(self):
        cases = []
        for mode in ["off", "auto"]:
            context = config(); context["intentProof"]["subtitleMode"] = mode
            context["session"]["plan"]["siloPlayback"]["selectedTracks"]["subtitle"] = {"id": "accepted-subtitle"}
            event = select(); event["intentProof"] = deepcopy(context["intentProof"])
            cases.append(dict(config=context, events=[event, stopped()], alias=""))
        traces = self.cases(cases)
        for trace in traces:
            projection = str(trace[0]["projection"])
            for private in ["synthetic.test", "Authorization", "lease-old", "audio-accepted", "plan-key", "sourceId", "profileId"]:
                self.assertNotIn(private, projection)
            self.assertLessEqual(len(trace[0]["projection"]["choices"]), 5)
        self.assertNotIn("subtitle", self.effects(traces[0], "request")[0]["params"]["selectedTracks"])
        self.assertNotIn("selectedTracks", self.effects(traces[1], "request")[0]["params"])

    def test_numeric_native_aliases_keep_real_values_and_boolean_unknown_facts_fail_closed(self):
        aliases = ["Integer", "roInt", "roInteger", "LongInteger", "roLongInteger", "Float", "roFloat", "Double", "roDouble"]
        cases = [dict(config=config(), events=[select(), stopped()], alias=alias) for alias in aliases]
        result = self.cases(cases, alias=True)
        self.assertTrue(all(self.effects(trace, "request")[0]["params"]["positionMs"] == 92400 for trace in result))
        bad = config(); bad["clipId"] = True
        unknown = config(); unknown["intentProof"].pop("audioSafe")
        for trace in self.cases([dict(config=c, events=[select()], alias="") for c in [bad, unknown]]):
            self.assertIsNone(trace[0]["state"])


if __name__ == "__main__":
    unittest.main()
