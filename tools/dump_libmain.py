"""libmain.so 의 모든 문자열을 뽑아 p4a 부트스트랩 동작을 파악한다."""
import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
apk = Path(r"E:\새 폴더\APK\infiniteplayer-1.0.0-arm64-v8a-debug.apk")
with zipfile.ZipFile(apk) as z:
    data = z.read("lib/arm64-v8a/libmain.so")
strs = [s.decode() for s in re.findall(rb"[\x20-\x7e]{4,}", data)]
print(f"### libmain.so 문자열 {len(strs)}개")
for s in strs:
    print("  ", s)
