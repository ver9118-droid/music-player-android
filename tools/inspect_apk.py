"""APK 내부 구조 점검 (매니페스트 문자열 / 서비스 / 에셋 / dex)."""
import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
apk = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"E:\새 폴더\APK\infiniteplayer-1.1.0-arm64-v8a-debug.apk")

with zipfile.ZipFile(apk) as z:
    names = z.namelist()
    print(f"=== {apk.name} ===")
    print(f"항목 수 {len(names)}")
    print("\n--- assets ---")
    for n in sorted(names):
        if n.startswith("assets/"):
            print(f"  {n}  ({z.getinfo(n).file_size/1024:.0f} KB)")
    print("\n--- lib ---")
    for n in sorted(names):
        if n.startswith("lib/"):
            print(f"  {n}  ({z.getinfo(n).file_size/1024/1024:.1f} MB)")
    print("\n--- 주요 dex/so ---")
    for n in sorted(names):
        if n.endswith(".dex") or n.endswith(".so") and "lib" not in n:
            print(f"  {n}  ({z.getinfo(n).file_size/1024/1024:.1f} MB)")

    # 매니페스트(바이너리 xml) 에서 권한/서비스 문자열 추출
    m = z.read("AndroidManifest.xml")
    strings = re.findall(rb"[\x20-\x7e]{4,}", m)
    txt = [s.decode() for s in strings]
    print("\n--- AndroidManifest 문자열 ---")
    for s in txt:
        if any(k in s for k in ("permission", "Service", "service", "mediaPlayback",
                                "FOREGROUND", "org.music", "infiniteplayer",
                                "provider", "activity")):
            print("  ", s)

    # dex 안에 서비스 클래스/패키지 문자열이 있는지
    for n in sorted(names):
        if n.endswith(".dex"):
            data = z.read(n)
            found = set()
            for pat in (b"ServiceMusic", b"org/music/infiniteplayer", b"org.music.infiniteplayer",
                        b"foregroundServiceType", b"mediaPlayback"):
                if pat in data:
                    found.add(pat.decode())
            print(f"\n--- {n} 에서 찾은 키워드 ---")
            print("  ", found if found else "없음")
