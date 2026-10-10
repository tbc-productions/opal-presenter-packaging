# Linux Gitea Actions Runner Setup

Step-by-step for registering a self-hosted Gitea Actions runner on Linux so
the `prepare-source`, `build-flatpak`, and `publish-release` jobs in
`opal-presenter-packaging/.gitea/workflows/build.yml` — plus the `test` and
`release` workflows in `opal-presenter` and the lightweight `release`
workflow in `opal-presenter-plugins` — can pick up work.

All three workflows target `runs-on: ubuntu-latest` and declare their own
container images (`alpine:3.20`, `python:3.12-bookworm`,
`bilelmoussaoui/flatpak-github-actions:gnome-46`). That means your Linux
host does **not** need Python, Qt, Flatpak, or build tools installed
directly — it only needs a working Docker engine and `act_runner`.

Instructions are provided for Ubuntu 22.04 / 24.04 LTS and Fedora 40+.
Other Debian / RHEL family distros follow the same pattern; just swap the
package manager commands.

---

## 1. Prerequisites

### 1a. System packages (Ubuntu / Debian)

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  curl ca-certificates gnupg lsb-release git
```

### 1a. System packages (Fedora)

```bash
sudo dnf install -y curl ca-certificates gnupg git
```

### 1b. Docker Engine

`act_runner` uses Docker to execute containerised jobs. Install the
official upstream packages (the distro-shipped `docker.io` / `moby-engine`
usually works too, but lags behind).

**Ubuntu / Debian:**

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

**Fedora:**

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf-3 config-manager --add-repo \
  https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

Enable and start the service on either distro:

```bash
sudo systemctl enable --now docker
docker run --rm hello-world
```

### 1c. Create a dedicated runner user (recommended)

Running the runner as an unprivileged user keeps workflows isolated from
your personal account. Skip this if you prefer to run as your own user.

```bash
sudo useradd --create-home --shell /bin/bash actions
sudo usermod -aG docker actions
```

> Adding the user to the `docker` group grants root-equivalent privileges
> on the host via Docker. This is the standard tradeoff for self-hosted
> runners. For stricter isolation, use Docker's rootless mode instead
> (see <https://docs.docker.com/engine/security/rootless/>).

From here on, run all commands as the runner user:

```bash
sudo -iu actions
```

---

## 2. Get a registration token from Gitea

1. Sign in to `https://<your-gitea-host>` as an admin.
2. Go to **Org `<your-org>` → Settings → Actions → Runners → Create new Runner**
   (or *Site Administration → Actions → Runners* for an instance-wide runner).
3. Copy the token. Looks like `3gJBmN...`.

> Org-scoped tokens are preferred — only your org's jobs can schedule onto
> this host.

---

## 3. Install `act_runner`

No distro ships `act_runner` natively yet, so download the binary from
Gitea's release mirror.

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
  armv7l)  ARCH=arm-7 ;;
esac

curl -L -o act_runner \
  "https://dl.gitea.com/act_runner/latest/act_runner-latest-linux-${ARCH}"
chmod +x act_runner
sudo mv act_runner /usr/local/bin/act_runner
act_runner --version
```

---

## 4. Register the runner

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner

act_runner register \
  --no-interactive \
  --instance https://<your-gitea-host> \
  --token <PASTE_TOKEN_HERE> \
  --name "$(hostname)-linux" \
  --labels "ubuntu-latest,ubuntu-22.04,self-hosted,Linux,X64"
```

Adjust the architecture label:

- `X64` for standard Intel/AMD 64-bit hosts
- `ARM64` for aarch64 (Raspberry Pi 4/5 64-bit, AWS Graviton, Apple M-series VM)

This creates a `.runner` file in `~/actions-runner/`. The label
`ubuntu-latest` **must** be present — the `prepare-source` /
`publish-release` jobs, the `opal-presenter` test job, and the
`opal-presenter-plugins` release job all use `runs-on: ubuntu-latest`.

### Optional: the `flatpak-builder` label

The `build-flatpak` job in `opal-presenter-packaging/.gitea/workflows/build.yml`
uses `runs-on: flatpak-builder` (not `ubuntu-latest`). This is
intentional — Flatpak builds are heavy and we don't want them scheduled
onto a lightweight always-on host like a Synology NAS. Add the label
only to a Linux runner you're happy to have carry those jobs
(a workstation or bigger server):

```bash
act_runner register \
  --no-interactive \
  --instance https://<your-gitea-host> \
  --token <PASTE_TOKEN_HERE> \
  --name "$(hostname)-linux-flatpak" \
  --labels "ubuntu-latest,ubuntu-22.04,self-hosted,Linux,X64,flatpak-builder"
```

If no online runner carries `flatpak-builder`, the `build-flatpak`
job is simply skipped (it is gated behind the `build_flatpak`
workflow input, default `false`) and `publish-release` still ships
the macOS and Windows artifacts.

> **Distro note:** the `ubuntu-latest` label is purely a name the
> workflow expects; it does not require the host to actually be Ubuntu.
> A Fedora runner with the `ubuntu-latest` label is perfectly fine
> because every job runs inside its own Docker container anyway.

---

## 5. Generate a config

```bash
cd ~/actions-runner
act_runner generate-config > config.yaml
```

Open `~/actions-runner/config.yaml` and confirm these two sections are
sensible:

```yaml
runner:
  labels:
    - ubuntu-latest
    - self-hosted
    - Linux
    - X64

container:
  # Leave network/options empty unless you know you need them.
  # Do NOT add ":host" here — Linux jobs must run inside their declared
  # containers (alpine, python:3.12-bookworm, flatpak-github-actions).
  network: ""
  privileged: false
  options: ""
  valid_volumes: []
  docker_host: ""
```

Points to double-check:

- Labels have **no** `:host` suffix. Unlike the macOS and Windows runners,
  every Linux job in this pipeline *expects* to run inside a container.
- `privileged: false` is fine for the `prepare-source` and
  `publish-release` jobs. The `build-flatpak` job does not require
  `privileged: true`; if a future job does, set this to `true` then.
- `docker_host` empty → uses `/var/run/docker.sock` of the host, which
  the `actions` user can reach via the `docker` group.

---

## 6. Smoke-test in the foreground

```bash
cd ~/actions-runner
act_runner daemon --config config.yaml
```

You should see:

```
INFO Starting runner daemon
INFO Runner: myhost-linux, with version ..., with labels [ubuntu-latest self-hosted Linux X64], is online and listening
```

Also check the Gitea UI (*Org → Settings → Actions → Runners*): the
runner should appear as **Idle** with a green dot.

Press **Ctrl-C** once confirmed.

---

## 7. Install as a systemd service

Both Ubuntu and Fedora use systemd. The service runs as the `actions`
user created in step 1c.

### 7a. Create the unit file

```bash
sudo tee /etc/systemd/system/gitea-actions-runner.service >/dev/null <<'EOF'
[Unit]
Description=Gitea Actions Runner (act_runner daemon)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=actions
Group=actions
WorkingDirectory=/home/actions/actions-runner
ExecStart=/usr/local/bin/act_runner daemon --config /home/actions/actions-runner/config.yaml
Restart=on-failure
RestartSec=5

# Harden a little (optional — remove if it blocks your jobs)
NoNewPrivileges=false
ProtectSystem=full
ProtectHome=false
PrivateTmp=true

StandardOutput=append:/home/actions/actions-runner/runner.log
StandardError=append:/home/actions/actions-runner/runner.err

[Install]
WantedBy=multi-user.target
EOF
```

> If you're not using the dedicated `actions` user, change the `User=`,
> `Group=`, `WorkingDirectory=`, `ExecStart=`, and log paths accordingly.

### 7b. Enable and start it

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gitea-actions-runner
```

### 7c. Verify it stays running

```bash
systemctl status gitea-actions-runner --no-pager
sudo journalctl -u gitea-actions-runner -f
# or
tail -n 50 -f /home/actions/actions-runner/runner.log
```

You should see:

```
INFO Runner: myhost-linux, ..., is online and listening
```

---

## 8. Fedora: SELinux considerations

Fedora ships with SELinux in enforcing mode. `act_runner` talking to
`/var/run/docker.sock` via the `docker` group is allowed by default, but
bind-mounting `/home/actions/...` into containers can get denied with
`permission denied` inside the container even though host `ls -l` looks
fine.

If you hit that, label the runner directory so containers can read it:

```bash
sudo semanage fcontext -a -t container_file_t "/home/actions/actions-runner(/.*)?"
sudo restorecon -R /home/actions/actions-runner
```

(The `semanage` tool is in the `policycoreutils-python-utils` package:
`sudo dnf install -y policycoreutils-python-utils`.)

Ubuntu uses AppArmor and the default Docker profile handles this
transparently, so no extra configuration is needed there.

---

## 9. Confirm Gitea sees it

1. Open `https://<your-gitea-host>`.
2. Go to **Org `<your-org>` → Settings → Actions → Runners**.
3. The runner should be **Idle / green**.
4. Confirm the labels listed include `ubuntu-latest` exactly (case sensitive).

---

## 10. Trigger a test run

1. On Gitea: `<your-org>/opal-presenter-packaging` → *Actions* → *Build Opal Presenter* →
   *Run workflow* → leave inputs blank → *Run*.
2. Watch the `prepare-source` job. It should go **Queued → Running**
   immediately on this host.
3. Tail the log to see the job pull `alpine:3.20`, merge the source
   trees, and upload the `merged-source` artifact:

   ```bash
   sudo journalctl -u gitea-actions-runner -f
   ```

4. The `build-flatpak` job runs next on the same host (pulls the
   Flatpak builder container). `build-macos` and `build-windows` will
   queue on their respective runners.

---

## Troubleshooting

### Service won't start / `systemctl status` shows `exit-code`

```bash
sudo journalctl -u gitea-actions-runner -n 100 --no-pager
```

Common causes:

- Wrong `ExecStart` path. Confirm with `which act_runner`
  (should be `/usr/local/bin/act_runner`).
- `config.yaml` missing or at a different path — use an absolute path.
- The `.runner` registration file is not in `WorkingDirectory`. Copy or
  re-register from `/home/actions/actions-runner/`.

### `docker: Got permission denied while trying to connect to the Docker daemon socket`

The runner user isn't in the `docker` group, or the group membership
hasn't taken effect in the running service.

```bash
sudo usermod -aG docker actions
sudo systemctl restart gitea-actions-runner
```

Log out of any existing `sudo -iu actions` session before retrying — group
membership only applies to new sessions.

### Job stays "queued" forever

The runner's labels don't match `runs-on: ubuntu-latest` in the workflow.
Check the runner row in Gitea's UI — `ubuntu-latest` must appear exactly
(case sensitive).

### Container jobs fail with "pull access denied" for `alpine:3.20` etc.

Your host can't reach Docker Hub, or it's rate-limited. Test with:

```bash
sudo -u actions docker pull alpine:3.20
```

Fix by adding a Docker Hub login (`docker login` as the `actions` user)
or mirroring the needed images to a local registry.

### Flatpak build errors about `/dev/fuse` or overlayfs

The Flatpak builder image occasionally needs extra container privileges.
Try setting `privileged: true` under `container:` in `config.yaml` and
restart the runner:

```bash
sudo systemctl restart gitea-actions-runner
```

### Updating `act_runner`

```bash
sudo systemctl stop gitea-actions-runner
sudo curl -L -o /usr/local/bin/act_runner \
  https://dl.gitea.com/act_runner/latest/act_runner-latest-linux-amd64
sudo chmod +x /usr/local/bin/act_runner
sudo systemctl start gitea-actions-runner
```

---

## Uninstall (if needed)

```bash
sudo systemctl disable --now gitea-actions-runner
sudo rm /etc/systemd/system/gitea-actions-runner.service
sudo systemctl daemon-reload
sudo rm -rf /home/actions/actions-runner
sudo rm /usr/local/bin/act_runner
sudo userdel -r actions        # if you created the dedicated user
```

Then in Gitea, remove the now-offline runner from **Settings → Actions → Runners**.
