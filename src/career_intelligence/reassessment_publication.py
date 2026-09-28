"""Whole-directory atomic publication on macOS/Linux; never a sequence of file swaps."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def file_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def tree_digest(path: Path) -> dict:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Expected a real directory: {path}")
    files = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"Symlinks are not supported in a publication: {item}")
        if item.is_file():
            files[str(item.relative_to(path))] = file_digest(item)
    return files


def fsync_tree(path: Path) -> None:
    for item in path.rglob("*"):
        if item.is_file():
            with item.open("rb") as handle:
                os.fsync(handle.fileno())
    for directory in [*sorted((p for p in path.rglob("*") if p.is_dir()), reverse=True), path]:
        fsync_directory(directory)


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def exchange_directories(left: Path, right: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        fn, cwd = getattr(libc, "renameatx_np", None), -2
    elif sys.platform.startswith("linux"):
        fn, cwd = getattr(libc, "renameat2", None), -100
    else:
        fn, cwd = None, 0
    if fn is None:
        raise RuntimeError("Atomic directory exchange unavailable; production not changed")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    # RENAME_SWAP (Darwin) / RENAME_EXCHANGE (Linux) are both 2.
    if fn(cwd, os.fsencode(left), cwd, os.fsencode(right), 2):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def publish(results: Path, candidate: Path, archive: Path, state_path: Path,
            *, metadata: dict, after_exchange=None) -> dict:
    """Caller owns DailyRunLock. PREPARED archive is sufficient for crash recovery."""
    before = tree_digest(results)
    after = tree_digest(candidate)
    archive.mkdir(parents=True, exist_ok=False)
    shutil.copytree(results, archive / "results")
    if tree_digest(archive / "results") != before:
        raise ValueError("Archive copy does not match production; refusing publication")
    state_hash = file_digest(state_path)
    if state_hash is not None:
        shutil.copy2(state_path, archive / "operator_state.json")
        if file_digest(archive / "operator_state.json") != state_hash:
            raise ValueError("Operator-state archive changed during copy")
    manifest = {"schema_version": 1, "status": "PREPARED", "before": before, "after": after,
                "results": str(results.resolve()), "state_path": str(state_path.resolve()),
                "state_hash": state_hash, "metadata": metadata}
    manifest["rollback_token"] = digest(manifest)
    (archive / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    fsync_tree(archive)
    fsync_directory(archive.parent)
    stage = Path(tempfile.mkdtemp(prefix=".career-publication-", dir=results.parent))
    exchanged = False
    try:
        shutil.copytree(candidate, stage, dirs_exist_ok=True)
        fsync_tree(stage)
        if tree_digest(stage) != after or tree_digest(results) != before:
            raise ValueError("Publication files changed during preparation")
        if file_digest(state_path) != state_hash:
            raise ValueError("Operator states changed during preparation")
        exchange_directories(stage, results)
        exchanged = True
        fsync_directory(results.parent)
        if after_exchange is not None:
            after_exchange()
        # Manifest is immutable. A separate receipt is informational, not recovery authority.
        (archive / "published.json").write_text(json.dumps({"after": after}) + "\n")
        fsync_tree(archive)
    except BaseException:
        if exchanged:
            # If reversal itself fails, retain stage and archive; live is still a COMPLETE set.
            exchange_directories(stage, results)
            exchanged = False
            fsync_directory(results.parent)
        shutil.rmtree(stage)
        raise
    else:
        # Publication is committed; cleanup failure must not report an ambiguous failed apply.
        shutil.rmtree(stage, ignore_errors=True)
    return manifest
