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
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mplayer.config import (  # noqa: E402
    CACHE_DIR, SVC_CMD_FILE, SVC_STATE_FILE, ensure_dirs, load_settings,
    log_line, setup_tls,
)
from mplayer.downloader import Downloader  # noqa: E402
from mplayer.mediasession import MediaController  # noqa: E402
from mplayer.models import Track  # noqa: E402
from mplayer.player import AndroidPlayer  # noqa: E402

POLL = 0.25


def log(msg: str) -> None:
    print(f"[music-svc] {msg}", flush=True)
    log_line(f"[svc] {msg}")


class MusicService:
    def __init__(self):
        ensure_dirs()
        setup_tls()
        self.settings = load_settings()
        self.downloader = Downloader(self.settings)
        self.player = AndroidPlayer()
        self.player.on_complete(self._on_complete)
        self.player.on_error(self._on_error)

        self.tracks: List[Track] = []
        self.index = 0
        self.order: List[int] = []
        self.repeat = str(self.settings.get("repeat", "all"))   # all | one | off
        self.shuffle = bool(self.settings.get("shuffle"))
        self.infinite = bool(self.settings.get("infinite", True))
        self.volume = float(self.settings.get("volume", 0.8))
        self.status = "대기 중"
        self.error = ""
        self.progress = 0
        self.prefetching = False
        self._complete_pending = False
        self._error_pending = False
        self._seq = 0
        self._lock = threading.RLock()
        self._last_pos = 0.0
        self._prefetch_top_running = False
        self._downloading: set = set()
        # MediaSession / 오디오 포커스 (차량 블루투스, 통화 등 대응)
        self._cmd_queue: List[tuple] = []
        self._cmd_lock = threading.Lock()
        self.media = MediaController(handlers={
            "play": lambda *a: self._push_cmd(("toggle",)),
            "pause": lambda *a: self._push_cmd(("pause_only",)),
            "next": lambda *a: self._push_cmd(("next",)),
            "prev": lambda *a: self._push_cmd(("prev",)),
            "seek": lambda pos: self._push_cmd(("seek", pos / 1000.0)),
            "stop": lambda *a: self._push_cmd(("stop",)),
            "noise": lambda *a: self._push_cmd(("pause_only",)),
            "focus_loss": lambda *a: self._push_cmd(("pause_only",)),
            "focus_loss_transient": lambda *a: self._push_cmd(("pause_only",)),
            "focus_gain": lambda *a: self._push_cmd(("resume_focus",)),
            "duck": lambda flag: self._push_cmd(("duck", bool(flag))),
        })
        self._ducked = False
        self._focus_paused = False
        self._last_media_update = 0.0
        self._last_notif_key = None

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
            "album": cur.album if cur else "",
            "index": self.index,
            "count": len(self.tracks),
            "volume": self.volume,
            "status": self.status,
            "error": self.error,
            "progress": self.progress,
            "repeat": self.repeat,
            "shuffle": self.shuffle,
            "infinite": self.infinite,
            "prefetching": self.prefetching,
            # 현재 곡의 실제 오디오 파일 경로 (기기 저장 등 UI 쪽 처리에서 사용)
            "file": (cur.file if cur else "") or self.player.path or "",
            "key": (cur.key if cur else ""),
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

    # ------------------------------------------------------------- 알림
    def _notify(self) -> None:
        """상태바 알림에 현재 곡을 표시한다."""
        cur = self.current()
        if not cur:
            return
        try:
            media = getattr(self, "media", None)
            if media is not None and media.ok:
                # MediaSession 스타일 알림으로 교체 (차량/이어폰에 곡 정보 표시)
                thumb = self.downloader.thumb_file(cur) if self.downloader else ""
                media.post_notification(cur.title, cur.artist, thumb)
                return
            from mplayer import notifier
            title = cur.title or "무한 음악 플레이어"
            text = cur.artist or "재생 중"
            if not notifier.update(title, text):
                notifier.post_standalone(title, text)
        except Exception:
            pass

    # ------------------------------------------------------------- 다운로드
    def _ensure(self, track: Track, progress=None) -> str:
        """같은 곡을 동시에 두 번 내려받지 않게 한다 (파일 손상 방지)."""
        key = track.key
        waited = 0
        while key in self._downloading and waited < 60:
            time.sleep(0.25)
            waited += 1
        self._downloading.add(key)
        try:
            return self.downloader.ensure_file(track, progress=progress)
        finally:
            self._downloading.discard(key)

    # ------------------------------------------------------------- 재생
    def _push_cmd(self, cmd) -> None:
        """MediaSession 콜백(자바 스레드)에서 넘어온 명령을 큐에 넣는다."""
        with self._cmd_lock:
            self._cmd_queue.append(cmd)

    def _drain_cmds(self) -> None:
        with self._cmd_lock:
            cmds = list(self._cmd_queue)
            self._cmd_queue.clear()
        for cmd in cmds:
            try:
                self._exec_media_cmd(cmd)
            except Exception:
                log("미디어 명령 오류: %s" % (cmd,))

    def _exec_media_cmd(self, cmd) -> None:
        name = cmd[0]
        if name == "toggle":
            self.toggle()
        elif name == "pause_only":
            self.pause()
        elif name == "resume_focus":
            self.resume()
        elif name == "next":
            self.next_track()
        elif name == "prev":
            self.prev_track()
        elif name == "seek":
            self.player.seek(float(cmd[1]))
            self.write_state()
        elif name == "stop":
            self.player.stop()
            self.status = "정지"
            self.write_state()
        elif name == "duck":
            self._ducked = bool(cmd[1])
            self.player.set_volume(self.volume * (0.15 if self._ducked else 1.0))

    def pause(self) -> None:
        """일시정지 (포커스 상실/노이즈/차량 조작)."""
        self.player.pause()
        if self.status != "정지":
            self.status = "일시정지"
        self._update_media(playing=False)
        self.write_state()

    def resume(self) -> None:
        """다시 재생 (포커스 복귀)."""
        if self.current() is None:
            return
        self.player.resume()
        self.status = "재생 중"
        self._update_media(playing=True)
        self.write_state()

    def play_index(self, index: int) -> None:
        if not self.tracks:
            return
        with self._lock:
            self.index = max(0, min(index, len(self.tracks) - 1))
            track = self.current()
            if track is None:
                return
            self.error = ""
            self.progress = 0
            # ★ 이전 곡을 먼저 멈춘다.
            #   멈추지 않으면 MediaPlayer 의 이전 재생 위치/길이가 새 곡에 적용돼
            #   "이전에 저장된 재생길이 부터" 재생되는 것처럼 보인다.
            try:
                self.player.stop()
            except Exception:
                pass
            self._last_pos = 0.0
            self.status = f"'{track.display}' 준비 중..."
            self._update_media(playing=False, reset=True)
            self.write_state()
            try:
                path = self._ensure(track, progress=self._on_progress)
            except Exception as exc:
                self.error = str(exc)
                self.status = "준비 실패"
                log(f"준비 실패: {exc}")
                self.write_state()
                return
            try:
                self.player.set_volume(self.volume * (0.15 if self._ducked else 1.0))
                self.player.play_file(path)
                self.progress = 100
                self.status = "재생 중"
                self._last_pos = 0.0
                log(f"재생: {track.display} ({path})")
            except Exception as exc:
                self.error = str(exc)
                self.status = "재생 실패"
                log(f"재생 실패: {exc}")
            self.write_state()
        self._update_media(playing=True, reset=True)
        self._notify()
        self._prefetch_next()

    def _update_media(self, playing: bool = False, reset: bool = False) -> None:
        """MediaSession / 알림에 현재 곡 정보를 반영한다."""
        try:
            if not getattr(self, "media", None) or not self.media.ok:
                return
            now = time.time()
            track = self.current()
            if track is None:
                return
            if playing:
                self.media.request_focus()
            pos = 0 if reset else int(self.player.position() * 1000)
            dur = int(self.player.duration() * 1000)
            if not reset and now - self._last_media_update < 1.0:
                return
            self._last_media_update = now
            thumb = self.downloader.thumb_file(track) if self.downloader else ""
            self.media.update(title=track.title, artist=track.artist,
                              album=track.album, duration_ms=dur,
                              position_ms=pos, playing=playing, artwork=thumb)
            # 알림은 곡이 바뀔 때만 다시 만든다 (매초 만들면 과부하)
            key = (track.title, track.artist, thumb)
            if key != self._last_notif_key:
                self._last_notif_key = key
                self.media.post_notification(track.title, track.artist, thumb)
        except Exception:
            pass

    def _on_progress(self, status: Dict[str, Any]) -> None:
        """yt-dlp 진행률 콜백."""
        try:
            if status.get("status") == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
                done = status.get("downloaded_bytes") or 0
                if total:
                    self.progress = max(0, min(100, int(done * 100 / total)))
                    self.status = f"음원 준비 중... {self.progress}%"
                else:
                    self.status = "음원 준비 중..."
            elif status.get("status") == "finished":
                self.progress = 100
        except Exception:
            pass

    def _prefetch_next(self) -> None:
        """다음 곡을 미리 내려받아 끊김 없이 이어재생한다."""
        if self.prefetching or not self.tracks:
            return
        try:
            nxt = self._next_index(1)
        except Exception:
            return
        if nxt == self.index or not (0 <= nxt < len(self.tracks)):
            return
        nxt_track = self.tracks[nxt]
        if self.downloader.is_cached(nxt_track):
            return
        self.prefetching = True

        def work():
            try:
                self._ensure(nxt_track)
                log(f"미리 받음: {nxt_track.display}")
            except Exception:
                pass
            finally:
                self.prefetching = False

        threading.Thread(target=work, daemon=True).start()

    def _prefetch_top(self, count: int) -> None:
        """목록 앞쪽 N 곡을 미리 내려받는다(바로 재생되게 준비)."""
        if count <= 0 or not self.tracks:
            return
        if self._prefetch_top_running:
            return
        self._prefetch_top_running = True
        targets = [t for t in self.tracks[:count]
                   if not self.downloader.is_cached(t)]

        def work():
            try:
                for t in targets:
                    if self.downloader.is_cached(t):
                        continue
                    self._ensure(t)
                    log(f"미리 받음: {t.display}")
            except Exception:
                pass
            finally:
                self._prefetch_top_running = False

        threading.Thread(target=work, daemon=True).start()

    def toggle(self) -> None:
        if self.player.is_playing():
            self.pause()
        else:
            if self.current() and not self.player.path:
                self.play_index(self.index)
            else:
                self.resume()
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

    def _detect_finished(self) -> None:
        """완료 콜백이 안 올라와도 재생 종료를 감지한다."""
        try:
            if not self.player.is_prepared:
                return
            dur = self.player.duration()
            pos = self.player.position()
            if dur <= 0:
                return
            if pos >= dur - 0.6 and not self.player.is_playing():
                if self._last_pos > 0:
                    self._complete_pending = True
            self._last_pos = pos
        except Exception:
            pass

    def _handle_pending(self) -> None:
        if self._error_pending:
            self._error_pending = False
            self.error = self.player.last_error or "재생 오류"
            self.status = "오류"
        if self._complete_pending:
            self._complete_pending = False
            if self.repeat == "one":
                self.play_index(self.index)
            else:
                self.next_track()

    # ------------------------------------------------------------- 기기 저장
    def export_index(self, index: int) -> None:
        """재생목록의 곡을 기기 공용 저장소(다운로드/음악 폴더)로 저장한다."""
        if not self.tracks:
            self.error = "저장할 곡이 없습니다."
            self.status = "저장 실패"
            self.write_state()
            return
        index = max(0, min(index, len(self.tracks) - 1))
        track = self.tracks[index]
        self.status = f"'{track.display}' 저장 준비 중..."
        self.error = ""
        self.write_state()
        try:
            path = self._ensure(track)
        except Exception as exc:
            self.error = f"준비 실패: {exc}"
            self.status = "저장 실패"
            log(f"저장 준비 실패: {exc}")
            self.write_state()
            return

        name = track.title or "audio"
        if track.artist:
            name = "%s - %s" % (track.artist, track.title)
        try:
            from mplayer.exporter import save_to_device
            saved = save_to_device(path, name)
        except Exception as exc:
            self.error = f"저장 실패: {exc}"
            self.status = "저장 실패"
            log(f"기기 저장 실패: {exc}")
            self.write_state()
            return
        self.status = f"저장 완료: {saved}"
        self.error = ""
        log(f"저장 완료: {saved}")
        self.write_state()

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
        elif name == "prefetch":
            self._prefetch_top(int(cmd.get("count", 3)))
        elif name == "export":
            self.export_index(int(cmd.get("index", self.index)))
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
        last_media = 0.0
        while True:
            try:
                self.poll_commands()
                self._drain_cmds()
                self._detect_finished()
                self._handle_pending()
                self.write_state()
                now = time.time()
                if now - last_media > 1.0:
                    last_media = now
                    self._update_media(playing=self.player.is_playing())
            except Exception:
                log("루프 오류:\n" + traceback.format_exc())
            time.sleep(POLL)


def main() -> None:
    try:
        log("서비스 초기화 시작")
        svc = MusicService()
        log("서비스 초기화 완료")
        svc.run()
    except KeyboardInterrupt:
        pass
    except Exception:
        log("치명적 오류:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
