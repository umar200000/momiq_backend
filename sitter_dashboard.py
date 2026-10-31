"""Bounded sitter overview from one database snapshot; never invents care progress."""
import json
from datetime import timedelta, timezone

import booking_rules as rules
import catalog
import wallet


def overview(con, user, now):
    wallet.require_sitter(con,user)
    if not con.in_transaction: con.execute('BEGIN')
    account,_=catalog.account_for(con,user)
    listing=catalog.document(con,user)
    current=rules.utc(now)
    local=current.astimezone(timezone(timedelta(hours=5)))
    start=local.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    end=start+timedelta(days=1)
    # Booking timestamps use engine.stamp's canonical UTC representation.
    from booking_engine import stamp as booking_stamp
    now_text=booking_stamp(current)
    counts=dict(con.execute("SELECT status,COUNT(*) FROM bookings WHERE sitter_id=? AND (status!='pending' OR reply_deadline>?) GROUP BY status",(user,now_text)))
    active_pets=con.execute("SELECT COUNT(*) FROM booking_animals a JOIN bookings b ON b.id=a.booking_id WHERE b.sitter_id=? AND b.status='active'",(user,)).fetchone()[0]
    def summaries(clause,args,order):
        rows=con.execute('SELECT b.id,b.status,b.starts_at,b.ends_at,b.service,q.snapshot FROM bookings b JOIN booking_quotes q ON q.id=b.quote_id WHERE b.sitter_id=? AND '+clause+' ORDER BY '+order+' LIMIT 6',(user,*args)).fetchall()
        items=[]
        for row in rows[:5]:
            snapshot=json.loads(row['snapshot'])
            items.append({'id':row['id'],'status':row['status'],'startsAt':row['starts_at'],'endsAt':row['ends_at'],
                          'service':row['service'],'peerName':snapshot['customerName'],
                          'petNames':[p.get('name') or p['type'] for p in snapshot['pets']],
                          'overdue':row['status']=='active' and row['ends_at']<=now_text})
        return {'items':items,'hasMore':len(rows)>5}
    upcoming=summaries("b.status='accepted' AND b.starts_at>?",[now_text],'b.starts_at,b.seq')
    today=summaries("b.status IN ('accepted','active','disputed') AND ((b.starts_at<? AND b.ends_at>?) OR (b.status='active' AND b.ends_at<=?))",
                    [booking_stamp(end),booking_stamp(start),now_text],'b.starts_at,b.seq')
    services=[{'service':i['type'],'active':i['active'],**listing['moderation'][i['type']],
               'missing':catalog.completeness(account,i)} for i in listing['listings']]
    value=wallet.balance(con,user)
    return {'asOf':current.isoformat(),'timezone':'Asia/Tashkent','localDate':local.date().isoformat(),
            'profilePresent':bool(account.get('sitterProfile')),'identityVerification':'not_integrated',
            'balanceMinor':value,'minimumBalanceMinor':wallet.MINIMUM_BALANCE_MINOR,
            'balanceEligible':value>=wallet.MINIMUM_BALANCE_MINOR,
            'pendingCount':counts.get('pending',0),'activeBookingCount':counts.get('active',0),
            'activePetCount':active_pets,'disputedCount':counts.get('disputed',0),
            'listings':services,'upcoming':upcoming,'today':today}
