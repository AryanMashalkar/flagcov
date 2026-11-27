import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_ENV = ROOT / "examples" / "demo_shop" / "environment.json"


@pytest.fixture
def doc():
    return copy.deepcopy(json.loads(DEMO_ENV.read_text(encoding="utf-8")))


@pytest.fixture
def demo_env_path():
    return DEMO_ENV
