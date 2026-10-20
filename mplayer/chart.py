"""음악 소스 파서: 멜론 차트/최신곡/최신앨범/최신MV + 로컬 음악 폴더."""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import List, Optional

import requests

from .models import Track

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac", ".wma", ".alac"}
DEFAULT_CHART_URL = "https://www.melon.com/chart/index.htm"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _http_get(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = "utf-8"          # 멜론 응답은 UTF-8 고정
    return resp.text


# --------------------------------------------------------------------- 멜론 곡 목록
def fetch_melon_songs(url: str = DEFAULT_CHART_URL, limit: int = 50) -> List[Track]:
    """차트/최신곡 페이지에서 곡 목록을 파싱한다 (테이블 구조 공통)."""
    page = _http_get(url)
    tracks: List[Track] = []
    for attrs, body in re.findall(r"<tr([^>]*)>(.*?)</tr>", page, re.S):
        if "ellipsis" not in body:
            continue
        m_song = re.search(r'data-song-no="(\d+)"', attrs + body)
        m_rank = re.search(r'<span class="rank[^"]*">\s*(\d+)</span>', body)
        blocks = dict(re.findall(r'class="ellipsis (rank\d+)"[^>]*>(.*?)</div>', body, re.S))
        title = _first_link(blocks.get("rank01", ""))
        artist = _all_links(blocks.get("rank02", ""))
        album = _first_link(blocks.get("rank03", ""))
        if not title:
            title = _first_link(blocks.get("rank03", ""))
            album = ""
            artist = artist or _all_links(blocks.get("rank01", ""))
        if not title:
            continue
        m_thumb = re.search(r'<img[^>]+src="(https://cdnimg\.melon\.co\.kr[^"]+)"', body)
        song_no = m_song.group(1) if m_song else ""
        tracks.append(Track(
            title=title,
            artist=artist,
            album=album,
            rank=int(m_rank.group(1)) if m_rank else len(tracks) + 1,
            source="melon",
            url=f"https://www.melon.com/song/detail.htm?songId={song_no}" if song_no else url,
            thumb=m_thumb.group(1) if m_thumb else "",
            melon_id=song_no,
        ))
        if len(tracks) >= limit:
            break
    if not tracks:
        raise RuntimeError("멜론 페이지 파싱에 실패했습니다. (구조가 바뀌었을 수 있음)")
    return tracks


# --------------------------------------------------------------------- 멜론 앨범/MV
def fetch_melon_items(url: str, limit: int = 50, kind: str = "album") -> List[Track]:
    """최신앨범 / 최신 뮤직비디오 페이지 파싱 (<li> 구조)."""
    page = _http_get(url)
    tracks: List[Track] = []
    for item in re.findall(r"<li>(.*?)</li>", page, re.S):
        if 'class="ellipsis album_name"' not in item:
            continue
        m_title = re.search(r'class="ellipsis album_name"[^>]*>(.*?)</a>', item, re.S)
        m_artist = re.search(r'class="ellipsis artist">(.*?)</span>', item, re.S)
        m_date = re.search(r'class="reg_date"[^>]*>(.*?)</span>', item, re.S)
        m_thumb = re.search(r'<img[^>]+src="(https://cdnimg\.melon\.co\.kr[^"]+)"', item)
        title = _clean(m_title.group(1)) if m_title else ""
        artist = _all_links(m_artist.group(1)) if m_artist else ""
        if not title:
            continue
        tracks.append(Track(
            title=title,
            artist=artist,
            album=_clean(m_date.group(1)) if m_date else "",
            rank=len(tracks) + 1,
            source="melon",
            url=url,
            thumb=m_thumb.group(1) if m_thumb else "",
            item_kind=kind,
        ))
        if len(tracks) >= limit:
            break
    if not tracks:
        raise RuntimeError("멜론 페이지 파싱에 실패했습니다.")
    return tracks


def _first_link(fragment: str) -> str:
    m = re.search(r"<a[^>]*>(.*?)</a>", fragment, re.S)
    return _clean(m.group(1)) if m else ""


def _all_links(fragment: str) -> str:
    names: List[str] = []
    for raw in re.findall(r"<a[^>]*>(.*?)</a>", fragment, re.S):
        name = _clean(raw)
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


# --------------------------------------------------------------------- 지니 장르차트
GENIE_GENRE_URL = "https://www.genie.co.kr/chart/genre?ditc=D&genrecode={code}&pg=1"


def fetch_genie_chart(code: str, limit: int = 50) -> List[Track]:
    """지니 장르별 차트를 파싱한다 (code: M0100 가요, M0900 댄스 ...)."""
    url = GENIE_GENRE_URL.format(code=code)
    page = _http_get(url)
    tracks: List[Track] = []
    for body in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        m_title = re.search(r'class="title[^"]*"[^>]*>(.*?)</a>', body, re.S)
        if not m_title:
            continue
        m_artist = re.search(r'class="artist[^"]*"[^>]*>(.*?)</a>', body, re.S)
        m_rank = re.search(r'class="rank[^"]*"[^>]*>.*?(\d+)</', body, re.S)
        title = _clean(m_title.group(1))
        artist = _clean(m_artist.group(1)) if m_artist else ""
        if not title:
            continue
        tracks.append(Track(
            title=title,
            artist=artist,
            rank=int(m_rank.group(1)) if m_rank else len(tracks) + 1,
            source="genie",
            url=url,
        ))
        if len(tracks) >= limit:
            break
    if not tracks:
        raise RuntimeError("지니 차트 파싱에 실패했습니다.")
    return tracks


# --------------------------------------------------------------------- 로컬/유튜브
def scan_local_folder(folder: str, limit: int = 500) -> List[Track]:
    root = Path(folder)
    if not root.is_dir():
        return []
    tracks: List[Track] = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in AUDIO_EXTS or not p.is_file():
            continue
        stem = p.stem
        artist, title = "", stem
        if " - " in stem:
            artist, title = stem.split(" - ", 1)
        tracks.append(Track(title=title.strip(), artist=artist.strip(),
                            source="local", url=str(p), file=str(p)))
        if len(tracks) >= limit:
            break
    return tracks


def parse_youtube_url(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def track_from_youtube_url(url: str, title: str = "", artist: str = "") -> Track:
    return Track(title=title or url, artist=artist, source="youtube",
                 url=url, video_id=parse_youtube_url(url) or "")
