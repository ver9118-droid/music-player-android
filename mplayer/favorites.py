"""즐겨찾기(저장된 재생목록) 관리."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DATA_DIR, ensure_dirs
from .models import Track

FAVORITES_FILE = DATA_DIR / "favorites.json"
DEFAULT_LIST_NAME = "내 즐겨찾기"


class Favorites:
    """즐겨찾기 목록(재생목록 스냅샷) 저장소."""

    def __init__(self, path: Path = FAVORITES_FILE) -> None:
        self.path = path
        ensure_dirs()
        self._data = self._load()

    # ------------------------------------------------------------------ 내부
    def _load(self) -> Dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict) and isinstance(data.get("lists"), list):
                return data
        except Exception:
            pass
        return {"lists": []}

    def _save(self) -> None:
        try:
            ensure_dirs()
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fp:
                json.dump(self._data, fp, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
        except Exception:
            pass

    # ------------------------------------------------------------------ 조회
    def lists(self) -> List[Dict[str, Any]]:
        return list(self._data.get("lists", []))

    def get(self, list_id: str) -> Optional[Dict[str, Any]]:
        for item in self.lists():
            if item.get("id") == list_id:
                return item
        return None

    def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        for item in self.lists():
            if item.get("name") == name:
                return item
        return None

    def default_list(self) -> Dict[str, Any]:
        """'내 즐겨찾기' 목록 (없으면 생성)."""
        found = self.find_by_name(DEFAULT_LIST_NAME)
        if found:
            return found
        return self.create(DEFAULT_LIST_NAME, [])

    # ------------------------------------------------------------------ 변경
    def create(self, name: str, tracks: List[Track]) -> Dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:12],
            "name": name.strip() or "이름 없는 목록",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tracks": [t.to_dict() for t in tracks],
        }
        self._data.setdefault("lists", []).append(item)
        self._save()
        return item

    def update(self, list_id: str, name: str, tracks: List[Track]) -> bool:
        item = self.get(list_id)
        if not item:
            return False
        item["name"] = name.strip() or item.get("name") or "이름 없는 목록"
        item["tracks"] = [t.to_dict() for t in tracks]
        item["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._save()
        return True

    def add_tracks(self, list_id: str, tracks: List[Track]) -> bool:
        item = self.get(list_id)
        if not item:
            return False
        # key 는 Track 의 계산 속성이므로 저장된 dict 를 Track 으로 되살려 비교한다
        existing = {Track.from_dict(t).key for t in item.get("tracks", [])}
        for track in tracks:
            if track.key in existing:
                continue
            item.setdefault("tracks", []).append(track.to_dict())
            existing.add(track.key)
        self._save()
        return True

    def rename(self, list_id: str, name: str) -> bool:
        item = self.get(list_id)
        if not item:
            return False
        item["name"] = name.strip() or item.get("name") or "이름 없는 목록"
        self._save()
        return True

    def delete(self, list_id: str) -> bool:
        lists = self._data.get("lists", [])
        remain = [i for i in lists if i.get("id") != list_id]
        if len(remain) == len(lists):
            return False
        self._data["lists"] = remain
        self._save()
        return True

    def tracks_of(self, list_id: str) -> List[Track]:
        item = self.get(list_id)
        if not item:
            return []
        return [Track.from_dict(t) for t in item.get("tracks", [])]
