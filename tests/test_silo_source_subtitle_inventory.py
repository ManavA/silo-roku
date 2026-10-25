"""Authoritative source subtitle choices at the approved pure policy seam."""
import copy
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
from tests.test_silo_playback_policy import plan, SCOPE

POLICY = Path(__file__).resolve().parents[1] / 'source/core/SiloPlaybackPolicy.brs'


def row(index=0, **changes):
    value = dict(track_id=f'file:f1:subtitle:{index}', combined_index=index,
                 source='external', codec='subrip', language='eng', label='English',
                 forced=False, default=False, hearing_impaired=False, delivery='sidecar')
    value.update(changes)
    return value


def raw(entries=None):
    return dict(plan_id='plan-0001', plan_attempt_key='plan-key-0001',
                session_id='session-0001', effective_media_file_id='f1',
                subtitle={'mode': 'off', 'inventory': [row()] if entries is None else entries})


class SiloSourceSubtitleInventoryTests(unittest.TestCase):
    def call(self, name, *args, bridge=''):
        with tempfile.TemporaryDirectory() as directory:
            files = [POLICY]
            if bridge:
                extra = Path(directory) / 'bridge.brs'
                extra.write_text(bridge)
                files.append(extra)
            return run_function(files, name, list(args), root=Path(directory))

    def project(self, value, current=None, scope=None):
        return self.call('SiloSourceSubtitleInventory', value, current or plan(), scope or SCOPE)

    def test_off_preserves_complete_mixed_inventory_and_only_public_metadata(self):
        entries = [row(url='https://private.example/token', sync_key='private'),
                   row(1, source='embedded', codec='dvd_subtitle', delivery='burn_in_only', default=True),
                   row(2, source='embedded', codec='ass', font_bundle_url='private'),
                   row(3, source='downloaded', language='spa', label='Spanish')]
        result = self.project(raw(entries))
        self.assertEqual(dict(sourceId='silo:synthetic', profileId='owner', generation=7,
                              sessionRevision=0, sessionId='session-0001', fileId='f1',
                              planId='plan-0001', planAttemptId='plan-attempt-0001',
                              planAttemptKey='plan-key-0001', playbackAttemptId='playback-attempt-0001',
                              attemptCount=0),
                         result['owner'])
        self.assertEqual([0, 1, 2, 3], [item['combinedIndex'] for item in result['entries']])
        self.assertEqual(dict(trackId='file:f1:subtitle:1', combinedIndex=1, source='embedded',
                              codec='dvd_subtitle', language='eng', label='English', forced=False,
                              default=True, hearingImpaired=False, delivery='burn_in_only'), result['entries'][1])
        self.assertEqual({'trackId','combinedIndex','source','codec','language','label','forced',
                          'default','hearingImpaired','delivery'}, set(result['entries'][0]))
        self.assertNotIn('private', str(result))

    def test_selection_resolves_only_exact_owned_canonical_pair(self):
        current = plan()
        current['sourceSubtitleInventory'] = self.project(raw([row(), row(1, source='downloaded')]))
        self.assertEqual({'id': 'file:f1:subtitle:1', 'index': 1},
                         self.call('SiloUserSubtitleSelection', current, SCOPE, 'file:f1:subtitle:1', 1))
        for track, index in [('file:f1:subtitle:1', 0), ('file:f2:subtitle:1', 1),
                             ('native-handle', 1), ('file:f1:subtitle:01', 1),
                             ('file:f1:subtitle:1', True), ('file:f1:subtitle:1', 1.5)]:
            with self.subTest(track=track, index=index):
                self.assertIsNone(self.call('SiloUserSubtitleSelection', current, SCOPE, track, index))

    def test_returning_to_same_plan_ids_cannot_reuse_earlier_inventory(self):
        initial = plan()
        initial['sourceSubtitleInventory'] = self.project(raw(), initial)
        returned = copy.deepcopy(initial)
        # A -> B -> A can restore deterministic server IDs while advancing the
        # accepted client mutation count. Ordinals from initial A are obsolete.
        returned['siloPlayback']['attemptCount'] = 2
        self.assertIsNone(self.call('SiloUserSubtitleSelection', returned, SCOPE,
                                    'file:f1:subtitle:0', 0))
        returned['sourceSubtitleInventory'] = self.project(raw([row(label='Fresh A')]), returned)
        self.assertEqual(2, returned['sourceSubtitleInventory']['owner']['attemptCount'])
        self.assertEqual({'id': 'file:f1:subtitle:0', 'index': 0},
                         self.call('SiloUserSubtitleSelection', returned, SCOPE,
                                   'file:f1:subtitle:0', 0))

    def test_inventory_attempt_count_must_be_present_exact_and_numeric(self):
        current = plan()
        current['siloPlayback']['attemptCount'] = 2
        current['sourceSubtitleInventory'] = self.project(raw(), current)
        cases = []
        for count in (0, 1, 3, True, False, '2', None, 2.5, -1, 9):
            changed = copy.deepcopy(current)
            changed['sourceSubtitleInventory']['owner']['attemptCount'] = count
            cases.append(changed)
        changed = copy.deepcopy(current)
        del changed['sourceSubtitleInventory']['owner']['attemptCount']
        cases.append(changed)
        # Boolean/integer comparison must not authorize attempt 0 or 1.
        for count, boolean in ((0, False), (1, True)):
            changed = copy.deepcopy(current)
            changed['siloPlayback']['attemptCount'] = count
            changed['sourceSubtitleInventory']['owner']['attemptCount'] = boolean
            cases.append(changed)
        bridge = """function SelectBadAttemptCounts(values as Object,scope as Object) as Object
 output=[]
 for each value in values
  output.Push(SiloUserSubtitleSelection(value,scope,"file:f1:subtitle:0",0))
 end for
 return output
end function"""
        self.assertEqual([None]*len(cases), self.call('SelectBadAttemptCounts', cases, SCOPE, bridge=bridge))

    def test_missing_malformed_unowned_and_unbounded_inventory_is_unavailable(self):
        cases = [None, {}]
        for inventory in (None, {}, 'tracks', [None], [row(1)], [row(), row(0)],
                          [row(i) for i in range(129)]):
            value = raw(); value['subtitle']['inventory'] = inventory; cases.append(value)
        for field, value in [('effective_media_file_id', 'f2'), ('effective_media_file_id', 1),
                             ('plan_id', 'stale'), ('plan_attempt_key', 'stale'),
                             ('session_id', 'foreign'), ('session_id', None)]:
            value_raw = raw(); value_raw[field] = value; cases.append(value_raw)
        for field in ('effective_media_file_id', 'plan_id', 'plan_attempt_key'):
            value = raw(); del value[field]; cases.append(value)
        for patch in ({'combined_index': True}, {'combined_index': 0.5}, {'combined_index': -1},
                      {'track_id': 'file:f2:subtitle:0'}, {'track_id': 'file:f1:subtitle:00'},
                      {'source': 'catalog'}, {'delivery': 'native'}, {'forced': 1},
                      {'default': 'false'}, {'hearing_impaired': None}, {'codec': 'x'*33},
                      {'language': 'x'*17}, {'label': 'x'*121}, {'label': 'bad\nlabel'},
                      {'codec': None}):
            cases.append(raw([row(**patch)]))
        for field in ('forced', 'default', 'hearing_impaired', 'delivery', 'source'):
            value = raw(); del value['subtitle']['inventory'][0][field]; cases.append(value)
        bridge = """function ProjectBadInventories(values as Object,plan as Object,scope as Object) as Object
 output=[]
 for each value in values
  output.Push(SiloSourceSubtitleInventory(value,plan,scope))
 end for
 return output
end function"""
        self.assertEqual([None]*len(cases), self.call('ProjectBadInventories', cases, plan(), SCOPE, bridge=bridge))

    def test_zero_and_128_entries_are_valid_and_wire_text_is_optional(self):
        self.assertEqual([], self.project(raw([]))['entries'])
        result = self.project(raw([row(i) for i in range(128)]))
        self.assertEqual('file:f1:subtitle:127', result['entries'][127]['trackId'])
        entry = row()
        for key in ('codec', 'language', 'label'):
            del entry[key]
        result = self.project(raw([entry]))
        self.assertEqual(('', '', ''), tuple(result['entries'][0][key] for key in ('codec','language','label')))
        current = plan(); current['sourceSubtitleInventory'] = self.project(raw([]))
        self.assertIsNone(self.call('SiloUserSubtitleSelection', current, SCOPE, 'file:f1:subtitle:0', 0))
        value = raw(); del value['session_id']
        self.assertIsNotNone(self.project(value))

    def test_selection_rejects_all_owner_changes_and_hidden_or_malformed_rows(self):
        current = plan(); current['sourceSubtitleInventory'] = self.project(raw([row(), row(1)]))
        cases = [plan()]
        for key in current['sourceSubtitleInventory']['owner']:
            changed = copy.deepcopy(current)
            value = changed['sourceSubtitleInventory']['owner'][key]
            changed['sourceSubtitleInventory']['owner'][key] = value+1 if isinstance(value, int) else value+'-other'
            cases.append(changed)
        for key, value in [('generation', True), ('sessionRevision', False), ('url', 'secret')]:
            changed = copy.deepcopy(current); changed['sourceSubtitleInventory']['owner'][key] = value; cases.append(changed)
        for patch in ({'url':'secret'}, {'fontBundleUrl':'secret'}, {'syncKey':'secret'},
                      {'combinedIndex': 0}, {'trackId':'file:f2:subtitle:1'},
                      {'forced':1}, {'language':'x'*17}, {'codec':None}, {'default':None}):
            changed = copy.deepcopy(current); changed['sourceSubtitleInventory']['entries'][1].update(patch); cases.append(changed)
        changed = copy.deepcopy(current); del changed['sourceSubtitleInventory']['entries'][1]['label']; cases.append(changed)
        changed = copy.deepcopy(current); changed['sourceSubtitleInventory']['url'] = 'secret'; cases.append(changed)
        changed = copy.deepcopy(current); changed['siloPlayback']['planAttemptId'] = 'new-attempt-0001'; cases.append(changed)
        changed = copy.deepcopy(current); changed['siloPlayback']['sessionRevision'] = 1; cases.append(changed)
        bridge = """function SelectBadInventories(values as Object,scope as Object) as Object
 output=[]
 for each value in values
  output.Push(SiloUserSubtitleSelection(value,scope,"file:f1:subtitle:0",0))
 end for
 return output
end function"""
        self.assertEqual([None]*len(cases), self.call('SelectBadInventories', cases, SCOPE, bridge=bridge))
        self.assertIsNone(self.call('SiloUserSubtitleSelection', current, {**SCOPE,'generation':8}, 'file:f1:subtitle:0', 0))

    def test_inventory_copies_metadata_and_excludes_unknown_wire_properties(self):
        bridge = """function MutateSourceInventory(raw as Object,plan as Object,scope as Object) as Object
 projected=SiloSourceSubtitleInventory(raw,plan,scope)
 raw.subtitle.inventory[0].label="changed"
 raw.plan_id="changed"
 return projected
end function"""
        result = self.call('MutateSourceInventory', raw([row(secret={'url':'private'}, font_bundle_url='private')]), plan(), SCOPE, bridge=bridge)
        self.assertEqual('English', result['entries'][0]['label'])
        self.assertEqual('plan-0001', result['owner']['planId'])
        self.assertNotIn('private', str(result))

    def test_ambiguous_wire_field_casing_cannot_authorize_a_choice(self):
        for key, value in [('Combined_Index', 1), ('Track_ID', 'file:f2:subtitle:0'),
                           ('Forced', True)]:
            with self.subTest(key=key):
                self.assertIsNone(self.project(raw([row(**{key:value})])))
        value = raw(); del value['session_id']; value['Session_ID'] = 'foreign'
        self.assertIsNone(self.project(value))


if __name__ == '__main__':
    unittest.main()
