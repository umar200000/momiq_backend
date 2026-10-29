"""Permission-scoped aggregate oversight; no row-level personal-data export."""
import csv
from datetime import datetime,timezone
from io import StringIO
from urllib.parse import urlparse

import booking_engine as engine


def counts(con,table,statuses):
    # Callers supply fixed internal table/status names, never request values.
    rows=dict(con.execute('SELECT status,COUNT(*) FROM '+table+' GROUP BY status'))
    return {status:rows.get(status,0) for status in statuses}


def age(con,table,status,now):
    value=con.execute('SELECT MIN(created) FROM '+table+' WHERE status=?',(status,)).fetchone()[0]
    if not value:return None
    created=datetime.fromisoformat(value)
    if created.tzinfo is None:created=created.replace(tzinfo=timezone.utc)
    return max(0,int((now-created).total_seconds()))


def snapshot(con,role,now):
    if role not in ('finance','administrator'):raise engine.BookingError(403,'Ko‘rsatkichlar uchun huquq yo‘q')
    con.execute('BEGIN')
    totals=dict(con.execute('SELECT kind,SUM(amount_minor) FROM wallet_entries GROUP BY kind'))
    result={'asOf':now.isoformat(),'period':'all_time','scope':role,'currency':'UZS','minorUnitScale':100,
        'wallet':{'topupCreditedMinor':str(totals.get('topup',0)),'commissionDebitedMinor':str(-totals.get('commission',0)),
                  'commissionRefundedMinor':str(totals.get('commission_refund',0)),'correctionDebitedMinor':str(-totals.get('topup_correction',0)),
                  'totalBalanceMinor':str(con.execute('SELECT COALESCE(SUM(balance_minor),0) FROM wallet_accounts').fetchone()[0])},
        'topups':counts(con,'topup_requests',('pending','needs_info','approved','rejected')),
        'oldestPendingTopupSeconds':age(con,'topup_requests','pending',now)}
    if role=='administrator':
        response=con.execute("SELECT COUNT(delay),CAST(ROUND(AVG(delay)) AS INTEGER) FROM (SELECT MAX(0,(julianday(MIN(m.created))-julianday(t.created))*86400) delay FROM support_tickets t JOIN support_messages m ON m.ticket_id=t.id AND m.author_role='support' GROUP BY t.id)").fetchone()
        result.update(bookings=counts(con,'bookings',('pending','accepted','active','disputed','completed','cancelled','rejected','expired')),
            support=counts(con,'support_tickets',('open','waiting_user','resolved')),
            oldestOpenSupportSeconds=age(con,'support_tickets','open',now),
            disputes=counts(con,'booking_disputes',('open','resolved')),
            overdueDisputes=con.execute("SELECT COUNT(*) FROM booking_disputes WHERE status='open' AND deadline<=?",(now.isoformat(),)).fetchone()[0],
            respondedSupportTickets=response[0],averageSupportFirstResponseSeconds=response[1])
    con.commit()
    return result


def export(report):
    stream=StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['metric','value','unit','as_of_utc'])
    for group in ('wallet','topups','bookings','support','disputes'):
        for key,value in report.get(group,{}).items():
            writer.writerow([group+'.'+key,value,'UZS_minor' if group=='wallet' else 'count',report['asOf']])
    for key in ('oldestPendingTopupSeconds','oldestOpenSupportSeconds','overdueDisputes','respondedSupportTickets','averageSupportFirstResponseSeconds'):
        if key in report:writer.writerow([key,'' if report[key] is None else report[key],'seconds' if key.endswith('Seconds') else 'count',report['asOf']])
    return stream.getvalue().encode('utf-8-sig')


def route(handler,con,actor,path):
    if path not in ('/api/admin/metrics','/api/admin/metrics.csv'):return False
    if handler.command!='GET':raise engine.BookingError(405,'Faqat o‘qish mumkin')
    if urlparse(handler.path).query:raise ValueError('Aggregate report does not accept filters')
    now=datetime.now(timezone.utc)
    report=snapshot(con,handler.operator_role,now)
    # Audit after the read snapshot: a slow aggregate must not reserve the writer.
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',
        (actor,'metrics-export' if path.endswith('.csv') else 'metrics-read',handler.operator_role+':all_time',now.isoformat()))
    con.commit()
    if not path.endswith('.csv'):handler.reply(200,report);return True
    raw=export(report)
    handler.send_response(200)
    for key,value in (('Content-Type','text/csv; charset=utf-8'),('Content-Length',str(len(raw))),('Cache-Control','no-store'),
                      ('X-Content-Type-Options','nosniff'),('Content-Disposition','attachment; filename="momiq-aggregate-metrics.csv"')):
        handler.send_header(key,value)
    handler.end_headers();handler.wfile.write(raw)
    return True
