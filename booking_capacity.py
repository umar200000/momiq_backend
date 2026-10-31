"""Shared read-only capacity calculation; acceptance runs it under its write lock."""
from datetime import timezone


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


def occupancy(con, sitter, start, end, now, *, exclude=''):
    if con.execute("SELECT 1 FROM bookings WHERE sitter_id=? AND id!=? AND status='active' AND ends_at<=? LIMIT 1",
                   (sitter,exclude,stamp(now))).fetchone():
        return None
    lower,upper = stamp(start),stamp(end)
    rows=con.execute("SELECT b.starts_at,b.ends_at,b.service,COUNT(a.animal_id) animals FROM bookings b JOIN booking_animals a ON a.booking_id=b.id WHERE b.sitter_id=? AND b.id!=? AND b.status IN ('accepted','active','disputed') AND b.starts_at<? AND b.ends_at>? GROUP BY b.id",
                     (sitter,exclude,upper,lower)).fetchall()
    services = {row['service'] for row in rows}
    sweep=[]
    for row in rows:
        sweep.extend([(max(lower,row['starts_at']),row['animals']),
                      (min(upper,row['ends_at']),-row['animals'])])
    occupied=peak=0
    for _,delta in sorted(sweep,key=lambda item:(item[0],item[1])):
        occupied+=delta
        peak=max(peak,occupied)
    return services,peak


def free_places(usage, service, capacity):
    if usage is None:
        return 0
    services,peak = usage
    if services and (service=='homeVisit' or services!={service}):
        return 0
    return max(0,capacity-peak)


def remaining(con, sitter, service, start, end, capacity, now, *, exclude=''):
    return free_places(occupancy(con,sitter,start,end,now,exclude=exclude),service,capacity)
