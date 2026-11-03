"""Shared read-only capacity calculation; acceptance runs it under its write lock."""
from datetime import timezone


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


def peak_usage(sweep):
    occupied=peak=0
    for _,delta in sorted(sweep):
        occupied+=delta
        peak=max(peak,occupied)
    return peak


def occupancies(con, sitters, start, end, now, *, exclude=''):
    """Read a catalog batch (or one sitter during acceptance) in the caller's transaction."""
    owners = tuple(dict.fromkeys(sitters))
    if not owners:
        return {}
    slots = ','.join('?' for _ in owners)
    overdue = {row[0] for row in con.execute(
        f"SELECT DISTINCT sitter_id FROM bookings WHERE sitter_id IN ({slots}) "
        "AND id!=? AND status='active' AND ends_at<=?", (*owners,exclude,stamp(now)))}
    result = dict.fromkeys(overdue)
    eligible = [owner for owner in owners if owner not in overdue]
    if not eligible:
        return result
    slots = ','.join('?' for _ in eligible)
    lower, upper = stamp(start), stamp(end)
    services = {owner:set() for owner in eligible}
    sweeps = {owner:[] for owner in eligible}
    rows = con.execute(f"""SELECT b.sitter_id,b.starts_at,b.ends_at,b.service,COUNT(a.animal_id) animals
        FROM bookings b JOIN booking_animals a ON a.booking_id=b.id
        WHERE b.sitter_id IN ({slots}) AND b.id!=? AND b.status IN ('accepted','active','disputed')
        AND b.starts_at<? AND b.ends_at>? GROUP BY b.id""", (*eligible,exclude,upper,lower))
    for row in rows:
        owner = row['sitter_id']
        services[owner].add(row['service'])
        sweeps[owner].extend([(max(lower,row['starts_at']),row['animals']),
                              (min(upper,row['ends_at']),-row['animals'])])
    result.update((owner,(services[owner],peak_usage(sweeps[owner]))) for owner in eligible)
    return result


def free_places(usage, service, capacity):
    if usage is None:
        return 0
    services,peak = usage
    if services and (service=='homeVisit' or services!={service}):
        return 0
    return max(0,capacity-peak)


def occupancy(con, sitter, start, end, now, *, exclude=''):
    return occupancies(con,(sitter,),start,end,now,exclude=exclude)[sitter]


def remaining(con, sitter, service, start, end, capacity, now, *, exclude=''):
    return free_places(occupancy(con,sitter,start,end,now,exclude=exclude),service,capacity)
