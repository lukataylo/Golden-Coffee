"""Guard the FLock bounty container against import drift.

`Dockerfile.flock` hand-copies only the modules the federated model needs (to keep
the image lean). That list silently rots the moment the import graph grows — and a
missing module means the on-chain FLock participant crashes on startup, not in CI.

This test reads the COPY lines out of `Dockerfile.flock`, reconstructs that exact
file-set in a temp dir, and imports + runs the model from there in a *subprocess*
with an isolated `sys.path`. If the Dockerfile is missing a dependency, this fails
loudly here instead of on the FLock platform.

Run:  python -m pytest federated/test_flock_packaging.py -q
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO / "Dockerfile.flock"


def _copy_specs() -> list[tuple[str, str]]:
    """Parse `COPY <src> <dst>` lines that reference repo paths (skip pip/SDK)."""
    specs: list[tuple[str, str]] = []
    for line in DOCKERFILE.read_text().splitlines():
        m = re.match(r"\s*COPY\s+(\S+)\s+(\S+)\s*$", line)
        if m:
            specs.append((m.group(1), m.group(2)))
    return specs


def _materialize(dest: Path) -> None:
    """Recreate the Docker build context's copied files under `dest`."""
    for src, dst in _copy_specs():
        s = REPO / src
        d = dest / dst
        d.parent.mkdir(parents=True, exist_ok=True)
        if src.endswith("/"):              # `COPY federated/ federated/` — whole dir
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


def test_flock_dockerfile_copyset_is_self_sufficient(tmp_path: Path) -> None:
    _materialize(tmp_path)
    # Import + exercise the model with ONLY the copied files visible (flock_sdk is
    # optional/lazy, so its absence is fine — that mirrors the local path).
    script = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, ".")
        from federated.flock_model import GoldenCoffeeModel
        import federated.flock_run  # must import even with flock_sdk absent
        m = GoldenCoffeeModel(); m.init_dataset("")
        p = m.train(); g = m.aggregate([p]); s = m.evaluate(g)
        assert isinstance(p, bytes) and p, "train() produced no params"
        assert 0.0 <= s <= 1.0, f"evaluate() out of range: {s}"
        print("FLOCK_OK", round(s, 3))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        "FLock container copy-set is missing a dependency — update Dockerfile.flock.\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert "FLOCK_OK" in proc.stdout, proc.stdout
