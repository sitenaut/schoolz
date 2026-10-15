# Build stage: anything that compiles does it here, so the runtime image
# carries no compiler. Base images are pinned by version and digest;
# Dependabot proposes the bumps.
FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH=/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PATH=/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The app never writes inside its own tree, so it runs as a user that can't.
# `fly ssh console` still lands as root for one-off scripts.
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin app

COPY --from=build /venv /venv
WORKDIR /app
COPY . .

USER app
EXPOSE 8000

# One image runs both the API and the scheduler; only the API answers HTTP,
# so this check is for the API container. On Fly the checks in fly.toml are
# what count; Docker's HEALTHCHECK is for the local stack.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
