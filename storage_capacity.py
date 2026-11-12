"""Admission checks for private media; not a quota or disk-space reservation."""
from pathlib import Path
import shutil

MIB = 1024 * 1024
RESERVE_BYTES = 256 * MIB
UNAVAILABLE = 'Saqlash xizmati vaqtincha band. Birozdan so‘ng qayta urining.'


class StorageUnavailable(Exception):
    def __init__(self):
        super().__init__(UNAVAILABLE)


def require_space(root, additional_bytes):
    if type(additional_bytes) is not int or additional_bytes < 0:
        raise ValueError('Invalid storage estimate')
    try:
        available = shutil.disk_usage(Path(root)).free
    except OSError as error:
        raise StorageUnavailable() from error
    if available < RESERVE_BYTES + additional_bytes:
        raise StorageUnavailable()


def receipt_space(root, receipt):
    # Current receipt + immutable claim, with room for SQLite pages/journaling.
    # This is a conservative preflight, not a guarantee against concurrent writes.
    if root is not None:
        require_space(root, 6 * len(receipt) + MIB)
