# Windows Gitea Actions Runner Setup

Step-by-step for registering a self-hosted Gitea Actions runner on Windows so
the `build-windows` job in `openlp-packaging/.gitea/workflows/build.yml` can
pick up work.

> Run every PowerShell block in an **elevated PowerShell** (right-click →
> *Run as Administrator*) unless noted otherwise.

---

## 1. Prerequisites

Install these on the Windows machine:

- **Git for Windows** — <https://gitforwindows.org/>
- **Node.js LTS** — <https://nodejs.org/> (required for Node-based actions like
  `actions/checkout` when the runner is in host mode)
- **Python 3.12** — <https://www.python.org/downloads/> (tick *Add to PATH*)
- **PowerShell 7** *(optional but nicer)* — `winget install Microsoft.PowerShell`
- **WiX Toolset** — `choco install wixtoolset` (needed by `windows-builder.py`
  for MSI creation)
- **Visual C++ Build Tools** — for any native Python wheels that might compile:
  `winget install Microsoft.VisualStudio.2022.BuildTools`

If you don't have Chocolatey:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

---

## 2. Get a registration token from Gitea

1. Sign in to <https://git.tbcproductions.net> as an admin.
2. Go to **Org `tbcproductions` → Settings → Actions → Runners → Create new Runner**
   (or *Site Administration → Actions → Runners* for an instance-wide runner).
3. Copy the token. Looks like `3gJBmN...`.

> Org-scoped tokens are preferred — only `tbcproductions` jobs can schedule
> onto your PC.

---

## 3. Install `act_runner`

There is no winget / Chocolatey package for `act_runner` on Windows — the
binary has to be downloaded directly from Gitea's release server.

```powershell
New-Item -ItemType Directory -Force -Path C:\actions-runner | Out-Null
Invoke-WebRequest `
  -Uri "https://dl.gitea.com/act_runner/latest/act_runner-latest-windows-amd64.exe" `
  -OutFile "C:\actions-runner\act_runner.exe"
```

> Pin a specific version instead of `latest` if you want reproducible
> upgrades, e.g. `act_runner-0.2.11-windows-amd64.exe`. Browse available
> versions at <https://dl.gitea.com/act_runner/>.

---

## 4. Register the runner

```powershell
cd C:\actions-runner

.\act_runner.exe register `
  --no-interactive `
  --instance https://git.tbcproductions.net `
  --token <PASTE_TOKEN_HERE> `
  --name "$($env:COMPUTERNAME)-windows" `
  --labels "windows,self-hosted,Windows,X64"
```

This creates a `.runner` file in `C:\actions-runner\` with the saved
registration. The label `windows` **must** be present — the workflow uses
`runs-on: windows`.

---

## 5. Generate a host-mode config

```powershell
.\act_runner.exe generate-config > config.yaml
```

Open `C:\actions-runner\config.yaml` and replace the `runner.labels` section
so every label ends with `:host`:

```yaml
runner:
  labels:
    - "windows:host"
    - "self-hosted:host"
    - "Windows:host"
    - "X64:host"
```

The `:host` suffix tells act_runner to execute steps directly on the Windows
host (not inside a Docker container). This is what PyInstaller needs.

---

## 6. Smoke-test in the foreground

```powershell
cd C:\actions-runner
.\act_runner.exe daemon --config config.yaml
```

You should see something like:

```
INFO Starting runner daemon
INFO Runner: MYPC-windows, with version ..., with labels [windows self-hosted ...], is online and listening
```

Also check the Gitea UI (*Org → Settings → Actions → Runners*): the runner
should appear as **Idle** with a green dot.

Press **Ctrl-C** once confirmed.

---

## 7. Install as a Windows service (via NSSM)

`act_runner.exe daemon` is a plain console app — it does **not** implement
the Windows Service Control Manager protocol. Installing it directly with
`sc.exe create` causes **Error 1503: "The service did not respond to the start
or control request in a timely fashion"** because SCM never receives a
`SERVICE_RUNNING` status back and kills the process after 30 seconds.

The fix is to wrap it with a service wrapper like
[NSSM](https://nssm.cc/) (Non-Sucking Service Manager).

### 7a. If you already tried `sc.exe create`, remove the broken service

```powershell
sc.exe stop "gitea-actions-runner"   # ignore "service not running" errors
sc.exe delete "gitea-actions-runner"
```

### 7b. Install NSSM

```powershell
choco install nssm -y
```

Or download `nssm.exe` manually from <https://nssm.cc/download> and drop it
in `C:\Windows\System32\`.

### 7c. Create the service

```powershell
cd C:\actions-runner

nssm install gitea-actions-runner `
  "C:\actions-runner\act_runner.exe" `
  "daemon --config C:\actions-runner\config.yaml"

nssm set gitea-actions-runner AppDirectory C:\actions-runner
nssm set gitea-actions-runner DisplayName "Gitea Actions Runner"
nssm set gitea-actions-runner Description "act_runner daemon for git.tbcproductions.net"
nssm set gitea-actions-runner Start SERVICE_AUTO_START
nssm set gitea-actions-runner AppStdout C:\actions-runner\runner.log
nssm set gitea-actions-runner AppStderr C:\actions-runner\runner.err
nssm set gitea-actions-runner AppRotateFiles 1
nssm set gitea-actions-runner AppRotateBytes 10485760
```

### 7d. (Recommended) run as your user account

NSSM defaults to `LocalSystem`, which doesn't see user-installed Python,
Chocolatey packages on the user PATH, or your developer tools. Switch to your
account:

```powershell
nssm set gitea-actions-runner ObjectName ".\YourWindowsUsername" "YourPassword"
```

- `.\User` — local account
- `DOMAIN\User` — domain account

### 7e. Start it

```powershell
nssm start gitea-actions-runner
# or: Start-Service gitea-actions-runner
```

### 7f. Verify it stays running

```powershell
Get-Service gitea-actions-runner
Get-Content C:\actions-runner\runner.log -Tail 50 -Wait
```

You should see:

```
INFO Runner: MYPC-windows, ..., is online and listening
```

and the service status should be `Running`.

---

## 8. Confirm Gitea sees it

1. Open <https://git.tbcproductions.net>
2. Go to **Org `tbcproductions` → Settings → Actions → Runners**.
3. The runner should be **Idle / green**.
4. Confirm the labels listed include `windows` exactly (case sensitive).

---

## 9. Trigger a test run

1. On Gitea: `tbcproductions/openlp-packaging` → *Actions* → *Build OpenLP+* →
   *Run workflow* → leave inputs blank → *Run*.
2. Watch the `build-windows` job. It should go **Queued → Running** as soon
   as the Synology runner finishes `prepare-source`.
3. Tail `C:\actions-runner\runner.log` to see the job executing locally.

---

## Troubleshooting

### Error 1503 on service start
You tried `sc.exe create` without a wrapper. See section 7 — use NSSM.

### Service starts then stops within seconds
Check `C:\actions-runner\runner.err`:

```powershell
Get-Content C:\actions-runner\runner.err -Tail 50
```

Common causes:
- `config.yaml` path is relative or wrong — use the absolute path.
- `.runner` registration file is not in `C:\actions-runner\`. Re-register in
  that folder, or copy the `.runner` file there.

### Job stays "queued" forever
The runner's labels don't match `runs-on: windows` in the workflow. Check
the runner row in Gitea's UI — `windows` must appear exactly (case sensitive).

### Job runs but fails with "exec: docker: not found"
You skipped the `:host` suffix in `config.yaml`. act_runner is trying to run
inside a Docker container that doesn't exist on Windows. Edit `config.yaml`
so every label ends with `:host`, then:

```powershell
Restart-Service gitea-actions-runner
```

### Node.js / Python / choco installs aren't found during a job
The service is running as `LocalSystem`. Switch to your user account (step
7d) and restart the service.

### Signing / permissions prompts during the build
The first interactive run may prompt; once approved the service runs
unattended afterwards. If the job runs as `LocalSystem`, certain Windows
prompts will never appear — another reason to run as your user account.

### Updating the runner

```powershell
Stop-Service gitea-actions-runner

# Download the newer act_runner.exe, overwriting the existing one
Invoke-WebRequest `
  -Uri "https://dl.gitea.com/act_runner/latest/act_runner-latest-windows-amd64.exe" `
  -OutFile "C:\actions-runner\act_runner.exe"

Start-Service gitea-actions-runner
```

---

## Uninstall (if needed)

```powershell
nssm stop gitea-actions-runner
nssm remove gitea-actions-runner confirm
Remove-Item C:\actions-runner -Recurse -Force
```

Then in Gitea, remove the now-offline runner from **Settings → Actions → Runners**.
