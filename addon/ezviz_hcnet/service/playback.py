"""Playback session manager for temporary HLS output."""

from __future__ import annotations

import asyncio
import ctypes as C
import logging
import queue
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .const import PLAYBACK_SESSION_IDLE_TIMEOUT
from .ctypes_defs import PLAY_DATA_CALLBACK
from .sdk_client import HcNetSdkClient, SdkCallError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PlaybackInfo:
    session_id: str
    entry_id: str
    start: datetime
    end: datetime
    status: str
    last_error: str | None
    created_at: datetime
    last_access: datetime


class PlaybackSession:
    """Single SDK playback session converted to HLS via ffmpeg."""

    def __init__(
        self,
        client: HcNetSdkClient,
        entry_id: str,
        start: datetime,
        end: datetime,
    ) -> None:
        self.client = client
        self.entry_id = entry_id
        self.start = start
        self.end = end
        self.session_id = uuid.uuid4().hex

        self.base_dir = Path("/tmp/ezviz_hcnet") / entry_id / self.session_id
        self.index_file = self.base_dir / "index.m3u8"

        self.handle: int | None = None
        self.status = "INIT"
        self.last_error: str | None = None
        self.created_at = datetime.now(tz=UTC)
        self.last_access = self.created_at

        self._callback: PLAY_DATA_CALLBACK | None = None
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=512)
        self._writer_thread: threading.Thread | None = None
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()

    def open(self) -> None:
        with self._lock:
            if shutil.which("ffmpeg") is None:
                raise RuntimeError("ffmpeg not found in PATH")

            self.base_dir.mkdir(parents=True, exist_ok=True)
            self.handle = self.client.playback_open(self.start, self.end)

            try:
                self._start_ffmpeg()
                self._start_writer_thread()
                self._attach_callback()
                assert self.handle is not None
                self.client.playback_start(self.handle)
            except Exception:
                self.close()
                raise

            self.status = "RUNNING"
            self._touch()

    def _start_ffmpeg(self) -> None:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-c",
            "copy",
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_list_size",
            "8",
            "-hls_flags",
            "delete_segments+append_list+omit_endlist",
            str(self.index_file),
        ]
        self._ffmpeg = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def _start_writer_thread(self) -> None:
        def _writer() -> None:
            proc = self._ffmpeg
            if proc is None or proc.stdin is None:
                return
            try:
                while True:
                    chunk = self._queue.get()
                    if chunk is None:
                        break
                    try:
                        proc.stdin.write(chunk)
                        proc.stdin.flush()
                    except BrokenPipeError:
                        self.last_error = "ffmpeg pipe broken"
                        break
            except Exception as err:  # pragma: no cover
                self.last_error = f"ffmpeg writer thread error: {err}"
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        self._writer_thread = threading.Thread(target=_writer, name=f"ezviz-playback-writer-{self.session_id}", daemon=True)
        self._writer_thread.start()

    def _attach_callback(self) -> None:
        assert self.handle is not None

        def _on_data(
            _play_handle: int,
            _data_type: int,
            p_buffer: int,
            buf_size: int,
            _user: int,
        ) -> None:
            if not p_buffer or buf_size <= 0:
                return
            try:
                data = C.string_at(p_buffer, buf_size)
                self._queue.put_nowait(data)
            except queue.Full:
                pass
            except Exception:
                pass

        self._callback = PLAY_DATA_CALLBACK(_on_data)
        self.client.playback_set_callback(self.handle, self._callback)

    def control(self, action: str, seek_percent: float | None = None) -> None:
        with self._lock:
            if self.handle is None:
                raise RuntimeError("Playback session is not open")
            self.client.playback_control(self.handle, action, seek_percent)
            self._touch()

    def get_progress(self) -> int:
        with self._lock:
            if self.handle is None:
                return 0
            try:
                return self.client.playback_get_pos(self.handle)
            except SdkCallError:
                return 0

    def close(self) -> None:
        with self._lock:
            self.status = "CLOSING"
            if self.handle is not None:
                self.client.playback_close(self.handle)
                self.handle = None

            try:
                self._queue.put_nowait(None)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except Exception:
                    pass
                try:
                    self._queue.put_nowait(None)
                except Exception:
                    pass

            if self._writer_thread is not None:
                self._writer_thread.join(timeout=2)
                self._writer_thread = None

            if self._ffmpeg is not None:
                proc = self._ffmpeg
                self._ffmpeg = None
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                stderr = b""
                try:
                    if proc.stderr is not None:
                        stderr = proc.stderr.read()
                except Exception:
                    pass
                if proc.returncode not in (0, None) and stderr:
                    self.last_error = stderr.decode("utf-8", errors="ignore").strip()[-500:]

            self._callback = None
            shutil.rmtree(self.base_dir, ignore_errors=True)
            self.status = "CLOSED"
            self._touch()

    def mark_failed(self, error: str) -> None:
        self.status = "FAILED"
        self.last_error = error
        self._touch()

    def is_stale(self, now: datetime) -> bool:
        return now - self.last_access > PLAYBACK_SESSION_IDLE_TIMEOUT

    def info(self) -> PlaybackInfo:
        return PlaybackInfo(
            session_id=self.session_id,
            entry_id=self.entry_id,
            start=self.start,
            end=self.end,
            status=self.status,
            last_error=self.last_error,
            created_at=self.created_at,
            last_access=self.last_access,
        )

    def _touch(self) -> None:
        self.last_access = datetime.now(tz=UTC)


class PlaybackSessionManager:
    """Async manager enforcing one session per entry."""

    def __init__(self, client: HcNetSdkClient, entry_id: str) -> None:
        self.client = client
        self.entry_id = entry_id
        self._session: PlaybackSession | None = None
        self._lock = asyncio.Lock()

    @property
    def current(self) -> PlaybackSession | None:
        return self._session

    async def async_open(self, start: datetime, end: datetime) -> PlaybackSession:
        async with self._lock:
            if self._session is not None:
                stale = self._session
                self._session = None
                await self.client.async_run_in_executor(stale.close)
            session = PlaybackSession(self.client, self.entry_id, start, end)
            try:
                await self.client.async_run_in_executor(session.open)
            except Exception as err:
                session.mark_failed(str(err))
                await self.client.async_run_in_executor(session.close)
                raise
            self._session = session
            return session

    async def async_control(self, session_id: str, action: str, seek_percent: float | None = None) -> PlaybackSession:
        async with self._lock:
            session = self._require_session(session_id)
            await self.client.async_run_in_executor(session.control, action, seek_percent)
            return session

    async def async_close(self, session_id: str | None = None) -> None:
        async with self._lock:
            session = self._session
            if session is None:
                return
            if session_id is not None and session.session_id != session_id:
                return
            self._session = None
            await self.client.async_run_in_executor(session.close)

    async def async_get_progress(self, session_id: str | None = None) -> int:
        async with self._lock:
            session = self._session
            if session is None:
                return 0
            if session_id is not None and session.session_id != session_id:
                return 0
            return await self.client.async_run_in_executor(session.get_progress)

    async def async_cleanup_if_stale(self) -> None:
        async with self._lock:
            session = self._session
            if session is None:
                return
            if session.is_stale(datetime.now(tz=UTC)):
                _LOGGER.debug("Closing stale playback session %s", session.session_id)
                self._session = None
                await self.client.async_run_in_executor(session.close)

    def _require_session(self, session_id: str) -> PlaybackSession:
        session = self._session
        if session is None:
            raise RuntimeError("No active playback session")
        if session.session_id != session_id:
            raise RuntimeError("Playback session not found")
        return session
