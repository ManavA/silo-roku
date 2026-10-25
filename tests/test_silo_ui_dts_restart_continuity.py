"""DTS may be recognized only as the unselected lane on a private P8 retry."""
import copy
import unittest

from tools.brightscript import run_function
from tests.test_silo_ui_original_playback import POLICY, descriptor


def proof(profile=8):
    value = descriptor()
    value['dolbyVisionProfile'] = profile
    value['sourceAudio'][0].update(codec='dts', channels=6, layout='5.1')
    return value


def tracks(ac3='current-ac3', dts='current-dts'):
    return [dict(Track=dts, Format='DTS Coherent Acoustics', Language='eng', Channels=6),
            dict(Track=ac3, Format='Dolby Digital', Language='eng', Channels=6)]


def field(state, name):
    return state.get(name, state.get(name.lower()))


class DtsRestartContinuity(unittest.TestCase):
    def create(self, value=None, experimental=True):
        return run_function([POLICY], 'SiloUIOriginalCreate',
                            [proof() if value is None else value, 7, 3, 0, experimental])

    def event(self, state, kind, now=1000, generation=None, **fields):
        return run_function([POLICY], 'SiloUIOriginalReduce',
                            [state, dict(kind=kind, token=7,
                                         generation=state['generation'] if generation is None else generation,
                                         nowMs=now, **fields)])

    def start_retry(self, value=None, experimental=True, raw=None, initial=True):
        state = self.create(value, experimental)
        state = self.event(state, 'observation', nativeState='buffering')['state']
        if initial:
            first = self.event(state, 'inventory', now=2000, inventory=tracks() if raw is None else raw)
            self.assertEqual('select', first['command']['kind'])
            state = first['state']
        state = self.event(state, 'observation', now=5000, nativeState='finished')['state']
        self.assertEqual('restarting', state['phase'])
        return self.event(state, 'observation', now=6000, nativeState='buffering')['state']

    def retry_inventory(self, state, raw=None, **fields):
        return self.event(state, 'inventory', now=6100, inventory=tracks() if raw is None else raw,
                          provenance='same_content_restart', bindingValidated=True, **fields)

    def test_private_p8_selects_current_ac3_without_fresh_inventory_callback(self):
        state = self.start_retry()
        self.assertTrue(field(state, 'initialRestartMapping'))
        retry = self.retry_inventory(state, tracks('new-ac3', 'new-dts'))
        self.assertEqual({'kind':'select','trackId':'new-ac3'}, retry['command'])
        self.assertEqual('same_content_restart', field(retry['state'], 'mappingProvenance'))
        state = retry['state']
        for handle, codec in [('current-ac3','ac3'), ('new-dts','dts')]:
            wrong = self.event(state, 'observation', now=7000, nativeState='playing',
                               audioTrack=handle, audioFormat=codec, positionMs=100)
            self.assertEqual('selected', wrong['state']['phase'])
        state = self.event(state, 'observation', now=8000, nativeState='playing',
                           audioTrack='new-ac3', audioFormat='ac3', positionMs=100)['state']
        self.assertEqual('selected', state['phase'])
        state = self.event(state, 'observation', now=9000, nativeState='playing',
                           audioTrack='new-ac3', audioFormat='ac3', positionMs=1100)['state']
        self.assertEqual('verified_playing', state['phase'])

    def test_normal_p7_missing_or_untrusted_profile_cannot_authorize_dts_retry(self):
        variants = [(proof(), False), (proof(7), True), (proof(9), True),
                    (proof('8'), True), (proof(True), True)]
        missing = proof(); del missing['dolbyVisionProfile']; variants.append((missing, True))
        for value, experimental in variants:
            with self.subTest(profile=value.get('dolbyVisionProfile'), experimental=experimental):
                state = self.start_retry(value, experimental)
                self.assertFalse(field(state, 'initialRestartMapping'))
                self.assertEqual('audio_unverified', self.retry_inventory(state)['command']['reason'])

    def test_prebuffer_missing_initial_binding_and_stale_owner_refuse(self):
        state = self.create()
        before = self.event(state, 'inventory', inventory=tracks(),
                            provenance='same_content_restart', bindingValidated=True)
        self.assertIsNone(before['command'])
        missing = self.start_retry(initial=False)
        self.assertEqual('audio_unverified', self.retry_inventory(missing)['command']['reason'])
        ready = self.start_retry()
        for generation in (3, 5):
            stale = self.event(ready, 'inventory', now=6100, generation=generation,
                               inventory=tracks(), provenance='same_content_restart', bindingValidated=True)
            self.assertIsNone(stale['command'])
            self.assertEqual(ready, stale['state'])
        denied = self.event(ready, 'inventory', now=6100, inventory=tracks(),
                            provenance='same_content_restart', bindingValidated=False)
        self.assertEqual('binding_changed', denied['command']['reason'])

    def test_cancel_deadline_and_second_finish_remain_terminal(self):
        ready = self.start_retry()
        closed = self.event(ready, 'cancel', now=6100)['state']
        self.assertEqual('closed', closed['phase'])
        self.assertIsNone(self.retry_inventory(closed)['command'])
        timeout = self.event(ready, 'tick', now=60000)
        self.assertEqual('startup_timeout', timeout['command']['reason'])
        failed = self.event(ready, 'observation', now=6100, nativeState='finished')
        self.assertEqual('startup_failure', failed['command']['reason'])

    def test_exact_lane_shape_and_metadata_are_required(self):
        variations = []
        value = proof(); value['sourceAudio'].append(dict(index=2, codec='aac', language='en', channels=2)); variations.append((value, tracks()))
        value = proof(); value['sourceAudio'][0]['codec'] = 'truehd'; variations.append((value, tracks()))
        value = proof(); value['sourceAudio'][0]['language'] = 'fr'; variations.append((value, tracks()))
        value = proof(); value['sourceAudio'][0]['codec'] = 'unknown'; variations.append((value, tracks()))
        for raw in (tracks()+[dict(Track='extra',Format='aac',Language='eng')],
                    [tracks()[0], copy.deepcopy(tracks()[0])],
                    [dict(Track='dts',Format='unknown',Language='eng'),tracks()[1]],
                    [dict(Track='dts',Format='DTS Coherent Acoustics',Language='fra'),tracks()[1]],
                    [dict(Track='dts',Format='DTS Coherent Acoustics',Language='eng',Channels=0),tracks()[1]],
                    [dict(Track='dts',Format='DTS Coherent Acoustics',Language='eng',Channels=8),tracks()[1]],
                    [dict(Track='dts',Format='DTS Coherent Acoustics',Language='eng',Channels=None),tracks()[1]],
                    [dict(Track='dts',Format='DTS Coherent Acoustics',Language='eng',Channels=True),tracks()[1]],
                    [tracks()[0],dict(Track='ac3',Format='Dolby Digital',Language='eng',Channels=2)],
                    [tracks()[0],dict(Track='ac3',Format='Dolby Digital',Language='eng',Channels=None)],
                    [tracks()[0],dict(Track='ac3',Format='Dolby Digital',Language='eng',Channels=True)],
                    [dict(Track='dts',Format='Dolby Metadata-enhanced Audio Transmission',Language='eng'),tracks()[1]]):
            variations.append((proof(), raw))
        for codec, channels in [('dts', 0), ('dts', 9), ('ac3', 8)]:
            value = proof()
            lane = 0 if codec == 'dts' else 1
            value['sourceAudio'][lane]['channels'] = channels
            if lane == 1:
                value['audioIdentity']['channels'] = channels
            variations.append((value, tracks()))
        for value, raw in variations:
            with self.subTest(value=value['sourceAudio'], raw=raw):
                state = self.create(value)
                self.assertFalse(run_function([POLICY], 'SiloUIOriginalRestartSubset',
                                              [value, raw, True]))
                if state is not None and len(value['sourceAudio']) == 2:
                    first = self.event(state, 'inventory', inventory=raw)
                    if first['command'] is not None and first['command']['kind'] == 'select':
                        self.assertFalse(field(first['state'], 'initialRestartMapping'))


if __name__ == '__main__':
    unittest.main()
