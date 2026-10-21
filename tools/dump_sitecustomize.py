"""APK 의 sitecustomize(.pyc) 를 꺼내 진입점 실행 방식을 확인."""
import gzip
import io
import re
import sys
import tarfile
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

apk = Path(r"E:\새 폴더\APK\infiniteplayer-1.0.0-arm64-v8a-debug.apk")
with zipfile.ZipFile(apk) as z:
    raw = gzip.decompress(z.read("assets/private.tar"))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
        for name in ("sitecustomize.pyc", "p4a_env_vars.txt"):
            try:
                m = tf.getmember(name)
            except KeyError:
                print(f"{name}: 없음")
                continue
            data = tf.extractfile(m).read()
            print(f"\n=== {name} ({len(data)} bytes) ===")
            if name.endswith(".txt"):
                print(data.decode("utf-8", "replace")[:1500])
                continue
            strs = [s.decode(errors="replace") for s in re.findall(rb"[\x20-\x7e]{4,}", data)]
            for s in strs:
                print("  ", s)
