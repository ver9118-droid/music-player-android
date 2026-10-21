"""오디오 파일을 기기 공용 저장소(다운로드/음악 폴더)로 저장.

안드로이드 10(API 29) 이상은 MediaStore 로 권한 없이 저장하고,
그 이전 버전은 앱 전용 외부 폴더(<sdcard>/Android/data/<pkg>/files/Music) 에
저장한다(권한 불필요).

※ 안드로이드에는 ffmpeg 가 없어 mp3 로 변환하지 않고 원본 포맷
   (m4a/webm/opus 등) 그대로 저장한다.
"""
from __future__ import annotations

import mimetypes
import os
import shutil
from typing import Optional

FOLDER = "무한 음악 플레이어"
SAVE_DIR = "Music"          # MediaStore RELATIVE_PATH 상위 폴더


def _mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        ext = os.path.splitext(path)[1].lower()
        mime = {
            ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac",
            ".webm": "audio/webm", ".opus": "audio/opus", ".ogg": "audio/ogg",
            ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
        }.get(ext, "application/octet-stream")
    return mime


def _safe_name(name: str) -> str:
    """파일명에 쓰면 안 되는 문자를 바꾼다."""
    bad = '\\/:*?"<>|\r\n\t'
    out = "".join("_" if ch in bad else ch for ch in (name or "")).strip()
    return out[:120] or "audio"


def _copy(src: str, dst: str) -> None:
    shutil.copyfile(src, dst)



def _sdk_int(default: int = 29) -> int:
    """안드로이드 API 레벨. 못 읽으면 기본값(29=API29+)을 쓴다."""
    try:
        from mplayer.javautil import autoclass
        Build = autoclass("android.os.Build")
        return int(Build.VERSION.SDK_INT)
    except Exception:
        return default


def save_to_device(src_path: str, display_name: str) -> str:
    """기기 저장소로 복사한다. 성공하면 저장 위치를 돌려준다.

    실패하면 예외가 발생한다.
    """
    if not src_path or not os.path.isfile(src_path):
        raise RuntimeError("저장할 오디오 파일이 없습니다.")

    display_name = _safe_name(display_name)
    if not os.path.splitext(display_name)[1]:
        display_name += os.path.splitext(src_path)[1] or ".m4a"

    sdk = _sdk_int()

    if sdk >= 29:
        return _save_mediastore(src_path, display_name)
    return _save_external_dir(src_path, display_name)


def _save_mediastore(src_path: str, display_name: str) -> str:
    """API 29+ : MediaStore.Downloads (권한 불필요)."""
    from mplayer.javautil import autoclass
    ContentValues = autoclass("android.content.ContentValues")
    MediaStore = autoclass("android.provider.MediaStore")
    PythonService = autoclass("org.kivy.android.PythonService")
    Service = PythonService.mService
    if Service is None:
        raise RuntimeError("서비스 컨텍스트를 얻지 못했습니다.")
    ctx = Service.getApplicationContext()
    resolver = ctx.getContentResolver()

    values = ContentValues()
    values.put(MediaStore.Downloads.DISPLAY_NAME, display_name)
    values.put(MediaStore.Downloads.MIME_TYPE, _mime(src_path))
    values.put(MediaStore.Downloads.RELATIVE_PATH, SAVE_DIR + "/" + FOLDER)
    values.put(MediaStore.Downloads.IS_PENDING, 1)

    uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise RuntimeError("저장 위치를 만들지 못했습니다.")

    try:
        out = resolver.openOutputStream(uri)
        if out is None:
            raise RuntimeError("저장 파일을 열지 못했습니다.")
        with open(src_path, "rb") as f:
            while True:
                chunk = f.read(262144)
                if not chunk:
                    break
                out.write(chunk)
        out.flush()
        out.close()
    except Exception:
        try:
            resolver.delete(uri, None, None)
        except Exception:
            pass
        raise

    values.clear()
    values.put(MediaStore.Downloads.IS_PENDING, 0)
    resolver.update(uri, values, None, None)
    return "%s/%s/%s" % (SAVE_DIR, FOLDER, display_name)


def _save_external_dir(src_path: str, display_name: str) -> str:
    """API 29 미만 : 앱 전용 외부 폴더에 저장 (권한 불필요)."""
    from mplayer.javautil import autoclass
    Environment = autoclass("android.os.Environment")
    PythonService = autoclass("org.kivy.android.PythonService")
    Service = PythonService.mService
    if Service is None:
        raise RuntimeError("서비스 컨텍스트를 얻지 못했습니다.")
    ctx = Service.getApplicationContext()

    base = ctx.getExternalFilesDir(Environment.DIRECTORY_MUSIC)
    if base is None:
        base = ctx.getFilesDir()
    target = base
    try:
        from java.io import File
        target = File(str(base), FOLDER)
        target.mkdirs()
    except Exception:
        target = base
    dst = os.path.join(str(target), display_name)
    _copy(src_path, dst)
    return str(dst)


def delete_saved(path: str) -> Optional[str]:
    """저장된 파일 삭제 (MediaStore 경로면 uri 로)."""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            return path
    except Exception:
        pass
    return None
