"""Filter device memory and app-focus events before publishing scene fields.

Native event types and factories are substituted only for entry-loop checks;
actual Roku event delivery remains a device verification item.
"""

from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "source" / "main.brs"

ENTRY_BOUNDARY = '''
function MainTestFactory(kind as String) as Dynamic
    if kind = "roMessagePort" then return {name:"host-port"}
    if kind = "roInput"
        return {SetMessagePort:sub(port as Object)
            m.global.mainTestInputPort = port.name
        end sub,
        EnableTransportEvents:function() as Boolean
            m.global.mainTestTransportCalls++
            return m.global.mainTestTransportEnabled
        end function,global:m}
    end if
    if kind = "roSGScreen"
        return {scene:m.mainTestScene,
            SetMessagePort:sub(port as Object)
            end sub,
            CreateScene:function(name as String) as Object
                return m.scene
            end function,
            Show:sub()
            end sub}
    end if
    if kind = "roAppMemoryMonitor"
        return {enabled:m.mainTestMemoryEnabled,
            SetMessagePort:sub(port as Object)
            end sub,
            EnableMemoryWarningEvent:function(enabled as Boolean) as Boolean
                return m.enabled
            end function,
            GetMemoryLimitPercent:function() as Integer
                return 37
            end function}
    end if
    if kind = "roDeviceInfo"
        m.mainTestDeviceCount++
        return m.mainTestDevice
    end if
    return invalid
end function

function MainTestNextMessage(port as Object) as Object
    message = m.mainTestMessages[m.mainTestMessageIndex]
    m.mainTestMessageIndex++
    return message
end function

function MainTestEntry(supportsFocus as Boolean, memoryEnabled as Boolean, initialFocus as Boolean, eventType as String, info as Dynamic, initialArgs as Dynamic, transportEnabled as Boolean) as Object
    m.mainTestDeviceCount = 0
    m.mainTestTransportCalls = 0
    m.mainTestTransportEnabled = transportEnabled
    m.mainTestMemoryEnabled = memoryEnabled
    m.mainTestScene = {supportsFocus:supportsFocus,memoryPressure:0,
        HasField:function(name as String) as Boolean
            return name = "appFocused" and m.supportsFocus
        end function}
    if supportsFocus then m.mainTestScene.appFocused = initialFocus
    m.mainTestDevice = {portSet:false,focusEnabled:false,exitEnabled:false,lowEnabled:false,
        SetMessagePort:sub(port as Object)
            m.portSet = true
        end sub,
        EnableAppFocusEvent:function(enabled as Boolean) as Boolean
            m.focusEnabled = enabled
            return enabled
        end function,
        EnableScreensaverExitedEvent:function(enabled as Boolean) as Boolean
            m.exitEnabled = enabled
            return enabled
        end function,
        EnableLowGeneralMemoryEvent:function(enabled as Boolean) as Boolean
            m.lowEnabled = enabled
            return enabled
        end function}
    m.mainTestMessages = [{nativeType:eventType,info:info,
        IsInput:function() as Boolean
            return true
        end function,
        GetInfo:function() as Dynamic
            return m.info
        end function}, {nativeType:"roSGScreenEvent",
        IsScreenClosed:function() as Boolean
            return true
        end function}]
    m.mainTestMessageIndex = 0
    RokuAppEntry(initialArgs)
    return {transportCalls:m.mainTestTransportCalls,launch:m.mainTestScene.Lookup("launchInput"),inputPort:m.mainTestInputPort,deviceCount:m.mainTestDeviceCount,portSet:m.mainTestDevice.portSet,
        focusEnabled:m.mainTestDevice.focusEnabled,exitEnabled:m.mainTestDevice.exitEnabled,
        lowEnabled:m.mainTestDevice.lowEnabled,pressure:m.mainTestScene.memoryPressure,
        focusField:m.mainTestScene.DoesExist("appFocused"),focused:m.mainTestScene.Lookup("appFocused")}
end function
'''


class RuntimePerformanceTests(unittest.TestCase):
    def call(self, function, arguments):
        source = ENTRY.read_text()
        self.assertRegex(source, rf"(?i)function\s+{function}\(",
                         f"{function} event sanitization is missing")
        # The test bridge declares Main itself. Rename only the app entry point
        # in a temporary copy so its actual policy and full script still parse.
        source, renamed = re.subn(r"(?im)^sub Main\(", "sub RokuAppEntry(", source, count=1)
        self.assertEqual(1, renamed)
        with tempfile.TemporaryDirectory(prefix="silo-memory-test-") as directory:
            script = Path(directory) / "main.brs"
            script.write_text(source)
            return run_function(script, function, arguments)

    def pressure(self, event_type, info):
        return self.call("MainMemoryPressure", [event_type, info])

    def focus(self, info):
        return self.call("MainAppFocus", [info])

    def test_native_boxed_integer_memory_event_reaches_the_pressure_filter(self):
        source, renamed = re.subn(r"(?im)^sub Main\(", "sub RokuAppEntry(", ENTRY.read_text(), count=1)
        self.assertEqual(renamed, 1)
        source = source.replace("usageType = type(usage)", "usageType = m.nativeNumericType")
        source += '''
function NativeMemoryFixture(alias as String, usage as Integer) as Integer
    m.nativeNumericType = alias
    return MainMemoryPressure("roAppMemoryNotificationEvent",{memoryUsagePercent:usage})
end function
'''
        with tempfile.TemporaryDirectory(prefix="silo-memory-native-type-") as directory:
            script = Path(directory) / "main.brs"
            script.write_text(source)
            for alias in ("roInteger", "roLongInteger"):
                with self.subTest(alias=alias):
                    self.assertEqual(run_function(script, "NativeMemoryFixture", [alias, 81]), 81)

    def entry(self, supports_focus=True, memory_enabled=True, initial_focus=True,
              event_type="roDeviceInfoEvent", info=None, initial_args=None, transport_enabled=True):
        source, renamed = re.subn(r"(?im)^sub Main\(", "sub RokuAppEntry(", ENTRY.read_text(), count=1)
        self.assertEqual(1, renamed)
        for kind in ("roSGScreen", "roMessagePort", "roDeviceInfo", "roAppMemoryMonitor", "roInput"):
            source = source.replace(f'CreateObject("{kind}")', f'MainTestFactory("{kind}")')
        source = source.replace("wait(0, port)", "MainTestNextMessage(port)")
        source = source.replace("messageType = type(message)", "messageType = message.nativeType")
        with tempfile.TemporaryDirectory(prefix="silo-entry-lifecycle-") as directory:
            script = Path(directory) / "main.brs"
            script.write_text(source)
            boundary = Path(directory) / "boundary.brs"
            boundary.write_text(ENTRY_BOUNDARY)
            return run_function([script, boundary], "MainTestEntry",
                                [supports_focus, memory_enabled, initial_focus, event_type, info, initial_args, transport_enabled])

    def test_cold_and_warm_launch_inputs_reach_the_scene(self):
        cold = {"contentId":"movie-1", "mediaType":"movie"}
        warm = {"contentId":"episode-2", "mediaType":"episode"}
        self.assertEqual(self.entry(initial_args=cold)['launch'], cold)
        result = self.entry(initial_args=cold, event_type="roInputEvent", info=warm)
        self.assertEqual(result['launch'], warm)
        self.assertEqual(result['inputPort'], 'host-port')

    def test_transport_registration_runs_once_and_false_keeps_launch_delivery(self):
        cold = {"contentId":"movie-1", "mediaType":"movie"}
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                result = self.entry(initial_args=cold, transport_enabled=enabled)
                self.assertEqual(1, result['transportCalls'])
                self.assertEqual(cold, result['launch'])
                self.assertEqual('host-port', result['inputPort'])

    def test_app_usage_percent_is_bounded_and_keeps_recovery_events(self):
        for value, expected in ((0, 0), (79, 79), (80, 80), (95, 95), (100, 100), (101, 100)):
            with self.subTest(value=value):
                self.assertEqual(expected, self.pressure("roAppMemoryNotificationEvent", {"memoryUsagePercent": value}))
        self.assertEqual(85, self.pressure("roAppMemoryNotificationEvent", {"MemoryUsagePercent": 85}))

    def test_malformed_app_events_cannot_clear_or_inflate_pressure(self):
        for info in (None, [], "low", {}, {"memoryUsagePercent": -1},
                     {"memoryUsagePercent": "95"}, {"memoryUsagePercent": True},
                     {"memoryUsagePercent": 85.5}, {"memoryUsagePercent": {"url": "secret"}}):
            with self.subTest(info=info):
                self.assertEqual(-1, self.pressure("roAppMemoryNotificationEvent", info))
        self.assertEqual(-1, self.pressure("roUrlEvent", {"memoryUsagePercent": 95}))

    def test_legacy_general_memory_levels_have_explicit_severity(self):
        for level, expected in (("normal", 0), ("low", 80), ("critical", 95)):
            with self.subTest(level=level):
                self.assertEqual(expected, self.pressure("roDeviceInfoEvent", {"generalMemoryLevel": level}))
        for info in ({}, {"linkStatus": False}, {"generalMemoryLevel": "unknown"}, {"generalMemoryLevel": 95}):
            self.assertEqual(-1, self.pressure("roDeviceInfoEvent", info))

    def test_typed_app_focus_preserves_both_loss_and_regain(self):
        for focused in (False, True):
            self.assertIs(focused, self.focus({"appFocused": focused}))
        self.assertIs(False, self.focus({"appFocused": False, "exitedScreensaver": True}))

    def test_only_typed_positive_screensaver_exit_means_regain(self):
        self.assertIs(True, self.focus({"exitedScreensaver": True}))
        self.assertIs(True, self.focus({"appFocused": "bad", "exitedScreensaver": True}))
        for value in (False, "true", 1, None, {}, []):
            self.assertIsNone(self.focus({"exitedScreensaver": value}))

    def test_other_and_malformed_device_events_do_not_change_focus(self):
        for info in (None, [], "focused", {}, {"appFocused": "false"},
                     {"appFocused": 0}, {"appFocused": 1}, {"appFocused": {}},
                     {"appFocused": []}, {"appFocused": None}, {"linkStatus": False},
                     {"audioGuideEnabled": True}, {"generalMemoryLevel": "critical"},
                     {"enteredScreensaver": True}, {"screensaverActive": True}):
            with self.subTest(info=info):
                self.assertIsNone(self.focus(info))

    def test_entry_keeps_one_device_listener_with_app_memory_monitor_enabled_or_disabled(self):
        for enabled in (True, False):
            result = self.entry(memory_enabled=enabled, info={"linkStatus": True})
            self.assertEqual((1, True, True, True, not enabled),
                             (result["deviceCount"], result["portSet"], result["focusEnabled"],
                              result["exitEnabled"], result["lowEnabled"]))
            self.assertEqual(37 if enabled else 0, result["pressure"])

    def test_entry_forwards_filtered_device_focus_only_to_supporting_scenes(self):
        for focused in (False, True):
            result = self.entry(initial_focus=not focused, info={"appFocused": focused})
            self.assertIs(focused, result["focused"])
            prototype = self.entry(supports_focus=False, info={"appFocused": focused})
            self.assertEqual((False, None), (prototype["focusField"], prototype["focused"]))
        exited = self.entry(initial_focus=False, info={"exitedScreensaver": True})
        self.assertIs(True, exited["focused"])

    def test_entry_ignores_focus_like_fields_on_other_events_and_preserves_memory_delivery(self):
        other = self.entry(event_type="roAppMemoryNotificationEvent",
                           info={"appFocused": False, "memoryUsagePercent": 80})
        self.assertEqual((True, 80), (other["focused"], other["pressure"]))
        malformed = self.entry(info={"appFocused": "false", "generalMemoryLevel": "critical"})
        self.assertEqual((True, 95), (malformed["focused"], malformed["pressure"]))


if __name__ == "__main__":
    unittest.main()
