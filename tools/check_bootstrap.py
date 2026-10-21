"""APK 의 네이티브 부트스트랩(libmain.so / libpybundle.so)이 main.pyc 를 요구하는지 확인."""
import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

for apk in [r"E:\새 폴더\APK\infiniteplayer-1.0.0-arm64-v8a-debug.apk",
            r"E:\새 폴더\APK\infiniteplayer-1.1.0-arm64-v8a-debug.apk"]:
    p = Path(apk)
    print(f"\n### {p.name}")
    with zipfile.ZipFile(p) as z:
        for lib in ("lib/arm64-v8a/libmain.so", "lib/arm64-v8a/libpythonbin.so",
                    "lib/arm64-v8a/libpybundle.so"):
            if lib not in z.namelist():
                continue
            data = z.read(lib)
            found = []
            for pat in (b"main.pyc", b"main.py", b"__main__", b"sitecustomize",
                        b"p4a_env_vars", b"private.tar", b"ANDROID_PRIVATE",
                        b"ANDROID_ARGUMENT", b".pyo"):
                if pat in data:
                    found.append(pat.decode())
            print(f"  {lib.split('/')[-1]:<18} {len(data)/1024:>8.0f} KB  키워드: {found}")
            # libmain.so 주변 문자열
            if "libmain" in lib:
                strs = [s.decode() for s in re.findall(rb"[\x20-\x7e]{5,}", data)]
                print("     문자열:", [s for s in strs if "main" in s or "pyc" in s or "py" == s][:20])
