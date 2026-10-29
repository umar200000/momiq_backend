"""Least-privilege operator routes; unlisted methods and paths are denied."""
import re

ROLES=('support','moderation','finance','administrator')
PANELS={
    'support':('support','workQueue'),
    'moderation':('listings','chatReports','reviews','workQueue'),
    'finance':('topups','metrics'),
    'administrator':('users','sitters','listings','topups','chatReports','bookings','disputes','support','reviews','settings','metrics','workQueue'),
}
HEX=r'[a-f0-9]{32}'
NUMBER=r'[1-9][0-9]{0,17}'
RULES={
    'support':(
        ('GET',rf'work-queue(?:/support/{HEX})?'),
        ('POST',rf'work-queue/support/{HEX}'),
        ('GET',rf'support(?:/{HEX}(?:/messages/{NUMBER}/image)?)?'),
        ('POST',rf'support/{HEX}'),
    ),
    'moderation':(
        ('GET',r'work-queue(?:/(?:listing|chat_report)/[^/]{1,100})?'),
        ('POST',r'work-queue/(?:listing|chat_report)/[^/]{1,100}'),
        ('GET',r'listings(?:/[a-f0-9]{1,64}/(?:boarding|homeVisit|personal))?'),
        ('POST',r'listings/[a-f0-9]+/(?:boarding|homeVisit|personal)/review'),
        ('GET',rf'chat-reports(?:/{NUMBER}/(?:evidence|image))?'),
        ('POST',rf'chat-reports/{NUMBER}/review'),
        ('GET',rf'reviews(?:/{NUMBER}/history)?'),
        ('POST',rf'reviews/{NUMBER}/moderate'),
    ),
    'finance':(
        ('GET',r'metrics(?:\.csv)?'),
        ('GET',rf'topups(?:/{HEX}/(?:receipt|corrections|history(?:/[0-9]{{1,9}}/receipt)?))?'),
        ('POST',rf'topups/{HEX}/(?:review|corrections)'),
    ),
}


def role_for(con,username):
    row=con.execute('SELECT p.role FROM admin_permissions p JOIN admins a ON a.username=p.username WHERE p.username=? AND p.enabled=1',(username,)).fetchone()
    return row[0] if row and row[0] in ROLES else None


def permits(role,method,path):
    if role not in ROLES or not path.startswith('/api/admin/'):return False
    relative=path.removeprefix('/api/admin/')
    if (method,relative) in (('GET','me'),('POST','logout')):return True
    if role=='administrator':return True
    return any(method==allowed and re.fullmatch(pattern,relative) for allowed,pattern in RULES[role])


def identity(username,role):
    return {'username':username,'role':role,'panels':list(PANELS[role])}
