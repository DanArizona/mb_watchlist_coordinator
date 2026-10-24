"""Strict test-only scan after owned controllers/writers have closed."""
from pathlib import Path


def scan_saved_artifacts(root, markers, *, read_bytes=None):
    root=Path(root)
    markers=tuple(markers)
    if not markers or any(type(m) is not bytes or not m for m in markers):
        raise ValueError('Nonempty explicit byte markers required')
    read_bytes=read_bytes or (lambda path:path.read_bytes())
    scanned=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(root).as_posix()
        try:data=read_bytes(path)
        except OSError as error:
            # Keep the path and numeric/type diagnostics, never arbitrary
            # exception text or contents. Unreadable/disappearing files FAIL.
            errno=error.errno if type(error.errno) is int else None
            winerror=getattr(error,'winerror',None)
            winerror=winerror if type(winerror) is int else None
            raise AssertionError('Secret scan could not read '+relative+
                f' ({type(error).__name__}; errno={errno}; winerror={winerror})') from None
        if any(marker in data for marker in markers):
            raise AssertionError('Secret marker found in '+relative)
        scanned.append(relative)
    return tuple(scanned)
