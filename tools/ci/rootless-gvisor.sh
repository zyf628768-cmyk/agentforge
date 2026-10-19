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

# Official release archive, including the post-2026 gvisor-bin sidecars.
task_gvisor_dir=$(mktemp -d)
task_gvisor_url="https://storage.googleapis.com/gvisor/releases/release/latest/$(uname -m)"
curl --fail --location --proto '=https' "$task_gvisor_url/gvisor.tar.zstd" -o "$task_gvisor_dir/gvisor.tar.zstd"
curl --fail --location --proto '=https' "$task_gvisor_url/gvisor.tar.zstd.sha512" -o "$task_gvisor_dir/gvisor.tar.zstd.sha512"
(cd "$task_gvisor_dir" && sha512sum -c gvisor.tar.zstd.sha512)
sudo tar --zstd -xf "$task_gvisor_dir/gvisor.tar.zstd" -C /usr/local/bin
/usr/local/bin/runsc --version
sha512sum "$task_gvisor_dir/gvisor.tar.zstd"

task_uid=$(id -u)
task_user=$(id -un)
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
