import math
import os
import sqlite3
import threading
from contextlib import closing

import pytest

from agentforge.core import ForgeError
from agentforge.leases import LeaseStore, reap


def ready_store(tmp_path, policy="policy"):
    store = LeaseStore(tmp_path / "leases", policy)
    store.heartbeat("trusted-supervisor")
    return store


def expire(store, name):
    with closing(store.connect()) as conn:
        conn.execute("UPDATE leases SET expires_mono=0 WHERE name=?", (name,))


def test_crash_after_create_reservation_is_recovered_from_persistent_name(tmp_path):
    store = ready_store(tmp_path)
    name = store.reserve(1)
    staged = store.staging(name)
    staged.mkdir()
    (staged / "code.py").write_text("untrusted")
    expire(store, name)
    restarted = LeaseStore(store.directory, "policy")
    removed = []
    result = reap(restarted, lambda identity: removed.append(identity) or True)
    assert result["removed"] == removed == [name]
    assert restarted.lookup(name)["state"] == "closed"
    assert not staged.exists()


def test_failed_cleanup_is_retained_and_retried_without_claiming_success(tmp_path):
    store = ready_store(tmp_path)
    name = store.reserve(1)
    store.update(name, "cleanup-pending")

    def unavailable(_):
        raise ForgeError("daemon unavailable")

    result = reap(store, unavailable)
    assert result["failed"] and not result["removed"]
    assert store.lookup(name)["state"] == "cleanup-pending"
    assert reap(store, lambda _: True)["removed"] == [name]


def test_late_daemon_creation_is_caught_after_lease_was_closed(tmp_path):
    store = ready_store(tmp_path)
    name = store.reserve(1)
    expire(store, name)
    assert reap(store, lambda _: True)["removed"] == [name]
    # Daemon finished create after the first inventory/cleanup attempt.
    assert reap(store, lambda _: True, inventory=[name])["removed"] == [name]


def test_reaper_cannot_remove_another_policy_or_unknown_container(tmp_path):
    first = ready_store(tmp_path)
    own = first.reserve(1)
    second = LeaseStore(first.directory, "another-policy")
    second.heartbeat("other-supervisor")
    other = second.reserve(1)
    expire(first, own)
    expire(second, other)
    removed = []
    result = reap(
        first, lambda name: removed.append(name) or True, inventory=[other, "agentforge-unknown"]
    )
    assert result["removed"] == removed == [own]
    assert second.lookup(other)["state"] == "reserved"


def test_monotonic_expiry_survives_wall_clock_rollback(tmp_path, monkeypatch):
    store = ready_store(tmp_path)
    name = store.reserve(1)
    expire(store, name)
    monkeypatch.setattr("agentforge.leases.time.time", lambda: 1)
    assert store.expired()[0]["name"] == name


def test_boot_change_expires_all_old_leases(tmp_path, monkeypatch):
    store = ready_store(tmp_path)
    name = store.reserve(30)
    monkeypatch.setattr("agentforge.leases.boot_identity", lambda: "new-boot")
    assert store.expired()[0]["name"] == name
    with pytest.raises(ForgeError, match="unavailable"):
        store.reserve(1)


def test_missing_or_stale_supervisor_refuses_new_execution(tmp_path):
    store = LeaseStore(tmp_path / "leases", "policy")
    with pytest.raises(ForgeError, match="unavailable"):
        store.reserve(1)
    store.heartbeat("supervisor")
    with closing(store.connect()) as conn:
        conn.execute("UPDATE supervisors SET mono=0")
    with pytest.raises(ForgeError, match="stale"):
        store.reserve(1)
    assert not store.outstanding()


def test_live_supervisor_cannot_be_silently_replaced(tmp_path):
    store = ready_store(tmp_path)
    with pytest.raises(ForgeError, match="already owns"):
        store.heartbeat("another-supervisor")


@pytest.mark.skipif(os.name == "nt", reason="Actual rootless staging cleanup uses POSIX unlink semantics")
def test_caller_and_supervisor_can_remove_the_same_staging_tree(tmp_path, monkeypatch):
    import shutil
    from concurrent.futures import ThreadPoolExecutor

    store = ready_store(tmp_path)
    name = store.reserve(5)
    staged = store.staging(name)
    staged.mkdir()
    for i in range(20):
        (staged / str(i)).write_text("untrusted source")
    original = shutil.rmtree
    barrier = threading.Barrier(2)

    def concurrent(path, *args, **kwargs):
        barrier.wait(timeout=5)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", concurrent)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(store.remove_staging, [name, name]))
    assert not staged.exists()


@pytest.mark.parametrize("seconds", [0, -1, 31, math.inf, math.nan])
def test_invalid_container_lease_budget_is_rejected(tmp_path, seconds):
    store = ready_store(tmp_path)
    with pytest.raises(ForgeError, match="finite"):
        store.reserve(seconds)


def test_arbitrary_database_and_unsafe_cleanup_names_are_refused(tmp_path):
    directory = tmp_path / "leases"
    directory.mkdir(mode=0o700)
    with sqlite3.connect(directory / "leases.sqlite3") as conn:
        conn.execute("CREATE TABLE unrelated(x)")
    with pytest.raises(ForgeError, match="not an AgentForge"):
        LeaseStore(directory, "policy")
    store = ready_store(tmp_path / "safe")
    for name in ["..", "agentforge-../../escape", "agentforge-" + "g" * 32]:
        with pytest.raises(ForgeError, match="Invalid lease"):
            store.remove_staging(name)


@pytest.mark.skipif(os.name == "nt", reason="POSIX private-directory enforcement")
def test_shared_lease_directory_is_refused(tmp_path):
    directory = tmp_path / "leases"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    with pytest.raises(ForgeError, match="private"):
        LeaseStore(directory, "policy")
