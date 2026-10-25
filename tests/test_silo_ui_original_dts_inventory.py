"""Observed DTS inventory permits a separate AC3 handle, never a DTS target."""
import unittest

from tools.brightscript import run_function
from tests.test_silo_ui_original_playback import POLICY, descriptor


def dts_descriptor(codec='dts'):
    proof = descriptor()
    proof['sourceAudio'][0].update(codec=codec, channels=6, layout='5.1')
    return proof


def native_inventory():
    # Deliberately put the selected source ordinal 1 at native array position 0.
    return [dict(Track='opaque-ac3-handle', Format='Dolby Digital', Language='eng', Name='DTS'),
            dict(Track='opaque-dts-handle', Format='DTS Coherent Acoustics', Language='eng', Name='AC3')]


class SiloUIOriginalDtsInventory(unittest.TestCase):
    def call(self, name, *args):
        return run_function(POLICY, name, list(args))

    def create(self, proof=None):
        return self.call('SiloUIOriginalCreate', dts_descriptor() if proof is None else proof, 7, 3, 0)

    def event(self, state, kind, **values):
        return self.call('SiloUIOriginalReduce', state,
                         dict(kind=kind, token=7, generation=3, nowMs=1000, **values))

    def test_observed_dts_and_dca_source_lanes_resolve_actual_unique_ac3_handle(self):
        for codec in ('dts', 'dca'):
            with self.subTest(codec=codec):
                proof = dts_descriptor(codec)
                self.assertIsNotNone(self.create(proof))
                for raw in (native_inventory(), list(reversed(native_inventory()))):
                    result = self.call('SiloUIOriginalResolve', proof, raw)
                    self.assertEqual({'status':'matched', 'trackId':'opaque-ac3-handle'}, result)

    def test_dts_target_is_refused_at_creation_and_resolution(self):
        for codec in ('dts', 'dca'):
            with self.subTest(codec=codec):
                proof = dts_descriptor(codec)
                proof['audioIdentity'].update(index=0, codec=codec)
                self.assertIsNone(self.create(proof))
                self.assertEqual('refused', self.call('SiloUIOriginalResolve', proof, native_inventory())['status'])

    def test_unknown_descriptions_and_native_description_as_source_remain_refused(self):
        proof = dts_descriptor('DTS Coherent Acoustics')
        self.assertIsNone(self.create(proof))
        for label in ('DTS-HD Master Audio', 'unrecognized codec'):
            raw = native_inventory()
            raw[1]['Format'] = label
            self.assertEqual('refused', self.call('SiloUIOriginalResolve', dts_descriptor(), raw)['status'])

    def test_missing_languages_and_ambiguous_ac3_still_refuse(self):
        for lane in (0, 1):
            proof = dts_descriptor()
            proof['sourceAudio'][lane]['language'] = ''
            self.assertIsNone(self.create(proof))
        raw = native_inventory()
        del raw[0]['Language']
        self.assertEqual('refused', self.call('SiloUIOriginalResolve', dts_descriptor(), raw)['status'])
        raw = native_inventory() + [dict(Track='second-ac3', Format='Dolby Digital', Language='eng')]
        self.assertEqual('refused', self.call('SiloUIOriginalResolve', dts_descriptor(), raw)['status'])
        proof = dts_descriptor()
        proof['sourceAudio'].append(dict(index=2, codec='ac3', language='en', channels=2))
        self.assertEqual('refused', self.call('SiloUIOriginalResolve', proof, native_inventory())['status'])

    def test_selected_ac3_requires_current_codec_handle_and_advancing_playback(self):
        state = self.create()
        self.assertIsNotNone(state)
        selected = self.event(state, 'inventory', inventory=native_inventory())
        self.assertEqual({'kind':'select', 'trackId':'opaque-ac3-handle'}, selected['command'])
        state = selected['state']
        for patch in (dict(nativeState='buffering'), dict(audioFormat='dts'),
                      dict(audioTrack='opaque-dts-handle'), {}):
            values = dict(nativeState='playing', positionMs=100, audioFormat='ac3', audioTrack='opaque-ac3-handle')
            values.update(patch)
            result = self.event(state, 'observation', **values)
            self.assertEqual('selected', result['state']['phase'])
            self.assertIsNone(result['command'])
        observed = self.event(state, 'observation', nativeState='playing', positionMs=100,
                              audioFormat='ac3', audioTrack='opaque-ac3-handle')['state']
        verified = self.event(observed, 'observation', nativeState='playing', positionMs=1100,
                              audioFormat='ac3', audioTrack='opaque-ac3-handle')
        self.assertEqual('verified_playing', verified['state']['phase'])


if __name__ == '__main__':
    unittest.main()
