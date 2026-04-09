FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (separate layer for better cache reuse)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy source
COPY mirage/ mirage/

# Partners and data directories are expected to be volume-mounted at runtime.
# Create them so the container starts cleanly even without mounts.
RUN mkdir -p /app/partners /app/data

EXPOSE 8000

ENTRYPOINT ["mirage", "start", "--host", "0.0.0.0", "--db", "/app/data/mirage.db", "--partners-dir", "/app/partners"]
