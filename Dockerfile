FROM python:3.12-slim

WORKDIR /app

# Copy package metadata and source, then install. partners/README.md is bundled into the wheel
# (served by /imnot/docs/partners); it is removed afterwards so /app/partners starts empty.
COPY pyproject.toml README.md ./
COPY partners/README.md partners/README.md
COPY imnot/ imnot/
RUN pip install --no-cache-dir . && rm -rf partners

# Partners and data directories are expected to be volume-mounted at runtime.
# Create them so the container starts cleanly even without mounts.
RUN mkdir -p /app/partners /app/data && \
    addgroup --system imnot && \
    adduser --system --ingroup imnot imnot && \
    chown -R imnot:imnot /app/partners /app/data

USER imnot

EXPOSE 8000

# IMNOT_ADMIN_KEY is read automatically by the --admin-key option via envvar.
# Set it in docker-compose.yml or pass -e IMNOT_ADMIN_KEY=<secret> at runtime.
ENTRYPOINT ["imnot", "start", "--host", "0.0.0.0", "--db", "/app/data/imnot.db", "--partners-dir", "/app/partners"]
