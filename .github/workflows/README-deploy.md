# Cloud Run setup, once

`deploy-backend.yml` assumes the project, repository, service accounts and
service already exist. This is the one-time setup that creates them. Run it with
an account that can administer IAM in the project.

> **Run these in Git Bash, not PowerShell.** They are bash: `export`, `for … in`
> and `read -s` are not PowerShell commands. Worse than failing loudly,
> `export FOO=bar` leaves `$FOO` empty, and gcloud accepts a flag whose value
> interpolated to nothing — so `add-iam-policy-binding` reports success and
> writes a policy with no bindings. `get-iam-policy` then returns `{"etag":
> "ACAB"}` and nothing else, which is the only sign anything went wrong, and it
> does not surface until the first deploy fails to authenticate. **After each
> binding step, check that `get-iam-policy` returns a `bindings` array.**
> PowerShell equivalents are at the end of this file.

Set these in your shell first; every command below reads them.

```bash
export PROJECT_ID=your-gcp-project
export REGION=asia-south1                       # keep it near the database
export REPOSITORY=nodus
export SERVICE=nodus-api
export GITHUB_REPO=raunak-shr/nodus-research

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com iamcredentials.googleapis.com

gcloud artifacts repositories create "$REPOSITORY" \
    --repository-format=docker --location="$REGION"
```

## Two service accounts, not one

The deployer pushes images and creates revisions. The runtime is what the
container *is* while it runs, and it needs to read secrets and nothing else.
Collapsing them means the running container holds deploy rights — exactly the
credential you do not want reachable from code that fetches arbitrary publisher
URLs.

```bash
# What GitHub Actions becomes
gcloud iam service-accounts create nodus-deployer --display-name="Nodus CI deployer"
export DEPLOYER="nodus-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

# What the container becomes
gcloud iam service-accounts create nodus-runtime --display-name="Nodus runtime"
export RUNTIME="nodus-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

for ROLE in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${DEPLOYER}" --role="$ROLE"
done

# The deployer must be allowed to *assign* the runtime identity to a revision.
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME" \
    --member="serviceAccount:${DEPLOYER}" --role=roles/iam.serviceAccountUser
```

## Workload Identity Federation, so there is no key to leak

```bash
gcloud iam workload-identity-pools create github --location=global \
    --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github \
    --location=global --workload-identity-pool=github \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
```

The `--attribute-condition` is the part that matters. Without it the provider
mints credentials for *any* GitHub repository's workflow, which is a project
takeover waiting for someone to guess the provider name.

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
POOL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" \
    --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/${POOL}/attribute.repository/${GITHUB_REPO}"

export WIF_PROVIDER="${POOL}/providers/github"
echo "$WIF_PROVIDER"
```

## Repository variables

Settings → Secrets and variables → Actions → **Variables**.

**The Variables tab, not Secrets.** The workflow reads `vars.*`, so an entry
added as a secret resolves to an empty string and the deploy fails on an empty
`workload_identity_provider` — an error that names nothing useful. None of the
seven is a credential either: the actual credential is minted at job runtime
from GitHub's OIDC token, which is why this setup needs no GitHub secrets at
all. And GitHub masks secret values in logs, so putting the region or project id
in a secret prints `***` over the image path and the service URL, making a
failed deploy much harder to read.

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | your project id |
| `GCP_REGION` | e.g. `asia-south1` |
| `AR_REPOSITORY` | `nodus` |
| `CLOUD_RUN_SERVICE` | `nodus-api` |
| `WIF_PROVIDER` | `$WIF_PROVIDER` from above |
| `DEPLOYER_SERVICE_ACCOUNT` | `nodus-deployer@<project>.iam.gserviceaccount.com` |
| `RUNTIME_SERVICE_ACCOUNT` | `nodus-runtime@<project>.iam.gserviceaccount.com` |

Or from the shell you already have set up:

```bash
gh variable set GCP_PROJECT_ID           --body "$PROJECT_ID"
gh variable set GCP_REGION               --body "$REGION"
gh variable set AR_REPOSITORY            --body "$REPOSITORY"
gh variable set CLOUD_RUN_SERVICE        --body "$SERVICE"
gh variable set WIF_PROVIDER             --body "$WIF_PROVIDER"
gh variable set DEPLOYER_SERVICE_ACCOUNT --body "$DEPLOYER"
gh variable set RUNTIME_SERVICE_ACCOUNT  --body "$RUNTIME"

gh variable list
```

## Secrets

These are runtime credentials: the container needs them, the build never sees
them. Cloud Run mounts them from Secret Manager, so they stay out of GitHub, out
of build logs, and out of the service's environment. Values are the same ones in
your local `.env`.

```bash
for NAME in DATABASE_URL GEMINI_API_KEY CLOUDFLARE_ACCOUNT_ID \
            CLOUDFLARE_API_TOKEN SEMANTIC_SCHOLAR_API_KEY ADMIN_API_KEY; do
  gcloud secrets describe "$NAME" >/dev/null 2>&1 \
    || gcloud secrets create "$NAME" --replication-policy=automatic
  gcloud secrets add-iam-policy-binding "$NAME" \
      --member="serviceAccount:${RUNTIME}" --role=roles/secretmanager.secretAccessor \
      --quiet >/dev/null
done
```

Then add each value. `--data-file=-` so it is piped rather than passed as an
argument — arguments are visible in `ps` and land in shell history, and a secret
should be neither. `read -s` keeps it off the screen too.

```bash
read -rs -p "DATABASE_URL: " V && printf '%s' "$V" \
  | gcloud secrets versions add DATABASE_URL --data-file=- && unset V
```

Repeat for `GEMINI_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
`SEMANTIC_SCHOLAR_API_KEY`, `ADMIN_API_KEY`.

`API_KEY` is optional and currently unset, which leaves the API open
(`auth_enabled: false`). Add it as a secret only if you want to close it — every
caller must then present it, including the frontend via `VITE_NODUS_API_KEY`.

## First deploy

Let the workflow build and deploy the image first — push to `main`, or run it
from the Actions tab. Then apply configuration to the service it created. That
order avoids needing a bootstrap image.

```bash
SECRETS="DATABASE_URL=DATABASE_URL:latest"
for NAME in GEMINI_API_KEY CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_TOKEN \
            SEMANTIC_SCHOLAR_API_KEY API_KEY ADMIN_API_KEY; do
  gcloud secrets describe "$NAME" >/dev/null 2>&1 || continue
  SECRETS="${SECRETS},${NAME}=${NAME}:latest"
done

gcloud run services update "$SERVICE" --region="$REGION" \
    --set-secrets="$SECRETS" \
    --set-env-vars='^@^LLM_PROVIDER=gemini@EMBEDDING_PROVIDER=cloudflare@TRUST_FORWARDED_FOR=true@CORS_ORIGINS=["https://nodus-research.vercel.app"]'
```

`^@^` changes the delimiter to `@`. `CORS_ORIGINS` is a JSON array, so it
contains a comma — which is `--set-env-vars`' own separator. Without the custom
delimiter gcloud splits the array in half and rejects the value. The inner double
quotes matter too: `config.py` parses this with a bare `json.loads`, so
`[https://…]` fails at import and takes every route down with it.

Only four environment variables, because those are the only ones whose deployed
value differs from the `config.py` default. `DATABASE_SSL` (auto),
`GEMINI_RPM_LIMIT` (14), `GEMINI_MAX_CONCURRENCY` (4), `GEMINI_THINKING_LEVEL`
(low), `MAX_ACTIVE_QUERIES` (2), `MAX_CONCURRENT_PAPERS` (10), `DB_POOL_SIZE`
(5), `DB_MAX_OVERFLOW` (5) and `USE_SYSTEM_CA` (true) are already correct from
the code. Setting one anyway would pin it, so a later change to the default
would not reach production and nothing would show the two had diverged.

Then confirm it took, rather than assuming:

```bash
URL=$(gcloud run services describe "$SERVICE" --region="$REGION" \
        --format='value(status.url)')
curl -fsS "$URL/health/config"
```

`embedding_warning` and `db_pool_warning` must both be `null`. They are non-null
exactly when the configuration cannot work, and a run would otherwise fail at
clustering with nothing on screen to explain why.

### Why the runtime flags are what they are

The workflow passes these on every deploy, so they live in version control
rather than in the service's history.

- **`--min-instances=1 --max-instances=1`** — the reason for moving off a
  per-request platform at all. See the header comment in the `Dockerfile`:
  the progress hub, the run gate and the connection pool all keep state in the
  process. Raising `--max-instances` re-introduces every bug this move fixes.
- **`--no-cpu-throttling`** — the pipeline runs as a detached `asyncio` task and
  keeps going after the WebSocket that started it goes away. Under the default,
  CPU is allocated only during a request, so that task freezes the moment the
  socket closes and a run appears to hang forever.
- **`--timeout=3600`** — Cloud Run's maximum, and a per-*request* timeout, which
  for a WebSocket is the socket's lifetime. The old host's 300s cap dropped the
  socket mid-run on nearly every query.
- **`--concurrency=80`** — requests share one instance. A ceiling on
  simultaneous sockets, not on throughput.
- **`MAX_ACTIVE_QUERIES`** — deliberately not set, so the service takes the
  default of 2. It was 10 on the old host, where it was silently per-instance
  and so never really enforced; on one instance, 10 concurrent runs would
  contend for a pool of 10 connections and one Gemini RPM budget.
- **`TRUST_FORWARDED_FOR=true`** — Cloud Run terminates TLS and forwards the
  caller in `X-Forwarded-For`. Rate limits key on the peer address, so without
  this every caller presents as the load balancer and one user's burst throttles
  everyone. The container also runs uvicorn with `--proxy-headers`; the two agree
  rather than conflict, because both take the client-most entry.

## Environment on deploy

The workflow deploys the image and the runtime shape, and never writes
environment variables. `gcloud run deploy` creates a revision inheriting the
service's existing configuration, so anything set above survives every deploy.
That is what makes the ordering rule possible: `Settings()` is constructed at
import, so a variable only new code understands has to be set *after* that code
is live. A workflow that rewrote the env block on every push would make the safe
order impossible.

## Migrations are not automatic

`alembic upgrade head` does not run on container start, on purpose: a failed
migration during a rollout would take the API down with it, and Cloud Run would
retry the container until the quota ran out. Run it yourself before deploying a
revision that needs it:

```bash
uv run --native-tls alembic upgrade head
```

Nothing creates the pgvector extension either — `create extension if not exists
vector;` has to have been run on the database once.

## Frontend

Stays on Vercel; it is a static Vite build, which is what Vercel is good at.
Point it at the new backend and redeploy:

- `VITE_NODUS_WS_URL` = `wss://<cloud-run-url>/api/v2/ws`

`VITE_` variables are baked in at build time, so changing this needs a redeploy,
not just a settings change.

## PowerShell equivalents

Git Bash is the smoother path — the commands above run unchanged. If you are in
PowerShell, these are the parts that differ. The `gcloud` invocations themselves
are identical; only variables, loops and piping change.

Variables. `export` does not exist; `$name = value` does, and `${name}` is the
safe interpolation form inside a string:

```powershell
$PROJECT_ID     = gcloud config get-value project
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$REGION         = "asia-south1"
$REPOSITORY     = "nodus"
$SERVICE        = "nodus-api"
$GITHUB_REPO    = "raunak-shr/nodus-research"
$DEPLOYER       = "nodus-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
$RUNTIME        = "nodus-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
$POOL           = "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github"
$WIF_PROVIDER   = "${POOL}/providers/github"

# Print them before using them. An empty variable does not make gcloud fail; it
# makes gcloud succeed at doing nothing.
$DEPLOYER; $RUNTIME; $POOL
```

Loops use `foreach`, and there is no `&&`:

```powershell
foreach ($ROLE in @("roles/run.admin", "roles/artifactregistry.writer")) {
  gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:${DEPLOYER}" --role=$ROLE
}

foreach ($NAME in @("DATABASE_URL","GEMINI_API_KEY","CLOUDFLARE_ACCOUNT_ID","CLOUDFLARE_API_TOKEN","SEMANTIC_SCHOLAR_API_KEY","ADMIN_API_KEY")) {
  gcloud secrets describe $NAME 2>$null
  if (-not $?) { gcloud secrets create $NAME --replication-policy=automatic }
  gcloud secrets add-iam-policy-binding $NAME --member="serviceAccount:${RUNTIME}" --role=roles/secretmanager.secretAccessor --quiet
}
```

Secret values. There is no `read -s` and no `printf | gcloud`; write to a
temporary file and delete it, so the value is never an argument:

```powershell
$V = Read-Host -AsSecureString "DATABASE_URL"
$P = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($V)
$T = New-TemporaryFile
[System.IO.File]::WriteAllText($T, [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($P))
gcloud secrets versions add DATABASE_URL --data-file=$T
Remove-Item $T -Force
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($P)
```

The env-vars string keeps its single quotes — PowerShell does not expand inside
them, which is what the embedded JSON needs:

```powershell
gcloud run services update $SERVICE --region=$REGION --set-secrets="$SECRETS" --set-env-vars='^@^LLM_PROVIDER=gemini@EMBEDDING_PROVIDER=cloudflare@TRUST_FORWARDED_FOR=true@CORS_ORIGINS=["https://nodus-research.vercel.app"]'
```

`Python was not found; run without arguments to install from the Microsoft
Store` before gcloud output is cosmetic: gcloud's launcher probes the `python`
alias, hits the Windows Store stub, and falls back to its bundled interpreter.
Point `CLOUDSDK_PYTHON` at a real interpreter to silence it — not the project
venv, which does not carry gcloud's dependencies:

```powershell
$env:CLOUDSDK_PYTHON = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
```
