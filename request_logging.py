"""Low-cardinality access diagnostics: never record raw URLs or remote identities."""
import json

CLIENT_GROUPS=frozenset(('auth','me','sitters','bookings','wallet','conversations','notifications','support','health'))
ADMIN_GROUPS=frozenset(('login','logout','users','sitters','listings','topups','settings','bookings','support','disputes','reviews','chat-reports'))
METHODS=frozenset(('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'))


def access_record(method,path,status):
    parts=str(path).split('?',1)[0].split('#',1)[0].split('/')
    group='other'
    if len(parts)>2 and parts[0]=='' and parts[1]=='api':
        if parts[2]=='admin':
            group='admin/'+(parts[3] if len(parts)>3 and parts[3] in ADMIN_GROUPS else 'other')
        else:group=parts[2] if parts[2] in CLIENT_GROUPS else 'other'
    elif len(parts)>1 and parts[0]=='' and parts[1]=='admin':group='admin-assets'
    try:code=int(status)
    except (TypeError,ValueError):code=0
    return json.dumps({'event':'http','method':method if method in METHODS else 'OTHER',
                       'group':group,'status':code if 100<=code<=599 else 0},separators=(',',':'))
