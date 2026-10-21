"""소스 정의: 멜론 TOP100 · 지니 장르차트 10종 · 한국대중음악(유튜브) 8종."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

# 즐겨찾기 목록은 소스 목록에 "★ 이름" 으로 붙는다.
FAVORITE_PREFIX = "★ "


@dataclass
class Source:
    key: str
    label: str
    group: str
    kind: str = "melon"      # melon | genie | yt_genre
    url: str = ""
    query: str = ""          # 유튜브 검색어 (장르 소스)
    limit: int = 50

    @property
    def display(self) -> str:
        return f"{self.group} > {self.label}"


MELON = "멜론 차트"
GENIE = "지니 장르차트"
KOREA = "한국대중음악"

SOURCES: List[Source] = [
    # ── 멜론 (TOP100)
    Source("top100", "TOP100", MELON, kind="melon",
           url="https://www.melon.com/chart/index.htm"),
    # ── 지니 장르차트 10종
    Source("g_genie_pop", "가요", GENIE, kind="genie", url="M0100"),
    Source("g_genie_dance", "댄스", GENIE, kind="genie", url="M0900"),
    Source("g_genie_rap", "랩/힙합", GENIE, kind="genie", url="M1000"),
    Source("g_genie_rock", "록/메탈", GENIE, kind="genie", url="M0700"),
    Source("g_genie_ccm", "CCM", GENIE, kind="genie", url="M0800"),
    Source("g_genie_pop2", "POP", GENIE, kind="genie", url="M0200"),
    Source("g_genie_ost", "OST", GENIE, kind="genie", url="M0300"),
    Source("g_genie_jpop", "JPOP", GENIE, kind="genie", url="M0400"),
    Source("g_genie_jazz", "JAZZ", GENIE, kind="genie", url="M0500"),
    Source("g_genie_classic", "CLASSIC", GENIE, kind="genie", url="M0600"),
    # ── 한국대중음악 장르별 (유튜브 검색 기반)
    Source("g_band", "밴드", KOREA, kind="yt_genre",
           query="한국대중음악 밴드 히트곡 명곡 모음"),
    Source("g_dance", "댄스", KOREA, kind="yt_genre",
           query="K-POP 댄스 신나는 명곡 모음 플레이리스트"),
    Source("g_rap", "랩/힙합", KOREA, kind="yt_genre",
           query="한국 랩/힙합 명곡 모음"),
    Source("g_rnb", "R&B/Soul", KOREA, kind="yt_genre",
           query="R&B 소울 한국 힌트 명곡 모음"),
    Source("g_indie", "인디음악", KOREA, kind="yt_genre",
           query="한국 인디음악 명곡 모음"),
    Source("g_rock", "록/메탈", KOREA, kind="yt_genre",
           query="한국 록 메탈 명곡 모음"),
    Source("g_trot", "트로트", KOREA, kind="yt_genre",
           query="트로트 명곡 모음"),
    Source("g_folk", "포크/블루스", KOREA, kind="yt_genre",
           query="포크 블루스 명곡 모음"),
]


def get_source(key: str) -> Source | None:
    for src in SOURCES:
        if src.key == key:
            return src
    return None


def source_label(key: str) -> str:
    src = get_source(key)
    if not src:
        return key
    return src.display


def grouped() -> List[tuple]:
    """(그룹, [Source...]) 목록 - UI 드롭다운용."""
    out: List[tuple] = []
    for src in SOURCES:
        if not out or out[-1][0] != src.group:
            out.append((src.group, []))
        out[-1][1].append(src)
    return out
