import threading
import unittest
from unittest.mock import patch

import booking_worker


class WorkerTests(unittest.TestCase):
    def test_transient_failure_retries_and_stop_wakes_sleep(self):
        reached=threading.Event()
        worker=booking_worker.ExpiryWorker(lambda:None,'local',interval=0.01)
        calls=[]
        def tick(*args):
            calls.append(1)
            if len(calls)==1:
                raise RuntimeError('TEST transient lock')
            reached.set()
            return 0
        with patch.object(booking_worker,'run_once',side_effect=tick):
            with self.assertLogs(level='ERROR') as logs:
                worker.start()
                try:
                    self.assertTrue(reached.wait(3))
                finally:
                    worker.stop()
        self.assertFalse(worker.thread.is_alive())
        self.assertGreaterEqual(len(calls),2)
        self.assertIn('RuntimeError',logs.output[0])
        self.assertNotIn('TEST transient lock',logs.output[0])

    def test_hosted_worker_is_not_silently_enabled(self):
        with self.assertRaises(ValueError):
            booking_worker.ExpiryWorker(lambda:None,'production')
