"""Trusted isolated-mode caller used only by disposable gVisor crash qualification."""

import argparse
from pathlib import Path

from agentforge.containers import PythonContainer
from agentforge.core import read_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--container-config", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--crash-child", action="store_true", help=argparse.SUPPRESS)
args = parser.parse_args()
PythonContainer(**read_json(args.container_config), timeout=3).execute(
    args.output, [{}], {"inputs": {}, "outputs": {}}
)
