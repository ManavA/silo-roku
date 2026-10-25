import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUIFormat.brs'

class SiloUIFormatTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.exists(), 'Formatting policy missing')
        with tempfile.TemporaryDirectory() as root:
            return run_function([POLICY], name, list(args), root=Path(root))

    def test_duration_boundaries_and_malformed_values(self):
        for value, expected in [(None,''),('60000',''),(-1,''),(59999,''),(60000,'1m'),(3600000,'1h'),(5460000,'1h 31m')]:
            self.assertEqual(self.call('FormatDuration',value), expected)

    def test_metadata_movie_series_and_episode(self):
        self.assertEqual(self.call('MetaLine',dict(year=2024,durationMs=5400000,contentRating='PG',type='movie')),'2024  ·  1h 30m  ·  PG  ·  Movie')
        self.assertEqual(self.call('MetaLine',dict(type='show')),'Series')
        self.assertEqual(self.call('MetaLine',dict(type='episode',seasonNumber=2,episodeNumber=3)),'S2 E3')
        self.assertEqual(self.call('MetaLine',dict(year='bad',durationMs=[],contentRating=4)), '')

    def test_quality_and_resolution_aliases(self):
        self.assertEqual(self.call('QualityLine',dict(badges=dict(resolution='2160p',hdr='HDR10',audio='EAC3',audio_channels='5.1'))),'4K  ·  HDR10  ·  EAC3  ·  5.1')
        self.assertEqual(self.call('QualityLine',dict(badges='bad')),'')
        for value, expected in [('2160p','4K'),('4k','4K'),('uhd','4K'),('1080p','1080P'),(None,''),(7,'')]:
            self.assertEqual(self.call('ResolutionLabel',value),expected)

    def test_ratings_skip_non_numbers(self):
        self.assertEqual(self.call('RatingsLine',dict(badges=dict(imdb=8.29,rtCritic=90,rtAudience=85))),'IMDb 8.2  ·  Rotten Tomatoes 90%  ·  Audience 85%')
        self.assertEqual(self.call('RatingsLine',dict(badges=dict(imdb='bad',rtCritic={},rtAudience=True))),'')
        self.assertEqual(self.call('RatingsLine',{}),'')

    def test_item_mapping_preserves_progress_and_normalizes_missing_plex_badges(self):
        item=dict(type='movie',title='Film',durationMs=120000,resumeMs=60000,watched=True)
        result=self.call('SiloUIItemFields',item,dict(poster='/poster'),False,'https://example.test')
        self.assertEqual(result,dict(title='Film',HDPosterUrl='https://example.test/poster',artCandidates=['https://example.test/poster'],item=item,landscape=False,badges={},durationMs=120000,resumeMs=60000,watched=True))
        result=self.call('SiloUIItemFields',dict(title=7,badges=[],durationMs='bad',resumeMs={},watched='true'),{},False)
        self.assertEqual([result[k] for k in ('title','badges','durationMs','resumeMs','watched')],['',{},0,0,False])

    def test_episode_art_and_titles_follow_card_orientation(self):
        item=dict(type='episode',title='Pilot',seriesTitle='Show',episodeNumber=3)
        portrait=self.call('SiloUIItemFields',item,dict(still='still'),False)
        self.assertEqual((portrait['title'],portrait['HDPosterUrl']),('Show','still'))
        for art, expected in [(dict(still='still',backdrop='back',poster='post'),'still'),(dict(backdrop='back',poster='post'),'back'),(dict(poster='post'),'post'),(None,'')]:
            result=self.call('SiloUIItemFields',item,art,True)
            self.assertEqual((result['title'],result['HDPosterUrl']),('3. Pilot',expected))
