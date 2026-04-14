FROM python:3.12-slim

WORKDIR /app

# Copy package metadata and source, then install
COPY pyproject.toml README.md ./
COPY imnot/ imnot/
RUN pip install --no-cache-dir .

# Partners and data directories are expected to be volume-mounted at runtime.
# Create them so the container starts cleanly even without mounts.
RUN mkdir -p /app/partners /app/data

EXPOSE 8000

# IMNOT_ADMIN_KEY is read automatically by the --admin-key option via envvar.
# Set it in docker-compose.yml or pass -e IMNOT_ADMIN_KEY=<secret> at runtime.
ENTRYPOINT ["imnot", "start", "--host", "0.0.0.0", "--db", "/app/data/imnot.db", "--partners-dir", "/app/partners"]
