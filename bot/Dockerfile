FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --shell /bin/bash botuser
WORKDIR /app

COPY requirements.txt /app/
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=botuser:botuser . /app/
RUN mkdir -p /app/data && chown botuser:botuser /app/data

USER botuser

CMD ["python", "app.py"]
