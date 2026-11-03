"""Build an isolated, offline TEST dataset for manual inspection."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from seed_test_data import check_fixture_file, fixture_directory, fixture_id, seed


SCENARIO = 'momiq-care-demo-v1'


def populate(directory, current):
    import booking_care
    import booking_chat
    import booking_engine as engine
    import catalog
    import conversations
    import server
    import wallet

    customer, sitter, pet = (fixture_id(name) for name in ('customer', 'boarding', 'cat'))
    with sqlite3.connect(directory / 'momiq.sqlite3', factory=server.ClosingConnection) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        account = json.loads(con.execute('SELECT account FROM users WHERE id=?', (sitter,)).fetchone()[0])
        photo = account['pets'][0]['photo']
        account['profile']['photo'] = photo
        account['sitterProfile']['homePhotos'] = [photo]
        con.execute('UPDATE users SET account=? WHERE id=?', (json.dumps(account), sitter))
        wallet.post_entry(con, sitter, 100000000, 'topup', SCENARIO, 'fixture', 'TEST opening balance')
        con.commit()
        catalog.review(con, sitter, 'boarding', {'decision': 'approve', 'reason': 'TEST scenario',
                       'testOnly': True, '_revision': catalog.revision(con, sitter)}, 'fixture', 'test')
        con.commit()

        for status, offset in [('active', -1), ('pending', 3), ('rejected', 4)]:
            start = current + timedelta(days=offset)
            requested = min(current, start - timedelta(days=1))
            quote = engine.prepare_quote(con, customer, sitter + ':boarding', [pet], start.isoformat(),
                                         (start + timedelta(days=2)).isoformat(), policy=engine.DailyPolicy(),
                                         environment='test', now=requested)
            con.commit()
            booking = engine.request_booking(con, customer, quote['id'], fixture_id(status),
                                             environment='test', now=requested)
            con.commit()
            if status == 'pending':
                continue
            action = 'accept' if status == 'active' else 'reject'
            identity = booking['id']
            booking = engine.act(con, sitter, identity, action, booking['revision'], fixture_id(action),
                                 reason='TEST scenario', environment='test', now=requested)
            con.commit()
            if status == 'rejected':
                continue
            for actor in (customer, sitter):
                booking = engine.act(con, actor, identity, 'start', booking['revision'], fixture_id('start-' + actor),
                                     environment='test', now=start)
                con.commit()
            chat = booking_chat.open_chat(con, identity, customer, 'test')
            con.commit()
            conversations.send(con, customer, chat['id'], {'requestId': fixture_id('message'),
                               'text': 'TEST — mushuk ovqatlandimi?'}, server.validate_photo)
            con.commit()
            booking_care.save(con, identity, sitter, {
                'kind': 'report', 'category': 'food', 'day': booking_care.today(current), 'petId': pet,
                'requestId': fixture_id('report'), 'revision': 0,
                'payload': {'state': 'done', 'note': 'TEST — mushuk ovqatlandi.'}}, current)
            con.commit()
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or con.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Invalid scenario database')
        con.execute('INSERT INTO runtime_metadata(key,value) VALUES(?,?)', ('fixture_scenario', SCENARIO))


def populate_payments(directory):
    """Only called on the private, unpublished staging copy of a new TEST scenario."""
    import base64
    from io import BytesIO
    from PIL import Image, ImageDraw
    import server
    import wallet

    def picture(label):
        with Image.new('RGB',(320,104),'white') as image, BytesIO() as output:
            draw = ImageDraw.Draw(image)
            draw.text((12,18),'MOMIQ TEST / NO PAYMENT',fill='black')
            draw.text((12,58),label,fill='black')
            image.save(output,format='PNG')
            return base64.b64encode(output.getvalue()).decode()

    with sqlite3.connect(directory/'momiq.sqlite3',factory=server.ClosingConnection) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        labels = dict(con.execute("SELECT key,value FROM runtime_metadata WHERE key IN ('environment','fixture_scenario')"))
        if labels != {'environment':'test','fixture_scenario':SCENARIO}:
            raise ValueError('Expected offline TEST scenario')
        def call(user, method, path, payload):
            class RecordedRequest:
                command = method
                def body(self):
                    return payload
                def reply(self, status, data):
                    if not 200 <= status < 300:
                        raise ValueError('TEST scenario write failed')
                    self.result = data
            request = RecordedRequest()
            request.path = path
            if not wallet.route(request, con, user, path, server.validate_photo, 'test'):
                raise ValueError('Missing wallet fixture route')
            return request.result
        actor, user = 'TEST finance', fixture_id('personal')
        qr = call(actor,'PUT','/api/admin/platform-settings',{
            'version':wallet.settings(con)['version'], 'testOnly':True,'qrActive':True,
            'qrImage':base64.b64encode((Path(__file__).parent/'fixtures/paynet-test-qr.png').read_bytes()).decode(),
            'recipientName':'TEST MOMIQ',
            'reason':'Offline simulation','paymentInstructions':'TEST. Do not send money.'})
        for case in ('approve','reject','request_info','amend','pending'):
            payload = {'amountMinor':2000000,'requestId':fixture_id(case),'receipt':picture('TEST RECEIPT '+case),
                       'qrVersion':qr['version'],'termsVersion':'balance-no-refund-v1','acceptNonRefundable':True,
                       'payerReference':'TEST-'+case.upper().replace('_','-')}
            topup = call(user,'POST','/api/wallet/topups',payload)['topup']
            if case == 'pending':
                continue
            review = '/api/admin/topups/'+topup['id']+'/review'
            decision = {'revision':0,'decision':'request_info' if case=='amend' else case,'reason':'TEST '+case}
            if case == 'approve':
                decision.update(fundsVerified=True,receivedAmountMinor=2000000,transferReference='TEST-INCOMING-0001')
            call(actor,'POST',review,decision)
            if case == 'approve':
                call(actor,'POST',review,decision)
            if case == 'amend':
                changed = dict(payload,revision=1,requestId=fixture_id('corrected'),receipt=picture('TEST CORRECTED'))
                call(user,'POST','/api/wallet/topups/'+topup['id']+'/amend',changed)
        con.execute("INSERT INTO runtime_metadata VALUES('fixture_payment_suite','1')")


def build(directory, *, payments=False):
    if os.environ.get('MOMIQ_ENV', 'local') not in ('local', 'test'):
        raise ValueError('Scenario fixtures require a local/test runtime')
    target = fixture_directory(directory)
    if target.exists():
        database = target / 'momiq.sqlite3'
        for name in ('momiq.sqlite3', 'momiq.sqlite3-wal', 'momiq.sqlite3-shm', 'momiq.sqlite3-journal'):
            check_fixture_file(target / name)
        if database.is_file():
            from contextlib import closing
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as con:
                labels = dict(con.execute("SELECT key,value FROM runtime_metadata WHERE key IN ('environment','fixture_scenario')"))
                if labels == {'environment': 'test', 'fixture_scenario': SCENARIO}:
                    if payments and not con.execute("SELECT 1 FROM runtime_metadata WHERE key='fixture_payment_suite' AND value='1'").fetchone():
                        raise ValueError('Use a new directory for a TEST payment scenario')
                    return 'already-created'
        raise ValueError('Scenario requires a new directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        staged = Path(temporary) / 'dataset'
        seed(staged, 'test')
        populate(staged, datetime.now(timezone.utc).replace(microsecond=0))
        if payments:
            populate_payments(staged)
        staged.rename(target)
    return 'created'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--payments', action='store_true')
    args = parser.parse_args()
    try:
        print(build(args.data_dir,payments=args.payments))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
