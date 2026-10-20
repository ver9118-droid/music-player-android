"""가사 조회: 멜론 가사 → 유튜브 설명문 fallback."""
from __future__ import annotations

import html as html_mod
import json
import re
import threading
from typing import Optional, Tuple

import requests

from .chart import UA
from .config import CACHE_DIR
from .models import Track

_LYRIC_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
CACHE_FILE = CACHE_DIR / "lyrics.json"


def _load_cache() -> None:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with _CACHE_LOCK:
                    _LYRIC_CACHE.update(data)
    except Exception:
        pass


def _save_cache() -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _CACHE_LOCK:
            data = dict(_LYRIC_CACHE)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except Exception:
        pass


_load_cache()


def cached_lyrics(track: Track) -> Optional[Tuple[str, str]]:
    with _CACHE_LOCK:
        item = _LYRIC_CACHE.get(track.key)
    if not item:
        return None
    try:
        return item[0], item[1]
    except Exception:
        return None


def store_lyrics(track: Track, text: str, source: str) -> None:
    if not text:
        return
    with _CACHE_LOCK:
        _LYRIC_CACHE[track.key] = [text, source]
    _save_cache()

_LYRIC_RE = re.compile(r'id="lyricArea"[^>]*>(.*?)</div>', re.S)
_LYRIC_BLOCK_RE = re.compile(r'class="lyric"[^>]*>(.*?)</div>', re.S)


def _clean_lyric(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    text = text.replace("\xa0", " ").replace("\r", "")
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    out: list[str] = []
    for ln in lines:
        if out and out[-1] == ln:      # 멜론이 원문/체크용으로 중복 출력하는 경우가 있음
            continue
        out.append(ln)
    return "\n".join(out)


def fetch_melon_lyrics(track: Track, timeout: int = 15) -> str:
    """멜론 곡 상세 페이지에서 가사를 가져온다."""
    if not track.melon_id:
        return ""
    url = f"https://www.melon.com/song/detail.htm?songId={track.melon_id}"
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception:
        return ""
    page = resp.text
    for pattern in (_LYRIC_RE, _LYRIC_BLOCK_RE):
        m = pattern.search(page)
        if not m:
            continue
        lyric = _clean_lyric(m.group(1))
        if lyric and len(lyric) > 20:
            return lyric
    return ""


def fetch_youtube_lyrics(track: Track, timeout: int = 20) -> str:
    """유튜브 영상 설명문에서 가사 부분을 추출한다 (fallback)."""
    if not track.video_id:
        return ""
    try:
        import yt_dlp
    except Exception:
        return ""
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "socket_timeout": timeout,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={track.video_id}", download=False)
    except Exception:
        return ""
    desc = (info or {}).get("description") or ""
    return extract_lyric_from_description(desc)


_LYRIC_HINT = re.compile(r"[\[\(].{0,30}(?:가사|lyrics|lyric).{0,30}[\]\)]", re.I)


def extract_lyric_from_description(desc: str) -> str:
    """설명문에서 가사처럼 보이는 구간만 뽑아낸다."""
    if not desc:
        return ""
    lines = [ln.strip() for ln in desc.splitlines()]
    start = None
    for i, ln in enumerate(lines):
        if _LYRIC_HINT.search(ln):
            start = i + 1
            break
    if start is None:
        # '제목 : 가사' 패턴
        for i, ln in enumerate(lines):
            if re.match(r"^\s*(제목|가사|lyrics?)\s*[:：]", ln, re.I):
                start = i + 1
                break
    if start is None:
        return ""
    collected: list[str] = []
    for ln in lines[start:]:
        if not ln:
            if collected:
                break
            continue
        if re.match(r"^\s*(#|https?://|※|참고|출처|제공)", ln):
            break
        if re.search(r"\d{1,2}:\d{2}", ln):     # 타임태그
            continue
        if len(ln) > 120:
            break
        collected.append(ln)
        if len(collected) > 120:
            break
    return "\n".join(collected)


def fetch_lyrics(track: Track) -> Tuple[str, str]:
    """(가사, 출처) 반환. 가사를 못 얻으면 ("", "")."""
    cached = cached_lyrics(track)
    if cached:
        return cached
    lyric = fetch_melon_lyrics(track)
    if lyric:
        store_lyrics(track, lyric, "멜론")
        return lyric, "멜론"
    lyric = fetch_youtube_lyrics(track)
    if lyric:
        store_lyrics(track, lyric, "유튜브 설명문")
        return lyric, "유튜브 설명문"
    return "", ""


# --------------------------------------------------------------------- 노래방(카라오케) 타임라인
def split_lines(lyric: str) -> List[str]:
    return [ln.strip() for ln in (lyric or "").splitlines() if ln.strip()]


_NOISE = re.compile(r"^\s*[\[\(](음악|music|기악|노래|instrumental|applause)[^\]\)]*[\]\)]\s*$", re.I)


def fetch_youtube_captions(video_id: str) -> List[Tuple[float, str]]:
    """유튜브 자동 캡션에서 (시작초, 텍스트) 목록을 가져온다 (싱크용)."""
    if not video_id:
        return []
    try:
        import yt_dlp
    except Exception:
        return []
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception:
        return []
    caps = info.get("automatic_captions") or {}
    tracks = caps.get("ko") or caps.get("ko-orig") or caps.get("en") or []
    target = next((t for t in tracks if t.get("ext") == "json3"), None)
    if not target:
        return []
    try:
        import urllib.request
        req = urllib.request.Request(target["url"],
                                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        data = json.loads(raw)
    except Exception:
        return []
    segments: List[Tuple[float, str]] = []
    for ev in data.get("events", []):
        if "segs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not text or _NOISE.match(text):
            continue
        start = float(ev.get("tStartMs", 0)) / 1000.0
        segments.append((start, text))
    return segments


def align_with_captions(lines: List[str], captions: List[Tuple[float, str]],
                        duration: float) -> List[float]:
    """자막 타임스탬프를 가사 줄에 배분한다 (누적 글자 비율 기반)."""
    if not lines:
        return []
    if not captions:
        return []
    if len(captions) == len(lines):
        return [t for t, _ in captions]
    caps = [(t, max(1, len(x))) for t, x in captions]
    cap_total = sum(c for _, c in caps)
    weights = [max(1, len(ln)) for ln in lines]
    total = sum(weights)
    times: List[float] = []
    acc = 0
    for w in weights:
        target = (acc / total) * cap_total
        run = 0
        chosen = caps[0][0]
        for t, c in caps:
            if run + c >= target:
                chosen = t
                break
            run += c
        times.append(chosen)
        acc += w
    return times


def estimate_vocal_onset(audio_path: str, duration: float = 0.0) -> float:
    """오디오 에너지로 보컬 시작 지점을 추정한다 (자막이 없을 때 사용).

    안드로이드에는 ffmpeg/numpy 가 없으므로 0 을 반환하고,
    가사 타임라인은 자막(캡션) 동기화를 우선 사용한다.
    """
    if not audio_path:
        return 0.0
    try:
        import subprocess
        import numpy as np
        try:
            from .downloader import find_ffmpeg
        except Exception:
            return 0.0
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return 0.0
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", audio_path,
               "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
        raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
        if not raw:
            return 0.0
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        win = 4000                      # 0.5초
        count = len(samples) // win
        if count < 8:
            return 0.0
        frames = samples[:count * win].reshape(count, win)
        rms = np.sqrt((frames ** 2).mean(axis=1))
        peak = float(rms.max()) or 1.0
        norm = rms / peak
        for i in range(min(count, 80)):          # 앞 40초 안에서 탐색
            if norm[i] > 0.45 and all(v > 0.32 for v in norm[i:i + 3]):
                return i * 0.5
    except Exception:
        pass
    return 0.0


def build_timeline(lines: List[str], duration: float, intro: float = 0.02) -> List[float]:
    """각 가사 줄의 시작 시간(초)을 추정한다.

    멜론 가사에는 타임스탬프가 없으므로 글자 수에 비례해 시간을 배분한다.
    (긴 줄 = 더 오래 걸리는 것으로 근사)
    """
    if not lines:
        return []
    if duration <= 0:
        duration = max(60.0, len(lines) * 4.0)
    weights = [max(1.0, len(ln)) for ln in lines]
    total = sum(weights)
    span = duration * (1.0 - intro)
    times: List[float] = []
    acc = duration * intro
    for w in weights:
        times.append(acc)
        acc += span * w / total
    return times


def line_index_at(times: List[float], position: float) -> int:
    """현재 재생 위치에 해당하는 가사 줄 번호."""
    if not times:
        return 0
    idx = 0
    for i, start in enumerate(times):
        if position >= start:
            idx = i
        else:
            break
    return idx
