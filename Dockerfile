# Nova Shop bot — production image.
# Python 3.12 matches the development toolchain; aiogram is pinned in
# bot/requirements.txt (2.25.2, which requires aiohttp 3.8.x).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first for layer caching.
COPY bot/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY bot/ ./

# The SQLite database lives on a volume so it survives image rebuilds.
VOLUME ["/app/data"]

CMD ["python", "app.py"]
