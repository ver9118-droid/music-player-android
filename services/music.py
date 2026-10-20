"""백그라운드 재생 서비스 (안드로이드 별도 프로세스).

p4a 의 arbitrary service 스크립트로 등록되어, 앱이 화면에서 닫혀도
계속 재생됩니다.  buildozer.spec 에서 foreground + mediaPlayback 로 선언.

  services = music:services/music.py:foreground:sticky:foregroundServiceType=mediaPlayback

UI(앱 프로세스)와는 파일로 통신한다.
  - 명령: svc_cmd_000001.json ... (순서대로 처리 후 삭제)
  - 상태: svc_state.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mplayer.config import (  # noqa: E402
    CACHE_DIR, SVC_CMD_FILE, SVC_STATE_FILE, ensure_dirs, setup_tls,
)
from mplayer.downloader import Downloader  # noqa: E402
from mplayer.models import Track  # noqa: E402
from mplayer.player import AndroidPlayer  # noqa: E402

POLL = 0.25


def log(msg: str) -> None:
    print(f"[music-svc] {msg}", flush=True)


class MusicService:
    def __init__(self):
        ensure_dirs()
        setup_tls()
        self.downloader = Downloader()
        self.player = AndroidPlayer()
        self.player.on_complete(self._on_complete)
        self.player.on_error(self._on_error)

        self.tracks: List[Track] = []
        self.index = 0
        self.order: List[int] = []
        self.repeat = "all"       # all | one | off
        self.shuffle = False
        self.infinite = True
        self.volume = 0.8
        self.status = "대기 중"
        self.error = ""
        self._complete_pending = False
        self._error_pending = False
        self._seq = 0

    # ------------------------------------------------------------- 상태 저장
    def write_state(self) -> None:
        cur = self.current()
        state = {
            "alive": True,
            "pid": os.getpid(),
            "playing": self.player.is_playing(),
            "paused": not self.player.is_playing() and bool(cur),
            "pos": round(self.player.position(), 2),
            "dur": round(self.player.duration(), 2),
            "title": cur.title if cur else "",
            "artist": cur.artist if cur else "",
            "index": self.index,
            "count": len(self.tracks),
            "volume": self.volume,
            "status": self.status,
            "error": self.error,
            "repeat": self.repeat,
            "shuffle": self.shuffle,
            "infinite": self.infinite,
        }
        try:
            SVC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = SVC_STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(SVC_STATE_FILE))
        except Exception:
            pass

    # ------------------------------------------------------------- 재생목록
    def current(self) -> Optional[Track]:
        if not self.tracks:
            return None
        if 0 <= self.index < len(self.tracks):
            return self.tracks[self.index]
        return None

    def set_playlist(self, tracks: List[Dict[str, Any]]) -> None:
        self.tracks = [Track.from_dict(t) for t in tracks]
        self._rebuild_order()
        self.index = 0
        self.status = f"{len(self.tracks)}곡 준비됨"

    def _rebuild_order(self) -> None:
        n = len(self.tracks)
        if not n:
            self.order = []
            return
        if self.shuffle:
            import random
            self.order = list(range(n))
            random.shuffle(self.order)
        else:
            self.order = list(range(n))

    def _next_index(self, step: int = 1) -> int:
        if not self.tracks:
            return 0
        if self.repeat == "one":
            return self.index
        if self.order:
            try:
                pos = self.order.index(self.index)
            except ValueError:
                pos = 0
            pos = (pos + step) % len(self.order)
            nxt = self.order[pos]
        else:
            nxt = (self.index + step) % len(self.tracks)
        if nxt <= self.index and self.index >= len(self.tracks) - 1:
            # 끝에 도달
            if self.repeat == "off" and not self.infinite:
                return self.index
        return nxt

    # ------------------------------------------------------------- 재생
    def play_index(self, index: int) -> None:
        if not self.tracks:
            return
        self.index = max(0, min(index, len(self.tracks) - 1))
        track = self.current()
        if track is None:
            return
        self.error = ""
        self.status = f"'{track.display}' 준비 중..."
        self.write_state()
        try:
            path = self.downloader.ensure_file(track)
        except Exception as exc:
            self.error = str(exc)
            self.status = "준비 실패"
            log(f"준비 실패: {exc}")
            self.write_state()
            return
        try:
            self.player.set_volume(self.volume)
            self.player.play_file(path)
            self.status = "재생 중"
            log(f"재생: {track.display}")
        except Exception as exc:
            self.error = str(exc)
            self.status = "재생 실패"
            log(f"재생 실패: {exc}")
        self.write_state()

    def toggle(self) -> None:
        if self.player.is_playing():
            self.player.pause()
            self.status = "일시정지"
        else:
            if self.current() and not self.player.path:
                self.play_index(self.index)
            else:
                self.player.resume()
                self.status = "재생 중"
        self.write_state()

    def next_track(self) -> None:
        self.play_index(self._next_index(1))

    def prev_track(self) -> None:
        # 3초 이내로 되감기 없으면 이전 곡
        if self.player.position() > 3.0:
            self.player.seek(0.0)
            self.write_state()
            return
        self.play_index(self._next_index(-1))

    def _on_complete(self) -> None:
        self._complete_pending = True

    def _on_error(self) -> None:
        self._error_pending = True

    def _handle_pending(self) -> None:
        if self._error_pending:
            self._error_pending = False
            self.error = "재생 오류"
            self.status = "오류"
        if self._complete_pending:
            self._complete_pending = False
            if self.repeat == "one":
                self.play_index(self.index)
            else:
                self.next_track()

    # ------------------------------------------------------------- 명령 처리
    def handle(self, cmd: Dict[str, Any]) -> None:
        name = cmd.get("cmd", "")
        if name == "play":
            self.play_index(int(cmd.get("index", 0)))
        elif name == "toggle":
            self.toggle()
        elif name == "pause":
            self.player.pause()
            self.status = "일시정지"
        elif name == "resume":
            self.player.resume()
            self.status = "재생 중"
        elif name == "next":
            self.next_track()
        elif name == "prev":
            self.prev_track()
        elif name == "seek":
            self.player.seek(float(cmd.get("pos", 0.0)))
        elif name == "volume":
            self.volume = max(0.0, min(1.0, float(cmd.get("value", 0.8))))
            self.player.set_volume(self.volume)
        elif name == "playlist":
            self.set_playlist(cmd.get("tracks") or [])
        elif name == "repeat":
            self.repeat = str(cmd.get("value", "all"))
            self._rebuild_order()
        elif name == "shuffle":
            self.shuffle = bool(cmd.get("value"))
            self._rebuild_order()
        elif name == "infinite":
            self.infinite = bool(cmd.get("value"))
        elif name == "stop":
            self.player.stop()
            self.status = "정지"

    def poll_commands(self) -> None:
        base = SVC_CMD_FILE.parent
        stem = SVC_CMD_FILE.stem
        try:
            files = sorted(p for p in base.glob(f"{stem}_*.json"))
        except Exception:
            return
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = None
            if data:
                try:
                    self.handle(data)
                except Exception:
                    log("명령 처리 오류:\n" + traceback.format_exc())
            try:
                path.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------- 메인 루프
    def run(self) -> None:
        log(f"서비스 시작 (pid={os.getpid()})")
        self.write_state()
        last = time.time()
        while True:
            try:
                self.poll_commands()
                self._handle_pending()
                self.write_state()
            except Exception:
                log("루프 오류:\n" + traceback.format_exc())
            time.sleep(POLL)


def main() -> None:
    try:
        MusicService().run()
    except KeyboardInterrupt:
        pass
    except Exception:
        log("치명적 오류:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
