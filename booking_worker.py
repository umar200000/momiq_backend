"""Bounded, replay-safe expiry worker. Only enabled for local/test bookings."""
from datetime import datetime, timezone
import logging
import threading

import booking_engine as engine


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
    return total


class ExpiryWorker:
    def __init__(self, db_factory, environment, interval=30):
        if environment not in ('local', 'test'):
            raise ValueError('Hosted booking worker is not enabled')
        self.db_factory, self.environment, self.interval = db_factory, environment, interval
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
            except Exception as error:
                # Do not log DB contents, account IDs, credentials or notes.
                logging.error('booking-expiry failed type=%s; retry on next tick', type(error).__name__)
            self.stopped.wait(self.interval)
