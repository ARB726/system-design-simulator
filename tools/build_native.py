"""Build the standalone C++ kernel; set CXX for a non-default compiler."""
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / ".local" / "bin" / ("sysdesign-mmc.exe" if os.name == "nt" else "sysdesign-mmc")
output.parent.mkdir(parents=True, exist_ok=True)
compiler = shlex.split(os.environ["CXX"]) if os.environ.get("CXX") else None
if not compiler:
    compiler = next(([name] for name in ("g++", "clang++") if shutil.which(name)), None)
if not compiler:
    try:
        import ziglang
    except ImportError:
        raise SystemExit("Install g++/clang++, set CXX, or install ziglang to build on Windows.")
    compiler = [sys.executable, "-m", "ziglang", "c++"]
subprocess.run([*compiler, "-O3", "-std=c++17", str(root / "native" / "mmc.cpp"), "-o", str(output)], check=True)
print(output)
