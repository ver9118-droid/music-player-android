"""재생목록 항목 모델."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict


@dataclass
class Track:
    title: str = ""
    artist: str = ""
    rank: int = 0
    album: str = ""
    source: str = "melon"     # melon | local | youtube
    url: str = ""             # 유튜브 URL 또는 로컬 파일 경로
    video_id: str = ""
    thumb: str = ""           # 표지 경로(로컬) 또는 URL
    duration: float = 0.0
    file: str = ""            # 캐시된 오디오 파일 경로
    melon_id: str = ""        # 멜론 곡 ID (가사 조회용)
    item_kind: str = ""       # album | mv (최신음악 소스 구분)

    @property
    def key(self) -> str:
        # video_id 는 준비 과정에서 채워지므로 key 에 넣으면 안 된다(캐시 인덱스가 깨진다)
        raw = f"{self.source}|{self.url or self.file}|{self.title}|{self.artist}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def display(self) -> str:
        if self.artist:
            return f"{self.title} - {self.artist}"
        return self.title

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Track":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in allowed})


@dataclass
class Playlist:
    """재생목록 + 현재 위치 관리."""

    tracks: list = field(default_factory=list)
    index: int = 0
    order: list = field(default_factory=list)  # 셔플용 재생 순서(인덱스)

    def __len__(self) -> int:
        return len(self.tracks)

    def current(self) -> Track | None:
        if not self.tracks:
            return None
        self.index = max(0, min(self.index, len(self.tracks) - 1))
        return self.tracks[self.index]

    def at(self, index: int) -> Track | None:
        if 0 <= index < len(self.tracks):
            return self.tracks[index]
        return None

    def replace(self, tracks: list) -> None:
        self.tracks = list(tracks)
        self.index = 0
        self.order = list(range(len(self.tracks)))

    def set_order(self, order: list) -> None:
        self.order = list(order)
