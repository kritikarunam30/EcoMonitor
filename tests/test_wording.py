import re

import pytest

from app.settings import REPO_ROOT
from app.wording import t

T_CALL = re.compile(r"""\bt\(\s*["']([^"']+)["']""")


def test_required_wording_exists():
    assert "not compliance evidence" in t("disclaimer")
    assert "uncalibrated" in t("score_label")
    assert "not a measurement of exposure" in t("exposure_caption")
    for key in ("evidence_caption_same_day", "evidence_caption_context"):
        assert "ontext" in t(key)


def test_unknown_key_raises():
    with pytest.raises(KeyError, match="no_such_key"):
        t("no_such_key")


def test_every_key_used_in_code_exists():
    for path in (REPO_ROOT / "backend" / "app").rglob("*.py"):
        for key in T_CALL.findall(path.read_text(encoding="utf-8")):
            assert t(key), f"{path.relative_to(REPO_ROOT)} uses wording key '{key}'"
