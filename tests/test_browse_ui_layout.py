"""Retained pure grid edges, row semantics and bounded progress projections."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
DRIVER='function UiSixColumnEdges() as Object\n    output=[]\n    for each sample in [{count:12,index:0},{count:12,index:4},{count:12,index:5},{count:12,index:6},{count:12,index:11},{count:14,index:6},{count:14,index:11},{count:14,index:12},{count:14,index:13},{count:1,index:0}]\n        output.Push([BrowseScreenLeftEdge("grid",sample.index,[0,0]),BrowseScreenBottomEdge("grid",sample.index,sample.count,[0,0],{})])\n    end for\n    return output\nend function'

class BrowseUiLayoutTests(unittest.TestCase):
    def call(self,name,*args):
        with tempfile.TemporaryDirectory(prefix='silo-ui-browse-') as directory:
            root=Path(directory)
            fixture=root/'fixture.brs'
            fixture.write_text(DRIVER)
            return run_function([ROOT/'source/core/BrowseScreenPolicy.brs',ROOT/'source/core/HomeRowsPolicy.brs',fixture],name,list(args),root=root)

    def test_native_grid_six_column_first_last_and_partial_row_edges(self):
        self.assertEqual([[True,False],[False,False],[False,False],[True,True],[False,True],
                          [True,False],[False,False],[True,True],[False,True],[True,True]],self.call('UiSixColumnEdges'))


    def test_home_styles_use_exact_semantics_and_movie_show_types_without_label_guessing(self):
        items=[{'rowId':'home.continue','rowTitle':'Localized','type':'movie'},
               {'rowId':'silo1','rowTitle':'Localized','type':'series','sectionType':'continue_watching'},
               {'rowId':'movies','rowTitle':'Continue watching','type':'movie'},
               {'rowId':'shows','type':'show'},{'rowId':'episodes','type':'episode'},
               {'rowId':'actions','uiAction':'refresh','title':'Refresh'}]
        rows=self.call('HomeRowsPlan',items)['rows']
        self.assertEqual(['wide','wide','poster','poster','wide','wide'],[row.get('cardStyle') for row in rows])
        self.assertEqual([210,210,230,230,210,210],[row.get('rowHeight') for row in rows])
        self.assertEqual([[236,176],[236,176],[112,198],[112,198],[236,176],[236,176]],[row.get('itemSize') for row in rows])


    def test_only_actual_finite_typed_resume_and_duration_reach_progress_dto(self):
        facts=[(10000,100000),(0,100000),(True,100000),('10000',100000),(10000,0),(-1,100000),(100001,100000),(1,1e30)]
        items=[{'itemId':str(i),'title':'A','type':'movie','resumeMs':p,'durationMs':d,'url':'https://private.example.test'} for i,(p,d) in enumerate(facts)]
        plan=self.call('BrowseScreenPlan',None,{'items':items,'presentation':'rows','scopeKey':'route-7'},0,'nav')
        self.assertEqual([{'positionMs':10000,'durationMs':100000},{'positionMs':0,'durationMs':100000}]+[{}]*6,[item.get('progress',{}) for item in plan['items']])
        self.assertTrue(all(item.get('type')=='movie' for item in plan['items']))
        self.assertNotIn('private.example.test',str(plan))
