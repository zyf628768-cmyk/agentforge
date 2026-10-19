import hashlib
import subprocess
import sys
from decimal import Decimal

import pytest

from agentforge.billing import BudgetLedger, units
from agentforge.core import ForgeError


def reserve(ledger, amount="0.1", tokens=100):
    return ledger.reserve(
        "shared", amount=amount, tokens=tokens, request_hash="a" * 64, model="test"
    )


def test_committed_reservation_survives_restart_and_unknown_never_refunds(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget")
    ledger.create("shared", dollars="0.2", tokens=200, requests=2)
    ident = reserve(ledger)
    ledger.unknown(ident)
    restarted = BudgetLedger(tmp_path / "budget")
    assert restarted.status("shared")["charged_or_held_usd"] == "0.1"
    assert restarted.status("shared")["unresolved"][0]["state"] == "unknown"
    reserve(restarted)
    with pytest.raises(ForgeError, match="exhausted"):
        reserve(restarted)


def test_atomic_cross_process_limits(tmp_path):
    directory = tmp_path / "budget"
    ledger = BudgetLedger(directory)
    ledger.create("shared", dollars="0.4", tokens=400, requests=4)
    script = tmp_path / "trusted_reserver.py"
    script.write_text(
        "from agentforge.billing import BudgetLedger\nfrom agentforge.core import ForgeError\n"
        f"ledger=BudgetLedger({str(directory)!r})\n"
        'try:\n ledger.reserve("shared",amount="0.1",tokens=100,request_hash="a"*64,model="test")\n print("reserved")\n'
        'except ForgeError: print("denied")\n'
    )
    children = [
        subprocess.Popen(
            [sys.executable, "-I", str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    outcomes = []
    for child in children:
        stdout, stderr = child.communicate(timeout=20)
        assert child.returncode == 0, stderr
        outcomes.append(stdout.strip())
    assert outcomes.count("reserved") == 4 and outcomes.count("denied") == 4
    assert ledger.status("shared")["requests"] == 4


def test_hard_process_exit_keeps_reservation(tmp_path):
    directory = tmp_path / "budget"
    ledger = BudgetLedger(directory)
    ledger.create("shared", dollars="0.1", tokens=100, requests=1)
    script = tmp_path / "trusted_crash.py"
    script.write_text(
        "from agentforge.billing import BudgetLedger\nimport os\n"
        f'BudgetLedger({str(directory)!r}).reserve("shared",amount="0.1",tokens=100,request_hash="a"*64,model="test")\n'
        "os._exit(27)\n"
    )
    assert subprocess.run([sys.executable, "-I", str(script)], timeout=10).returncode == 27
    assert ledger.status("shared")["unresolved"][0]["state"] == "reserved"
    with pytest.raises(ForgeError, match="exhausted"):
        reserve(ledger)


def test_actual_charges_reconciliation_and_overage(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget")
    ledger.create("shared", dollars="1", tokens=1000, requests=10)
    ident = reserve(ledger)
    ledger.finish(ident, amount="0.02", tokens=20, receipt=b"public-test-receipt")
    assert ledger.status("shared")["charged_or_held_usd"] == "0.02"
    with pytest.raises(ForgeError, match="finalized"):
        ledger.finish(ident, amount=0, tokens=0, receipt=b"x")
    pending = reserve(ledger)
    ledger.reconcile(
        pending, amount="1.5", tokens=200, receipt=b"public-overage", note="operator-reviewed"
    )
    assert Decimal(ledger.status("shared")["remaining_usd"]) < 0
    with pytest.raises(ForgeError, match="exhausted"):
        reserve(ledger)
    assert (
        ledger.history("shared")[0]["receipt_hash"] == hashlib.sha256(b"public-overage").hexdigest()
    )
    with pytest.raises(ForgeError, match="unresolved"):
        ledger.reconcile(pending, amount=0, tokens=0, receipt=b"x", note="again")


def test_account_limits_cannot_silently_increase_and_amounts_are_integer(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget")
    ledger.create("shared", dollars=0, tokens=100, requests=1)
    with pytest.raises(ForgeError, match="exists"):
        ledger.create("shared", dollars=100, tokens=100000, requests=1000)
    assert units("0.0000000001") == 1
    for value in ["NaN", "-1", "Infinity", "text", True]:
        with pytest.raises(ForgeError):
            units(value)
    ident = reserve(ledger, amount=0)
    with pytest.raises(ForgeError, match="exceeds"):
        ledger.finish(ident, amount=1, tokens=101, receipt=b"x")
    assert ledger.status("shared")["unresolved"][0]["state"] == "unknown"


def test_private_artifact_boundary_and_database_identity(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(ForgeError, match="outside"):
        BudgetLedger(tmp_path / "budget")


def test_real_transport_requires_durable_reservation_before_sending():
    from agentforge.providers import ModelConfig, ResponsesBackend

    class FreeLocal:
        offline = False
        free = True

        def post(self, *a, **kw):
            pytest.fail("Missing budget must prevent transport")

    backend = ResponsesBackend(ModelConfig(model="local"), FreeLocal())
    with pytest.raises(ForgeError, match="persistent budget"):
        backend.request({}, {"type": "object"})


def test_reconciliation_notes_are_redacted_at_rest(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget")
    ledger.create("shared", dollars=1, tokens=1000, requests=10)
    ident = reserve(ledger)
    ledger.reconcile(ident, amount=0, tokens=0, receipt=b"public", note="password=do-not-persist")
    assert "do-not-persist" not in ledger.db.read_bytes().decode("latin1")
