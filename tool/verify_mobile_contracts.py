"""Replay fresh synthetic API payloads through the Dart validators in selected mobile commits."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_support_tickets import SupportTests


def fixture_responses():
    case = SupportTests()
    try:
        case.setUp()
        chat = case.req('/api/conversations', 'POST', {'listingId':'abc:boarding'})
        case.req('/api/conversations/'+chat['id']+'/messages', 'POST',
                 {'requestId':'c'*32,'text':'TEST message','image':None})
        ticket = case.req('/api/support','POST',case.data())['ticket']['id']
        return {'quote':case.quote(), 'draft':case.payload, 'bookings':case.req('/api/bookings'),
                'inbox':case.req('/api/conversations'), 'messages':case.req('/api/conversations/'+chat['id']+'/messages'),
                'chatId':chat['id'], 'notices':case.req('/api/notifications',user='abc'),
                'support':case.req('/api/support'), 'thread':case.req('/api/support/'+ticket), 'ticketId':ticket}
    finally:
        case.doCleanups()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',required=True,type=Path)
    parser.add_argument('--dart',required=True,type=Path)
    parser.add_argument('revision',nargs='+')
    args=parser.parse_args()
    dart=args.dart.resolve(strict=True)
    files=('chat/data/conversation_data','support/support_data','notifications/data/notification_data','bookings/data/booking_contract')
    values=fixture_responses()
    assert all(values[k]['items'] for k in ('inbox','messages','notices','support','thread'))
    with TemporaryDirectory() as tmp:
        folder=Path(tmp)
        (folder/'responses.json').write_text(json.dumps(values),encoding='utf-8')
        script="""import 'dart:convert'; import 'dart:io';
import 'conversation_data.dart'; import 'support_data.dart'; import 'notification_data.dart'; import 'booking_contract.dart';
void main() {
  final v=jsonDecode(File('responses.json').readAsStringSync());
  checkBookingQuote(v['quote'],v['draft']['listingId'],v['draft']);
  checkBookingPage(v['bookings'],null);
  chatInbox(v['inbox']); chatPage(v['messages'],id:v['chatId']);
  notificationPage(v['notices']); supportList(v['support']); supportThread(v['thread'],id:v['ticketId']);
  try { supportThread(v['thread'],id:'different'); } on FormatException { return; }
  throw StateError('Foreign support ticket accepted');
}
"""
        (folder/'check.dart').write_text(script,encoding='utf-8')
        for rev in args.revision:
            sha=subprocess.check_output(['git','-C',str(args.app),'rev-parse','--verify','--end-of-options',rev+'^{commit}'],text=True).strip()
            for f in files:
                source=subprocess.check_output(['git','-C',str(args.app),'show',sha+':lib/features/'+f+'.dart'])
                (folder/(Path(f).name+'.dart')).write_bytes(source)
            subprocess.run([str(dart),'check.dart'],cwd=folder,check=True,timeout=40)
            print(sha,'7 payloads accepted, foreign ticket rejected',flush=True)


if __name__=='__main__':
    main()
