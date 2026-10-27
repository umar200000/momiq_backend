"""Manual Paynet Xolis top-ups. Amounts are integer UZS minor units (1/100 so'm)."""
import base64
import hashlib
import re
import secrets
import notifications
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlparse

MINIMUM_BALANCE_MINOR = 1_500_000
TERMS_VERSION = 'balance-no-refund-v1'


class WalletError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit, required=True):
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):
        raise ValueError('Matn noto‘g‘ri')
    return value.strip()


def amount(value):
    if type(value) is not int or not 0 < value <= 100_000_000_000:
        raise ValueError('Summa butun tiyinlarda berilishi kerak')
    return value


def payment_time(value):
    if value is None or value == '': return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('To‘lov vaqti noto‘g‘ri')
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None: raise ValueError()
        parsed = parsed.astimezone(timezone.utc)
        if parsed.year < 2000 or parsed > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError()
        return parsed.isoformat()
    except (ValueError, OverflowError):
        raise ValueError('Chekdagi haqiqiy to‘lov vaqti va vaqt zonasini ko‘rsating') from None


def settings(con):
    row=con.execute('SELECT * FROM platform_settings ORDER BY version DESC LIMIT 1').fetchone()
    return {'version':row['version'],'commissionBps':row['commission_bps'],
            'minimumBalanceMinor':MINIMUM_BALANCE_MINOR,'currency':'UZS',
            'provider':'paynet_xolis','qrImage':row['qr_image'], 'testOnly':bool(row['test_only']),
            'recipientName':row['recipient_name'],'paymentInstructions':row['payment_instructions'],
            'qrActive':bool(row['qr_active']),
            'termsVersion':TERMS_VERSION,'unusedBalanceRefundable':False}


def balance(con, uid):
    row=con.execute('SELECT balance_minor FROM wallet_accounts WHERE user_id=?',(uid,)).fetchone()
    return row[0] if row else 0


def post_entry(con, uid, value, kind, source, actor, reason):
    """Caller must hold a write transaction. Compensation appends a new entry."""
    if not con.in_transaction: raise RuntimeError('Wallet mutation requires a transaction')
    if type(value) is not int or value==0: raise ValueError('Invalid journal amount')
    existing=con.execute('SELECT * FROM wallet_entries WHERE source_key=?',(source,)).fetchone()
    if existing:
        if existing['user_id']!=uid or existing['amount_minor']!=value or existing['kind']!=kind:
            raise WalletError(409,'Balans amali identifikatori boshqa ma’lumot bilan ishlatilgan')
        return existing['id']
    con.execute('INSERT OR IGNORE INTO wallet_accounts(user_id) VALUES(?)',(uid,))
    changed=con.execute('UPDATE wallet_accounts SET balance_minor=balance_minor+? WHERE user_id=? AND balance_minor+?>=0',(value,uid,value)).rowcount
    if not changed: raise WalletError(409,'Balans yetarli emas')
    entry=secrets.token_hex(16)
    con.execute('INSERT INTO wallet_entries VALUES(?,?,?,?,?,?,?,?,?)',
                (entry,uid,value,balance(con,uid),kind,source,actor,reason,now()))
    return entry


def topup_view(row, *, admin=False):
    result={'id':row['id'],'amountMinor':row['amount_minor'],'currency':'UZS',
            'qrVersion':row['qr_version'],'status':row['status'],'created':row['created'],
            'reviewReason':row['review_reason'],'reviewedAt':row['reviewed_at'],
            'payerReference':row['payer_reference'],'paidAt':row['paid_at']}
    if admin:
        result.update(userId=row['user_id'],transferReference=row['transfer_reference'])
    return result


def topup_page(handler, con, uid, admin=False):
    query=parse_qs(urlparse(handler.path).query)
    predicates=[];args=[]
    if not admin:
        predicates.append('user_id=?');args.append(uid)
    status=query.get('status',['all'])[0]
    if status not in ('all','pending','approved','rejected'): raise ValueError('Invalid status')
    if status!='all': predicates.append('status=?');args.append(status)
    cursor=query.get('cursor',[None])[0]
    if cursor:
        if not re.fullmatch('[a-f0-9]{32}',cursor): raise ValueError('Invalid cursor')
        row=con.execute('SELECT user_id,created,id FROM topup_requests WHERE id=?',(cursor,)).fetchone()
        if not row or (not admin and row['user_id']!=uid): raise WalletError(400,'Invalid cursor')
        predicates.append('(created,id)<(?,?)');args.extend([row['created'],row['id']])
    clause=' WHERE '+' AND '.join(predicates) if predicates else ''
    rows=con.execute('SELECT * FROM topup_requests'+clause+' ORDER BY created DESC,id DESC LIMIT 21',args).fetchall()
    return {'topups':[topup_view(r,admin=admin) for r in rows[:20]],
            'nextCursor':rows[19]['id'] if len(rows)>20 else None}


def require_sitter(con, uid):
    user=con.execute('SELECT blocked FROM users WHERE id=?',(uid,)).fetchone()
    if not user or user['blocked'] or not con.execute("SELECT 1 FROM user_roles WHERE user_id=? AND role='sitter'",(uid,)).fetchone():
        raise WalletError(403,'Enaga hisobi talab qilinadi')


def route(handler, con, uid, path, photo, environment):
    method=handler.command
    receipt_match=re.fullmatch(r'/api/(admin|wallet)/topups/([a-f0-9]{32})/receipt',path)
    if receipt_match and method=='GET':
        row=con.execute('SELECT t.user_id,t.receipt,s.qr_image,s.version,s.recipient_name,s.payment_instructions,s.test_only FROM topup_requests t JOIN platform_settings s ON s.version=t.qr_version WHERE t.id=?',(receipt_match[2],)).fetchone()
        if receipt_match[1]=='wallet': require_sitter(con,uid)
        if not row or (receipt_match[1]=='wallet' and row['user_id']!=uid):
            raise WalletError(404,'Chek topilmadi')
        handler.reply(200,{'receipt':row['receipt'],'paymentSnapshot':{'version':row['version'],
            'qrImage':row['qr_image'],'recipientName':row['recipient_name'],
            'paymentInstructions':row['payment_instructions'],'testOnly':bool(row['test_only'])}});return True
    if path == '/api/admin/platform-settings' and method in ('GET','PUT'):
        if method=='PUT':
            data=handler.body()
            con.execute('BEGIN IMMEDIATE')
            current=settings(con)
            if data.get('version')!=current['version'] or type(data.get('version')) is not int:
                raise WalletError(409,'Sozlamalar o‘zgargan. Qayta yuklang.')
            rate=data.get('commissionBps',current['commissionBps'])
            if type(rate) is not int or not 0<=rate<=10000: raise ValueError('Foiz 0–100 oralig‘ida bo‘lsin')
            qr=photo(data['qrImage']) if 'qrImage' in data else current['qrImage']
            test_only=data.get('testOnly',current['testOnly'])
            if type(test_only) is not bool: raise ValueError('Test belgisi noto‘g‘ri')
            if environment=='production' and test_only: raise WalletError(400,'Productionda test QR mumkin emas')
            reason=text(data.get('reason'),1000)
            recipient=text(data.get('recipientName',current['recipientName']),200,required=False)
            instructions=text(data.get('paymentInstructions',current['paymentInstructions']),1000,required=False)
            active=data.get('qrActive',current['qrActive'])
            if type(active) is not bool: raise ValueError('QR holati noto‘g‘ri')
            if active and (not qr or not recipient):
                raise WalletError(400,'Faol QR uchun rasm va oluvchi nomi majburiy')
            con.execute('INSERT INTO platform_settings(commission_bps,qr_image,test_only,actor,reason,created,recipient_name,payment_instructions,qr_active) VALUES(?,?,?,?,?,?,?,?,?)',
                        (rate,qr,int(test_only),uid,reason,now(),recipient,instructions,int(active)))
            con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(uid,'platform-settings',reason,now()))
            con.commit()
        handler.reply(200,settings(con));return True
    if path == '/api/wallet' and method=='GET':
        # Balance and entries must describe one snapshot during concurrent credit.
        con.execute('BEGIN')
        require_sitter(con,uid)
        entries=[{'id':r['id'],'amountMinor':r['amount_minor'],'balanceAfter':r['balance_after'],'kind':r['kind'],'reason':r['reason'],'created':r['created']}
                 for r in con.execute('SELECT * FROM wallet_entries WHERE user_id=? ORDER BY created DESC,id DESC LIMIT 50',(uid,))]
        value=balance(con,uid)
        handler.reply(200,{'balanceMinor':value,'currency':'UZS','minimumBalanceMinor':MINIMUM_BALANCE_MINOR,
                           'balanceEligible':value>=MINIMUM_BALANCE_MINOR,'entries':entries,'config':settings(con)})
        return True
    if path == '/api/wallet/topups' and method in ('GET','POST'):
        require_sitter(con,uid)
        if method=='GET':
            handler.reply(200,topup_page(handler,con,uid))
            return True
        data=handler.body()
        value=amount(data.get('amountMinor'))
        receipt=photo(data.get('receipt'))
        if not receipt: raise ValueError('Chek rasmi majburiy')
        digest=hashlib.sha256(base64.b64decode(receipt,validate=True)).hexdigest()
        request_id=text(data.get('requestId'),100)
        payer_reference=text(data.get('payerReference',''),200,required=False)
        paid_at=payment_time(data.get('paidAt'))
        version=data.get('qrVersion')
        if type(version) is not int: raise ValueError('QR versiyasi noto‘g‘ri')
        if data.get('acceptNonRefundable') is not True or data.get('termsVersion')!=TERMS_VERSION:
            raise WalletError(400,'Balans qoldig‘i qaytarilmasligi haqidagi shartni tasdiqlang')
        con.execute('BEGIN IMMEDIATE')
        require_sitter(con,uid)
        existing=con.execute('SELECT * FROM topup_requests WHERE user_id=? AND request_id=?',(uid,request_id)).fetchone()
        if existing:
            if (existing['amount_minor']!=value or existing['receipt_hash']!=digest or existing['qr_version']!=version
                    or existing['payer_reference']!=payer_reference or existing['paid_at']!=paid_at):
                raise WalletError(409,'So‘rov identifikatori boshqa ma’lumot bilan ishlatilgan')
            handler.reply(200,{'topup':topup_view(existing)});return True
        if not payer_reference and not paid_at:
            raise WalletError(400,'Chekdagi to‘lov vaqtini yoki operatsiya ID raqamini kiriting')
        qr=con.execute('SELECT * FROM platform_settings WHERE version=?',(version,)).fetchone()
        if not qr or not qr['qr_image']: raise WalletError(409,'Balans to‘ldirish uchun QR hali berilmagan')
        # Historic active versions remain valid evidence after replacement or pause.
        # Versions created before recipient migration also remain reviewable.
        if not qr['qr_active'] and not qr['legacy_receipt_allowed']:
            raise WalletError(409,'Bu QR versiyasi to‘lov qabul qilish uchun faollashtirilmagan')
        if environment=='production' and qr['test_only']: raise WalletError(400,'Test QR mumkin emas')
        if con.execute('SELECT 1 FROM topup_requests WHERE receipt_hash=?',(digest,)).fetchone():
            raise WalletError(409,'Bu chek avval yuborilgan. Yordam xizmatiga murojaat qiling.')
        topup=secrets.token_hex(16)
        con.execute('INSERT INTO topup_requests(id,user_id,amount_minor,receipt,receipt_hash,qr_version,terms_version,request_id,status,created,payer_reference,paid_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (topup,uid,value,receipt,digest,version,TERMS_VERSION,request_id,'pending',now(),payer_reference,paid_at))
        con.commit()
        handler.reply(201,{'topup':topup_view(con.execute('SELECT * FROM topup_requests WHERE id=?',(topup,)).fetchone())})
        return True
    if path == '/api/admin/topups' and method=='GET':
        handler.reply(200,topup_page(handler,con,uid,admin=True))
        return True
    match=re.fullmatch(r'/api/admin/topups/([a-f0-9]{32})/review',path)
    if match and method=='POST':
        data=handler.body();reason=text(data.get('reason'),1000)
        decision=data.get('decision')
        if decision not in ('approve','reject'): raise ValueError('Qaror noto‘g‘ri')
        reference=text(data.get('transferReference'),200) if decision=='approve' else None
        if reference:
            reference=reference.upper()
        if decision=='approve' and data.get('fundsVerified') is not True:
            raise WalletError(400,'Chek bilan birga haqiqiy tushumni ham tekshiring')
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM topup_requests WHERE id=?',(match[1],)).fetchone()
        if not row: raise WalletError(404,'Chek so‘rovi topilmadi')
        if decision=='approve' and (type(data.get('receivedAmountMinor')) is not int or data['receivedAmountMinor']!=row['amount_minor']):
            raise WalletError(409,'Tekshirilgan tushum summasi so‘rovga mos emas. Avval aniqlashtiring.')
        status='approved' if decision=='approve' else 'rejected'
        if row['status']!='pending':
            if row['status']==status and row['transfer_reference']==reference:
                handler.reply(200,{'topup':topup_view(row,admin=True)});return True
            raise WalletError(409,'Bu so‘rov allaqachon ko‘rib chiqilgan')
        if reference and con.execute('SELECT 1 FROM topup_requests WHERE transfer_reference=?',(reference,)).fetchone():
            raise WalletError(409,'Bu tushum boshqa so‘rovda ishlatilgan')
        if decision=='approve':
            post_entry(con,row['user_id'],row['amount_minor'],'topup','topup:'+row['id'],uid,reason)
        con.execute('UPDATE topup_requests SET status=?,transfer_reference=?,reviewed_by=?,review_reason=?,reviewed_at=? WHERE id=?',
                    (status,reference,uid,reason,now(),row['id']))
        con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(uid,'topup-'+decision,row['id']+': '+reason,now()))
        notifications.publish(con,row['user_id'],'topup-review:'+row['id'],'wallet_topup',row['id'],status,reason)
        con.commit()
        handler.reply(200,{'topup':topup_view(con.execute('SELECT * FROM topup_requests WHERE id=?',(row['id'],)).fetchone(),admin=True)})
        return True
    return False
