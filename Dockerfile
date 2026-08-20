# Nodus API — one long-lived container, for Cloud Run or any container host.
#
# Why a container at all: this application keeps state in memory on purpose.
# `app/core/events.py` is an in-process progress hub, `app/services/limits.py`
# is an in-process run gate and rate limiter, and `app/db/session.py` sizes its
# pool against the *provider's* client cap on the assumption that one process
# holds one pool. A platform that answers each request from a fresh instance
# breaks all three at once: progress events published by one instance are
# invisible to a client attached to another, MAX_ACTIVE_QUERIES becomes a
# per-instance number, and N instances × (DB_POOL_SIZE + DB_MAX_OVERFLOW)
# walks past Supavisor's 15-client ceiling and answers EMAXCONNSESSION.
#
# So: one image, one process, one worker. Scaling past that means doing the
# Redis-pub/sub-plus-event-table work `events.py` already names as the path,
# not raising the instance count.
#
# Chromium is baked in. PDF export renders the report in headless Chromium, and
# the browser is a separate ~150MB download from the `playwright` package — a
# host that installs Python dependencies but never runs `playwright install`
# leaves `report.pdf` failing with `unavailable` forever.

# ---------------------------------------------------------------- builder
# Dependencies resolve into a standalone venv here so the runtime stage carries
# no build tooling and no uv cache.
FROM python:3.12-slim AS builder

# UV_PROJECT_ENVIRONMENT puts the venv at the path it will occupy in the
# runtime stage. A venv is not relocatable: every console script it generates
# (`uvicorn`, `playwright`, `alembic`) carries an absolute shebang, so building
# at /build/.venv and copying to /opt/venv leaves each of them pointing at an
# interpreter that does not exist there — which `sh` reports as
# "playwright: not found", naming the script rather than the missing shebang
# target and sending you looking in the wrong place entirely.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN pip install --no-cache-dir uv

WORKDIR /build

# Only the lockfile inputs, so this layer survives every change to app/.
COPY pyproject.toml uv.lock ./

# --no-install-project: nothing imports `nodus` as a package. The app runs as
# `uvicorn app.main:app` with /app on the path, so installing the project would
# only invoke hatchling for no gain — and would drag app/ into this layer and
# invalidate the dependency cache on every source edit.
RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

# A fixed, world-readable browser path. Playwright's default is under $HOME,
# which differs between the root user that installs and the unprivileged user
# that runs — the symptom is the "Executable doesn't exist" launch failure,
# from a browser that is present but not where the running user looks.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8080

COPY --from=builder /opt/venv /opt/venv

# --with-deps pulls the OS libraries Chromium needs (fonts, X, nss, …) via
# Playwright's own dependency list rather than a hand-maintained apt list that
# drifts with every Playwright release. Must run as root, and before the user
# switch below.
RUN playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/* /root/.cache

WORKDIR /app
COPY app ./app
COPY alembic.ini ./
COPY README.md ./

# Unprivileged, and no writable application directory. Chromium is launched
# with --no-sandbox (see app/services/pdf_export.py), which is what makes a
# non-root browser workable without granting SYS_ADMIN.
RUN useradd --create-home --uid 10001 nodus && chown -R nodus:nodus /app
USER nodus

EXPOSE 8080

# For `docker compose up` and any orchestrator that reads it. Cloud Run ignores
# this and uses its own startup probe against the same endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health').read()"

# Three things this command is careful about:
#
#   --workers 1      The in-memory hub and run gate are not shared between
#                    workers. A second worker does not double capacity, it
#                    splits the run registry in half.
#   --proxy-headers  The rate limiter keys on the peer address
#                    (`websocket.client.host` in app/api/v2/session.py). Behind
#                    a load balancer every caller presents as the balancer, so
#                    without this one user's burst throttles everyone.
#   exec             So uvicorn is PID 1's direct successor and receives
#                    SIGTERM on shutdown instead of the shell swallowing it.
#
# ${PORT} rather than a literal, because Cloud Run assigns it.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
