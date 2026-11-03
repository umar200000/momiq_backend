"""Approved booking arithmetic/deadlines used by the transactional booking API.

The server calculates each started 24-hour period; no client-supplied total,
package, extra-animal discount or home-visit minute charge changes the price.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MINIMUM_BALANCE_MINOR = 1_500_000
MAX_MONEY_MINOR = 100_000_000_000
SERVICES = ('boarding', 'homeVisit', 'personal')


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Expected bounded integer')
    return value


def utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware time required')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class AnimalRate:
    animal_id: str
    daily_minor: int


@dataclass(frozen=True)
class PriceSnapshot:
    service: str
    rates: tuple[AnimalRate, ...]
    billable_days: int
    service_total_minor: int
    commission_bps: int
    commission_minor: int
    settings_version: int
    rounding: str = 'nearest_minor_half_up'


def price_snapshot(service, rates, billable_days, commission_bps, settings_version):
    """Snapshot one daily rate per selected animal; no packages/extra-pet discount."""
    if service not in SERVICES:
        raise ValueError('Unknown service')
    if not isinstance(rates, (tuple, list)) or not rates:
        raise ValueError('Select animals')
    if service == 'personal' and len(rates) != 1:
        raise ValueError('Personal sitter accepts exactly one animal')
    days = integer(billable_days, 1, 366)
    bps = integer(commission_bps, 0, 10000)
    version = integer(settings_version, 1, 2**53-1)
    copied = []
    identifiers = set()
    for rate in rates:
        if not isinstance(rate, AnimalRate) or not isinstance(rate.animal_id, str) or not rate.animal_id or len(rate.animal_id)>100:
            raise ValueError('Invalid animal rate')
        if rate.animal_id in identifiers:
            raise ValueError('Duplicate animal')
        identifiers.add(rate.animal_id)
        copied.append(AnimalRate(rate.animal_id, integer(rate.daily_minor, 1, MAX_MONEY_MINOR)))
    total = integer(sum(r.daily_minor for r in copied)*days, 1, MAX_MONEY_MINOR)
    # Round once on the total, not per animal/day. Pure integer arithmetic.
    commission = (total*bps + 5000)//10000
    return PriceSnapshot(service, tuple(copied), days, total, bps, commission, version)


def acceptance_requirement(snapshot):
    return max(MINIMUM_BALANCE_MINOR, snapshot.commission_minor)


def balance_after_acceptance(balance_minor, snapshot):
    balance = integer(balance_minor, 0, MAX_MONEY_MINOR)
    if balance < acceptance_requirement(snapshot):
        raise ValueError('Balance is below minimum or commission')
    return balance - snapshot.commission_minor


def reply_deadline(created_at, starts_at):
    created, start = utc(created_at), utc(starts_at)
    if start <= created:
        raise ValueError('Service must start in the future')
    return min(created + timedelta(hours=2), start)


def billable_days(starts_at, ends_at):
    """Each started 24 hours is one day; exact integer microsecond arithmetic."""
    duration = utc(ends_at) - utc(starts_at)
    if duration <= timedelta(0) or duration > timedelta(days=366):
        raise ValueError('Service must last between zero and 366 days')
    micros = (duration.days*86400 + duration.seconds)*1_000_000 + duration.microseconds
    day = 86400*1_000_000
    return (micros + day - 1)//day


def expired(deadline, now):
    return utc(now) >= utc(deadline)


def late_cancellation(starts_at, cancelled_at):
    remaining = utc(starts_at)-utc(cancelled_at)
    return timedelta(0) <= remaining < timedelta(hours=24)


def cancellation_commission_refund(snapshot, status, starts_at, cancelled_at):
    """None requires admin adjudication. This never refunds customer service money."""
    if status in ('pending', 'rejected', 'expired'):
        return 0
    if status == 'accepted' and utc(cancelled_at) < utc(starts_at):
        return snapshot.commission_minor
    if status in ('accepted', 'active', 'disputed'):
        return None
    raise ValueError('Terminal/unknown booking cannot be cancelled again')


def no_show_stage(starts_at, now, *, service_started):
    if type(service_started) is not bool:
        raise ValueError('Explicit service state required')
    if service_started:
        return 'not_applicable'
    delay = utc(now)-utc(starts_at)
    if delay >= timedelta(minutes=30):
        return 'complaint_available'
    if delay >= timedelta(minutes=15):
        return 'contact_reminder'
    return 'waiting'


def no_show_review_deadline(reported_at):
    return utc(reported_at) + timedelta(hours=48)


@dataclass(frozen=True)
class Incident:
    booking_id: str
    occurred_at: datetime
    kind: str
    confirmed: bool
    excused_emergency: bool


def incidents_for_review(incidents, now):
    """Three distinct bookings in a rolling 30-day window; no automatic penalty."""
    end = utc(now); start = end-timedelta(days=30)
    counted = set()
    for incident in incidents:
        if not isinstance(incident, Incident) or not incident.booking_id:
            raise ValueError('Invalid incident')
        moment = utc(incident.occurred_at)
        if (start <= moment <= end and not incident.excused_emergency
                and incident.kind in ('late_cancellation','no_show') and incident.confirmed):
            counted.add(incident.booking_id)
    return {'bookingIds': sorted(counted), 'reviewRequired': len(counted)>=3}
