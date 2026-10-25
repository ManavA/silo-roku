import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function, run_brightscript
import json
import re
ROOT=Path(__file__).resolve().parents[1]
class RatingChipsTests(unittest.TestCase):
    def call(self,item):
        with tempfile.TemporaryDirectory() as d:
            return run_function([ROOT/'source/core/SiloUIRatingPolicy.brs'],'SiloUIRatingChips',[item],root=Path(d))
    def test_canonical_order_scale_and_empty_authority(self):
        self.assertEqual(self.call({'ratings':[], 'badges':{'imdb':8.2}}),[])
        chips=self.call({'ratings':[{'source':'rt_audience','name':'Popcornmeter','score':92,'display':'92%'},{'source':'imdb','name':'IMDb','score':82,'display':'8.2'},{'source':'plugin','name':'Other','score':75,'display':'3/4'}]})
        self.assertEqual([c['text'] for c in chips],['92%','8.2/10','Other 3/4'])
        self.assertEqual([c['source'] for c in chips],['rt_audience','imdb','plugin'])
    def test_native_formatted_precision_survives(self):
        self.assertEqual(self.call({'ratings':[{'source':'imdb','score':82.5,'name':'IMDb','display':'8.25'}]})[0]['text'],'8.25/10')
    def test_bounds_aliases_and_overflow(self):
        self.assertEqual(self.call({'badges':{'imdb':11,'rtCritic':101,'rtAudience':-1}}),[])
        self.assertEqual(self.call({'badges':{'imdb':'8','rtCritic':True,'rtAudience':{}}}),[])
        chips=self.call({'badges':{'imdb':10,'rtCritic':0,'rtAudience':60}})
        self.assertEqual([c['text'] for c in chips],['10/10','0%','60%'])
        self.assertEqual([c['asset'] for c in chips],['imdb','rt-rotten','rt-audience-fresh'])
        ratings=[{'source':'x','name':'Unknown','score':1,'display':'1%'}]*9
        self.assertEqual(self.call({'ratings':ratings})[-1]['text'],'+4 more')
    def test_adapter_preserves_authoritative_array_and_validates_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            result=run_function([ROOT/'source/adapters/SiloAdapter.brs'],'SiloItem',[{'content_id':'x','title':'X','type':'movie','ratings':[], 'rating_imdb':12,'rating_rt_critic':101}],root=Path(d))
        self.assertEqual(result['item']['ratings'],[])
        self.assertEqual(result['item']['badges'],{})

    def test_shipping_render_thread_needs_no_filesystem_and_failed_logos_keep_captions(self):
        files=[ROOT/'source/core/SiloUIRatingPolicy.brs',ROOT/'components/SiloUIRatings.brs',ROOT/'components/SiloUIHome.brs',ROOT/'components/SiloUIDetail.brs',ROOT/'source/core/SiloUIDetailPolicy.brs',ROOT/'source/core/SiloUIFormat.brs']
        with tempfile.TemporaryDirectory() as d:
            stub=Path(d)/'nodes.brs';stub.write_text('''function SiloUIFont(size,bold) as Object
 return {}
end function
function RatingGroup() as Object
 return {children:[],getChildren:function(a,b)
 return m.children
 end function,removeChildren:sub(children)
 m.children=[]
 end sub,createChild:function(kind)
 c={kind:kind,loadStatus:"failed",hasField:function(name)
 return m.DoesExist(name)
 end function,addFields:sub(fields)
 m.Append(fields)
 end sub,observeField:sub(field,callback)
 end sub,unobserveField:sub(field)
 end sub}:m.children.Push(c):return c
 end function}
end function
''')
            detail=Path(d)/'detail.brs'
            detail.write_text(re.sub(r'sub DetailLayout\(\).*?\nend sub','sub DetailLayout()\nend sub',files[3].read_text(),count=1,flags=re.S))
            detail.write_text(re.sub(r'sub DetailCompactRender\(\).*?\nend sub','sub DetailCompactRender()\nend sub',detail.read_text(),count=1,flags=re.S))
            files[3]=detail
            renderer=Path(d)/'renderer.brs'
            renderer.write_text(files[1].read_text().replace('CreateObject(', 'RenderThreadObject('))
            files[1]=renderer
            stub.write_text(stub.read_text()+'''
function RenderThreadObject(kind as String) as Dynamic
 m.filesystemCalls=NumberOr(m.filesystemCalls,0)+1
 return invalid
end function
''')
            stub.write_text(stub.read_text()+'''
function ItemArt(item)
 return {}
end function
function ArtField(art,key)
 return ""
end function
sub BuildButtons(group,zone,labels)
end sub
sub PaintButtons(zone,focused)
end sub
sub SetBackdrop(uri)
end sub
''')
            out=run_brightscript(files+[stub],'''
                m.filesystemCalls=0
                m.heroChips=RatingGroup()
                HomeRatingChips({badges:{imdb:8.2,rtCritic:90,rtAudience:91}})
                home=m.heroChips.children
                m.assetsAvailable=true
                HomeRatingChips({badges:{imdb:8.2,rtCritic:90,rtAudience:20}})
                logos=m.heroChips.children
                m.detailRatings=RatingGroup():m.detailTitle={}:m.detailLogo={uri:""}
                m.detailSub={}:m.detailMeta={}:m.detailQuality={}:m.detailSummary={}
                m.detailButtons={}:m.backdrop={}:m.backdropOld={}:m.provider="silo":m.zone=""
                DetailRender({itemId:"x",type:"movie",ratings:[{source:"custom",name:"Custom",score:80,display:"4/5"}]})
                for each nodes in [home,logos,m.detailRatings.children]
                    for each node in nodes
                        for each key in ["hasField","addFields","observeField","unobserveField"]
                            node.Delete(key)
                        end for
                    end for
                end for
                print FormatJson({filesystemCalls:m.filesystemCalls,home:home,logos:logos,height:m.detailRatingsHeight,detail:m.detailRatings.children})
            ''',root=Path(d))
        result=json.loads(out)
        self.assertEqual(result['filesystemCalls'],0)
        self.assertTrue(all(n['loadStatus']=='failed' for n in result['logos']))
        self.assertEqual([n['text'] for n in result['home'] if n['kind']=='Label'],['IMDb 8.2/10','RT Critics 90%','RT Audience 91%'])
        self.assertEqual([n['uri'] for n in result['logos'] if n['kind']=='Poster' and '/ratings/' in n['uri']],['pkg:/images/ratings/imdb.png','pkg:/images/ratings/rt-fresh.png','pkg:/images/ratings/rt-audience-rotten.png'])
        self.assertEqual([n['text'] for n in result['logos'] if n['kind']=='Label'],['IMDb 8.2/10','RT Critics 90%','RT Audience 20%'])
        self.assertLess(result['logos'][0]['width'],220)
        self.assertEqual(result['height'],28)
        self.assertEqual(result['detail'][-1]['text'],'Custom 4/5')
        self.assertIn('RenderRatingChips(m.detailRatings, item)',(ROOT/'components/SiloUIDetail.brs').read_text())
        import xml.etree.ElementTree as ET
        xml=ET.parse(ROOT/'components/SiloUIScene.xml')
        self.assertEqual(xml.find('.//*[@id="detailRatings"]').tag,'Group')
        for script in ['SiloUIRatings.brs','SiloUIRatingPolicy.brs']:
            self.assertTrue(any(n.attrib.get('uri','').endswith(script) for n in xml.findall('script')))

    def test_delayed_logo_failure_and_rebuild_keep_live_captions_and_release_observers(self):
        with tempfile.TemporaryDirectory() as d:
            stub=Path(d)/'nodes.brs'
            stub.write_text('''function SiloUIFont(size,bold)
 return {}
end function
function RatingNode(kind)
 return {kind:kind,loadStatus:"loading",observed:false,hasField:function(name)
 return m.DoesExist(name)
 end function,addFields:sub(fields)
 m.Append(fields)
 end sub,observeField:sub(field,callback)
 m.observed=true
 end sub,unobserveField:sub(field)
 m.observed=false
 end sub}
end function
function RatingGroup()
 return {children:[],getChildren:function(a,b)
 return m.children
 end function,removeChildren:sub(children)
 m.children=[]
 end sub,createChild:function(kind)
 c=RatingNode(kind):m.children.Push(c):return c
 end function}
end function
sub LogoEvent(node,status)
 node.loadStatus=status
 onRatingLogoStatus({node:node,getRoSGNode:function()
 return m.node
 end function})
end sub
''')
            out=run_brightscript([ROOT/'source/core/SiloUIRatingPolicy.brs',ROOT/'components/SiloUIRatings.brs',stub],'''
                group=RatingGroup()
                height=RenderRatingChips(group,{badges:{imdb:8.2,rtCritic:90,rtAudience:91}})
                imdb=group.children[1]:imdbLabel=group.children[2]
                rt=group.children[4]:rtLabel=group.children[5]
                old=group.children[7]:oldLabel=group.children[8]
                pending=imdb.observed and rt.observed and old.observed
                LogoEvent(imdb,"ready")
                LogoEvent(rt,"failed")
                ready={text:imdbLabel.text,observed:imdb.observed,released:imdb.ratingLabel=invalid}
                failed={text:rtLabel.text,visible:rt.visible,width:rtLabel.width,x:rtLabel.translation[0],observed:rt.observed,released:rt.ratingLabel=invalid}
                RenderRatingChips(group,{ratings:[{source:"custom",name:"Custom",score:80,display:"4/5"}]})
                LogoEvent(old,"failed")
                print FormatJson({height:height,pending:pending,ready:ready,failed:failed,oldObserved:old.observed,oldText:oldLabel.text,live:group.children[1].text,count:group.children.Count()})
            ''',root=Path(d))
        result=json.loads(out)
        self.assertEqual(result['height'],28)
        self.assertTrue(result['pending'])
        self.assertEqual(result['ready'],dict(text='8.2/10',observed=False,released=True))
        self.assertEqual(result['failed'],dict(text='RT Critics 90%',visible=False,width=168,x=173,observed=False,released=True))
        self.assertFalse(result['oldObserved'])
        self.assertEqual(result['oldText'],'91%')
        self.assertEqual((result['live'],result['count']),('Custom 4/5',2))

    def test_local_logo_pngs_are_bounded_and_scene_package_includes_them(self):
        import struct
        import zipfile
        import subprocess
        names=['imdb','tmdb','rt-fresh','rt-rotten','rt-audience-fresh','rt-audience-rotten']
        for name in names:
            data=(ROOT/'images/ratings'/f'{name}.png').read_bytes()
            self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
            width,height=struct.unpack('>II',data[16:24])
            self.assertLessEqual(width,96)
            self.assertLessEqual(height,64)
        with tempfile.TemporaryDirectory() as d:
            archive=Path(d)/'ratings.zip'
            subprocess.run(['python3',str(ROOT/'tools/package.py'),'--output',str(archive)],cwd=ROOT,check=True,capture_output=True)
            with zipfile.ZipFile(archive) as package:
                self.assertIn('manifest',package.namelist())
                for name in names:
                    self.assertEqual(package.read(f'images/ratings/{name}.png'),(ROOT/'images/ratings'/f'{name}.png').read_bytes())

    def test_home_native_tmdb_flat_score_uses_ten_point_scale(self):
        with tempfile.TemporaryDirectory() as d:
            item=run_function([ROOT/'source/adapters/SiloAdapter.brs'],'SiloItem',[{'content_id':'x','title':'X','type':'movie','rating_tmdb':7.605}],root=Path(d))['item']
        chip=self.call(item)[0]
        self.assertEqual((chip['source'],chip['text'],chip['asset']),('tmdb','7.6/10','tmdb'))

    def test_large_canonical_input_is_bounded_and_scale_suffix_is_not_repeated(self):
        ratings=[{'source':'imdb','name':'IMDb','score':82,'display':'8.2/10'}]*70
        chips=self.call({'ratings':ratings})
        self.assertEqual(chips[0]['text'],'8.2/10')
        self.assertEqual(chips[-1]['text'],'More ratings')
        self.assertEqual(len(chips),6)
        self.assertEqual(self.call({'ratings':[{'source':'imdb','score':101}]*70}),[])

    def test_detail_initialization_and_loading_logo_layout_clear_previous_ratings(self):
        with tempfile.TemporaryDirectory() as d:
            detail=(ROOT/'components/SiloUIDetail.brs').read_text()
            for name in ['DetailScroll','DetailCompactRender','DetailPhotosClear']:
                detail=re.sub(r'sub '+name+r'\(\).*?\nend sub','sub '+name+'()\nend sub',detail,count=1,flags=re.S)
            detail=detail.replace('CreateObject(', 'NativeObject(')
            path=Path(d)/'detail.brs';path.write_text(detail)
            stub=Path(d)/'native.brs';stub.write_text('''
function SiloUIFont(size,bold)
 return {}
end function
function NativeNode() as Object
 return {text:"",uri:"",visible:false,height:0,children:[],nodes:{},loadStatus:"ready",observeField:sub(field,callback)
 end sub,findNode:function(id)
 if m.nodes[id]=invalid then m.nodes[id]=NativeNode()
 return m.nodes[id]
 end function,boundingRect:function()
 return {height:24,width:200}
 end function,getChildren:function(a,b)
 return m.children
 end function,getChildCount:function()
 return m.children.Count()
 end function,removeChildren:sub(children)
 m.children=[]
 end sub,removeChildrenIndex:sub(count,index)
 m.children=[]
 end sub,createChild:function(kind)
 child=NativeNode():m.children.Push(child):return child
 end function}
end function
function NativeObject(kind,detail)
 return NativeNode()
end function
function ItemArt(item)
 return {}
end function
function ArtField(art,key)
 return ""
end function
sub PlayerDiscardPrebuffer()
end sub
function StreamingScopeKey() as String
 return "fixture-scope"
end function
sub ShowView(view)
 m.view=view
 onDetailLogo()
 DetailLayout()
 m.loadingHeight=m.detailRatingsHeight
 m.loadingChildren=m.detailRatings.getChildCount()
end sub
sub FitLogo(node,width,height)
 node.height=100
end sub
sub BuildButtons(group,zone,labels)
end sub
sub PaintButtons(zone,focused)
end sub
sub SetBackdrop(uri)
end sub
sub SetZone(zone)
 m.zone=zone
end sub
sub Api(action,params,purpose,extra)
end sub
''')
            out=run_brightscript([ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/SiloUIRatingPolicy.brs',ROOT/'source/core/SiloUIDetailPolicy.brs',ROOT/'components/SiloUIRatings.brs',path,stub],'''
                m.top=NativeNode():m.provider="silo":m.view="home":m.zone="heroButtons"
                m.history=[]:m.pillGroups={}:m.backdrop={}:m.backdropOld={}
                DetailInit()
                initial=m.detailRatingsHeight
                DetailOpen({itemId:"first",type:"movie",title:"First",badges:{}})
                m.detailRatingsHeight=invalid
                DetailLayout()
                m.detailRatingsHeight=60
                m.detailRatings.createChild("Label")
                DetailOpen({itemId:"new",type:"movie",title:"New",badges:{}})
                print FormatJson({initial:initial,loadingHeight:m.loadingHeight,loadingChildren:m.loadingChildren,height:m.detailRatingsHeight,visible:m.detailRatings.visible})
            ''',root=Path(d))
        self.assertEqual(json.loads(out),dict(initial=0,loadingHeight=0,loadingChildren=0,height=0,visible=False))

    def test_actual_hero_summary_uses_absolute_space_before_actions(self):
        with tempfile.TemporaryDirectory() as d:
            out=run_brightscript([ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIHome.brs'],'''
                results=[]
                cases=[{logo:true,height:140,title:0,chips:0,rating:0},{logo:true,height:140,title:0,chips:1,rating:28},{logo:true,height:140,title:0,chips:6,rating:60},{logo:false,height:0,title:104,chips:6,rating:60},{logo:false,height:0,title:52,chips:1,rating:28},{logo:false,height:0,title:0,chips:0},{logo:true,height:152,title:0,chips:1,rating:28},{logo:false,height:0,title:116,chips:1,rating:28},{logo:true,height:124,title:0,chips:1,rating:28}]
                for each c in cases
                    m.top={findNode:function(id)
                        return {translation:[56,118]}
                    end function}
                    m.heroLogo={visible:c.logo,height:c.height}
                    m.heroTitle={height:c.title,boundingRect:function()
                        return {height:m.height}
                    end function}
                    m.heroMeta={}:m.heroSummary={}:m.heroButtons={}
                    m.heroRatingsHeight=c.rating
                    m.heroChips={count:c.chips,getChildCount:function()
                        return m.count
                    end function}
                    HeroLayout()
                    results.Push({visible:m.heroSummary.visible,lines:m.heroSummary.maxLines,top:118+m.heroSummary.translation[1],buttons:m.heroButtons.translation[1]})
                end for
                print FormatJson(results)
            ''',root=Path(d))
        results=json.loads(out)
        self.assertEqual([(r['visible'],r['lines']) for r in results],[(True,2),(True,1),(False,1),(False,1),(True,3),(True,3),(False,1),(False,1),(True,1)])
        for r in results:
            if r['visible']:
                self.assertLessEqual(r['top']+24*r['lines'],r['buttons']-8)
