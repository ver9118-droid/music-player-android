"""1.0.0 의 libpybundle 안에서 'main.pyc' 문자열 주변을 찾아 시작 메커니즘을 확인."""
import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
apk = Path(r"E:\새 폴더\APK\infiniteplayer-1.0.0-arm64-v8a-debug.apk")
with zipfile.ZipFile(apk) as z:
    data = z.read("lib/arm64-v8a/libpybundle.so")

for pat in (b"main.pyc", b"main.py", b"__main__"):
    print(f"\n=== '{pat.decode()}' 주변 컨텍스트 ===")
    for m in list(re.finditer(re.escape(pat), data))[:6]:
        s = max(0, m.start() - 260)
        chunk = data[s:m.end() + 260]
        # 주변에서 읽을 만한 문자열만 뽑는다
        strs = [x.decode(errors="replace") for x in re.findall(rb"[\x20-\x7e]{6,}", chunk)]
        print("  ---")
        for x in strs[:14]:
            print("    ", x)
