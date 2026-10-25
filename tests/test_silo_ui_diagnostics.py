"""Diagnostics public formatting and native-node lifecycle boundaries."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_function, run_brightscript
ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUIDiagnosticsPolicy.brs'
class DiagnosticsTests(unittest.TestCase):
    def call(self, stats, source):
        with tempfile.TemporaryDirectory() as root:
            return run_function([POLICY], 'SiloUIDiagnosticsText', [stats, source], root=Path(root))
    def test_formats_only_known_values_and_distinguishes_source(self):
        text = self.call(dict(state='playing',videoFormat='hevc',audioFormat='aac',position=12,duration=90,bitrate=8000000,buffering=25,outputMode='2160p60'),dict(streamFormat='mkv'))
        for value in ['Native Video', 'playing', 'hevc', 'aac', '8000000 bps', '25%', '12 s / 90 s', 'Declared stream format: mkv', 'Display mode: 2160p60', 'Native stream HDR: Unknown']:
            self.assertIn(value, text)
    def test_observed_segment_size_is_separate_from_source_and_display(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([POLICY, ROOT/'components/SiloUIDiagnostics.brs'], '''
                m.view = "player"
                m.video = {state:"playing",videoFormat:"hevc",audioFormat:"aac",streamingSegment:{segTypeStr:"video",width:3840,height:2160,segUrl:"https://private/token"}}
                m.playPlan = {streamFormat:"hls"}
                m.playVersions = [{versionId:"v",videoTracks:[{codec:"h264",width:1920,height:1080}]}]
                m.playPlan.versionId = "v"
                m.diagnostics = {visible:true}
                m.diagnosticsText = {text:""}
                m.diagnosticsOutputMode = "1080p"
                onPlayerSegment()
                m.video.streamingSegment = {segTypeStr:"audio",width:1,height:1,segUrl:"https://private/audio"}
                onPlayerSegment()
                onDiagnosticsTimer()
                print m.diagnosticsText.text
            ''', root=Path(root))
        self.assertIn('Native video: hevc 3840 x 2160 / Native audio: aac', output)
        self.assertIn('Source: h264 1920 x 1080', output)
        self.assertIn('Display mode: 1080p', output)
        self.assertNotIn('private', output)
        self.assertLessEqual(len(output.splitlines()), 17)

    def test_original_source_mapping_and_output_remain_distinct(self):
        source = dict(streamFormat='mkv', originalPlayback={'guarded':True,'audioIdentity':{'codec':'ac3','language':'en','channels':6}},
                      sourceVideo={'codec':'hevc','dv_profile':7,'width':3840,'height':2160}, mappingPhase='selected')
        text = self.call(dict(state='playing',videoFormat='hevc',audioFormat='ac3'),source)
        for value in ['Source: hevc P7 3840 x 2160','Delivery: Original / MKV / unchanged bytes',
                      'Selected source audio: ac3 en 6 ch','Audio mapping: audio matched', 'Native stream HDR: Unknown']:
            self.assertIn(value,text)
        self.assertNotIn('playing verified',text)
        source['mappingPhase']='recovering'
        self.assertIn('Audio mapping: original startup failed',self.call({},source))

    def test_copied_hdr10_recipe_is_delivery_evidence_not_native_hdr(self):
        text = self.call({},dict(streamFormat='hls',delivery='server_remux_hls',recipeRange='hdr10',sourceVideo={'codec':'hevc','dv_profile':7,'width':3840,'height':2160,'color_primaries':'bt2020','color_transfer':'smpte2084','color_space':'bt2020nc'}))
        self.assertIn('Source: hevc P7 3840 x 2160',text)
        self.assertIn('Source color: bt2020 / smpte2084 / bt2020nc',text)
        self.assertIn('Recipe range: hdr10',text)
        self.assertIn('Native stream HDR: Unknown',text)
        self.assertLessEqual(len(text.splitlines()),17)

    def test_progressive_remux_delivery_is_visible_without_inferred_native_hdr(self):
        text = self.call({},dict(streamFormat='mkv',delivery='server_remux_progressive',recipeRange='hdr10'))
        self.assertIn('Recipe range: hdr10',text)
        self.assertIn('Native stream HDR: Unknown',text)
        self.assertLessEqual(len(text.splitlines()),17)

    def test_segment_hdr_is_allowlisted_and_not_inferred_from_source(self):
        self.assertIn('Native stream HDR: Dolby Vision', self.call({'hdrMode':'dolby_vision'},{}))
        self.assertIn('Native stream HDR: Unknown', self.call({'hdrMode':'private-url'},{}))

    def test_source_range_and_native_content_never_claim_display_hdr(self):
        common=dict(codec='hevc',width=3840,height=2160,bit_depth=10,color_primaries='bt2020',color_transfer='smpte2084',color_space='bt2020nc',dv_config_present=True,dv_bl_compat_id_present=True,dv_bl_present=True)
        cases=[(dict(common,dv_profile=5,dv_bl_compat_id=0),'Dolby Vision P5'),
               (dict(common,dv_profile=7,dv_bl_compat_id=6),'Dolby Vision P7 / HDR10 base proven'),
               (dict(common,dv_profile=8,dv_bl_compat_id=1),'Dolby Vision P8 / HDR10 base proven'),
               (common,'HDR10'),
               (dict(codec='h264',width=3840,height=2160,bit_depth=8,color_transfer='bt709'),'SDR'),
               (dict(codec='hevc',width=3840,height=2160,dv_profile=8),'Dolby Vision P8 / HDR10 base unknown')]
        for video,expected in cases:
            with self.subTest(expected=expected):
                source=dict(streamFormat='mkv',sourceVideo={'codec':'h264'},originalPlayback=dict(videoFacts=video,audioIdentity={}),recipeRange='dolby_vision')
                native='dolby_vision';native_label='Dolby Vision'
                if expected == 'HDR10':native='hdr10';native_label='HDR10'
                if expected == 'SDR':native='none';native_label='SDR'
                if expected.endswith('base unknown'):native=None;native_label='Unknown'
                text=self.call(dict(outputMode='2160p60Dv',hdrMode=native),source)
                self.assertIn('Source range: '+expected,text)
                self.assertIn('3840 x 2160',text)
                self.assertIn('Native stream HDR: '+native_label,text)
                self.assertIn('Display HDR: Unknown',text)
                self.assertIn('Recipe range: dolby_vision',text)
                self.assertNotIn('Display HDR: Dolby Vision',text)
                self.assertNotIn('private',text)
                self.assertLessEqual(len(text.splitlines()),17)

    def test_diagnostics_panel_fits_hd_canvas(self):
        import xml.etree.ElementTree as ET
        scene=ET.parse(ROOT/'components/SiloUIScene.xml').getroot()
        panel=scene.find(".//*[@id='playerDiagnostics']")
        rectangle=panel.find('Rectangle');label=panel.find('Label')
        x,y=json.loads(panel.attrib['translation'])
        label_x,label_y=json.loads(label.attrib['translation'])
        self.assertLessEqual(y+int(rectangle.attrib['height']),720)
        self.assertLessEqual(x+int(rectangle.attrib['width']),1280)
        self.assertLessEqual(label_y+int(label.attrib['height']),int(rectangle.attrib['height']))
        self.assertLessEqual(label_x+int(label.attrib['width']),int(rectangle.attrib['width']))
        self.assertGreaterEqual(int(label.attrib['numLines']),17)

    def test_audio_segment_cannot_erase_video_hdr_state(self):
        value = run_function([POLICY], 'SiloUIDiagnosticsSegmentHDR', ['dolby_vision',{'segTypeStr':'audio','hdrModeStr':'none','segUrl':'private'}])
        self.assertEqual('dolby_vision',value)
        self.assertEqual('hdr10',run_function([POLICY], 'SiloUIDiagnosticsSegmentHDR', ['dolby_vision',{'segTypeStr':'video','hdrModeStr':'hdr10'}]))

    def test_segment_dimensions_require_bounded_positive_integer_pair(self):
        prior = {'width':3840,'height':2160}
        bad = [None, {}, {'width':1920}, {'width':0,'height':1080},
               {'width':-1,'height':1080}, {'width':16385,'height':1080},
               {'width':1920,'height':16385}, {'width':1920.5,'height':1080},
               {'width':'1920','height':1080}, {'width':True,'height':1080},
               {'width':{'segUrl':'private'},'height':1080}]
        for fields in bad:
            with self.subTest(fields=fields):
                segment = dict(fields,segTypeStr='video',segUrl='private') if fields is not None else None
                self.assertEqual(prior, run_function([POLICY], 'SiloUIDiagnosticsSegmentSize', [prior,segment]))
                self.assertEqual({}, run_function([POLICY], 'SiloUIDiagnosticsSegmentSize', [None,segment]))
                text = self.call({'videoSize':fields},{})
                self.assertIn('Native video: Unavailable Unavailable / Native audio:',text)
                self.assertNotIn('private',text)
        self.assertEqual({'width':1280,'height':720},run_function([POLICY], 'SiloUIDiagnosticsSegmentSize', [prior,{'segTypeStr':'mux','width':1280,'height':720,'segUrl':'private'}]))
        self.assertEqual({},run_function([POLICY], 'SiloUIDiagnosticsSegmentSize', [None,{'segTypeStr':'audio','width':1280,'height':720}]))

    def test_private_or_malformed_values_never_render(self):
        secret = 'https://private/token?secret=abc'
        text = self.call(dict(state=secret,videoFormat=secret,audioFormat=secret,position=secret,duration=-1,bitrate=secret,buffering=101,streamInfo=dict(streamUrl=secret)),dict(streamFormat=secret,url=secret))
        self.assertNotIn(secret, text)
        self.assertIn('Declared stream format: Unavailable', text)
        self.assertIn('Buffering: Unavailable', text)
    def test_up_toggles_back_closes_and_timer_reads_only_when_visible(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([POLICY, ROOT/'components/SiloUIDiagnostics.brs', ROOT/'components/SiloUIPlayer.brs'], '''
                m.view = "player"
                m.video = {state:"playing",position:12,duration:90,videoFormat:"hevc",audioFormat:"aac",control:"play",streamInfo:{streamBitrate:8000000,streamUrl:"private"}}
                m.playPlan = {streamFormat:"mkv",url:"private"}
                m.diagnostics = {visible:false}
                m.diagnosticsText = {text:""}
                m.diagnosticsTimer = {control:"stop"}
                first = PlayerKey("up")
                shown = m.diagnostics.visible
                running = m.diagnosticsTimer.control
                second = PlayerKey("up")
                cleared = m.diagnosticsText.text
                PlayerKey("up")
                back = PlayerKey("back")
                onDiagnosticsTimer()
                print FormatJson({first:first,shown:shown,running:running,second:second,cleared:cleared,back:back,visible:m.diagnostics.visible,timer:m.diagnosticsTimer.control,text:m.diagnosticsText.text,play:m.video.control})
            ''', root=Path(root))
        self.assertEqual(json.loads(output),dict(first=True,shown=True,running='start',second=True,cleared='',back=True,visible=False,timer='stop',text='',play='play'))
    def test_reset_chrome_clears_diagnostics_before_replacement_playback(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([ROOT/'components/SiloUIDiagnostics.brs', ROOT/'components/SiloUIPlayer.brs'], '''
                m.diagnostics = {visible:true}
                m.nativeHdrMode = "dolby_vision"
                m.nativeVideoSize = {width:3840,height:2160}
                m.diagnosticsText = {text:"old stats"}
                m.diagnosticsTimer = {control:"start"}
                m.upNextTimer = {control:"start"}
                m.playerCue = {visible:true}
                m.video = {playbackActionButtons:[]}
                PlayerResetChrome()
                print FormatJson({visible:m.diagnostics.visible,text:m.diagnosticsText.text,timer:m.diagnosticsTimer.control,hdr:m.nativeHdrMode,size:m.nativeVideoSize})
            ''', root=Path(root))
        self.assertEqual(json.loads(output),dict(visible=False,text='',timer='stop',hdr=None,size=None))
    def test_native_boxed_numbers_keep_values_and_bounds_in_real_formatter(self):
        import re
        helpers = '''
function FixtureNativeType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.nativeNumericType
    return kind
end function
function NativeDiagnostics(alias as String) as String
    m.nativeNumericType = alias
    return SiloUIDiagnosticsText({bitrate:8000000,buffering:101,position:12,duration:-1}, {})
end function
'''
        with tempfile.TemporaryDirectory() as root:
            temporary = Path(root)
            policy = temporary / 'policy.brs'
            policy.write_text(re.sub(r'\btype\s*\(', 'FixtureNativeType(', POLICY.read_text(), flags=re.I))
            boundary = temporary / 'native-type.brs'
            boundary.write_text(helpers)
            for alias in ('roInteger', 'roLongInteger'):
                with self.subTest(alias=alias):
                    text = run_function([policy, boundary], 'NativeDiagnostics', [alias], root=temporary)
                    self.assertIn('Stream bitrate: 8000000 bps', text)
                    self.assertIn('Native position: 12 s / Unavailable', text)
                    self.assertIn('Buffering: Unavailable', text)

    def test_documented_10bit_display_mode_does_not_infer_display_hdr(self):
        text=self.call(dict(outputMode='2160p60b10'),{})
        self.assertIn('Display mode: 2160p60b10',text)
        self.assertIn('Display HDR: Unknown',text)
