"""무한 음악 플레이어 (안드로이드) — 경로/설정.

안드로이드에서는 앱 전용 폴더(ANDROID_PRIVATE)를 쓰고,
데스크톱에서는 사용자 홈 아래 AppData 를 쓴다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

APP_NAME = "무한 음악 플레이어"
APP_ID = "InfiniteMusicPlayer"
VERSION = "1.0.0"

IS_ANDROID = "ANDROID_PRIVATE" in os.environ or "ANDROID_ARGUMENT" in os.environ


def _base_dir() -> Path:
    # 서비스 프로세스/앱 프로세스가 같은 폴더를 써야 한다.
    if IS_ANDROID:
        return Path(os.environ["ANDROID_PRIVATE"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _base_dir()
DATA_DIR = APP_DIR
CACHE_DIR = DATA_DIR / "cache"
THUMB_DIR = CACHE_DIR / "thumbs"
SETTINGS_FILE = DATA_DIR / "settings.json"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "app.log"

# 서비스(백그라운드 재생 프로세스)와 UI 가 파일로 통신한다.
# 같은 앱(같은 UID)의 별도 프로세스이므로 파일 공유가 가능하다.
SVC_CMD_FILE = DATA_DIR / "svc_cmd.json"
SVC_STATE_FILE = DATA_DIR / "svc_state.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "volume": 0.8,
    "repeat": "all",          # all | one | off
    "shuffle": False,
    "infinite": True,         # 목록 끝나면 자동 셔플 재시작
    "chart_limit": 50,
    "auto_update_hours": 6,
    "search_query": "{artist} {title}",
    "lyrics_enabled": True,
    "theme": "dark",
}


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, THUMB_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return fallback


def _write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False)
        os.replace(str(tmp), str(path))
    except Exception:
        pass


def load_settings() -> Dict[str, Any]:
    data = dict(DEFAULT_SETTINGS)
    data.update(_read_json(SETTINGS_FILE, {}) or {})
    return data


def save_settings(settings: Dict[str, Any]) -> None:
    _write_json(SETTINGS_FILE, settings)


def ca_bundle_path() -> str:
    """HTTPS 검증용 CA 번들 경로 (앱에 포함)."""
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "assets" / "cacert.pem",
                 here / "assets" / "cacert.pem"):
        if cand.exists():
            return str(cand)
    return ""


def setup_tls() -> None:
    """시스템 CA 저장소가 없는 안드로이드에서 인증서를 신뢰하도록 설정."""
    ca = ca_bundle_path()
    if not ca:
        return
    os.environ.setdefault("SSL_CERT_FILE", ca)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:
        pass
