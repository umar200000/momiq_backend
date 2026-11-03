from datetime import datetime, timedelta, timezone
import unittest
import video_policy as video


class VideoPolicyTests(unittest.TestCase):
    def test_server_tashkent_windows_and_exact_half_open_boundaries(self):
        for slot, hour in [('morning', 2), ('evening', 13)]:
            start = datetime(2027, 1, 2, hour, tzinfo=timezone.utc)
            video.require_window('2027-01-02', slot, start)
            video.require_window('2027-01-02', slot, start+timedelta(hours=4)-timedelta(microseconds=1))
            for moment in [start-timedelta(microseconds=1), start+timedelta(hours=4)]:
                with self.assertRaises(ValueError): video.require_window('2027-01-02', slot, moment)
            with self.assertRaises(ValueError): video.require_window('2027-01-01', slot, start)
        self.assertEqual(video.policy(datetime(2027,1,1,19,tzinfo=timezone.utc))['today'], '2027-01-02')
        with self.assertRaises(ValueError): video.policy(datetime(2027,1,1))

    def test_measured_duration_inclusive_bounds_and_invalid_values(self):
        self.assertEqual(video.duration_ms('10.000'),10000)
        self.assertEqual(video.duration_ms(60),60000)
        for value in ['9.999999','60.000001','NaN','Infinity',None,True,'junk']:
            with self.assertRaises(ValueError): video.duration_ms(value)
