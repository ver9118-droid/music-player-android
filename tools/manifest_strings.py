"""바이너리 AndroidManifest.xml 에서 문자열/속성 추출 (간단 AXML 파서)."""
import struct
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
apk = Path(r"E:\새 폴더\APK\infiniteplayer-1.1.0-arm64-v8a-debug.apk")

with zipfile.ZipFile(apk) as z:
    data = z.read("AndroidManifest.xml")

# UTF-16LE 문자열 대충 추출
strings = []
i = 0
while i < len(data) - 1:
    if 0x20 <= data[i] < 0x7F and data[i + 1] == 0:
        j = i
        buf = []
        while j < len(data) - 1 and 0x20 <= data[j] < 0x7F and data[j + 1] == 0:
            buf.append(chr(data[j]))
            j += 2
        s = "".join(buf)
        if len(s) >= 3:
            strings.append(s)
        i = j
    else:
        i += 1

print("=== AndroidManifest.xml 문자열 (필터) ===")
keys = ("permission", "Service", "service", "mediaPlayback", "org.music", "infiniteplayer",
        "FOREGROUND", "provider", "Activity", "intent", "action", "category")
seen = set()
for s in strings:
    if any(k in s for k in keys) and s not in seen:
        seen.add(s)
        print("  ", s)

print("\n=== 전체 고유 문자열 (앞 60개) ===")
uniq = []
for s in strings:
    if s not in uniq:
        uniq.append(s)
for s in uniq[:60]:
    print("  ", s)
print(f"\n총 고유 문자열 {len(uniq)}개")
