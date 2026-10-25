"""Installed manifest identity reaches the actual Task namespaces and requests."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = '''
function IdentityMetadataSection() as Object
 return {Read:function(key)
 return "https://metadata.example"
 end function}
end function

function IdentityFixtureDevice() as Object
 return {GetChannelClientId:function() as String
 return "fixture-device"
 end function,GetModel:function() as String
 return "fixture-model"
 end function,GetOSVersion:function() as Object
 return {major:"15",minor:"3",revision:"4"}
 end function,CanDecodeAudio:function(query as Object) as Object
 return {result:false}
 end function}
end function
function IdentitySnapshot(api as Boolean) as Object
 session={baseUrl:"https://server.example",sourceId:"silo:fixture",profileId:"fixture",accessToken:"synthetic-token"}
 if api then session=TaskDeviceSession("silo",session) else session=EpisodeNeighborDeviceSession("silo",session)
 request=BuildSiloRequest("playback_capabilities",session,{})
 result={version:session.appVersion,header:request.headers["X-Silo-Client-Version"]}
 if api
  context=TaskRokuSiloContext(IdentityFixtureDevice(),{containers:["mp4"],codecs_video:["h264"]})
  publicRequest=TaskBuildRequest("silo","discover_trending",{appVersion:"0.1.0"},{page:1})
  result["contextVersion"]=context.app_version
  result["metadataHeader"]=publicRequest.headers["X-Silo-Client"]
 end if
 return result
end function
'''


class RuntimeIdentityTests(unittest.TestCase):
    def snapshot(self, component, version):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            major, minor, build = version.split('.')
            (folder / 'manifest').write_text(
                f'major_version={major}\nminor_version={minor}\nbuild_version={build}\n')
            scene = ET.parse(ROOT / f'components/{component}.xml').getroot()
            files = []
            for index, script in enumerate(scene.findall('script')):
                original = ROOT / script.attrib['uri'].removeprefix('pkg:/')
                local = folder / f'{index}-{original.name}'
                local.write_text(original.read_text().replace(
                    'CreateObject("roDeviceInfo")', 'IdentityFixtureDevice()').replace(
                    'CreateObject("roRegistrySection", "silo.metadata")', 'IdentityMetadataSection()'))
                files.append(local)
            boundary = folder / 'boundary.brs'
            boundary.write_text(BOUNDARY)
            return run_function([*files, boundary], 'IdentitySnapshot',
                                [component == 'ApiTask'], root=folder)

    def test_api_task_uses_installed_version_in_session_playback_and_public_metadata(self):
        for version in ('7.8.42', '7.8.43'):
            with self.subTest(version=version):
                value = self.snapshot('ApiTask', version)
                self.assertEqual(version, value['version'])
                self.assertEqual(version, value['header'])
                self.assertEqual(version, value['contextVersion'])
                self.assertEqual('roku/' + version, value['metadataHeader'])

    def test_public_artwork_paths_use_current_version_without_provider_headers(self):
        from tests.test_silo_artwork_task import BOUNDARIES as artwork_boundaries
        from tests.test_silo_artwork_task import PARAMS, OWNER, SCOPE, SESSION, DETAIL, META
        import json
        from tests.test_plex_artwork_task import case
        for provider in ('silo', 'plex'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                (folder / 'manifest').write_text(
                    'major_version=7\nminor_version=8\nbuild_version=42\n')
                scene = ET.parse(ROOT / 'components/ApiTask.xml').getroot()
                files = []
                for index, script in enumerate(scene.findall('script')):
                    original = ROOT / script.attrib['uri'].removeprefix('pkg:/')
                    source = original.read_text().replace('CreateObject("roDeviceInfo")',
                                                          'IdentityFixtureDevice()')
                    source = source.replace('CreateObject("roTimespan")', 'ArtworkFixtureClock()')
                    source = source.replace('CreateObject("roRegistrySection", "silo.metadata")', 'IdentityMetadataSection()')
                    for name in ('HttpRequest', 'LoadSession', 'SessionRevision'):
                        source = source.replace('function ' + name + '(',
                                                'function Unused' + name + '(', 1)
                    local = folder / f'{index}-{original.name}'
                    local.write_text(source)
                    files.append(local)
                boundaries = artwork_boundaries.replace('function MetadataRequestConfig(', 'function UnusedFixtureMetadataRequestConfig(', 1).replace('function TaskDeviceSession(',
                                                        'function UnusedFixtureDeviceSession(', 1)
                fixture = folder / 'boundary.brs'
                fixture.write_text(BOUNDARY + boundaries.replace('RunSiloArtwork', 'RunIdentityArtwork'))
                if provider == 'silo':
                    values = [PARAMS, OWNER, SCOPE, SESSION,
                              [{'body':json.dumps(DETAIL)}, {'body':json.dumps(META)}], 0]
                else:
                    entry = case()
                    values = [entry[key] for key in ('params','owner','scope','session','responses','revisionAt')]
                result = run_function([*files, fixture], 'RunIdentityArtwork', values, root=folder)
                self.assertTrue(result['outcome']['ok'])
                self.assertEqual({'Accept':'application/json','X-Silo-Client':'roku/7.8.42'},
                                 result['requests'][-1]['headers'])

    def test_missing_or_malformed_manifest_version_is_unknown(self):
        for manifest in ('', 'major_version=7\nminor_version=8\nbuild_version=private-token\n',
                         'major_version=' + '1' * 41 + '\nminor_version=2\nbuild_version=3\n'):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                (folder / 'manifest').write_text(manifest)
                self.assertEqual('unknown', run_function(
                    [ROOT / 'source/core/RuntimeIdentity.brs'], 'RuntimeAppVersion', [], root=folder))

    def test_episode_neighbor_task_uses_installed_version_in_provider_requests(self):
        value = self.snapshot('EpisodeNeighborTask', '7.8.42')
        self.assertEqual({'version':'7.8.42','header':'7.8.42'}, value)
