import base64
import io
import struct
import unittest
import zlib
from unittest.mock import patch
from PIL import Image
from media_validation import validate_photo, public_photo, MAX_BYTES, MediaBusy


def fixture_image(color='red', format='PNG', size=(2, 2)):
    output=io.BytesIO()
    with Image.new('RGB',size,color) as image:
        image.save(output,format=format)
    return base64.b64encode(output.getvalue()).decode()


class MediaTests(unittest.TestCase):
    def test_public_derivative_strips_metadata_and_orients_without_changing_evidence(self):
        output=io.BytesIO()
        image=Image.new('RGB',(2000,1000),'red')
        exif=Image.Exif();exif[274]=6;exif[270]='PRIVATE ADDRESS';exif[315]='PRIVATE OWNER'
        image.save(output,format='JPEG',exif=exif)
        original=base64.b64encode(output.getvalue()).decode()
        result=public_photo(original)
        with Image.open(io.BytesIO(base64.b64decode(result))) as public:
            self.assertEqual(public.size,(640,1280))
            self.assertFalse(public.getexif())
            self.assertNotIn('exif',public.info)
        self.assertEqual(validate_photo(original),original)

    def test_real_formats_decode_and_evidence_is_unchanged(self):
        for format in ('PNG','JPEG','WEBP'):
            value=fixture_image(format=format)
            self.assertEqual(validate_photo(value),value)
        self.assertIsNone(validate_photo(None))

    def test_headers_truncation_unsupported_format_and_size_are_rejected(self):
        raw=base64.b64decode(fixture_image())
        for value in (base64.b64encode(b'\x89PNG\r\n\x1a\nnot-an-image').decode(),
                      base64.b64encode(raw[:40]).decode(), fixture_image(format='GIF'),
                      base64.b64encode(b'x'*(MAX_BYTES+1)).decode(), 'bad-base64'):
            with self.assertRaises(ValueError): validate_photo(value)
        with self.assertRaises(ValueError): validate_photo(fixture_image(size=(8193,1)))

    def test_pixel_bomb_is_rejected_before_decode(self):
        raw=bytearray(base64.b64decode(fixture_image()))
        raw[16:24]=struct.pack('>II',5000,5000)
        raw[29:33]=struct.pack('>I',zlib.crc32(raw[12:29]))
        with self.assertRaises(ValueError): validate_photo(base64.b64encode(raw).decode())

    def test_decoder_saturation_is_retryable(self):
        with patch('media_validation._decoders') as limiter:
            limiter.acquire.return_value=False
            with self.assertRaises(MediaBusy): validate_photo(fixture_image())
            limiter.release.assert_not_called()


if __name__=='__main__': unittest.main()
