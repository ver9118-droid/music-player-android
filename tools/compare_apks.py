"""APK 3종의 private.tar 구조 비교 (main.pyc vs main.py)."""
import gzip
import io
import sys
import tarfile
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

APKS = [
    r"E:\새 폴더\APK\infiniteplayer-1.0.0-arm64-v8a-debug.apk",
    r"E:\새 폴더\APK\infiniteplayer-1.1.0-arm64-v8a-debug.apk",
    r"E:\새 폴더\APK\infiniteplayer-1.1.0-arm64-v8a-noslim-debug.apk",
]

for apk_path in APKS:
    p = Path(apk_path)
    if not p.exists():
        print(f"\n### {p.name}: 없음")
        continue
    print(f"\n### {p.name}  ({p.stat().st_size/1024/1024:.1f} MB)")
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        bundle = [n for n in names if n.endswith("libpybundle.so")]
        print(f"  libpybundle: " + ", ".join(f"{n.split('/')[-1]}={z.getinfo(n).file_size/1024/1024:.1f}MB" for n in bundle))
        raw = gzip.decompress(z.read("assets/private.tar"))
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
            members = tf.getmembers()
        names2 = [m.name for m in members]
        pyc = [n for n in names2 if n.endswith(".pyc")]
        py = [n for n in names2 if n.endswith(".py")]
        print(f"  private.tar 항목 {len(names2)}개  (.pyc {len(pyc)} / .py {len(py)})")
        print(f"  main 관련: {[n for n in names2 if n.startswith('main')]}")
        print(f"  mplayer:   {[n for n in names2 if n.startswith('mplayer/')]}")
        print(f"  sitecustomize: {'sitecustomize.pyc' in names2}")
        print(f"  p4a_env_vars: {'p4a_env_vars.txt' in names2}")
