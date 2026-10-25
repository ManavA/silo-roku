"""Offline inherited-pipe transport boundary; no sockets or credentials."""
import unittest
from tools.brightscript import run_function
from tests.test_silo_playback_task import ROOT


class HostHttpBridge(unittest.TestCase):
    def test_exact_request_and_timeout_reach_broker_and_shipping_http_response(self):
        import tempfile
        from pathlib import Path
        request = {'method': 'POST', 'url': 'https://silo.example/start',
                   'headers': {'Authorization': 'synthetic-only'}, 'body': '{"a":1}'}
        seen = []
        def broker(actual, timeout):
            seen.append((actual, timeout))
            return {'statusCode': 201, 'body': '{"receipt":true}'}
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / 'bridge.brs'
            script.write_text('''function Probe(request as Object) as Object
 response=HostHttpRequest(request,1234)
 return HttpResponse(request,response.statusCode,response.body)
end function
''')
            result = run_function([ROOT/'source/network/Http.brs', script], 'Probe',
                                  [request], host_http=broker)
        self.assertEqual([(request, 1234)], seen)
        self.assertEqual({'ok': True, 'statusCode': 201, 'body': '{"receipt":true}'}, result)

    def test_single_shipping_job_chooses_original_then_1080_through_broker(self):
        import json
        from tests.test_silo_stock_auto_ladder import StockAutoLadder
        from tests.test_silo_playback_task import FIXTURES
        fixture = json.loads((FIXTURES/'stock_auto_1080_ladder.json').read_text())
        requests = []
        replies = []
        for key in ('original_response', 'fallback_response'):
            replies.extend([{'statusCode': 200, 'body': json.dumps(fixture['detail'])},
                            {'statusCode': 200, 'body': json.dumps(fixture['capabilities'])},
                            {'statusCode': fixture[key]['status'],
                             'body': json.dumps(fixture[key]['decision'])}])
        def broker(request, timeout):
            index = len(requests)
            self.assertLess(index, 6)
            self.assertEqual(['GET','GET','POST'][index % 3], request['method'])
            self.assertEqual('https://silo.example/api/v2/' +
                             ['catalog/items/fixture-item?image_size=medium', 'playback/capabilities', 'playback/start'][index % 3],
                             request['url'])
            self.assertEqual([4000,6000,90000][index % 3], timeout)
            requests.append(request)
            return replies[index]
        result = StockAutoLadder().stock_job(host_http=broker)
        self.assertEqual(6, len(requests))
        self.assertEqual([r['url'] for r in requests[:2]], [r['url'] for r in requests[3:5]])
        starts = [json.loads(r['body']) for r in requests if r['method']=='POST']
        self.assertEqual(['original','1080p'], [s['quality_preference'] for s in starts])
        self.assertEqual(['731','731'], [s['file_id'] for s in starts])
        self.assertNotEqual(starts[0]['playback_attempt_id'], starts[1]['playback_attempt_id'])
        self.assertEqual(starts[0]['client_capabilities'], starts[1]['client_capabilities'])
        self.assertEqual(starts[0]['client_playback_context'], starts[1]['client_playback_context'])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertEqual(('hls','fixture-plan','fixture-session'),
                         tuple(result['outcome']['plan'][k] for k in ('streamFormat','planId','sessionId')))

    def test_timeout_or_disconnect_cannot_forward_another_start(self):
        import json
        from tests.test_silo_stock_auto_ladder import StockAutoLadder
        from tests.test_silo_playback_task import FIXTURES
        fixture = json.loads((FIXTURES/'stock_auto_1080_ladder.json').read_text())
        for failure in (TimeoutError, ConnectionError):
            with self.subTest(failure=failure.__name__):
                requests = []
                def broker(request, timeout):
                    requests.append(request)
                    if request['method']=='POST':
                        raise failure('synthetic-secret-never-print')
                    key = 'capabilities' if 'capabilities' in request['url'] else 'detail'
                    return {'statusCode':200, 'body':json.dumps(fixture[key])}
                with self.assertRaisesRegex(RuntimeError, '^Host HTTP bridge failed closed$'):
                    StockAutoLadder().stock_job(host_http=broker)
                self.assertEqual(['GET','GET','POST'], [r['method'] for r in requests])

    def test_request_deadline_closes_bridge_without_resending(self):
        import tempfile
        import time
        from pathlib import Path
        seen = []
        def slow(request, timeout):
            seen.append(request)
            time.sleep(.2)
            return {'statusCode':200, 'body':''}
        with tempfile.TemporaryDirectory() as td:
            script = Path(td)/'slow.brs'
            script.write_text('''function Probe() as Object
 request={method:"POST",url:"https://silo.example/start"}
 first=HostHttpRequest(request,10)
 second=HostHttpRequest(request,10)
 return second
end function
''')
            with self.assertRaisesRegex(RuntimeError, '^Host HTTP bridge failed closed$'):
                run_function([script], 'Probe', [], host_http=slow)
        self.assertEqual(1, len(seen))

    def test_request_count_and_response_bytes_are_bounded(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        for limit, body, expected in ((16, '', 16), (16, 'x'*256, 1)):
            with self.subTest(oversized=bool(body)), tempfile.TemporaryDirectory() as td:
                seen = []
                def broker(request, timeout):
                    seen.append(request)
                    return {'statusCode':200, 'body':body}
                script = Path(td)/'bounded.brs'
                script.write_text('''function Probe() as Object
 for i=1 to 17
  response=HostHttpRequest({method:"POST",url:"https://silo.example/start"},1000)
 end for
 return response
end function
''')
                with patch('tools.brightscript_http.FRAME_LIMIT', 128 if body else 3145728):
                    with self.assertRaisesRegex(RuntimeError, '^Host HTTP bridge failed closed$'):
                        run_function([script], 'Probe', [], host_http=broker)
                self.assertEqual(expected, len(seen))
