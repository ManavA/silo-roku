"""The observed Dolby Digital Plus label maps native inventory, not source IDs."""
import unittest

from tools.brightscript import run_function
from tests.test_silo_ui_original_playback import POLICY, descriptor


def eac3_descriptor():
    proof = descriptor()
    proof['audioIdentity'].update(index=0, id='source-eac3', codec='eac3')
    proof['sourceAudio'] = [dict(index=0, codec='eac3', language='en', channels=6)]
    return proof


def native_inventory():
    # The actual Roku inventory omitted Channels; a unique source lane suffices.
    return [dict(Track='native-eac3-handle', Format='Dolby Digital Plus', Language='en')]


class SiloUIOriginalEac3Inventory(unittest.TestCase):
    def call(self, name, *args):
        return run_function(POLICY, name, list(args))

    def create(self, proof=None):
        return self.call('SiloUIOriginalCreate', eac3_descriptor() if proof is None else proof, 7, 3, 0)

    def event(self, state, kind, **values):
        return self.call('SiloUIOriginalReduce', state,
                         dict(kind=kind, token=7, generation=3, nowMs=1000, **values))

    def test_exact_native_label_resolves_unique_source_eac3_without_channels(self):
        result = self.event(self.create(), 'inventory', inventory=native_inventory())
        self.assertEqual({'kind':'select', 'trackId':'native-eac3-handle'}, result['command'])
        self.assertEqual('selected', result['state']['phase'])

    def test_native_label_is_not_a_source_alias_and_similar_labels_remain_unknown(self):
        proof = eac3_descriptor()
        proof['audioIdentity']['codec'] = 'Dolby Digital Plus'
        proof['sourceAudio'][0]['codec'] = 'Dolby Digital Plus'
        self.assertIsNone(self.create(proof))
        for label in ('Dolby Digital Plus Atmos', 'Dolby Digital+', 'Dolby Digital Plus unknown'):
            with self.subTest(label=label):
                raw = native_inventory(); raw[0]['Format'] = label
                self.assertEqual('refused', self.call('SiloUIOriginalResolve', eac3_descriptor(), raw)['status'])

    def test_ambiguous_eac3_or_missing_language_remain_refused(self):
        raw = native_inventory() + [dict(Track='other-eac3', Format='Dolby Digital Plus', Language='en')]
        self.assertEqual('refused', self.call('SiloUIOriginalResolve', eac3_descriptor(), raw)['status'])
        proof = eac3_descriptor()
        proof['sourceAudio'].append(dict(index=1, codec='eac3', language='en', channels=2))
        self.assertEqual('refused', self.call('SiloUIOriginalResolve', proof, native_inventory())['status'])
        for language in (None, '', 'unrecognized'):
            raw = native_inventory()
            if language is None:
                del raw[0]['Language']
            else:
                raw[0]['Language'] = language
            self.assertEqual('refused', self.call('SiloUIOriginalResolve', eac3_descriptor(), raw)['status'])

    def test_eac3_needs_current_handle_codec_and_advancing_playing_readback(self):
        result = self.event(self.create(), 'inventory', inventory=native_inventory())
        self.assertEqual('select', result['command']['kind'])
        state = result['state']
        for patch in (dict(nativeState='buffering'), dict(audioFormat='ac3'),
                      dict(audioTrack='stale-handle')):
            values = dict(nativeState='playing', positionMs=100, audioFormat='eac3', audioTrack='native-eac3-handle')
            values.update(patch)
            observed = self.event(state, 'observation', **values)
            self.assertEqual('selected', observed['state']['phase'])
        for position in (100, 100):
            state = self.event(state, 'observation', nativeState='playing', positionMs=position,
                               audioFormat='eac3', audioTrack='native-eac3-handle')['state']
            self.assertEqual('selected', state['phase'])
        state = self.event(state, 'observation', nativeState='playing', positionMs=1100,
                           audioFormat='eac3', audioTrack='native-eac3-handle')['state']
        self.assertEqual('verified_playing', state['phase'])


if __name__ == '__main__':
    unittest.main()
