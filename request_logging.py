"""Low-cardinality access diagnostics: never record raw URLs or remote identities."""
import json
import math

CLIENT_GROUPS=frozenset(('auth','me','sitters','bookings','wallet','conversations','notifications','support','health','ready'))
ADMIN_GROUPS=frozenset(('login','logout','me','users','sitters','listings','topups','settings','platform-settings','bookings','support','disputes','reviews','chat-reports','metrics','metrics.csv','work-queue'))
METHODS=frozenset(('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'))
OUTCOMES=frozenset(('ok','rejected','invalid_input','database_busy','media_busy','disconnected','server_error'))


def access_record(method,path,status,*,elapsed_seconds=None,outcome=None):
    parts=str(path).split('?',1)[0].split('#',1)[0].split('/')
    group='other'
    if len(parts)>2 and parts[0]=='' and parts[1]=='api':
        if parts[2]=='admin':
            group='admin/'+(parts[3] if len(parts)>3 and parts[3] in ADMIN_GROUPS else 'other')
        else:group=parts[2] if parts[2] in CLIENT_GROUPS else 'other'
    elif len(parts)>1 and parts[0]=='' and parts[1]=='admin':group='admin-assets'
    try:code=int(status)
    except (TypeError,ValueError):code=0
    result={'event':'http','method':method if method in METHODS else 'OTHER',
            'group':group,'status':code if 100<=code<=599 else 0}
    if elapsed_seconds is not None:
        result['durationMs']=(round(min(elapsed_seconds,86400)*1000,2)
                              if type(elapsed_seconds) in (int,float) and math.isfinite(elapsed_seconds) and elapsed_seconds>=0 else None)
    if outcome is not None:result['outcome']=outcome if outcome in OUTCOMES else 'server_error'
    return json.dumps(result,separators=(',',':'))
