"""Server-resolved public-text references; no private documents or media custody."""
import json
import re

import booking_engine as engine
import booking_reviews
import catalog


def validate(value):
    if (not isinstance(value,dict) or set(value)!={'kind','id'}
            or value['kind'] not in ('listing','review') or not isinstance(value['id'],str)):
        raise ValueError('Invalid support target')
    pattern=r'[^/:\s]{1,100}:(?:boarding|homeVisit|personal)' if value['kind']=='listing' else r'[1-9][0-9]{0,17}'
    if not re.fullmatch(pattern,value['id']):raise ValueError('Invalid support target identity')


def capture(con,target,environment):
    # Inside the ticket transaction: never accept a client-supplied snapshot.
    validate(target)
    identity=target['id']
    if target['kind']=='listing':
        item=catalog.profile(con,environment,identity)
        if not item:raise engine.BookingError(404,'E’lon topilmadi')
        snapshot={k:item[k] for k in ('name','about','service','price','priceUnit','pets','capacity','years','testOnly')}
        snapshot['revision']=catalog.revision(con,item['userId'])
    else:
        row=con.execute('SELECT * FROM booking_reviews WHERE id=? AND hidden=0 AND withdrawn=0',(int(identity),)).fetchone()
        if (not row or (environment=='production' and row['test_only'])
                or not catalog.profile(con,environment,row['sitter_id']+':'+row['service'])):
            raise engine.BookingError(404,'Sharh topilmadi')
        snapshot=booking_reviews.public(row)
        snapshot['listingId']=row['sitter_id']+':'+row['service']
    return snapshot


def attach(con,ticket_id,target,snapshot,created):
    con.execute('INSERT INTO support_targets VALUES(?,?,?,?,?)',
                (ticket_id,target['kind'],target['id'],engine.encode(snapshot),created))


def detail(con,ticket_id):
    row=con.execute('SELECT * FROM support_targets WHERE ticket_id=?',(ticket_id,)).fetchone()
    if not row:return None
    return {'kind':row['kind'],'id':row['target_id'],'snapshot':json.loads(row['snapshot']),'capturedAt':row['created']}
