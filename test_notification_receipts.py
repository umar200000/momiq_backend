"""Read acknowledgements are owner-scoped server snapshots, including retries."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
import notifications
import server
import test_api


class NotificationReceiptTests(unittest.TestCase):
    setUpClass=classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(test_api.ApiTests.tearDownClass.__func__)
    setUp=test_api.ApiTests.setUp
    req=test_api.ApiTests.req
    login=test_api.ApiTests.login

    def notices(self,phone):
        owner=self.login(phone)
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            for n in range(3):notifications.publish(con,owner['userId'],phone+':TEST:'+str(n),'support','a'*32,'waiting_user','TEST reason')
        items=self.req('/api/notifications',token=owner['token'])['items']
        return owner,items

    def test_retry_keeps_read_time_and_returns_current_count_after_other_reader(self):
        owner,items=self.notices('998900013001');token=owner['token']
        path='/api/notifications/'+items[0]['id']+'/read'
        first=self.req(path,'POST',{},token=token)
        self.assertTrue(first['ok']);self.assertEqual(first['unreadCount'],2)
        self.assertIsNotNone(first['readAt'])
        other=self.req('/api/notifications/'+items[1]['id']+'/read','POST',{},token=token)
        self.assertEqual(other['unreadCount'],1)
        retry=self.req(path,'POST',{},token=token)
        self.assertEqual(retry['readAt'],first['readAt']);self.assertEqual(retry['unreadCount'],1)
        page=self.req('/api/notifications',token=token)
        self.assertEqual(page['unreadCount'],1)
        self.assertEqual(page['items'][0]['readAt'],first['readAt'])

    def test_parallel_read_same_notice_marks_once_and_preserves_timestamp(self):
        owner,items=self.notices('998900013002');gate=threading.Barrier(2)
        def read(_):
            gate.wait()
            return self.req('/api/notifications/'+items[0]['id']+'/read','POST',{},token=owner['token'])
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(read,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(results[0]['unreadCount'],2)

    def test_invalid_filters_or_read_envelope_cannot_change_owner_notice(self):
        owner,items=self.notices('998900013003');stranger=self.login('998900013004')
        path='/api/notifications/'+items[0]['id']+'/read'
        with server.db() as con:before=[tuple(r) for r in con.execute('SELECT * FROM notifications')]
        for query in ('before=','before=1&before=2','ownerId=other','before=01'):
            self.req('/api/notifications?'+query,token=owner['token'],expected=400)
        for data in ({'userId':stranger['userId']},{'readAt':'2000-01-01T00:00:00Z'},{'unreadCount':0}):
            self.req(path,'POST',data,token=owner['token'],expected=400)
        self.req(path+'?force=true','POST',{},token=owner['token'],expected=400)
        self.req(path,'POST',{},token=stranger['token'],expected=404)
        with server.db() as con:self.assertEqual([tuple(r) for r in con.execute('SELECT * FROM notifications')],before)
