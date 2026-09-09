# Pinned to match the playwright version in requirements.txt - this image
# already bundles the exact matching OS deps for headless Chromium, which
# `playwright install --with-deps` on a plain python:slim base cannot
# reliably resolve across Debian releases.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

COPY . .

EXPOSE 8765

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765"]
