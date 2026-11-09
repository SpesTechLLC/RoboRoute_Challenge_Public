"""Bounded ZIP extraction into a new directory. Never extractall untrusted input."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import tempfile
import zipfile

MAX_FILES = 1024
MAX_BYTES = 32 * 1024 * 1024
MAX_DIRECTORY_BYTES = 256 * 1024


def submission_path(name, seen):
    """Validate the same member names during preflight and extraction."""
    path = PurePosixPath(name)
    normalized = str(path).casefold()
    is_directory = name.endswith('/')
    if (not name or '\\' in name or '\x00' in name or ':' in name
            or path.is_absolute() or any(p in ('', '.', '..') for p in name.rstrip('/').split('/'))
            or normalized in seen
            or any(normalized.startswith(parent + '/') and not directory
                   or parent.startswith(normalized + '/') and not is_directory
                   for parent, directory in seen.items())):
        raise ValueError(f'Unsafe ZIP entry: {name!r}')
    seen[normalized] = is_directory
    return path


@contextmanager
def validated_submission(output, *, require_slides=True):
    """Publish a ZIP only after the existing submission extractor accepts it."""
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError(f'{output} は既に存在します。--outputで別名を指定してください。')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rr-pack-', dir=output.parent) as temporary:
        archive = Path(temporary) / 'submission.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            yield zipped
        extract_submission(archive, Path(temporary) / 'validated', require_slides=require_slides)
        # Exclusive creation also protects files created after the initial check.
        with output.open('xb') as target, archive.open('rb') as source:
            try:
                shutil.copyfileobj(source, target)
            except BaseException:
                output.unlink(missing_ok=True)
                raise


def extract_submission(archive, destination, *, require_slides=True):
    """Require code/report and, by default, slides.pdf; allow explicit separate slides."""
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
            or cd_size > MAX_DIRECTORY_BYTES or cd_offset == 0xffffffff
            or len(tail) - offset != 22 + comment_size):
        raise ValueError('Unsupported or oversized ZIP directory.')
    destination = Path(destination)
    destination.mkdir()  # caller must supply a fresh, private destination
    try:
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if len(entries) > MAX_FILES or sum(e.file_size for e in entries) > MAX_BYTES:
                raise ValueError('ZIP exceeds submission size/file count limits.')
            seen = {}
            for info in entries:
                name = info.filename
                path = submission_path(name, seen)
                mode = info.external_attr >> 16
                if (info.orig_filename != name
                        or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                        or (stat.S_ISDIR(mode) and not info.is_dir())
                        or info.flag_bits & 1
                        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError(f'Unsafe ZIP entry: {name!r}')
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
            for required in (('main.py', 'slides.pdf') if require_slides else ('main.py',)):
                if not (destination / required).is_file():
                    raise ValueError(f'Missing required ZIP file: {required}')
            if not any((destination / 'report' / ('experiment_log' + suffix)).is_file() for suffix in ('.md', '.txt')):
                raise ValueError('Missing required ZIP file: report/experiment_log.md or report/experiment_log.txt')
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination
