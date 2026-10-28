import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import video_media as media


class VideoMediaTests(unittest.TestCase):
    def test_real_decode_derivatives_duration_and_private_metadata_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.mp4'
            subprocess.run([media.executable('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=blue:s=128x96:r=24',
                            '-t','10','-c:v','libx264','-metadata','comment=PRIVATE TEST GPS','-metadata','location=+41.3123+069.2789/',
                            '-pix_fmt','yuv420p',str(source)],check=True,timeout=20,
                           creationflags=subprocess.CREATE_NO_WINDOW if media.os.name=='nt' else 0)
            result=media.prepare(source,root)
            self.assertEqual(result['durationMs'],10000)
            self.assertTrue(result['posterFile'].is_file())
            self.assertLess(result['bytes'],media.video_policy.MAX_BYTES)
            tags=media.run('ffprobe',['-i',str(result['videoFile']),'-show_entries','format_tags:stream_tags','-of','json'])
            self.assertNotIn('PRIVATE',tags.decode())
            self.assertNotIn('41.3123',tags.decode())
            self.assertEqual(result['sourceHash'],media.sha256(source))

    def test_invalid_media_size_container_and_busy_never_creates_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'fake.mp4'
            source.write_bytes(b'not a real video file')
            with self.assertRaises(ValueError):media.prepare(source,root)
            source.write_bytes(b'\0\0\0\x18ftypisom'+b'\0'*24)
            with self.assertRaises(ValueError):media.prepare(source,root)
            self.assertFalse((root/'playback.mp4').exists())
            media._workers.acquire();media._workers.acquire()
            try:
                with self.assertRaises(media.VideoUnavailable):media.prepare(source,root)
            finally:media._workers.release();media._workers.release()

    def test_probe_rejects_spoofed_limits_and_unsupported_codec(self):
        base={'codec_type':'video','codec_name':'h264','width':1920,'height':1080,'duration':'10','avg_frame_rate':'24/1'}
        for change in [{'duration':'60.01'},{'width':3840},{'codec_name':'vp9'}, {'avg_frame_rate':'120/1'}, {'avg_frame_rate':'1/0'}]:
            with patch.object(media,'run',return_value=json.dumps({'streams':[dict(base,**change)]}).encode()):
                with self.assertRaises(ValueError):media.probe(Path('not-opened'))
