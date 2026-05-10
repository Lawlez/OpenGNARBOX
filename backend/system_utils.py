"""OpenGNAR system utilities — file operations, hashing, and hardware monitoring.

GNARBOX 2.0 device layout:
  /media/GNARBOX     – 447 GB NVMe user storage (main backup target)
  /media/<LABEL>     – SD cards auto-mounted by syslinkd (e.g. /media/EOS_DIGITAL)
  /app_data/         – encrypted config partition (auth tokens, keys)
  /run/syslinkd/     – network state Unix socket
  /run/shivad/       – Docker orchestrator Unix socket
  /sys/class/power_supply/ – battery sysfs
"""

import os
import shutil
import hashlib
import time
import asyncio
import zipfile
from typing import List, Dict, Any

import aiofiles

# ── Device paths ──────────────────────────────────────────────────────
NVME_MOUNT_PATH = os.environ.get("NVME_MOUNT_PATH", "/media/GNARBOX")
SD_MOUNT_ROOT = os.environ.get("SD_MOUNT_ROOT", "/media")
BATTERY_SYSFS_PATH = "/sys/class/power_supply/BAT0/capacity"

# Legacy compat aliases
SD_MOUNT_PATH = SD_MOUNT_ROOT

# ── Legacy service URLs (Docker DNS on ingress-net) ──────────────────
TAPPERD_URL = os.environ.get("TAPPERD_URL", "http://tapperd:80")
TBD_URL = os.environ.get("TBD_URL", "http://tbd:80")
MOONSHOTD_URL = os.environ.get("MOONSHOTD_URL", "http://moonshotd:80")
OVERLOOKD_URL = os.environ.get("OVERLOOKD_URL", "http://overlookd:80")
SHAMAND_URL = os.environ.get("SHAMAND_URL", "http://shamand:80")
BLUEBIRD_URL = os.environ.get("BLUEBIRD_URL", "http://bluebird:80")
PROVIDERMGRD_URL = os.environ.get("PROVIDERMGRD_URL", "http://providermgrd:80")

# Mock Mode: when running locally without hardware mounts
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# In mock mode, we want to simulate a filesystem.
_mock_file_system: Dict[str, list] = {}


def _is_within_sandbox(resolved_path: str) -> bool:
    """Check if a resolved (realpath) path is within allowed roots.

    On the GNARBOX 2.0, storage is at /media/GNARBOX (NVMe) and SD cards
    are auto-mounted under /media/<LABEL> by syslinkd. We allow any path
    under /media/ to accommodate arbitrary card labels.
    """
    return (
        resolved_path.startswith("/media/") or resolved_path == "/media"
        or resolved_path.startswith("/tmp/") or resolved_path == "/tmp"
    )


def is_safe_path(target_path: str) -> bool:
    """Lightweight boolean check used by API-layer guards in main.py."""
    if MOCK_MODE:
        return True
    try:
        resolved = os.path.realpath(target_path)
        return _is_within_sandbox(resolved)
    except OSError:
        return False


def get_storage_stats(path: str) -> Dict[str, object]:
    """Return disk usage statistics for a given mount point."""
    if MOCK_MODE:
        return {"presence": True, "total_gb": 1000, "used_gb": 250, "free_gb": 750}

    if not os.path.exists(path) or not os.path.ismount(path):
        return {"presence": False, "total_gb": 0, "used_gb": 0, "free_gb": 0}

    try:
        total, used, free = shutil.disk_usage(path)
        return {
            "presence": True,
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2)
        }
    except OSError:
        return {"presence": False, "total_gb": 0, "used_gb": 0, "free_gb": 0}


def get_battery_stats() -> Dict[str, object]:
    """Return battery level and status from sysfs."""
    if MOCK_MODE:
        return {"level": 88, "status": "mock"}

    try:
        if os.path.exists(BATTERY_SYSFS_PATH):
            with open(BATTERY_SYSFS_PATH, 'r', encoding='utf-8') as f:
                return {"level": int(f.read().strip()), "status": "ok"}
    except (OSError, ValueError):
        pass
    return {"level": 85, "status": "mock"}


def _get_file_type(ext: str) -> str:
    """Map a file extension to a type category."""
    ext = ext.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.arw', '.cr2', '.nef', '.dng'):
        return "IMAGE"
    if ext in ('.mp4', '.mov', '.avi', '.m4v'):
        return "VIDEO"
    if ext in ('.xml', '.thm', '.lrv', '.xmp'):
        return "META"
    return "UNKNOWN"


def scan_dir(path: str) -> List[Dict[str, Any]]:
    """Recursively scan a directory and return file metadata."""
    if MOCK_MODE:
        if path == "/media/sd":
            if "/media/sd" not in _mock_file_system:
                _mock_file_system["/media/sd"] = [
                    {
                        "id": "mock1", "name": "2024-05-10_SONY_DSC001.ARW",
                        "currentPath": "/media/sd/2024-05-10_SONY_DSC001.ARW",
                        "size": 25000000, "extension": "ARW",
                        "createdDate": int(time.time() * 1000), "cameraModel": "SONY"
                    },
                    {
                        "id": "mock2", "name": "2024-05-10_SONY_DSC002.MP4",
                        "currentPath": "/media/sd/2024-05-10_SONY_DSC002.MP4",
                        "size": 150000000, "extension": "MP4",
                        "createdDate": int(time.time() * 1000), "cameraModel": "SONY"
                    }
                ]

            for f in _mock_file_system["/media/sd"]:
                f["type"] = _get_file_type(f["extension"])
            return _mock_file_system["/media/sd"]

        if path not in _mock_file_system:
            return []

        for f in _mock_file_system[path]:
            f["type"] = _get_file_type(f["extension"])
        return _mock_file_system[path]

    # Real mode — resolve, validate inline, then use
    safe_path = os.path.realpath(path)
    if not _is_within_sandbox(safe_path):
        raise ValueError(f"Path outside allowed roots: {path}")

    files: List[Dict[str, Any]] = []
    if not os.path.exists(safe_path):
        return files

    for root, _, filenames in os.walk(safe_path):
        for name in filenames:
            file_path = os.path.join(root, name)
            try:
                stat = os.stat(file_path)
                ext = name.split('.')[-1].upper() if '.' in name else ''
                files.append({
                    "id": name + str(stat.st_mtime),
                    "name": name,
                    "originalPath": file_path,
                    "currentPath": file_path,
                    "displayPath": file_path,
                    "size": stat.st_size,
                    "type": _get_file_type(ext),
                    "extension": ext,
                    "hash": None,
                    "createdDate": int(stat.st_mtime * 1000),
                    "cameraModel": "OpenGNAR"
                })
            except OSError:
                pass
    return files


def hash_file(path: str) -> str:
    """Compute the SHA-256 hash of a file."""
    if MOCK_MODE:
        time.sleep(0.5)
        basis = path.split('/')[-1]
        for vlist in _mock_file_system.values():
            for f in vlist:
                if f["currentPath"] == path:
                    basis += f"_{f['size']}"
                    break
        return hashlib.sha256(basis.encode()).hexdigest()

    # Real mode — resolve, validate inline, then use
    safe_path = os.path.realpath(path)
    if not _is_within_sandbox(safe_path):
        raise ValueError(f"Path outside allowed roots: {path}")

    if not os.path.exists(safe_path):
        raise FileNotFoundError(f"File not found: {path}")

    sha256 = hashlib.sha256()
    with open(safe_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def check_duplicate(source: str, dest_dir: str) -> Dict[str, Any]:
    """Check if the source file already exists in the destination directory tree.

    Uses a two-tier strategy:
      1. Content hash (SHA-256) — strongest, byte-exact match
      2. Metadata fingerprint (size + mtime within 2s) — fast fallback

    Returns a dict:
      {"is_duplicate": bool, "match_type": str|None, "existing_path": str|None}
    """
    if MOCK_MODE:
        source_obj = None
        for vlist in _mock_file_system.values():
            for f in vlist:
                if f["currentPath"] == source:
                    source_obj = f
                    break
            if source_obj:
                break
        if not source_obj:
            return {"is_duplicate": False, "match_type": None, "existing_path": None}

        source_hash = hash_file(source)
        for vlist in _mock_file_system.values():
            for f in vlist:
                if f["currentPath"] == source:
                    continue
                if not f["currentPath"].startswith(dest_dir):
                    continue
                candidate_hash = hash_file(f["currentPath"])
                if candidate_hash == source_hash:
                    return {
                        "is_duplicate": True, "match_type": "hash",
                        "existing_path": f["currentPath"]
                    }
        return {"is_duplicate": False, "match_type": None, "existing_path": None}

    # Real mode — resolve and validate both paths inline
    safe_source = os.path.realpath(source)
    if not _is_within_sandbox(safe_source):
        raise ValueError(f"Source path outside allowed roots: {source}")

    safe_dest_dir = os.path.realpath(dest_dir)
    if not _is_within_sandbox(safe_dest_dir):
        raise ValueError(f"Dest path outside allowed roots: {dest_dir}")

    if not os.path.exists(safe_source):
        raise FileNotFoundError(f"Source not found: {source}")
    if not os.path.exists(safe_dest_dir):
        return {"is_duplicate": False, "match_type": None, "existing_path": None}

    source_stat = os.stat(safe_source)
    source_size = source_stat.st_size
    source_mtime_ms = int(source_stat.st_mtime * 1000)
    source_hash = None

    for root, _, filenames in os.walk(safe_dest_dir):
        for name in filenames:
            candidate_path = os.path.join(root, name)
            try:
                cand_stat = os.stat(candidate_path)
            except OSError:
                continue

            if cand_stat.st_size != source_size:
                continue

            if source_hash is None:
                source_hash = hash_file(safe_source)
            candidate_hash = hash_file(candidate_path)
            if candidate_hash == source_hash:
                return {
                    "is_duplicate": True, "match_type": "hash",
                    "existing_path": candidate_path
                }

            cand_mtime_ms = int(cand_stat.st_mtime * 1000)
            if abs(source_mtime_ms - cand_mtime_ms) <= 2000:
                return {
                    "is_duplicate": True, "match_type": "fingerprint",
                    "existing_path": candidate_path
                }

    return {"is_duplicate": False, "match_type": None, "existing_path": None}


def copy_file(source: str, dest: str) -> bool:
    """Copy a file from source to dest with path validation."""
    if MOCK_MODE:
        time.sleep(1.0)
        f_obj = None
        for _, vlist in _mock_file_system.items():
            for f in vlist:
                if f["currentPath"] == source:
                    f_obj = dict(f)
                    break
            if f_obj:
                break

        if not f_obj:
            raise FileNotFoundError(f"Source mock file not found: {source}")

        mock_dest_dir = os.path.dirname(dest)
        if mock_dest_dir not in _mock_file_system:
            _mock_file_system[mock_dest_dir] = []

        f_obj["currentPath"] = dest
        f_obj["name"] = os.path.basename(dest)
        _mock_file_system[mock_dest_dir].append(f_obj)
        return True

    # Real mode — resolve and validate both paths inline
    safe_source = os.path.realpath(source)
    if not _is_within_sandbox(safe_source):
        raise ValueError(f"Source path outside allowed roots: {source}")

    safe_dest = os.path.realpath(dest)
    if not _is_within_sandbox(safe_dest):
        raise ValueError(f"Dest path outside allowed roots: {dest}")

    os.makedirs(os.path.dirname(safe_dest), exist_ok=True)
    shutil.copy2(safe_source, safe_dest)
    return True


def delete_file(path: str) -> bool:
    """Delete a file after validating the path is within the sandbox."""
    if MOCK_MODE:
        for _, vlist in _mock_file_system.items():
            _mock_file_system[_] = [f for f in vlist if f["currentPath"] != path]
        return True

    # Real mode — resolve, validate inline, then use
    safe_path = os.path.realpath(path)
    if not _is_within_sandbox(safe_path):
        raise ValueError(f"Path outside allowed roots: {path}")

    if os.path.exists(safe_path):
        os.remove(safe_path)
    return True


def list_dir_contents(path: str) -> List[Dict[str, Any]]:
    """List the immediate contents of a directory for the file browser."""
    if MOCK_MODE:
        if path == "/media":
            return [
                {"name": "nvme", "isDirectory": True, "path": "/media/nvme", "size": 0},
                {"name": "sd", "isDirectory": True, "path": "/media/sd", "size": 0}
            ]
        if path == "/media/sd":
            if "/media/sd" not in _mock_file_system:
                _mock_file_system["/media/sd"] = [
                    {
                        "name": "2024-05-10_SONY_DSC001.ARW", "isDirectory": False,
                        "path": "/media/sd/2024-05-10_SONY_DSC001.ARW", "size": 25000000
                    },
                    {"name": "DCIM", "isDirectory": True, "path": "/media/sd/DCIM", "size": 0}
                ]
            return _mock_file_system["/media/sd"]
        return []

    # Real mode — resolve and validate path inline
    safe_path = os.path.realpath(path)
    if not _is_within_sandbox(safe_path):
        raise ValueError(f"Path outside allowed roots: {path}")

    files: List[Dict[str, Any]] = []
    if not os.path.exists(safe_path):
        return files

    try:
        entries = os.listdir(safe_path)
        for name in entries:
            full_path = os.path.join(safe_path, name)
            try:
                stat = os.stat(full_path)
                files.append({
                    "name": name,
                    "isDirectory": os.path.isdir(full_path),
                    "path": full_path,
                    "size": stat.st_size,
                    "createdDate": int(stat.st_mtime * 1000)
                })
            except OSError:
                pass
    except OSError:
        pass
    return sorted(files, key=lambda x: (not x["isDirectory"], x["name"].lower()))


async def copy_file_chunked(source: str, dest: str):
    """Async generator that copies a file in chunks, yielding progress percentage."""
    if MOCK_MODE:
        for i in range(1, 11):
            await asyncio.sleep(0.1)
            yield float(i * 10)
        return

    # Real mode — resolve and validate both paths inline
    safe_source = os.path.realpath(source)
    if not _is_within_sandbox(safe_source):
        raise ValueError(f"Source path outside allowed roots: {source}")

    safe_dest = os.path.realpath(dest)
    if not _is_within_sandbox(safe_dest):
        raise ValueError(f"Dest path outside allowed roots: {dest}")

    os.makedirs(os.path.dirname(safe_dest), exist_ok=True)
    file_size = os.path.getsize(safe_source)
    if file_size == 0:
        yield 100.0
        return

    chunk_size = 1024 * 1024 * 10  # 10MB chunks
    copied = 0

    async with aiofiles.open(safe_source, 'rb') as src, \
               aiofiles.open(safe_dest, 'wb') as dst:
        while True:
            chunk = await src.read(chunk_size)
            if not chunk:
                break
            await dst.write(chunk)
            copied += len(chunk)
            yield min(100.0, (copied / file_size) * 100)


def create_zip_file(paths: List[str], output_path: str, max_mb: int = 4000) -> str:
    """Create a ZIP archive from a list of file/directory paths."""
    # Validate and resolve output path inline
    safe_output = os.path.realpath(output_path)
    if not _is_within_sandbox(safe_output):
        raise ValueError(f"Output path outside allowed roots: {output_path}")

    # Validate and resolve all input paths inline
    safe_paths = []
    for p in paths:
        resolved = os.path.realpath(p)
        if _is_within_sandbox(resolved):
            safe_paths.append(resolved)

    max_bytes = max_mb * 1024 * 1024
    current_bytes = 0

    with zipfile.ZipFile(safe_output, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for safe_path in safe_paths:
            if not os.path.exists(safe_path):
                continue

            if os.path.isfile(safe_path):
                size = os.path.getsize(safe_path)
                if current_bytes + size > max_bytes:
                    break
                zipf.write(safe_path, arcname=os.path.basename(safe_path))
                current_bytes += size

            elif os.path.isdir(safe_path):
                for root, _, files in os.walk(safe_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        size = os.path.getsize(file_path)
                        if current_bytes + size > max_bytes:
                            break
                        arcname = os.path.relpath(file_path, os.path.dirname(safe_path))
                        zipf.write(file_path, arcname=arcname)
                        current_bytes += size
                    if current_bytes > max_bytes:
                        break
    return safe_output
