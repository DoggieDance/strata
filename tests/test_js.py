"""Run the app's pure-JS engine tests (tests/js/*.test.mjs) under node --test."""
import shutil
import subprocess

import pytest

from tests.conftest import ROOT

FILES = sorted((ROOT / "tests" / "js").glob("*.test.mjs"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_js(path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(["node", "--test", str(path)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
