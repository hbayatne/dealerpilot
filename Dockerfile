# One image that runs the same way on Railway, Render, Fly or a plain VM.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code change doesn't reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY chaos ./chaos
COPY run.sh Procfile README.md ./

# Where SQLite lives when no DATABASE_URL is set. Mount a volume here, or the
# lot and the mailbox history vanish on the next deploy.
ENV CHAOS_DB=/data/chaos.db
RUN mkdir -p /data

# The platform tells us the port; 8000 is only the local default.
ENV PORT=8000
EXPOSE 8000

# Not a JSON-array CMD: $PORT has to be expanded by a shell at start time.
CMD exec python3 -m uvicorn chaos.app:app --host 0.0.0.0 --port ${PORT}
