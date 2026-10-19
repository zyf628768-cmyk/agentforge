#!/usr/bin/env bash
# Explicit provisioning for an ephemeral CI VM, never invoked by Skill execution.
set -euo pipefail
exec > >(tee sandbox-provision.log) 2>&1
test "$(id -u)" -ne 0
sudo apt-get update -qq
sudo apt-get install -y uidmap dbus-user-session slirp4netns zstd
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
task_codename=$(python -c 'import platform; print(platform.freedesktop_os_release()["VERSION_CODENAME"])')
printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$task_codename" "$(dpkg --print-architecture)" | sudo tee /etc/apt/sources.list.d/agentforge-docker.sources
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends docker-ce-rootless-extras

# All binaries come from the same fixed source build, never a floating release.
task_runtime_dir=$(realpath "${1:?explicit pinned runtime directory is required}")
task_manifest_sha=${2:?reviewed runtime manifest SHA-256 is required}
python - "$task_runtime_dir" "$task_manifest_sha" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);raw=(root/'runtime-provenance.json').read_bytes()
assert len(sys.argv[2])==64 and all(c in '0123456789abcdef' for c in sys.argv[2])
assert hashlib.sha256(raw).hexdigest()==sys.argv[2]
manifest=json.loads(raw)
assert manifest['commit']=='8ecc635e5e32b8eb1cb2acdc308d480f00bf7264'
assert manifest.get('cgroup_unit_tests')=='passed'
assert {'runsc','gvisor-bin/checkpointgofer','gvisor-bin/runsc-metric-server'} <= set(manifest['files'])
for name,digest in manifest['files'].items():
    path=root/name
    assert not path.is_symlink() and path.resolve().is_relative_to(root)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
PY
sudo install -m 0755 "$task_runtime_dir/runsc" /usr/local/bin/runsc
sudo install -m 0755 -d /usr/local/bin/gvisor-bin
sudo install -m 0755 "$task_runtime_dir/gvisor-bin/checkpointgofer" /usr/local/bin/gvisor-bin/checkpointgofer
sudo install -m 0755 "$task_runtime_dir/gvisor-bin/runsc-metric-server" /usr/local/bin/gvisor-bin/runsc-metric-server
/usr/local/bin/runsc --version
cat "$task_runtime_dir/runtime-provenance.json"

task_uid=$(id -u)
task_user=$(id -un)
findmnt -n -o FSTYPE /sys/fs/cgroup
test -f /sys/fs/cgroup/cgroup.controllers
cat /sys/fs/cgroup/cgroup.controllers
export XDG_RUNTIME_DIR="/run/user/$task_uid"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
sudo mkdir -p /etc/systemd/system/user@.service.d
printf '[Service]\nDelegate=cpu cpuset io memory pids\n' | sudo tee /etc/systemd/system/user@.service.d/agentforge-ci.conf
sudo systemctl daemon-reload
sudo loginctl enable-linger "$task_user"
sudo systemctl start "user-runtime-dir@$task_uid.service"
if ! sudo systemctl restart "user@$task_uid.service"; then
  sudo systemctl status "user@$task_uid.service" --no-pager || true
  sudo journalctl -u "user@$task_uid.service" --no-pager -n 80
  exit 1
fi
mkdir -p "$HOME/.config/docker"
python - <<'PY'
import json
from pathlib import Path
config = {'runtimes': {'runsc': {'path': '/usr/local/bin/runsc',
          'runtimeArgs': ['--platform=systrap', '--network=none']}},
          'exec-opts': ['native.cgroupdriver=systemd'], 'storage-driver': 'vfs'}
(Path.home()/'.config/docker/daemon.json').write_text(json.dumps(config))
PY
dockerd-rootless-setuptool.sh install --force
systemctl --user restart docker
task_socket="unix://$XDG_RUNTIME_DIR/docker.sock"
docker --host "$task_socket" info
docker --host "$task_socket" pull python:3.11-slim-bookworm
task_image=$(docker --host "$task_socket" image inspect python:3.11-slim-bookworm --format '{{index .RepoDigests 0}}')
python - "$task_socket" "$task_image" <<'PY'
import json
import sys
from pathlib import Path
policy = {'socket': sys.argv[1], 'image': sys.argv[2],
          'lease_dir': str((Path.cwd()/'work/sandbox-leases').resolve())}
Path('sandbox-policy.json').write_text(json.dumps(policy, indent=2))
PY
