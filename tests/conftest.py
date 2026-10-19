import socket

import pytest

from agentforge.generator import OfflineGenerator
from agentforge.spec import plan


@pytest.fixture(autouse=True)
def forbid_test_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Tests must not use a live network or model API")

    monkeypatch.setattr(socket.socket, "connect", denied)


@pytest.fixture
def make_skill(tmp_path):
    counter = 0

    def make(variant="correct", version="0.1.0"):
        nonlocal counter
        counter += 1
        spec = plan("Clean text whitespace")
        spec["version"] = version
        return OfflineGenerator().generate(spec, tmp_path / str(counter) / spec["name"], variant)

    return make
