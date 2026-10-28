"""Append-only compensation for an erroneously approved incoming top-up."""
import re
import secrets
from urllib.parse import parse_qs, urlparse
import notifications
import wallet


def total(con, topup):
    return con.execute('SELECT COALESCE(SUM(amount_minor),0) FROM wallet_corrections WHERE topup_id=?', (topup,)).fetchone()[0]


def view(row):
    return {key: row[column] for key, column in (
        ('id','id'), ('topupId','topup_id'), ('originalEntryId','original_entry_id'),
        ('entryId','entry_id'), ('amountMinor','amount_minor'), ('actor','actor'),
        ('reason','reason'), ('created','created'))}


def correct(con, actor, topup, data):
    # The caller owns commit/rollback; publication, debit and evidence are atomic.
    if not con.in_transaction: raise RuntimeError('Correction requires a write transaction')
    if set(data) != {'amountMinor','reason','requestId','expectedCorrectedMinor'}:
        raise ValueError('Tuzatish maydonlari noto‘g‘ri')
    value=wallet.amount(data['amountMinor'])
    reason=wallet.text(data['reason'],1000)
    request=wallet.text(data['requestId'],100)
    expected=data['expectedCorrectedMinor']
    if type(expected) is not int or not 0 <= expected <= 100_000_000_000:
        raise ValueError('Tuzatish versiyasi noto‘g‘ri')
    previous=con.execute('SELECT * FROM wallet_corrections WHERE request_id=?',(request,)).fetchone()
    if previous:
        if (previous['topup_id'],previous['actor'],previous['amount_minor'],previous['reason'],previous['expected_minor']) != (topup,actor,value,reason,expected):
            raise wallet.WalletError(409,'Tuzatish identifikatori boshqa ma’lumot bilan ishlatilgan')
        return view(previous)
    row=con.execute('SELECT * FROM topup_requests WHERE id=?',(topup,)).fetchone()
    if not row: raise wallet.WalletError(404,'Tushum topilmadi')
    original=con.execute("SELECT * FROM wallet_entries WHERE source_key=? AND kind='topup'",('topup:'+topup,)).fetchone()
    if (row['status']!='approved' or not original or original['user_id']!=row['user_id']
            or original['amount_minor']!=row['amount_minor']):
        raise wallet.WalletError(409,'Faqat tasdiqlangan asl tushumni tuzatish mumkin')
    corrected=total(con,topup)
    if corrected!=expected:
        raise wallet.WalletError(409,'Tushum allaqachon tuzatilgan. Tarixni qayta yuklang.')
    if value > original['amount_minor']-corrected:
        raise wallet.WalletError(409,'Tuzatish asl tushumning qolgan summasidan oshmasin')
    if wallet.balance(con,row['user_id']) < value:
        raise wallet.WalletError(409,'Balans yetarli emas. Tuzatish bajarilmadi; yordam xizmati orqali ko‘rib chiqing.')
    identity=secrets.token_hex(16)
    entry=wallet.post_entry(con,row['user_id'],-value,'topup_correction','topup-correction:'+identity,actor,reason)
    created=wallet.now()
    con.execute('INSERT INTO wallet_corrections VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (identity,topup,original['id'],entry,value,expected,request,actor,reason,created,row['user_id']))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
                (actor,'topup-correction',topup+':'+identity,created))
    notifications.publish(con,row['user_id'],'topup-correction:'+identity,'wallet_topup',topup,'corrected',reason)
    return view(con.execute('SELECT * FROM wallet_corrections WHERE id=?',(identity,)).fetchone())


def route(handler, con, actor, path):
    match=re.fullmatch(r'/api/(admin|wallet)/topups/([a-f0-9]{32})/corrections',path)
    if not match: return False
    admin=match[1]=='admin'
    if handler.command=='POST' and admin:
        data=handler.body()
        con.execute('BEGIN IMMEDIATE')
        result=correct(con,actor,match[2],data)
        con.commit()
        handler.reply(200,{'correction':result})
        return True
    if handler.command!='GET': raise wallet.WalletError(405,'Amal ruxsat etilmagan')
    query=parse_qs(urlparse(handler.path).query,keep_blank_values=True)
    before=query.get('before',[None])[0]
    if set(query)-{'before'} or any(len(values)!=1 for values in query.values()) or (before is not None and not re.fullmatch('[a-f0-9]{32}',before)):
        raise ValueError('Tarix cursori noto‘g‘ri')
    con.execute('BEGIN')
    row=con.execute('SELECT * FROM topup_requests WHERE id=?',(match[2],)).fetchone()
    if not row or (not admin and row['user_id']!=actor): raise wallet.WalletError(404,'Tushum topilmadi')
    if not admin: wallet.require_sitter(con,actor)
    args=[row['id']]; clause=''
    if before:
        cursor=con.execute('SELECT created,id FROM wallet_corrections WHERE id=? AND topup_id=?',(before,row['id'])).fetchone()
        if not cursor: raise wallet.WalletError(400,'Tarix cursori noto‘g‘ri')
        clause=' AND (created,id)<(?,?)'; args.extend(cursor)
    rows=con.execute('SELECT * FROM wallet_corrections WHERE topup_id=?'+clause+' ORDER BY created DESC,id DESC LIMIT 21',args).fetchall()
    items=[view(item) for item in rows[:20]]
    if not admin:
        for item in items: item.pop('actor')
    handler.reply(200,{'items':items,'nextCursor':rows[19]['id'] if len(rows)>20 else None,
                       'correctedMinor':total(con,row['id']), 'originalAmountMinor':row['amount_minor'],
                       'balanceMinor':wallet.balance(con,row['user_id']), 'transferReference':row['transfer_reference'] if admin else None})
    return True
