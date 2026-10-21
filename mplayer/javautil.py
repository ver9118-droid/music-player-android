"""jnius 헬퍼 — 서비스 프로세스에서도 동작하는 autoclass.

★ 문제
    서비스(별도 프로세스)에는 Activity 가 없어 jnius 의 기본 클래스로더를
    사용할 수 없는 경우가 있다. 그때 `autoclass("android.os.Build")` 는
    클래스를 찾지 못하고 **클래스명 문자열**을 돌려준다. 그래서
    `Build.VERSION.SDK_INT` 접근 시
    "'stringType' object 'android.os.Build' has no attribute 'VERSION'" 오류가
    났고(기기 저장 실패), 저장 명령이 실패하면서 서비스가 죽고
    sticky 로 재시작하면서 재생중이던 곡이 처음부터 다시 시작됐다.

★ 해결
    못 찾으면 서비스 컨텍스트의 클래스로더로 `Class.forName()` 을 사용해
    직접 resolve 한다.
"""
from jnius import autoclass as _autoclass

_loader = None
_loader_failed = False


def _service_class_loader():
    """PythonService 컨텍스트의 클래스로더 (없으면 None)."""
    global _loader, _loader_failed
    if _loader is not None or _loader_failed:
        return _loader
    try:
        from jnius import autoclass
        PythonService = autoclass("org.kivy.android.PythonService")
        Service = PythonService.mService
        if Service is None:
            _loader_failed = True
            return None
        ctx = Service.getApplicationContext()
        _loader = ctx.getClass().getClassLoader()
    except Exception:
        _loader_failed = True
        _loader = None
    return _loader


def autoclass(name):
    """jnius.autoclass 의 서비스 프로세스 대응 버전.

    찾으면 클래스, 못 찾으면 명확한 오류를 낸다(문자열 반환 금지).
    """
    cls = _autoclass(name)
    if not isinstance(cls, str):
        return cls
    try:
        from jnius.reflect import Class
        loader = _service_class_loader()
        if loader is not None:
            found = Class.forName(name, True, loader)
            if found is not None and not isinstance(found, str):
                return found
    except Exception:
        pass
    raise RuntimeError(
        "클래스를 찾을 수 없습니다: %s (jnius 클래스로더를 사용할 수 없음)" % name)
