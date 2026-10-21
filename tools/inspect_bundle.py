"""APK 의 pybundle 에 어떤 파이썬 모듈이 들어 있는지 확인 + private.tar 내용."""
import re
import sys
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
apk = Path(r"E:\새 폴더\APK\infiniteplayer-1.1.0-arm64-v8a-debug.apk")

with zipfile.ZipFile(apk) as z:
    # 1) private.tar (에셋) 내용
    print("=== assets/private.tar ===")
    with tarfile.open(fileobj=BytesIO(z.read("assets/private.tar"))) as tf:
        for m in tf.getmembers():
            print(f"  {m.name}  ({m.size/1024:.0f} KB)")

    # 2) libpybundle.so 에 포함된 모듈 이름
    print("\n=== libpybundle.so 모듈 목록 ===")
    data = z.read("lib/arm64-v8a/libpybundle.so")
    # 파이썬 모듈 경로 문자열 추출
    names = set(re.findall(rb"[A-Za-z_][A-Za-z0-9_/\.]{2,60}\.py", data))
    interesting = sorted(n.decode() for n in names
                         if any(k in n for k in (b"mplayer", b"kivy", b"main", b"certifi",
                                                b"yt_dlp", b"requests", b"pyjnius")))
    for n in interesting[:60]:
        print("  ", n)
    print(f"  (총 {len(interesting)}개 관련 항목)")

    # 3) 번들에 포함된 top-level 패키지 (site-packages) 목록
    print("\n=== site-packages 주요 패키지 존재 여부 ===")
    for pkg in (b"yt_dlp", b"certifi", b"requests", b"pyjnius", b"kivy", b"openssl",
                b"urllib3", b"idna", b"charset_normalizer", b"chardet"):
        print(f"  {pkg.decode():<20} {'있음' if pkg in data else '없음'}")
