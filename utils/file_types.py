import enum
import mimetypes
from functools import reduce
from operator import or_
from pathlib import Path

import strawberry
from django.db.models import Q


@strawberry.enum
class FileTypeEnum(enum.Enum):
    PDF = "pdf"
    WORD = "word"
    EXCEL = "excel"
    CSV = "csv"
    IMAGE = "image"


FILE_TYPE_EXTENSIONS: dict[FileTypeEnum, tuple[str, ...]] = {
    FileTypeEnum.PDF: ("pdf",),
    FileTypeEnum.WORD: ("doc", "docx"),
    FileTypeEnum.EXCEL: ("xls", "xlsx", "xlsm"),
    FileTypeEnum.CSV: ("csv",),
    FileTypeEnum.IMAGE: ("png", "jpg", "jpeg"),
}


# Python's built-in table misses Office types when the OS has no /etc/mime.types (slim images).
_CONTENT_TYPES: dict[str, str] = {
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
}


def guess_content_type(name: str) -> str | None:
    """MIME type guessed from the file name's extension (no storage call)."""
    extension = Path(name).suffix[1:].lower()
    return _CONTENT_TYPES.get(extension) or mimetypes.guess_type(name)[0]


def file_type_q(field: str, file_types: list[FileTypeEnum]) -> Q:
    """Q matching rows whose `field` file name ends with any extension of `file_types`.

    Based on the stored file name, so no storage call is made.
    """
    extensions = {ext for file_type in file_types for ext in FILE_TYPE_EXTENSIONS[file_type]}
    if not extensions:
        return Q()
    return reduce(or_, (Q(**{f"{field}__iendswith": f".{ext}"}) for ext in sorted(extensions)))
