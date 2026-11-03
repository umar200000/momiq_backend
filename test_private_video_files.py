import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from booking_videos import open_derivative
from video_media import VideoUnavailable


class PrivateVideoFileTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'data'
        self.video = 'a' * 32
        self.folder = self.root / 'care-videos' / self.video
        self.folder.mkdir(parents=True)
        self.external = Path(temp.name) / 'sensitive'
        self.external.write_bytes(b'PRIVATE')

    def test_regular_playback_and_poster_only(self):
        for kind, name in [('playback', 'playback.mp4'), ('poster', 'poster.jpg')]:
            (self.folder / name).write_bytes(name.encode())
            with open_derivative(self.root, self.video, kind) as stream:
                self.assertEqual(stream.read(), name.encode())
        for identity, kind in [(self.video, '../sensitive'), ('../sensitive', 'poster')]:
            with self.assertRaises(VideoUnavailable), open_derivative(self.root, identity, kind):
                self.fail('Unexpected file opened')

    def test_hard_link_is_not_private_media(self):
        os.link(self.external, self.folder / 'playback.mp4')
        with self.assertRaises(VideoUnavailable), open_derivative(self.root, self.video, 'playback'):
            self.fail('Unexpected hard link opened')

    @unittest.skipUnless(os.name == 'posix', 'POSIX descriptor traversal')
    def test_linked_folder_linked_file_and_fifo_fail_without_reading(self):
        import video_media
        target = self.folder / 'poster.jpg'
        target.symlink_to(self.external)
        with self.assertRaises(VideoUnavailable), open_derivative(self.root, self.video, 'poster'):
            self.fail('Unexpected link opened')
        target.unlink()
        os.mkfifo(target)
        with self.assertRaises(VideoUnavailable), open_derivative(self.root, self.video, 'poster'):
            self.fail('Unexpected nonregular file opened')
        linked = self.folder.parent / ('b' * 32)
        linked.symlink_to(self.folder, target_is_directory=True)
        with self.assertRaises(VideoUnavailable), open_derivative(self.root, linked.name, 'poster'):
            self.fail('Unexpected linked folder opened')
        alternate = self.root/'other-instance'
        alternate.mkdir()
        (alternate/'care-videos').symlink_to(self.folder.parent,target_is_directory=True)
        with self.assertRaises(VideoUnavailable):
            video_media.private_directory(alternate)
