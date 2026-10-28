# Demo-day guide

Step-by-step script for recording the live demo:

- the cluster running in a Codespace;
- the Argo CD web UI in your browser;
- the HealthQueue SLO dashboard in Grafana;
- a pull request (PR) merge rolling out a new signed image;
- Argo CD repairing a manual change on camera.

Every command here was run end to end on 2026-10-26 (see
[phase 8 evidence](evidence/phase-8-deploy-pr.md); Grafana:
[phase 10 evidence](evidence/phase-10-observability.md)).

| When | What | Time |
|---|---|---|
| Before recording | [1. Start the Codespace](#1-start-the-codespace) | 5–10 min |
| | [2. Bring the cluster back](#2-bring-the-cluster-back) | 1–5 min |
| | [3. Prepare a release to deploy](#3-prepare-a-release-to-deploy) | about 10 min, mostly waiting |
| | [4. Open Argo CD and Grafana](#4-open-argo-cd-and-grafana-in-your-browser) and [5. Set up the terminals](#5-set-up-the-on-camera-terminals) | 5 min, at least 10 min before recording |
| On camera | [6. Recording script](#6-recording-script) | 7–10 min |
| Afterwards | [7. Shut down](#7-shut-down) | 1 min |

**Conventions**

- **Laptop** commands are for Windows PowerShell on your laptop. Commands sent to the
  Codespace are wrapped in single quotes and avoid double quotes, because Windows
  PowerShell 5.1 mangles embedded double quotes when it passes arguments to `gh`.
- **Codespace** commands run inside the Codespace. Open a shell there from a laptop terminal
  with `gh codespace ssh -c $cs`, using the `$cs` variable set in step 1.
- Each new laptop terminal needs `$cs` set again (step 1).

---

## Before recording

### 1. Start the Codespace

The Codespace from phase 7 is deleted automatically 72 hours after it was last stopped, so
you will usually create a new one. Both cases end with `$cs` holding its name.

**Laptop:**

```powershell
gh codespace list -R martineh4/healthqueue-platform
```

**If one is listed** (any state, including `Shutdown`), reuse it:

```powershell
$cs = gh codespace list -R martineh4/healthqueue-platform --json name --jq '.[0].name'
```

**If none is listed,** create one (4-core; first build about 5 minutes):

```powershell
$cs = gh codespace create -R martineh4/healthqueue-platform -b main -m standardLinux32gb --idle-timeout 60m --display-name hq-demo
$cs   # should print a name like hq-demo-abc123; if not, set it with the list command above
```

The 60-minute idle timeout keeps the Codespace from stopping mid-demo. The next command
starts the Codespace if it is stopped, waits for setup to finish, and checks the tools:

```powershell
gh codespace ssh -c $cs -- 'cd /workspaces/healthqueue-platform && git pull -q --ff-only && kind version && kubectl version --client && docker version --format {{.Server.Version}}'
```

Expected: three version lines (kind v0.33.0, kubectl v1.37.1, Docker). `command not found`
means the dev container build failed. See [Troubleshooting](#troubleshooting).

### 2. Bring the cluster back

**Laptop:**

```powershell
gh codespace ssh -c $cs -- 'cd /workspaces/healthqueue-platform && deploy/scripts/bootstrap-cluster.sh'
```

Possible outcomes:

- **Exit 0, about 30 seconds:** the cluster was resumed. The script restarts the kind node if
  needed and waits until the commit on `main` is deployed. Go to step 3.
- **New Codespace, about 4 minutes:** it creates the cluster, installs Argo CD, then stops at
  **step 3/5 with "The acr-pull secret is missing"**. This is expected: the registry password
  is never stored in Git. Run the next command, then the bootstrap command again.
- **An existing secret expires in under 7 days:** the bootstrap warns
  `warning: rotate soon`. Run the next command too.

Create (or rotate) the 30-day pull-only registry password. It is minted on your laptop with
your Azure login and piped straight into the cluster; it is never shown or saved.

**Laptop:** if `az` is not found, run `az login` in a new terminal first.

```powershell
az acr token credential generate -r crhealthqueueora3w -n kind-pull --password1 --expiration-in-days 30 --query "passwords[?name=='password1'] | [0].[value, expiry]" -o tsv | gh codespace ssh -c $cs -- 'cd /workspaces/healthqueue-platform && deploy/scripts/create-pull-secret.sh --stdin'
```

Expected: `healthqueue/acr-pull: token kind-pull, expires <date> (29 days left)`.

Done when the bootstrap ends with all four applications `Synced` and `Healthy`:

```
NAME              SYNC STATUS   HEALTH STATUS
argocd            Synced        Healthy
healthqueue-api   Synced        Healthy
monitoring        Synced        Healthy
root              Synced        Healthy
```

On a new cluster the monitoring stack's first install takes a few minutes more.

### 3. Prepare a release to deploy

On camera you will merge a **deploy PR**: the PR that `release.yml` opens after it has built,
scanned, signed and verified a new image. Get one waiting now, so the recording does not
include the build.

Any merged change under `app/` triggers a release. A version bump makes the change visible
on `/version`.

**Laptop**, in your clone of the repository:

```powershell
git switch main; git pull
git switch -c demo/version-0.2.0
foreach ($f in 'app/src/healthqueue/__init__.py', 'app/pyproject.toml') { $p = (Resolve-Path $f).Path; [IO.File]::WriteAllText($p, ([IO.File]::ReadAllText($p) -replace '0\.1\.0', '0.2.0')) }
git diff
git commit -am "Bump healthqueue-api to 0.2.0"
git push -u origin demo/version-0.2.0
gh pr create -B main -t "Bump healthqueue-api to 0.2.0" -b "Demo release."
gh pr checks --watch
gh pr merge --rebase --delete-branch
```

The `foreach` line edits the version in both files without adding a byte-order mark (BOM).
`Set-Content -Encoding utf8` would add one. `git diff` should show exactly two changed lines.

Then:

1. In **GitHub → Actions → Release**, wait for the run to finish (about 4 minutes): first
   `build-sign-attest`, then `open-deploy-pr`.
2. Open the new PR **"Deploy healthqueue-api <commit> to prod"** (label `deploy`), or list it
   with `gh pr list --label deploy`.
3. Click **Approve workflows to run**. CI on PRs opened by the bot waits for a maintainer
   ([ADR-0007](adr/0007-pr-driven-image-promotion.md)).
4. Wait for every check to turn green (about 2 minutes). **Do not merge yet.**

### 4. Open Argo CD and Grafana in your browser

You need four laptop terminals, A, B, E and F. Leave them running for the whole recording.
Set `$cs` in each first (step 1).

**Terminal A:** port-forward to Argo CD inside the Codespace.

```powershell
gh codespace ssh -c $cs -- 'kubectl -n argocd port-forward svc/argocd-server 8080:443'
```

Expected: `Forwarding from 127.0.0.1:8080 -> 8080`.

**Terminal E:** port-forward to Grafana inside the Codespace.

```powershell
gh codespace ssh -c $cs -- 'kubectl -n monitoring port-forward svc/kps-grafana 3000:80'
```

Expected: `Forwarding from 127.0.0.1:3000 -> 3000`.

**Terminal B:** tunnel both ports to your laptop.

```powershell
gh codespace ports forward 8080:8080 3000:3000 -c $cs
```

Expected: `Forwarding ports: remote 3000 <=> local 3000` and the same line for 8080.

**Terminal F:** demo traffic, so the dashboard has data. Start it **at least 10 minutes
before recording**: the burn-rate panels need 5 minutes of data, and the panels refresh every
30 seconds.

```powershell
gh codespace ssh -c $cs -- 'cd /workspaces/healthqueue-platform && deploy/scripts/generate-traffic.sh 1800 5'
```

Expected: `sending ~5 req/s for 1800s`, then a count of status codes every 30 seconds. The
traffic is bookings, lists, availability checks and unknown IDs, so you will see 200, 201, 404
and a few 409s, and no 5xx. It waits until the API is ready before sending anything, so you can
start it while the bootstrap is still running. It runs inside the API pod. When the pod is
replaced in scene 4, it prints `lost healthqueue-api ...`, waits for the new pod and carries on.

**Get the login passwords.** Run these in another terminal, or one you will close before
recording, so the passwords are never on screen:

```powershell
gh codespace ssh -c $cs -- 'argocd admin initial-password -n argocd | head -1'
gh codespace ssh -c $cs -- 'kubectl -n monitoring get secret grafana-admin -o jsonpath={.data.admin-password} | base64 -d; echo'
```

The first is Argo CD's, and the second is Grafana's. Both are generated per cluster and never
stored in Git.

**Browser:**

1. Go to **https://localhost:8080**.
2. The browser warns about the certificate, because the kind cluster's Argo CD uses a
   self-signed one. Choose **Advanced → Continue to localhost**. The traffic still goes
   through an encrypted tunnel.
3. Log in as `admin` with the password above.

Tidy the view for the camera:

1. Open the **healthqueue-api** application. The tree view shows the Deployment,
   ReplicaSet, Pod, Service, PVC and NetworkPolicies.
2. Zoom the browser to 125%.
3. In a second tab, open the deploy PR from step 3.

If Codespaces pops up "Your application running on port 8080 is available", ignore it. That
browser link cannot speak to Argo CD's HTTPS port; use `https://localhost:8080`.

**Grafana**, in a third browser tab:

1. Go to **http://localhost:3000/d/healthqueue-slo?from=now-30m&to=now**. Grafana is plain
   HTTP here, because the tunnel is already encrypted.
2. Log in as `admin` with the Grafana password above. The **HealthQueue SLOs** dashboard
   opens. It also appears under **Dashboards**.
3. Set the browser zoom so the top row of SLO tiles and both burn-rate graphs fit on screen.

### 5. Set up the on-camera terminals

**Terminal C:** shows the running version every 2 seconds.

```powershell
gh codespace ssh -c $cs -- 'cd /workspaces/healthqueue-platform && deploy/scripts/watch-version.sh'
```

Expected: `{"version":"0.1.0","commit":"<old commit>"}` repeating.

**Terminal D:** a Codespace shell for the self-heal demo.

```powershell
gh codespace ssh -c $cs
```

Pre-type, but do not run, in terminal D:

```bash
kubectl -n healthqueue scale deploy/healthqueue-api --replicas=0
```

Final check before you start:

- the browser shows Argo CD with everything **Synced / Healthy**;
- Grafana's **Requests per second** graph shows traffic, and both burn-rate graphs have
  lines;
- the deploy PR's checks are green;
- terminal C prints the old version.

---

## 6. Recording script

**Scene 1: what is running (1 min)**

- **Show:** Argo CD's **Applications** page with four apps, all Synced and Healthy.
- Open **healthqueue-api** and point at the Pod.
- Point at terminal C: it shows version 0.1.0 and the old commit.

**Scene 2: how we know it is healthy (2 min)**

- Switch to the Grafana tab, showing **HealthQueue SLOs**.
- **Show the top row:** the availability SLI, the latency SLI and the error budget left for
  each.
- **Show** the two **burn rate** graphs.
- **Show** **Requests per second by route and status**: 201 bookings, a few 409 clashes, and
  404s.
- **Show** **What is deployed**: the image digest, and every Argo CD application's state.

**Scene 3: a release is a pull request (2 min)**

- Switch to the deploy PR tab.
- **Show:**
  - the PR body: built-from commit, compare link, digest, vulnerability counts, evidence
    location, verify commands;
  - **Files changed**: two lines, the digest and its evidence pointer.
- Show the green checks, then click **Rebase and merge**.

**Scene 4: GitOps rollout (1–3 min)**

- Back in Argo CD, on **healthqueue-api**, click **Refresh**. (Argo CD also polls on its
  own, within 3 minutes.)
- **Watch:** the app goes **OutOfSync**, then syncs. A new ReplicaSet appears; the old pod
  terminates and the new one starts.
- Terminal C briefly shows `(no ready pod)`, then `{"version":"0.2.0","commit":"<new commit>"}`.

**Scene 5: self-healing (1 min)**

- In terminal D, run the pre-typed `kubectl ... --replicas=0`.
- **Watch:** Argo CD flags the drift and restores 1 replica within a few seconds. The pod
  reappears in the tree, and terminal C recovers.

**Optional scene 6: rollback (2–3 min)**

- On the merged deploy PR, click **Revert**, then create the PR. Your account opens this
  one, so CI runs without the approval click.
- When the checks pass, merge it, then press **Refresh** in Argo CD.
- Terminal C returns to 0.1.0.

---

## 7. Shut down

1. Press `Ctrl+C` in terminals A to F.
2. Stop the Codespace so it stops using hours. **Laptop:**

   ```powershell
   gh codespace stop -c $cs
   ```

3. Optional: once you no longer need it, delete it with `gh codespace delete -c $cs`. Nothing
   in it is needed again: the cluster can be recreated from Git in about 5 minutes.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Tools `MISSING` in step 1 | The dev container build failed and Codespaces started a recovery container. See the build log in the browser (**Codespaces → … → View creation log**). Then delete the Codespace and create it again. |
| `gh codespace ssh` says no SSH server | Same cause: the recovery container is running. Same fix. |
| Bootstrap exits 2 at step 3/5 | The pull secret is missing. Run the `az acr token credential generate ...` command in step 2, then the bootstrap again. |
| Pod stuck in `ImagePullBackOff` | The pull password expired or was rotated elsewhere. Run the step 2 password command (it replaces the secret), then `kubectl -n healthqueue delete pod -l app.kubernetes.io/name=healthqueue-api`. More: [runbook](runbooks/image-pull-failures.md). |
| `az: not found` or `az` errors | Run `az login`. The command needs rights to generate ACR token passwords (you are Owner). |
| Deploy PR checks say "waiting for approval" | Click **Approve workflows to run** on the PR (step 3). |
| Deploy PR says the branch is out of date | Something merged after it. Click **Update branch**, wait for the checks, then merge. |
| No deploy PR appeared | Check the **Release** run. `open-deploy-pr` prints "already what main deploys" if the digest did not change. The release only runs for changes under `app/`. |
| `https://localhost:8080` does not load | Terminal A or B was closed, or the Codespace stopped. Restart both. If port 8080 is busy on the laptop, use `gh codespace ports forward 8081:8080 -c $cs` and `https://localhost:8081`. |
| `http://localhost:3000` does not load | Terminal E or B was closed. Restart both. If port 3000 is busy on the laptop, use `3001:3000` in terminal B and `http://localhost:3001`. |
| Grafana login fails | The password is per cluster. Get it again with the command in step 4. |
| `RESTARTS` on the API pod goes up after resuming the Codespace | Expected. Stopping the Codespace stops the kind node, so every pod restarts once when it resumes (`SandboxChanged` in `kubectl describe pod`, last state exit 255, reason `Unknown`). A crash would show a non-zero app exit code or `OOMKilled`, with a `Back-off restarting` event. |
| Grafana panels say **No data** | No traffic yet, or it stopped. Restart terminal F and wait 5 minutes. The SLI tiles need at least one `/v1` request in the window. |
| Argo CD login fails | The password belongs to that cluster; get it again with the command in step 4. A new cluster has a new password. |
| Argo CD shows the old version after merging | Click **Refresh** on the app. Polling takes up to 3 minutes. |
| `kubectl ... connection refused` right after resuming | The node is still starting. Re-run the bootstrap; it waits for the API server. |
