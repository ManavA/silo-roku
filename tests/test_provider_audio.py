"""Provider Audio restarts wait for exact decoder and ordered terminal barriers."""

from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/ProviderAudioPolicy.brs"

TRACE = '''
function ProviderAudioTrace(config as Object, events as Object) as Object
    state = ProviderAudioCreate(config)
    trace = [{state:state,projection:ProviderAudioProjection(state),effects:[]}]
    for each event in events
        decision = ProviderAudioReduce(state,event)
        state = decision.state
        trace.Push({state:state,projection:ProviderAudioProjection(state),effects:decision.effects,accepted:decision.accepted})
    end for
    return trace
end function
'''


def scope(generation=20, session=False, **changes):
    value = dict(provider="plex", sourceId="plex:source", profileId="owner", generation=generation)
    if session:
        value["sessionId"] = "server-old"
    value.update(changes)
    return value


def status(attempt="old", state="playing", position=92.4, **changes):
    value = dict(attemptId=attempt, mode="playback", state=state, clipId=7,
                 position=999, renderedPosition=position, renderedClipId=7, renderedEpoch=0, errorCode=0)
    value.update(changes)
    return value


def config(landed=True, paused=False, **changes):
    plan = dict(provider="plex", sourceId="plex:source", itemId="1", versionId="file-1",
                sessionId="server-old", startPositionMs=90000, originalResumeMs=90000,
                relativeTimeline=False, timelineOffsetMs=0, streamFormat="hls",
                url="https://synthetic.test/old.m3u8", headers={"X-Plex-Token": "synthetic-private"})
    version = dict(versionId="file-1", mediaIndex=0, partIndex=0, audio=[
        dict(id="11", title="English AAC", language="eng", codec="aac", default=True),
        dict(id="22", title="French AAC", language="fra", codec="aac")])
    value = dict(scope=scope(), operationId="audio-1", clipId=7, paused=paused,
                 session=dict(attemptId="old", scope=scope(19, session=True), plan=plan,
                              item=dict(itemId="1", sourceId="plex:source", durationMs=600000),
                              closed=False, started=True, landed=landed),
                 detail=dict(item=dict(itemId="1", sourceId="plex:source"), versions=[version]),
                 native=status())
    value.update(changes)
    return value


def select(**changes):
    value = dict(kind="select", scope=scope(), attemptId="old", versionId="file-1", clipId=7,
                 inventoryRevision=1, handle="pa-1-1", stopId="stop-1", native=status(), landed=True, paused=False)
    value.update(changes)
    return value


def stopped():
    return dict(kind="native", status=status(state="stopped", clipId=-1), landed=False)


def terminal(ok=True, **changes):
    value = dict(kind="terminal", scope=scope(19, session=True), stopId="stop-1", ok=ok)
    value.update(changes)
    return value


def bound():
    return dict(kind="request_bound", operationId="audio-1", scope=scope(), requestId="new")


def result(**changes):
    plan = dict(provider="plex", sourceId="plex:source", itemId="1", versionId="file-1",
                sessionId="server-new", startPositionMs=92400, relativeTimeline=False,
                url="https://synthetic.test/new.m3u8", headers={"X-Plex-Token": "synthetic-private"}, streamFormat="hls")
    response = dict(scope(), requestId="new", ok=True, plan=plan)
    response.update(changes)
    return dict(kind="plan", scope=scope(), operationId="audio-1", requestId="new", result=response)


class ProviderAudioTests(unittest.TestCase):
    def trace(self, *events, context=None):
        self.assertTrue(POLICY.exists(), "provider audio ownership policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-provider-audio-") as directory:
            helper = Path(directory) / "trace.brs"
            helper.write_text(TRACE)
            return run_function([ROOT / "tests/fixtures/legacy_policy_values.brs", ROOT / "source/core/VideoOwnerPolicy.brs",
                                 ROOT / "source/core/PlexReplacementPolicy.brs", POLICY, helper], "ProviderAudioTrace", [context or config(), events], root=Path(directory))

    def effects(self, trace, kind):
        return [effect for entry in trace for effect in entry["effects"] if effect["kind"] == kind]

    def test_projection_exposes_only_bounded_opaque_handles_and_labels(self):
        trace = self.trace()
        projection = trace[0]["projection"]
        self.assertTrue(projection["available"])
        self.assertEqual(["pa-1-0", "pa-1-1"], [row["handle"] for row in projection["choices"]])
        self.assertTrue(all(not row["selected"] for row in projection["choices"]))
        for private in ("synthetic.test", "synthetic-private", "sourceId", "profileId", "server-old", "audioStreamId"):
            self.assertNotIn(private, str(projection))

    def test_selection_stops_once_and_waits_for_both_barriers_in_either_order(self):
        for receipts in ((stopped(), terminal()), (terminal(), stopped())):
            with self.subTest(receipts=receipts):
                trace = self.trace(select(), select(), *receipts)
                self.assertEqual(1, len(self.effects(trace, "close")))
                self.assertEqual([], trace[-2]["effects"])
                request = self.effects(trace, "request")
                self.assertEqual(1, len(request))
                params = request[0]["params"]
                self.assertEqual(("22", "file-1", 0, 0, 92400),
                                 (params["audioStreamId"], params["versionId"], params["versionIndex"], params["partIndex"], params["startPositionMs"]))
                self.assertTrue(params["forceTranscode"])

    def test_unlanded_original_resume_stays_owed_despite_earlier_or_optimistic_position(self):
        trace = self.trace(select(landed=False), stopped(), terminal(), context=config(landed=False))
        self.assertEqual(90000, self.effects(trace, "request")[0]["params"]["startPositionMs"])

    def test_epoch_one_and_foreign_clip_do_not_replace_last_confirmed_rendered_position(self):
        for bad in (status(position=150, renderedEpoch=1), status(position=150, renderedClipId=8),
                    status(position=150, clipId=8), status(position=150, errorCode=5)):
            with self.subTest(bad=bad):
                trace = self.trace(dict(kind="native", status=bad, landed=True), select(native=bad), stopped(), terminal())
                self.assertEqual(92400, self.effects(trace, "request")[0]["params"]["startPositionMs"])

    def test_source_profile_attempt_version_clip_revision_and_unknown_handle_are_rejected(self):
        for change in (dict(scope=scope(sourceId="plex:other")), dict(scope=scope(profileId="child")),
                       dict(scope=scope(generation=21)), dict(attemptId="foreign"), dict(versionId="file-2"),
                       dict(clipId=8), dict(inventoryRevision=2), dict(handle="22")):
            with self.subTest(change=change):
                trace = self.trace(select(**change))
                self.assertEqual([], trace[-1]["effects"])
                self.assertEqual("ready", trace[-1]["state"]["phase"])

    def test_failed_or_foreign_terminal_never_admits_replacement(self):
        for receipt in (terminal(False), terminal(scope=scope(19, session=True, sessionId="other")),
                        terminal(stopId="other"), terminal(ok=1)):
            with self.subTest(receipt=receipt):
                trace = self.trace(select(), stopped(), receipt)
                self.assertEqual([], self.effects(trace, "request"))
        trace = self.trace(select(), stopped(), terminal(False), dict(kind="retry_cleanup"), terminal())
        self.assertEqual(1, len(self.effects(trace, "retry_cleanup")))
        self.assertEqual(1, len(self.effects(trace, "request")))

    def test_cancelled_intent_never_allocates_after_terminal_and_decoder_stop(self):
        trace = self.trace(select(), dict(kind="cancel"), terminal(), stopped())
        self.assertEqual([], self.effects(trace, "request"))
        self.assertEqual("cancelled", trace[-1]["state"]["phase"])

    def test_request_bound_and_plan_receipt_require_exact_operation_scope_and_file(self):
        trace = self.trace(select(), stopped(), terminal(), bound(), result())
        self.assertEqual(1, len(self.effects(trace, "install")))
        for changes in (dict(versionId="file-2"), dict(sourceId="plex:other"), dict(itemId="2"), dict(startPositionMs=0)):
            with self.subTest(changes=changes):
                event = result()
                event["result"]["plan"].update(changes)
                trace = self.trace(select(), stopped(), terminal(), bound(), event)
                self.assertEqual([], self.effects(trace, "install"))
                self.assertEqual(1, len(self.effects(trace, "cleanup")))

    def test_late_allocating_plan_cleanup_uses_original_scope_and_never_installs(self):
        trace = self.trace(select(), stopped(), terminal(), bound(), dict(kind="cancel"), result())
        self.assertEqual([], self.effects(trace, "install"))
        cleanup = self.effects(trace, "cleanup")
        self.assertEqual(1, len(cleanup))
        self.assertEqual(scope(), cleanup[0]["scope"])

    def test_pause_restore_waits_for_real_new_landing_and_matching_epoch_zero(self):
        events = [select(paused=True), stopped(), terminal(), bound(), result()]
        before = self.trace(*events, dict(kind="native", status=status("new", position=92.4), landed=False))
        self.assertEqual([], self.effects(before, "pause"))
        trace = self.trace(*events, dict(kind="native", status=status("new", position=92.4, renderedEpoch=1), landed=True),
                           dict(kind="native", status=status("new", position=92.4), landed=True),
                           dict(kind="native", status=status("new", position=92.4), landed=True))
        self.assertEqual(1, len(self.effects(trace, "pause")))
        self.assertEqual("new", self.effects(trace, "pause")[0]["attemptId"])

    def test_provider_rows_and_labels_are_bounded_and_unknown_silo_replan_is_unavailable(self):
        context = config()
        context["detail"]["versions"][0]["audio"] = [dict(id=str(index+10), title="https://synthetic.test/private") for index in range(80)]
        rows = self.trace(context=context)[0]["projection"]["choices"]
        self.assertEqual(24, len(rows))
        self.assertNotIn("synthetic.test", str(rows))
        context = config(scope=scope(provider="silo", sourceId="https://silo.synthetic.test"))
        self.assertIsNone(self.trace(context=context)[0]["state"])

    def test_foreign_operation_receipt_cannot_fail_or_cancel_current_manual_replacement(self):
        foreign = result()
        foreign["operationId"] = "audio-other"
        trace = self.trace(select(), stopped(), terminal(), bound(), foreign, result())
        self.assertEqual("requesting", trace[-2]["state"]["phase"])
        self.assertEqual([], trace[-2]["effects"])
        self.assertEqual(1, len(self.effects(trace, "install")))

    def test_rejected_plan_cleanup_is_idempotent_and_can_be_retried_without_progress(self):
        invalid = result()
        invalid["result"]["plan"]["versionId"] = "file-2"
        trace = self.trace(select(), stopped(), terminal(), bound(), invalid, invalid, terminal(False,scope=scope(20,session=True,sessionId="server-new"),stopId="stop-1-late"), dict(kind="retry_cleanup"))
        cleanup = self.effects(trace, "cleanup")
        self.assertEqual([], trace[-3]["effects"])
        self.assertEqual(2, len(cleanup))
        self.assertEqual(cleanup[0]["stopId"], cleanup[1]["stopId"])
        self.assertEqual(cleanup[0]["plan"], cleanup[1]["plan"])

    def test_data_scheme_and_malformed_labels_cannot_reach_renderer(self):
        context = config()
        context["detail"]["versions"][0]["audio"] = [
            dict(id="11", title="data:private-value", language="eng"),
            dict(id="22", title=123, language={"unsafe":"value"})]
        rows = self.trace(context=context)[0]["projection"]["choices"]
        self.assertEqual(["eng", "Audio 2"], [row["label"] for row in rows])

    def test_session_closed_requires_actual_boolean_false(self):
        context = config()
        context["session"]["closed"] = 0
        self.assertIsNone(self.trace(context=context)[0]["state"])

    def test_confirmed_terminal_override_exists_only_after_landing(self):
        landed = self.effects(self.trace(select()), "close")[0]
        self.assertEqual(92400, landed["confirmedPositionMs"])
        unlanded = self.effects(self.trace(select(landed=False), context=config(landed=False)), "close")[0]
        self.assertNotIn("confirmedPositionMs", unlanded)

    def test_native_numeric_box_aliases_keep_real_full_policy_trace(self):
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory(prefix="silo-audio-native-alias-") as directory:
                temporary = Path(directory)
                policy = temporary / "policy.brs"
                policy.write_text(POLICY.read_text().replace("type(", "PaFacadeType("))
                helper = temporary / "trace.brs"
                helper.write_text(TRACE + '\nfunction PaFacadeType(value as Dynamic) as String\n'
                    + '    if type(value) = "Integer" or type(value) = "roInt" then return "' + alias + '"\n'
                    + '    return type(value)\nend function\n')
                trace = run_function([ROOT / "tests/fixtures/legacy_policy_values.brs", ROOT / "source/core/VideoOwnerPolicy.brs",
                    ROOT / "source/core/PlexReplacementPolicy.brs", policy, helper],
                    "ProviderAudioTrace", [config(), [select(), stopped(), terminal(), bound(), result()]], root=temporary)
                self.assertEqual(92400, self.effects(trace,"request")[0]["params"]["startPositionMs"])
                self.assertEqual(1,len(self.effects(trace,"install")))

    def test_invalid_numeric_identity_and_owed_position_fail_closed(self):
        for field, value in (("clipId", True), ("clipId", -1), ("clipId", 7.5), ("clipId", 2147483647)):
            with self.subTest(field=field, value=value):
                context = config(**{field:value})
                self.assertIsNone(self.trace(context=context)[0]["state"])
        for position in (True, "90000", -1, 604800001):
            with self.subTest(position=position):
                context=config()
                context["session"]["plan"]["originalResumeMs"]=position
                self.assertIsNone(self.trace(context=context)[0]["state"])

    def test_retry_does_not_duplicate_a_late_terminal_still_in_flight(self):
        invalid=result()
        invalid["result"]["plan"]["versionId"]="file-2"
        trace=self.trace(select(),stopped(),terminal(),bound(),invalid,dict(kind="retry_cleanup"))
        self.assertEqual(1,len(self.effects(trace,"cleanup")))
        self.assertEqual([],trace[-1]["effects"])

    def test_boolean_receipt_identity_cannot_alias_numeric_scope_or_clip(self):
        context=config(scope=scope(generation=1),clipId=1,native=status(clipId=1,renderedClipId=1))
        for event in (select(scope=scope(generation=True),clipId=1), select(scope=scope(generation=1),clipId=True)):
            with self.subTest(event=event):
                trace=self.trace(event,context=context)
                self.assertFalse(trace[-1]["accepted"])
                self.assertEqual([],trace[-1]["effects"])
        malformed=status(position=150,clipId=True,renderedClipId=True)
        trace=self.trace(dict(kind="native",status=malformed,landed=True),
                         select(scope=scope(generation=1),clipId=1,native=malformed),context=context)
        self.assertEqual(92400,self.effects(trace,"close")[0]["confirmedPositionMs"])


if __name__ == "__main__":
    unittest.main()
