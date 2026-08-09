from __future__ import annotations

import mimetypes
from pathlib import Path


# Python delegates part of its MIME database to the operating system. Windows
# commonly calls ZIP files application/x-zip-compressed while Linux generally
# returns application/zip. Keep archive metadata stable across fsociety builds
# so recipients see the same type regardless of the sender's platform.
ARCHIVE_MIME_TYPES = {
    ".zip": "application/zip",
    ".rar": "application/vnd.rar",
}


def guess_attachment_mime(path: str | Path) -> str:
    suffix = Path(path).suffix.casefold()
    if suffix in ARCHIVE_MIME_TYPES:
        return ARCHIVE_MIME_TYPES[suffix]
    return (mimetypes.guess_type(str(path))[0] or "application/octet-stream").lower()

