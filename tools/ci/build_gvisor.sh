#!/usr/bin/env bash
# Explicit disposable-runner qualification of the complete upstream rootless fix.
set -euo pipefail
exec > >(tee gvisor-build.log) 2>&1
task_commit=8ecc635e5e32b8eb1cb2acdc308d480f00bf7264
task_output=$(realpath -m "${1:?runtime output directory is required}")
test ! -e "$task_output"
task_source=$(mktemp -d)
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends libbpf-dev libelf-dev clang llvm crossbuild-essential-arm64
git -C "$task_source" init
git -C "$task_source" remote add origin https://github.com/google/gvisor.git
git -C "$task_source" fetch --depth=1 origin "$task_commit"
git -C "$task_source" checkout --detach FETCH_HEAD
test "$(git -C "$task_source" rev-parse HEAD)" = "$task_commit"
task_bazel="$task_source/bazel-8.3.1"
curl --fail --location --retry 3 --proto '=https' https://github.com/bazelbuild/bazel/releases/download/8.3.1/bazel-8.3.1-linux-x86_64 -o "$task_bazel"
printf '%s  %s\n' 17247e8a84245f59d3bc633d0cfe0a840992a7760a11af1a30012d03da31604c "$task_bazel" | sha256sum -c -
chmod 0755 "$task_bazel"
cd "$task_source"
"$task_bazel" --batch build --jobs=4 --local_resources=memory=6000 -c opt //runsc:runsc //debian:gvisor-bin-tar
"$task_bazel" --batch test --jobs=4 --local_resources=memory=6000 --test_output=errors //runsc/cgroup:cgroup_test
mkdir -p "$task_output"
cp bazel-bin/runsc/runsc_/runsc "$task_output/runsc"
tar -xf bazel-bin/debian/gvisor-bin-tar.tar -C "$task_output"
cp LICENSE "$task_output/LICENSE.gvisor"
python - "$task_output" "$task_commit" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
assert {'runsc','gvisor-bin/checkpointgofer','gvisor-bin/runsc-metric-server'} <= set(files)
(root/'runtime-provenance.json').write_text(json.dumps({'source':'https://github.com/google/gvisor','commit':sys.argv[2],'upstream_pr':13853,'merged_upstream':False,'bazel_version':'8.3.1','files':files},indent=2))
PY
"$task_output/runsc" --version
