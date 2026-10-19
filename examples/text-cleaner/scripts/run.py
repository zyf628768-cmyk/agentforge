"""Auditable convenience wrapper; not executed by AgentForge tests."""
from pathlib import Path
from agentforge.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["run", str(Path(__file__).resolve().parents[1])]))
