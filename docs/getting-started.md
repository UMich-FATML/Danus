# Danus — Getting Started

This is deployment setup, not a prerequisite for repository coding. For coding,
read [CONTRIBUTING.md](../CONTRIBUTING.md) and leave the operator template blank.
Do not initialize live services or make model calls as part of implementation.
For the mental model see [concepts](concepts.md); existing deployments should read
[DSH migration](dsh-migration.md).

## Prerequisites

- A Linux host appropriate for autonomous agents: preferably a dedicated
  VM/container, not a workstation containing unrelated data. Read
  [security and trust](security-and-trust.md).
- Git, Bash, and Pixi. Python dependencies and Node are managed by the repository's
  Pixi manifest, not an ad-hoc venv or system package install.
- An operator-approved DSH binary and an explicitly selected provider route with
  supported model/effort and credentials. Do not infer support from an upstream
  model name or silently fall back to another runtime.
- Optional rendering dependencies: a LaTeX engine for papers and Chrome/Chromium
  for report PDFs. They are not needed for proving.

## 1. Provision the software environment

```bash
pixi install
bash scripts/bootstrap.sh
```

Bootstrap uses the Pixi environment and prepares local runtime paths. It does not
log into an old backend, run paid inference, or configure a different running GUI.
Keep the installed DSH binary explicit with `DANUS_DSH_BIN`.

## 2. Configure the deployment

```bash
cp config/danus.env.example config/danus.env
cp config/dsh.env.example config/dsh.env
```

Read the templates and fill the gitignored files with the operator's settings.
Set `DANUS_DSH_PROVIDER`, provider endpoint/auth configuration, and explicit
`DANUS_MAIN_MODEL` / `DANUS_MAIN_EFFORT`. The standard generated-provider path uses
`DANUS_DSH_API`, `DANUS_DSH_API_BASE_URL`, `DANUS_DSH_API_KEY`, and
`DANUS_DSH_REASONING_EFFORTS`; an approved preconfigured JSON
provider overlay can instead be named by absolute `DANUS_DSH_PROVIDER_PATCH`.
No provider choice or key should be guessed. See [configuration](configuration.md).

```bash
bash scripts/setup-dsh.sh
bash scripts/check-dsh.sh
bash scripts/doctor.sh
```

Setup generates the provider overlay with an environment-variable key reference.
Check/doctor are nonbillable diagnostics; a successful check does **not** establish
live inference reachability or model quality. Do not perform a live test without
authorization. There is no legacy login flow or runtime fallback.

## 3. Initialize only when operating

Launch the main agent through the repository main wrapper (`bin/danus-main`),
whose default isolated Web mode binds `127.0.0.1:8090` (`DANUS_MAIN_PORT`).
It composes `.dsh/` main-role configuration, native goals/schedules/subagents,
MCP tools and the completed-turn snapshot hook. The optional `--headless` mode
is one-shot and does not provide schedules. `bin/dsh` provides the isolated underlying DSH wrapper. Do not
assume an unrelated ambient DSH GUI session has this project's configuration.

On a fresh deployment, explicitly run the `initialize` skill. It collects missing
operator preferences, confirms the configured route rather than inventing one,
and starts the required service only with deployment authorization:

```bash
bash scripts/services.sh up verify
bash scripts/services.sh status
```

The verifier at `127.0.0.1:8091` must be up before proving; without it no submission
can become a fact. Mark initialization complete only after checking the actual
required stack, not merely because offline configuration checks passed.

Continue with [the operating guide](operating-guide.md). The main agent reasons
continuously, uses speculative DSH subagents, and directs verifier-gated workers.
Review [Git recovery](git-resume.md) before relying on snapshots. Recovery after a
host restart is in [operations](operations.md).
