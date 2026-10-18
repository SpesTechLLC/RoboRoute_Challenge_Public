"""Bounded ZIP extraction into a new directory. Never extractall untrusted input."""
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import zipfile

MAX_FILES = 1024
MAX_BYTES = 32 * 1024 * 1024


def extract_submission(archive, destination):
    """Require main.py, report/experiment_log.md or .txt, and slides.pdf."""
    archive = Path(archive)
    if archive.stat().st_size > MAX_BYTES:
        raise ValueError('Compressed ZIP exceeds 32 MiB.')
    # Bound central-directory parsing before ZipFile allocates all ZipInfo objects.
    # This submission format deliberately excludes ZIP64 and multi-volume ZIPs.
    with archive.open('rb') as file:
        file.seek(max(0, archive.stat().st_size - 65557))
        tail = file.read()
    offset = tail.rfind(b'PK\x05\x06')
    if offset < 0 or len(tail) - offset < 22:
        raise ValueError('Missing ZIP end record.')
    _, disk, cd_disk, count_disk, count, cd_size, cd_offset, comment_size = struct.unpack_from('<4s4H2LH', tail, offset)
    if (disk or cd_disk or count_disk != count or count > MAX_FILES
            or cd_size > 256 * 1024 or cd_offset == 0xffffffff
            or len(tail) - offset != 22 + comment_size):
        raise ValueError('Unsupported or oversized ZIP directory.')
    destination = Path(destination)
    destination.mkdir()  # caller must supply a fresh, private destination
    try:
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if len(entries) > MAX_FILES or sum(e.file_size for e in entries) > MAX_BYTES:
                raise ValueError('ZIP exceeds submission size/file count limits.')
            seen = set()
            for info in entries:
                name = info.filename
                path = PurePosixPath(name)
                mode = info.external_attr >> 16
                if (info.orig_filename != name or not name or '\\' in name or '\x00' in name or ':' in name
                        or path.is_absolute() or any(p in ('', '.', '..') for p in name.rstrip('/').split('/'))
                        or str(path).casefold() in seen
                        or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                        or (stat.S_ISDIR(mode) and not info.is_dir())
                        or info.flag_bits & 1
                        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError(f'Unsafe ZIP entry: {name!r}')
                seen.add(str(path).casefold())
                target = destination.joinpath(*path.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Never trust declared expanded size alone.
                    with zipped.open(info) as source, target.open('xb') as output:
                        remaining = info.file_size
                        while chunk := source.read(min(65536, remaining + 1)):
                            remaining -= len(chunk)
                            if remaining < 0:
                                raise ValueError('ZIP expanded beyond declared size.')
                            output.write(chunk)
            for required in ('main.py', 'slides.pdf'):
                if not (destination / required).is_file():
                    raise ValueError(f'Missing required ZIP file: {required}')
            if not any((destination / 'report' / ('experiment_log' + suffix)).is_file() for suffix in ('.md', '.txt')):
                raise ValueError('Missing required ZIP file: report/experiment_log.md or report/experiment_log.txt')
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination
