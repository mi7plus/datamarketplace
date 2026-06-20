# app/filesafety.py
#
# Upload safety: decide a file is a text dataset by its CONTENT, not its extension
# or client-supplied Content-Type (both trivially forged). A renamed executable,
# archive, image, or Office doc is refused before it is ever stored or served (S2).

from fastapi import HTTPException

# Binary magic-byte prefixes. CSV/JSONL are text and never start with these.
_BINARY_MAGIC = (
    b"MZ",                              # DOS/PE executable (.exe/.dll)
    b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08",  # ZIP / xlsx / docx / jar
    b"\x7fELF",                         # ELF executable
    b"%PDF",                           # PDF
    b"\x89PNG",                        # PNG
    b"GIF8",                           # GIF
    b"\xff\xd8\xff",                   # JPEG
    b"\x1f\x8b",                       # gzip
    b"BZh",                            # bzip2
    b"7z\xbc\xaf\x27\x1c",            # 7-Zip
    b"Rar!",                           # RAR
    b"\xfd7zXZ\x00",                  # xz
    b"\xca\xfe\xba\xbe",              # Java class / Mach-O fat binary
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",  # Mach-O
    b"\x00\x00\x01\x00",              # ICO
    b"OggS", b"RIFF", b"ID3",         # media containers
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # legacy MS Office (.doc/.xls)
)

_NUL_SCAN_BYTES = 64 * 1024


def assert_safe_text_upload(file_bytes: bytes, filename: str = "upload") -> None:
    """
    Raise 422 unless the bytes look like a plain-text dataset.

    Archives are rejected here rather than decompressed, so there is no
    decompression-bomb surface; the caller's hard size cap bounds the read.
    """
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    for magic in _BINARY_MAGIC:
        if file_bytes.startswith(magic):
            raise HTTPException(
                status_code=422,
                detail=(
                    "File content is not a text dataset (binary signature detected). "
                    "Only CSV and JSONL text files are accepted."
                ),
            )

    # NUL bytes never appear in a valid UTF-8 text dataset and are a reliable
    # binary indicator (catches binaries with no known magic prefix).
    if b"\x00" in file_bytes[:_NUL_SCAN_BYTES]:
        raise HTTPException(
            status_code=422,
            detail="File content is not a text dataset (contains NUL bytes).",
        )
