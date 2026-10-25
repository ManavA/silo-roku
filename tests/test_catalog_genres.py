"""Scoped genre facets through the real adapter and library menu."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit
import test_silo_adapter as adapter_tests


class CatalogGenresTests(unittest.TestCase):
    setUpClass = classmethod(adapter_tests.SiloAdapterTests.setUpClass.__func__)
    tearDownClass = classmethod(adapter_tests.SiloAdapterTests.tearDownClass.__func__)
    call = adapter_tests.SiloAdapterTests.call
    request = adapter_tests.SiloAdapterTests.request

    def test_all_supported_scopes_and_bounds_fail_closed(self):
        for source in ('query','person','library_collection','user_collection','favorites','watchlist','history'):
            result=self.request('catalog_genres',dict(source=source,personId='1',libraryId='2',collectionId='3'))
            self.assertTrue(result['ok'],source)
            self.assertEqual([source],parse_qs(urlsplit(result['url']).query)['source'])
        for params in ({'source':'section','sectionId':'s'}, {'source':'unknown'}, {'source':'person'}, {'source':'library_collection','collectionId':'c'}, {'source':'query','sectionId':'s'}, {'source':'query','genre':'Drama'}):
            self.assertFalse(self.request('catalog_genres',params)['ok'])
        session=dict(adapter_tests.SESSION, accessToken='')
        self.assertFalse(self.request('catalog_genres',session=session)['ok'])
        for count,expected in ((1000,True),(1001,False)):
            result=self.call('DecodeSiloResponse','catalog_genres',json.dumps({'genres':['Genre '+str(i) for i in range(count)]}),{})
            self.assertEqual(expected,result['ok'])

    def test_genres_request_preserves_structural_scope_and_auth(self):
        params = dict(source='user_collection', scope='owned', libraryId='lib', collectionId='list', type='movie')
        result = self.request('catalog_genres', params)
        self.assertTrue(result['ok'])
        self.assertEqual('/api/v2/catalog/filters', urlsplit(result['url']).path)
        self.assertEqual(dict(source=['user_collection'], scope=['owned'], library_id=['lib'], collection_id=['list'], type=['movie'], skip_technical=['true']), parse_qs(urlsplit(result['url']).query))
        self.assertEqual('Bearer synthetic-access', result['headers']['Authorization'])
        self.assertEqual('p1', result['headers']['X-Profile-Id'])

    def test_genres_decode_preserves_custom_unicode_and_empty_is_valid(self):
        labels = ['Cinéma japonais', '自定义'] + ['Custom '+str(i) for i in range(25)]
        for genres in ([], labels):
            result = self.call('DecodeSiloResponse', 'catalog_genres', json.dumps({'genres': genres}), {})
            self.assertTrue(result['ok'])
            self.assertEqual(genres, result['data']['genres'])
        for wire in ({}, {'genres': None}, {'genres': ['Drama', {}]}, {'genres':['bad\nlabel']}, {'genres':['x'*101]}):
            self.assertFalse(self.call('DecodeSiloResponse','catalog_genres',json.dumps(wire),{})['ok'])

class GenreMenuTests(unittest.TestCase):
    def run_menu(self, body):
        import tempfile
        from pathlib import Path
        from tools.brightscript import run_brightscript
        from test_silo_adapter import ROOT
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory)/'helpers.brs'
            helper.write_text('''
function TextOr(value as Dynamic) as String
 if type(value)="String" then return value
 return ""
end function
function NumberOr(value as Dynamic, fallback as Dynamic) as Dynamic
 if value=invalid then return fallback
 return value
end function
function BrowseCaptureContext() as Object
 return {visit:m.libraryToken,source:m.sourceId}
end function
function BrowseContextCurrent(value as Dynamic) as Boolean
 return value.visit=m.libraryToken and value.source=m.sourceId
end function
function DetailPhotoSessionRevision() as Integer
 return m.revision
end function
sub BrowseDialog(title as String, labels as Object, handler as String)
 m.browseDialogSequence=NumberOr(m.browseDialogSequence,0)+1
 node={wasClosed:false,close:false,buttonSelected:0,isSameNode:function(other as Dynamic) as Boolean
 return m.id=other.id
 end function,id:m.browseDialogSequence}
 m.browseDialog=node:m.top.dialog=node
 m.browseDialogTicket={used:false,node:node}
end sub
sub BrowsePagedChoices(title as String, labels as Object, handler as String, start=0 as Integer)
 m.title=title:m.labels=labels
 m.top.dialog=invalid
end sub
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.requests.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
''')
            source=(ROOT/'components/SiloUILibrary.brs').read_text()
            import re
            source=re.sub(r'sub Browse(?:Dialog|PagedChoices)\(.*?end sub', '', source, flags=re.S)
            source=re.sub(r'function LibraryGenreNow\(\).*?end function', 'function LibraryGenreNow() as Integer\n return m.now\nend function', source, flags=re.S)
            library=Path(directory)/'library.brs';library.write_text(source)
            out=run_brightscript([library,helper], '''
m.provider="silo":m.sourceId="server":m.profileId="p":m.generation=1:m.revision=2:m.now=100
m.libraryType="movie":m.libraryId="lib":m.libraryCollection="":m.libraryPerson="":m.librarySource="query"
m.libraryToken=4:m.top={}:m.requests=[]
'''+body,root=Path(directory))
            return json.loads(out.splitlines()[-1])

    def test_lazy_genres_show_custom_labels_and_reuse_scope_cache(self):
        result=self.run_menu('''
LibraryGenresOpen()
r=m.requests[0]
LibraryResult("lib_genres",{ok:true},{genres:["自定义","Cinema"]},r.extra)
first=m.labels
LibraryGenresOpen()
print FormatJson({request:r,labels:first,requests:m.requests.Count(),cache:m.libraryGenreCache.Count()})
''')
        self.assertEqual(['All genres','自定义','Cinema'],result['labels'])
        self.assertEqual('catalog_genres',result['request']['action'])
        self.assertEqual(dict(source='query',libraryId='lib',collectionId='',personId='',type='movie'),result['request']['params'])
        self.assertEqual(1,result['requests'])
        self.assertEqual(1,result['cache'])

    def test_stale_results_neither_open_menu_nor_populate_cache(self):
        for change in ('m.top.dialog=invalid','m.browseDialog.wasClosed=true','m.revision=3','m.sourceId="other"','m.profileId="other"','m.generation=2','m.libraryToken=5','m.libraryId="other"','BrowseDialog("Other",[],"other")','m.libraryGenrePending=invalid'):
            with self.subTest(change=change):
                result=self.run_menu('''
LibraryGenresOpen():r=m.requests[0]
'''+change+'''
LibraryResult("lib_genres",{ok:true},{genres:["Stale"]},r.extra)
print FormatJson({cache:m.libraryGenreCache.Count(),shown:m.labels<>invalid})
''')
                self.assertEqual(dict(cache=0,shown=False),result)

    def test_cache_expires_and_keeps_at_most_four_scopes(self):
        result=self.run_menu('''
for i=1 to 6
 m.libraryId=i.ToStr():LibraryGenresOpen():r=m.requests.Peek()
 LibraryResult("lib_genres",{ok:true},{genres:[]},r.extra)
end for
size=m.libraryGenreCache.Count():m.now=400
LibraryGenresOpen()
print FormatJson({size:size,cache:m.libraryGenreCache.Count(),requests:m.requests.Count(),labels:m.labels})
''')
        self.assertEqual(4,result['size'])
        self.assertEqual(0,result['cache'])
        self.assertEqual(7,result['requests'])
        self.assertEqual(['All genres'],result['labels'])

    def test_error_uses_explicit_standard_fallback_without_cache(self):
        result=self.run_menu('''
LibraryGenresOpen():r=m.requests[0]
LibraryResult("lib_genres",{ok:false},{},r.extra)
print FormatJson({title:m.title,labels:m.labels,cache:m.libraryGenreCache.Count(),requests:m.requests.Count()})
''')
        self.assertIn('unavailable',result['title'])
        self.assertIn('Science Fiction',result['labels'])
        self.assertEqual(0,result['cache'])
        self.assertEqual(1,result['requests'])

    def test_custom_genre_selection_keeps_exact_label_and_all_clears(self):
        import re
        import tempfile
        from pathlib import Path
        from tools.brightscript import run_brightscript
        from test_silo_adapter import ROOT
        source = (ROOT/'components/SiloUILibrary.brs').read_text()
        choice = re.search(r'sub onLibraryChoice\(.*?end sub',source,re.S)[0]
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'choice.brs'
            file.write_text(choice+'''
function BrowseChoiceIndex(event as Object) as Integer
 return m.selection
end function
sub LibraryQuery(reset as Boolean)
 m.queries=m.queries+1
end sub
''')
            out=run_brightscript(file,'''
m.browseChoiceKind="genre":m.browseChoices=["All genres","自定义"]:m.queries=0:m.selection=1
onLibraryChoice(invalid):selected=m.libraryGenre
m.selection=0:onLibraryChoice(invalid)
print FormatJson({selected:selected,cleared:m.libraryGenre,queries:m.queries})
''',root=Path(directory))
        self.assertEqual(dict(selected='自定义',cleared='',queries=2),json.loads(out.splitlines()[-1]))
