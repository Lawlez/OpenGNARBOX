"""OpenGNAR Core API — FastAPI backend for the OpenGNARBOX device."""

import os
import time
import traceback
import uuid

from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from system_utils import (
    get_storage_stats, get_battery_stats, NVME_MOUNT_PATH, SD_MOUNT_PATH,
    scan_dir, hash_file, copy_file, delete_file, list_dir_contents,
    copy_file_chunked, create_zip_file, is_safe_path, check_duplicate
)

DOWNLOAD_SESSIONS = {}

app = FastAPI(title="OpenGNAR Core API")


@app.get("/api/status")
def get_status():
    """Return system status: NVMe, SD card, and battery info."""
    return {
        "nvme": get_storage_stats(NVME_MOUNT_PATH),
        "sd": get_storage_stats(SD_MOUNT_PATH),
        "battery": get_battery_stats()
    }


class PathRequest(BaseModel):
    """Request body containing a single file path."""
    path: str


class CopyRequest(BaseModel):
    """Request body for copy operations with source and target paths."""
    source: str
    target: str


class CheckDuplicateRequest(BaseModel):
    """Request body for duplicate checks with source and destination directory."""
    source: str
    dest_dir: str


class DownloadSessionRequest(BaseModel):
    """Request body for creating a download session with multiple paths."""
    paths: list[str]


@app.get("/api/files/scan")
def _scan_files(path: str):
    """Recursively scan a directory and return file metadata."""
    if not is_safe_path(path):
        raise HTTPException(status_code=403, detail="Forbidden Path")
    try:
        files = scan_dir(path)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/files/hash")
def _hash_file(req: PathRequest):
    """Compute SHA-256 hash of a file."""
    if not is_safe_path(req.path):
        raise HTTPException(status_code=403, detail="Forbidden Path")
    try:
        h = hash_file(req.path)
        return {"hash": h}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/files/copy")
def _copy_file(req: CopyRequest):
    """Copy a file with duplicate detection."""
    if not is_safe_path(req.source) or not is_safe_path(req.target):
        raise HTTPException(status_code=403, detail="Forbidden Path")
    try:
        dest_dir = os.path.dirname(req.target)
        dup = check_duplicate(req.source, dest_dir)
        if dup["is_duplicate"]:
            return {
                "success": False,
                "skipped": True,
                "reason": f"Duplicate detected ({dup['match_type']})",
                "existing_path": dup["existing_path"]
            }
        success = copy_file(req.source, req.target)
        return {"success": success, "skipped": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/files/check-duplicate")
def _check_duplicate(req: CheckDuplicateRequest):
    """Check whether a source file is a duplicate in the target directory."""
    if not is_safe_path(req.source) or not is_safe_path(req.dest_dir):
        raise HTTPException(status_code=403, detail="Forbidden Path")
    try:
        result = check_duplicate(req.source, req.dest_dir)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/api/files/delete")
def _delete_file(req: PathRequest):
    """Delete a file from an authorized path."""
    if not is_safe_path(req.path):
        raise HTTPException(status_code=403, detail="Forbidden Path")
    try:
        success = delete_file(req.path)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/files/list")
def _list_files(path: str = "/media"):
    """List directory contents for the file browser."""
    if not is_safe_path(path):
        raise HTTPException(status_code=403, detail="Forbidden Path")
    try:
        files = list_dir_contents(path)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/files/download/session")
def _create_download_session(req: DownloadSessionRequest):
    """Create a temporary download session for multi-file ZIP generation."""
    session_id = str(uuid.uuid4())
    DOWNLOAD_SESSIONS[session_id] = req.paths
    return {"downloadId": session_id}


@app.get("/api/files/download/{session_id}")
def _download_files(session_id: str, background_tasks: BackgroundTasks):
    """Serve a download for a previously created session."""
    try:
        paths = DOWNLOAD_SESSIONS.pop(session_id, None)
        if not paths:
            raise HTTPException(
                status_code=404, detail="Invalid or expired download session"
            )

        path_list = [p.strip() for p in paths if is_safe_path(p.strip())]
        if not path_list:
            raise HTTPException(status_code=400, detail="No valid paths provided")

        if len(path_list) == 1 and os.path.isfile(path_list[0]):
            return FileResponse(path_list[0], filename=os.path.basename(path_list[0]))

        # multiple files or a directory -> create zip
        zip_name = f"OpenGNAR_Download_{int(time.time())}.zip"
        zip_path = os.path.join("/tmp/", zip_name)

        create_zip_file(path_list, zip_path)

        if not os.path.exists(zip_path):
            raise HTTPException(status_code=500, detail="Failed to create zip")

        # cleanup after sending
        background_tasks.add_task(os.remove, zip_path)

        return FileResponse(zip_path, filename=zip_name, media_type="application/zip")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.websocket("/api/ws/copy")
async def websocket_copy(websocket: WebSocket):
    """WebSocket endpoint for chunked file copy with real-time progress."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            source = data.get("source")
            target = data.get("target")
            if not source or not target:
                await websocket.send_json({"error": "Missing source or target"})
                continue
            if not is_safe_path(source) or not is_safe_path(target):
                await websocket.send_json({"error": "Forbidden Path"})
                continue

            try:
                dest_dir = os.path.dirname(target)
                dup = check_duplicate(source, dest_dir)
                if dup["is_duplicate"]:
                    await websocket.send_json({
                        "status": "skipped",
                        "reason": f"Duplicate detected ({dup['match_type']})",
                        "existing_path": dup["existing_path"]
                    })
                    continue

                async for progress in copy_file_chunked(source, target):
                    await websocket.send_json({"progress": progress})

                await websocket.send_json({"status": "completed"})
            except Exception as e:
                traceback.print_exc()
                await websocket.send_json({"error": str(e), "status": "error"})

    except WebSocketDisconnect:
        pass


# Mount the static files (frontend dist built by Vite)
frontend_path = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')
if os.path.exists(frontend_path):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(frontend_path, "assets")),
        name="assets"
    )

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):  # pylint: disable=unused-argument
        """Serve the SPA index.html for all unmatched routes."""
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "Frontend not found"}
else:
    @app.get("/")
    def serve_fallback():
        """Fallback when frontend dist is not available."""
        return {"message": "OpenGNAR Core is running, but frontend/dist files were not found."}
