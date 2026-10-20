"""안드로이드 네이티브 MediaPlayer 래퍼.

이유:
  - SDL2_mixer 는 m4a(AAC)/opus(webm) 를 지원하지 않는다.
    유튜브 음원은 대부분 m4a 이므로 ffmpeg 로 mp3 변환이 필요한데,
    안드로이드용 ffmpeg 바이너리를 넣으면 APK 가 30MB 이상 커진다.
  - 안드로이드 MediaPlayer 는 m4a/webm/mp3 를 모두 지원하고,
    시스템이 오디오 포커스/알림/백그라운드 재생을 처리한다.
  - jnius(파이썬→자바) 로 네이티브 API 를 직접 부를 수 있다.
"""
from __future__ import annotations

import threading
from typing import Optional

from .config import IS_ANDROID


class AndroidPlayer:
    """android.media.MediaPlayer 를 감싼 최소 재생 컨트롤."""

    def __init__(self):
        self._mp = None
        self._lock = threading.RLock()
        self._path = ""
        self._prepared = False
        self._paused = False
        self._volume = 0.8
        self._on_complete = None
        self._on_error = None

    # ------------------------------------------------------------- jnius 준비
    @staticmethod
    def _java():
        from jnius import autoclass
        return autoclass

    def _new_player(self):
        autoclass = self._java()
        MediaPlayer = autoclass("android.media.MediaPlayer")
        mp = MediaPlayer()
        # 완료/오류 콜백을 UI 스레드로 넘기기 위해 핸들러를 쓴다.
        Handler = autoclass("android.os.Handler")
        Looper = autoclass("android.os.Looper")
        handler = Handler(Looper.getMainLooper())
        listener = autoclass("android.media.MediaPlayer$OnCompletionListener")
        mp.setOnCompletionListener(listener(lambda *a: self._fire_complete()))
        err_listener = autoclass("android.media.MediaPlayer$OnErrorListener")
        mp.setOnErrorListener(err_listener(lambda *a, b: self._fire_error()))
        return mp, handler

    # ------------------------------------------------------------- 콜백
    def on_complete(self, fn):
        self._on_complete = fn

    def on_error(self, fn):
        self._on_error = fn

    def _fire_complete(self):
        if self._on_complete:
            try:
                self._on_complete()
            except Exception:
                pass

    def _fire_error(self):
        if self._on_error:
            try:
                self._on_error()
            except Exception:
                pass

    # ------------------------------------------------------------- 재생 제어
    def play_file(self, path: str, start_pos: float = 0.0) -> bool:
        """파일 재생 (재생 준비까지 대기)."""
        if not IS_ANDROID:
            raise RuntimeError("이 플레이어는 안드로이드 전용입니다.")
        with self._lock:
            self.release()
            mp, handler = self._new_player()
            self._mp = mp
            self._path = path
            self._paused = False
            mp.setDataSource(path)
            mp.prepare()
            if start_pos > 0:
                ms = int(start_pos * 1000)
                if ms < mp.getDuration():
                    mp.seekTo(ms)
            mp.setVolume(self._volume, self._volume)
            mp.start()
            self._prepared = True
            return True

    def pause(self):
        with self._lock:
            if self._mp and self._prepared:
                self._mp.pause()
                self._paused = True

    def resume(self):
        with self._lock:
            if self._mp and self._prepared:
                self._mp.start()
                self._paused = False

    def stop(self):
        with self._lock:
            if self._mp:
                try:
                    if self._prepared:
                        self._mp.stop()
                except Exception:
                    pass
            self.release()

    def release(self):
        with self._lock:
            if self._mp is not None:
                try:
                    self._mp.release()
                except Exception:
                    pass
            self._mp = None
            self._prepared = False
            self._paused = False

    def seek(self, seconds: float):
        with self._lock:
            if self._mp and self._prepared:
                self._mp.seekTo(int(max(0.0, seconds) * 1000))

    def set_volume(self, value: float):
        self._volume = max(0.0, min(1.0, float(value)))
        with self._lock:
            if self._mp and self._prepared:
                try:
                    self._mp.setVolume(self._volume, self._volume)
                except Exception:
                    pass

    # ------------------------------------------------------------- 상태
    def position(self) -> float:
        with self._lock:
            if self._mp and self._prepared:
                try:
                    return self._mp.getCurrentPosition() / 1000.0
                except Exception:
                    return 0.0
        return 0.0

    def duration(self) -> float:
        with self._lock:
            if self._mp and self._prepared:
                try:
                    return self._mp.getDuration() / 1000.0
                except Exception:
                    return 0.0
        return 0.0

    def is_playing(self) -> bool:
        with self._lock:
            if self._mp and self._prepared:
                try:
                    return bool(self._mp.isPlaying())
                except Exception:
                    return False
        return False

    @property
    def path(self) -> str:
        return self._path
