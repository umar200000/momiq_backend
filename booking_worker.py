"""Bounded, replay-safe expiry and no-show reminders for local/test bookings."""
from datetime import datetime, timedelta, timezone
import logging
import threading

import booking_engine as engine
import notifications


def remind_due(con, environment, current, stage, limit):
    """An alert is not a no-show finding and cannot change bookings or money."""
    messages={
        'contact_reminder': (15, 'Boshlanish tasdig‘i hali tugallanmagan. Ikkinchi tomon bilan bog‘laning.'),
        'complaint_available': (30, 'Boshlanish tasdig‘i hali tugallanmagan. Xizmat boshlanmagan bo‘lsa, buyurtma ichida kelmaslik haqida murojaat qilishingiz mumkin.'),
    }
    minutes,message=messages[stage]
    engine.begin(con)
    engine.test_gate(con,environment)
    cutoff=engine.stamp(current-timedelta(minutes=minutes))
    clause='';args=[cutoff]
    if stage=='contact_reminder':
        # After a restart later than 30 minutes, emit only the actionable alert.
        clause=' AND b.starts_at>?'
        args.append(engine.stamp(current-timedelta(minutes=30)))
    prefix='booking-reminder:'
    args.extend([prefix,':'+stage+':',prefix,':'+stage+':',limit])
    rows=con.execute("SELECT b.* FROM bookings b WHERE b.status='accepted' AND b.starts_at<=?"+clause+
        " AND (NOT EXISTS(SELECT 1 FROM notifications n WHERE n.source_key=?||b.id||?||b.customer_id) OR NOT EXISTS(SELECT 1 FROM notifications n WHERE n.source_key=?||b.id||?||b.sitter_id)) ORDER BY b.starts_at,b.id LIMIT ?",args).fetchall()
    for row in rows:
        for user in (row['customer_id'],row['sitter_id']):
            notifications.publish(con,user,f'{prefix}{row["id"]}:{stage}:{user}','booking',row['id'],stage,message)
    return len(rows)


def run_once(db_factory, environment, *, now=None, batch_size=200, max_batches=5):
    if environment not in ('local', 'test'):
        raise engine.BookingError(503, 'Booking worker is local/test only')
    engine.rules.integer(batch_size, 1, 1000)
    engine.rules.integer(max_batches, 1, 20)
    current = now or datetime.now(timezone.utc)
    total = 0
    for _ in range(max_batches):
        # Each batch is independently committed; restart/retry never duplicates
        # an event or its notices and never charges an expired request.
        with db_factory() as con:
            changed = engine.expire_due(con, environment=environment, now=current, limit=batch_size)
        total += changed
        if changed < batch_size:
            break
    for stage in ('contact_reminder','complaint_available'):
        for _ in range(max_batches):
            with db_factory() as con:
                changed=remind_due(con,environment,current,stage,batch_size)
            total+=changed
            if changed<batch_size:break
    return total


class ExpiryWorker:
    def __init__(self, db_factory, environment, interval=30, media_root=None):
        if environment not in ('local', 'test'):
            raise ValueError('Hosted booking worker is not enabled')
        self.db_factory, self.environment, self.interval = db_factory, environment, interval
        self.media_root = media_root
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name='booking-expiry', daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.thread.join(timeout=25)

    def run(self):
        while not self.stopped.is_set():
            try:
                count = run_once(self.db_factory, self.environment)
                if count:
                    logging.info('booking-expiry completed count=%s', count)
                if self.media_root is not None:
                    import video_retention
                    with self.db_factory() as con:
                        result=video_retention.cleanup(con,self.media_root,datetime.now(timezone.utc))
                    if result['failed']:
                        logging.error('video-retention pending failed=%s; retry next tick',result['failed'])
            except Exception as error:
                # Do not log DB contents, account IDs, credentials or notes.
                logging.error('booking-expiry failed type=%s; retry on next tick', type(error).__name__)
            self.stopped.wait(self.interval)
