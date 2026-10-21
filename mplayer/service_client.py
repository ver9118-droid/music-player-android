"""서비스(백그라운드 재생 프로세스) 클라이언트 — UI 쪽.

앱 프로세스 ↔ 서비스 프로세스는 같은 앱(같은 UID)의 별도 프로세스라
파일로 통신한다.  명령은 파일 하나씩(순서 보장), 상태는 상태 파일 하나로.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import IS_ANDROID, SVC_CMD_FILE, SVC_STATE_FILE, ensure_dirs

# buildozer.spec 의 package.domain + package.name
JAVA_PACKAGE = "org.music.infiniteplayer"
SERVICE_CLASS = "ServiceMusic"


class ServiceClient:
    def __init__(self):
        ensure_dirs()
        self._seq = 0
        self._service = None
        self._started = False
        self.last_error = ""

    # ------------------------------------------------------------- 서비스 기동
    def _java_service(self):
        if self._service is not None:
            return self._service
        from jnius import autoclass
        cls = autoclass(f"{JAVA_PACKAGE}.{SERVICE_CLASS}")
        self._service = cls
        return cls

    def start(self, title: str = "무한 음악 플레이어", text: str = "재생 대기 중") -> bool:
        """포그라운드 서비스로 백그라운드 재생을 시작한다."""
        if not IS_ANDROID:
            return False
        try:
            cls = self._java_service()
            activity_cls = autoclass_activity()
            mActivity = activity_cls.mActivity
            if mActivity is None:
                self.last_error = "Activity 를 찾을 수 없습니다."
                return False
            # start(활동, 작은아이콘, 제목, 내용, 인자)
            cls.start(mActivity, "icon", title, text, "")
            self._started = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = f"재생 서비스 시작 실패: {exc}"
            return False

    def stop(self):
        if not IS_ANDROID:
            return
        try:
            cls = self._java_service()
            ctx = autoclass_activity().mActivity
            # p4a 는 start(Context,...) 와 stop(Context) 두 형태를 모두 제공한다.
            try:
                cls.stop(ctx)
            except Exception:
                pass
        except Exception:
            pass
        self._started = False

    def update_notification(self, title: str, text: str):
        """알림 텍스트를 갱신한다(재생 곡이 바뀔 때)."""
        if not IS_ANDROID:
            return
        try:
            from . import notifier
            notifier.update(title, text)
        except Exception:
            pass

    # ------------------------------------------------------------- 명령
    def send(self, cmd: str, **payload) -> None:
        """서비스에 명령을 보낸다."""
        if not IS_ANDROID:
            return
        self._seq += 1
        data = {"cmd": cmd, "ts": time.time()}
        data.update(payload)
        try:
            SVC_CMD_FILE.parent.mkdir(parents=True, exist_ok=True)
            path = SVC_CMD_FILE.parent / f"{SVC_CMD_FILE.stem}_{self._seq:06d}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(path))
        except Exception:
            pass

    # ------------------------------------------------------------- 상태
    def state(self) -> Dict[str, Any]:
        """서비스가 publishes 한 상태를 읽는다."""
        try:
            with SVC_STATE_FILE.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}

    def is_running(self) -> bool:
        st = self.state()
        return bool(st.get("alive"))

    def wait_ready(self, timeout: float = 8.0) -> bool:
        """서비스가 살아날 때까지 기다린다."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_running():
                return True
            time.sleep(0.25)
        return False

    # ------------------------------------------------------------- 권한
    def request_notification_permission(self) -> bool:
        """안드로이드 13+ 알림 권한을 요청한다(있으면 이미 granted)."""
        if not IS_ANDROID:
            return True
        try:
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            PackageManager = autoclass("android.content.pm.PackageManager")
            activity = autoclass_activity().mActivity
            if activity is None:
                return False
            pm = activity.getPackageManager()
            if pm.checkPermission("android.permission.POST_NOTIFICATIONS",
                                  activity.getPackageName()) == PackageManager.PERMISSION_GRANTED:
                return True
            activity.requestPermissions(
                ["android.permission.POST_NOTIFICATIONS"], 1001)
            return True
        except Exception as exc:
            self.last_error = f"알림 권한 요청 실패: {exc}"
            return False


def autoclass_activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity")
