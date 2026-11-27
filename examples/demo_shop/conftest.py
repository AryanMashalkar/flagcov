"""Wire the shop to Flagsmith exactly like production does, but offline.

The Flagsmith SDK evaluates the committed environment document locally
(the same approach Flagsmith's own API uses for its flags), so tests are fast
and deterministic, and FlagCov compares them with that same document.
"""

import os
import sys
from pathlib import Path

import pytest
from flagsmith import Flagsmith
from flagsmith.offline_handlers import LocalFileHandler
from openfeature import api
from openfeature_flagsmith.provider import FlagsmithProvider

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
# CI and the self-hosted demo point this at a document downloaded from Flagsmith.
ENV_DOCUMENT = Path(os.environ.get("FLAGCOV_ENV_DOCUMENT", HERE / "environment.json"))


@pytest.fixture(scope="session", autouse=True)
def flagsmith_provider():
    client = Flagsmith(
        environment_key="ser.demo-shop-production",
        offline_mode=True,
        offline_handler=LocalFileHandler(str(ENV_DOCUMENT)),
    )
    api.set_provider(FlagsmithProvider(client=client))
    yield
    api.clear_providers()
