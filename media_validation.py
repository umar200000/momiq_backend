"""Bounded decoding of upload images; never accept a magic header alone."""
import base64
import io
import threading
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_DIMENSION = 8192
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
_decoders = threading.BoundedSemaphore(2)


class MediaBusy(Exception):
    pass


def validate_photo(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > ((MAX_BYTES + 2) // 3) * 4:
        raise ValueError('Rasm 3 MB dan kichik bo‘lishi kerak')
    raw = base64.b64decode(value, validate=True)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('Rasm 3 MB dan kichik bo‘lishi kerak')
    if not _decoders.acquire(timeout=1):
        raise MediaBusy('Rasm tekshiruvi band. Qayta urinib ko‘ring.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=('PNG', 'JPEG', 'WEBP')) as image:
                if image.width * image.height > MAX_PIXELS or max(image.size) > MAX_DIMENSION:
                    raise ValueError('Rasm o‘lchami juda katta')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Animatsiyali rasm qabul qilinmaydi')
                image.verify()
            # verify() checks structure, load() also rejects corrupt/truncated pixel data.
            with Image.open(io.BytesIO(raw), formats=('PNG', 'JPEG', 'WEBP')) as image:
                image.load()
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise ValueError('To‘liq PNG, JPEG yoki WebP rasm yuboring') from error
    finally:
        _decoders.release()
    # Keep the submitted evidence bytes unchanged; metadata cleanup is a separate
    # public-derivative/storage operation, not a mutation of payment evidence.
    return value


def public_photo(value):
    """Generate a small, oriented discovery image without private EXIF/GPS data.

    Called on moderation approval, never on every public catalog request.
    Payment receipts and original uploads are untouched.
    """
    if value is None: return None
    validate_photo(value)
    if not _decoders.acquire(timeout=1):
        raise MediaBusy('Rasm tayyorlash band. Qayta urinib ko‘ring.')
    try:
        with Image.open(io.BytesIO(base64.b64decode(value))) as source:
            oriented = ImageOps.exif_transpose(source)
            oriented.thumbnail((1280,1280))
            clean = Image.new('RGB',oriented.size,'white')
            if 'A' in oriented.getbands():
                clean.paste(oriented.convert('RGB'),mask=oriented.getchannel('A'))
            else:
                clean.paste(oriented.convert('RGB'))
            output=io.BytesIO()
            clean.save(output,format='JPEG',quality=85)
            return base64.b64encode(output.getvalue()).decode('ascii')
    finally:
        _decoders.release()
