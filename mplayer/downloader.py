"""유튜브 검색 + 오디오 다운로드(캐시).

안드로이드에서는 ffmpeg 로 mp3 변환을 하지 않는다.
  - 안드로이드용 ffmpeg 바이너리를 APK 에 넣으면 크기가 30MB 이상 커진다.
  - 대신 원본 스트림(m4a/webm)을 그대로 받고, 재생은 안드로이드
    MediaPlayer 가 담당한다(지원 포맷: m4a/AAC, webm/opus, mp3, ogg).

안드로이드에는 자바스크립트 런타임(deno/node)이 없기 때문에,
유튜브 "player" 클라이언트 중 JS 가 필요 없는 것만 사용한다.
  (tv / tv_simply / ios / android)
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional

from .config import CACHE_DIR, THUMB_DIR, setup_tls
from .models import Track

try:
    import yt_dlp
except Exception as exc:      # pragma: no cover
    yt_dlp = None
    _YTDLP_IMPORT_ERROR = str(exc)
else:
    _YTDLP_IMPORT_ERROR = ""


def ytdlp_status() -> tuple:
    """(사용 가능 여부, 버전 또는 오류 메시지)"""
    if yt_dlp is None:
        return False, _YTDLP_IMPORT_ERROR or "yt-dlp 없음"
    try:
        ver = yt_dlp.version.__version__        # type: ignore[attr-defined]
    except Exception:
        ver = "알 수 없음"
    return True, ver


# JS 런타임이 필요 없는 유튜브 player 클라이언트 (안드로이드용).
# 2026.08 기준 android_vr(1.65.10) 은 전 포맷 404/403 이라 제외한다.
CLIENT_PRESETS = {
    "auto": ["tv", "tv_simply", "ios", "android"],
    "tv": ["tv", "tv_simply"],
    "ios": ["ios", "mweb"],
    "android": ["android", "android_vr"],
    "web": ["web", "web_safari", "mweb"],
}

FORMAT_PRESETS = {
    "auto": "bestaudio/best",
    # 안드로이드 MediaPlayer 가 가장 잘 먹는 포맷 우선
    "m4a": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
    "webm": "bestaudio[ext=webm]/bestaudio/best",
    "mp3": "bestaudio[ext=mp4]/bestaudio/best",
}


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", (text or "").lower())


def find_ffmpeg() -> str:
    """ffmpeg 실행 파일 경로 (없으면 빈 문자열).

    안드로이드에는 ffmpeg 를 넣지 않으므로 항상 비어 있다.
    오디오는 원본 스트림(m4a/webm) 그대로 받아 안드로이드 MediaPlayer 로 재생한다.
    """
    import shutil
    for name in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def _similar(want: str, got: str) -> bool:
    w, g = _norm(want), _norm(got)
    if not w:
        return True
    if w in g:
        return True
    return SequenceMatcher(None, w, g).ratio() >= 0.62


def build_query(track: Track, template: str = "{artist} {title}") -> str:
    """검색어 템플릿을 채운다 ({artist} {title} {album} 지원)."""
    template = template or "{artist} {title}"
    try:
        return template.format(artist=track.artist or "",
                               title=track.title or "",
                               album=track.album or "").strip()
    except Exception:
        return f"{track.artist} {track.title}".strip()


def _queries(track: Track, template: str = "{artist} {title}") -> List[str]:
    out = []
    main = build_query(track, template)
    if main:
        out.append(main)
    if track.title and main != track.title:
        out.append(track.title)
    if track.artist:
        out.append(f"{track.artist} official audio")
    seen = set()
    uniq = []
    for q in out:
        if q and q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


class Downloader:
    """검색/다운로드/캐시 인덱스 관리."""

    def __init__(self, settings: Optional[dict] = None):
        setup_tls()
        self.settings = settings or {}
        self.index_path = CACHE_DIR / "index.json"
        self.index = self._load_index()

    # ------------------------------------------------------------- 인덱스
    def _load_index(self) -> dict:
        import json
        try:
            with self.index_path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}

    def _save_index(self):
        import json
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with self.index_path.open("w", encoding="utf-8") as fp:
                json.dump(self.index, fp, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------- 설정
    @property
    def search_template(self) -> str:
        return str(self.settings.get("search_query") or "{artist} {title}")

    @property
    def player_clients(self) -> List[str]:
        key = str(self.settings.get("yt_client") or "auto")
        return list(CLIENT_PRESETS.get(key, CLIENT_PRESETS["auto"]))

    @property
    def audio_format(self) -> str:
        key = str(self.settings.get("audio_format") or "auto")
        return FORMAT_PRESETS.get(key, FORMAT_PRESETS["auto"])

    def _base_opts(self) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 5,
            "nocheckcertificate": False,
            "ignoreerrors": False,
            "noprogress": True,
        }
        clients = self.player_clients
        if clients:
            opts["extractor_args"] = {"youtube": {"player_client": clients}}
        return opts

    # ------------------------------------------------------------- 캐시
    @staticmethod
    def cached_file(track: Track) -> str:
        info = getattr(Downloader, "_shared_index", {}).get(track.key, {})
        path = info.get("file", "")
        if path and Path(path).exists():
            return path
        return ""

    @staticmethod
    def _index_of(track: Track) -> dict:
        return getattr(Downloader, "_shared_index", {}).get(track.key, {})

    def cached_file_for(self, track: Track) -> str:
        path = (self.index.get(track.key) or {}).get("file", "")
        if path and Path(path).exists():
            return path
        return ""

    def thumb_file(self, track: Track) -> str:
        return (self.index.get(track.key) or {}).get("thumb_local", "")

    def is_cached(self, track: Track) -> bool:
        return bool(self.cached_file_for(track))

    # ------------------------------------------------------------- 검색
    def search(self, query: str, limit: int = 20) -> List[Track]:
        """유튜브 검색 → 재생목록."""
        if yt_dlp is None:
            raise RuntimeError(f"yt-dlp 를 사용할 수 없습니다: {_YTDLP_IMPORT_ERROR}")
        opts = self._base_opts()
        opts.update({"skip_download": True, "extract_flat": "in_playlist"})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        except Exception as exc:
            raise RuntimeError(f"유튜브 검색 실패: {exc}") from exc
        entries = (info or {}).get("entries") or []
        tracks: List[Track] = []
        for entry in entries:
            if not entry:
                continue
            vid = entry.get("id") or ""
            title = entry.get("title") or ""
            if not vid or not title:
                continue
            thumbs = entry.get("thumbnails") or []
            tracks.append(Track(
                title=title,
                artist=entry.get("uploader") or entry.get("channel") or "",
                rank=len(tracks) + 1,
                source="youtube",
                url=f"https://www.youtube.com/watch?v={vid}",
                video_id=vid,
                thumb=thumbs[-1].get("url", "") if thumbs else "",
                duration=float(entry.get("duration") or 0.0),
            ))
        return tracks

    def resolve_video_id(self, track: Track) -> str:
        """검색으로 영상 ID 확보."""
        if track.video_id:
            return track.video_id
        cached = (self.index.get(track.key) or {}).get("video_id")
        if cached:
            track.video_id = cached
            return cached
        if yt_dlp is None:
            return ""
        opts = self._base_opts()
        opts.update({"skip_download": True, "extract_flat": "in_playlist"})
        for query in _queries(track, self.search_template):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    res = ydl.extract_info(f"ytsearch1:{query}", download=False)
            except Exception:
                continue
            entries = (res or {}).get("entries") or []
            entry = next((e for e in entries if e), None)
            if entry and entry.get("id"):
                track.video_id = entry["id"]
                track.duration = float(entry.get("duration") or track.duration or 0.0)
                self.index[track.key] = dict(self.index.get(track.key) or {})
                self.index[track.key]["video_id"] = track.video_id
                self.index[track.key]["duration"] = track.duration
                self._save_index()
                return track.video_id
        return ""

    # ------------------------------------------------------------- 다운로드
    def ensure_file(self, track: Track, progress=None) -> str:
        """오디오 파일 경로를 확보한다(없으면 검색 후 다운로드)."""
        path = self.cached_file_for(track)
        if path:
            track.file = path
            info = self.index.get(track.key) or {}
            track.video_id = info.get("video_id", track.video_id)
            track.duration = float(info.get("duration") or track.duration or 0.0)
            return path

        if yt_dlp is None:
            raise RuntimeError(f"yt-dlp 를 사용할 수 없습니다: {_YTDLP_IMPORT_ERROR}")

        vid = self.resolve_video_id(track)
        if not vid:
            raise RuntimeError(f"'{track.display}' 을(를) 찾지 못했습니다.")

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        outtmpl = str(CACHE_DIR / "%(id)s.%(ext)s")
        opts = self._base_opts()
        opts.update({
            "outtmpl": outtmpl,
            "format": self.audio_format,
            "overwrites": False,
        })
        if progress:
            def _hook(status):
                try:
                    progress(status)
                except Exception:
                    pass
            opts["progress_hooks"] = [_hook]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={vid}", download=True)
        except Exception as exc:
            raise RuntimeError(f"다운로드 실패: {exc}") from exc

        path = ""
        if info:
            for cand in info.get("requested_downloads") or []:
                fp = cand.get("filepath") or cand.get("_filename")
                if fp and Path(fp).exists():
                    path = fp
                    break
            if not path:
                for key in ("filepath", "_filename"):
                    fp = info.get(key)
                    if fp and Path(fp).exists():
                        path = fp
                        break
        if not path:
            raise RuntimeError("다운로드를 완료하지 못했습니다.")

        track.file = path
        track.video_id = vid
        track.duration = float(info.get("duration") or track.duration or 0.0)
        self.index[track.key] = {
            "file": path,
            "video_id": vid,
            "duration": track.duration,
            "thumb": track.thumb,
        }
        self._save_index()
        return path

    # ------------------------------------------------------------- 표지
    def download_thumb(self, track: Track) -> str:
        """표지 이미지를 로컬로 내려받는다(오프라인 표시용)."""
        url = track.thumb
        if not url:
            return ""
        try:
            import requests
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"})
            data = resp.content
        except Exception:
            return ""
        if not data:
            return ""
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        path = THUMB_DIR / (hashlib.md5(url.encode()).hexdigest() + ".jpg")
        try:
            path.write_bytes(data)
        except Exception:
            return ""
        return str(path)
