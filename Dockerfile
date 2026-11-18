FROM python:3.12-slim

WORKDIR /app

# Copy package metadata and source, then install. partners/README.md is bundled into the wheel
# (served by /imnot/docs/partners); it is removed afterwards so /app/partners starts empty.
COPY pyproject.toml README.md ./
COPY partners/README.md partners/README.md
COPY imnot/ imnot/
RUN pip install --no-cache-dir . && rm -rf partners

# Partners and data directories are expected to be volume-mounted at runtime (or, with
# IMNOT_STATELESS=1, partners are baked into a derived image and nothing is written at all).
# Create them so the container starts cleanly even without mounts.
# The uid is fixed and numeric so that `runAsNonRoot` can verify it and volumes can be chown-ed to it.
RUN mkdir -p /app/partners /app/data && \
    addgroup --system --gid 10001 imnot && \
    adduser --system --uid 10001 --ingroup imnot imnot && \
    chown -R 10001:10001 /app/partners /app/data

USER 10001:10001

EXPOSE 8000

# Defaults as environment variables, so a derived image or the runtime can override each one
# (docker run -e IMNOT_STATELESS=1 …). Command-line flags still win: `docker run <image> --port 9000`.
# IMNOT_ADMIN_KEY is read the same way: set it in docker-compose.yml or pass -e IMNOT_ADMIN_KEY=<secret>.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IMNOT_BIND_HOST=0.0.0.0 \
    IMNOT_DB_PATH=/app/data/imnot.db \
    IMNOT_PARTNERS_DIR=/app/partners

ENTRYPOINT ["imnot", "start"]
