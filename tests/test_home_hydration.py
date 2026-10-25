import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class HomeHydrationTests(unittest.TestCase):
    def test_queue_preserves_order_bounds_and_ignores_stale_or_duplicate_results(self):
        with tempfile.TemporaryDirectory() as d:
            output=run_brightscript([ROOT/'source/core/SiloUIHomePolicy.brs'], '''
                rows=[{rowId:"a",items:[],totalCount:2},{rowId:"inline",items:[{itemId:"x"}]},{rowId:"b",items:[],totalCount:1}]
                s=SiloUIHomeHydration(rows,"owner")
                a=SiloUIHomeHydrationNext(s)
                blocked=SiloUIHomeHydrationNext(s)
                SiloUIHomeHydrationComplete(s,"stale",a,{ok:true},{items:[{itemId:"bad"}]})
                stale=s.rows[0].items.Count()
                SiloUIHomeHydrationComplete(s,"owner",a,{ok:false},{})
                b=SiloUIHomeHydrationNext(s)
                SiloUIHomeHydrationComplete(s,"owner",a,{ok:true},{items:[{itemId:"duplicate"}]})
                SiloUIHomeHydrationComplete(s,"owner",b,{ok:true},{items:[{itemId:"good"}]})
                print FormatJson({a:a,b:b,blocked:blocked,stale:stale,errors:s.errors,rows:s.rows,done:SiloUIHomeHydrationNext(s)})
            ''', root=Path(d))
        import json
        r=json.loads(output)
        self.assertEqual((r['a'],r['b'],r['blocked'],r['stale'],r['errors'],r['done']),(0,2,-1,0,1,-1))
        self.assertEqual([x['rowId'] for x in r['rows']],['a','inline','b'])
        self.assertEqual(r['rows'][2]['items'],[{'itemId':'good'}])

    def test_hydration_caps_rows_and_cards(self):
        from tools.brightscript import run_function
        rows=[{'rowId':str(i),'items':[{'itemId':str(n)} for n in range(55)],'totalCount':55} for i in range(30)]
        with tempfile.TemporaryDirectory() as d:
            state=run_function(ROOT/'source/core/SiloUIHomePolicy.brs','SiloUIHomeHydration',[rows,'owner'],root=Path(d))
        self.assertEqual(len(state['rows']),24)
        self.assertEqual(len(state['rows'][0]['items']),40)
        self.assertEqual(state['queue'],[])

    def test_shipping_home_requests_section_and_retains_inline_rows_on_error(self):
        import re,json
        source=(ROOT/'components/SiloUIHome.brs').read_text()
        source=re.sub(r'sub HomeCacheStart\(.*?\nend sub','sub HomeCacheStart(action as String)\nend sub',source,count=1,flags=re.S)
        source=re.sub(r'sub HomeSetRows\(.*?\nend sub','sub HomeSetRows(rows as Object)\n m.rendered=rows\n m.homeRows=rows\nend sub',source,count=1,flags=re.S)
        source=re.sub(r'sub HomeShowRetry\(.*?\nend sub','sub HomeShowRetry()\n m.retried=true\nend sub',source,count=1,flags=re.S)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'home.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
function TextOr(v as Dynamic) as String
 if v=invalid then return ""
 return v
end function
function NumberOr(v as Dynamic, fallback as Dynamic) as Dynamic
 if v=invalid then return fallback
 return v
end function
sub Api(action as String, params as Object, purpose as String, extra as Object)
 m.sent={action:action,params:params,purpose:purpose,extra:extra}
end sub
''')
            output=run_brightscript([ROOT/'source/core/SiloUIHomePolicy.brs',p,stub],'''
                m.view="home":m.generation=1:m.provider="silo":m.sourceId="silo:test":m.profileId="p":m.homeToken=2
                HomeResult("home_silo",{ok:true},{rows:[{rowId:"missing",items:[],totalCount:1},{rowId:"inline",items:[{itemId:"x"}]}]},{token:2,scope:HomeProgressScope()})
                immediate=""
                if type(m.rendered) = "roArray" then immediate=m.rendered[0].rowId
                sent=m.sent
                m.profileId="other"
                HomeResult(sent.purpose,{ok:false},{},sent.extra)
                fenced=m.homeHydration.active
                m.profileId="p"
                HomeResult(sent.purpose,{ok:false},{},sent.extra)
                print FormatJson({sent:sent,fenced:fenced,rendered:m.rendered,immediate:immediate,retried:m.retried})
            ''',root=Path(d))
        r=json.loads(output)
        self.assertEqual(r['immediate'],'inline')
        self.assertEqual(r['sent']['action'],'home_section_items')
        self.assertEqual(r['fenced'],0)
        self.assertEqual(r['rendered'][0]['rowId'],'inline')
        self.assertTrue(r['retried'])
