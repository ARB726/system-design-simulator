"""Optional native M/M/c backend. The full topology engine remains SimPy."""
import json
import os
import shutil
import subprocess
from pathlib import Path


def binary_path():
    return os.environ.get("SYSDESIGN_NATIVE_BINARY") or shutil.which("sysdesign-mmc") or str(
        Path(__file__).resolve().parents[1] / ".local" / "bin" / ("sysdesign-mmc.exe" if os.name == "nt" else "sysdesign-mmc"))


def available():
    return Path(binary_path()).is_file()


def simulate_mmc(c, lam, mu, duration=300, warmup=20, seed=7):
    if not available():
        raise ValueError("The C++ validation binary is not installed. Use the Python / SimPy engine.")
    from .config import Config, AppTier, Workload
    from .limits import validate_config
    cfg = Config(app=AppTier(workers=c), workload=Workload(rps=lam, duration_s=duration,
                 warmup_s=warmup, timeout_ms=None), seed=seed)
    validate_config(cfg)
    command = [binary_path(), *map(str, (c, lam, mu, duration, warmup, seed))]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise ValueError("The C++ validation run failed. Check its workload and installed binary.") from exc
