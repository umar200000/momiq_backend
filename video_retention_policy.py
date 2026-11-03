"""Standard-library-only policy shared by the API and standalone backup job."""
from datetime import datetime, timedelta


def expires_at(con, booking):
    row=con.execute('SELECT status,updated FROM bookings WHERE id=?',(booking,)).fetchone()
    if not row or row['status'] not in ('completed','cancelled','rejected','expired'):return None
    dispute=con.execute('SELECT status,resolved_at FROM booking_disputes WHERE booking_id=?',(booking,)).fetchone()
    if dispute and dispute['status']=='open':return None
    anchor=datetime.fromisoformat(row['updated'])
    if dispute and dispute['resolved_at']:anchor=max(anchor,datetime.fromisoformat(dispute['resolved_at']))
    return anchor+timedelta(days=30)
