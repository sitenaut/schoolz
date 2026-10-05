---
name: verify
description: Run automated health, auth, backend, and frontend verification against the local schoolz development stack. Use when testing changes, verifying registration/login flows, or running regression tests.
user-invocable: true
---

# Verifying the schoolz local stack

The local development stack runs in Docker (`schoolz-api-local`, `schoolz-web-local`, `schoolz-postgres-local`, `schoolz-scraper-1`).

## 1. Quick Verification Commands

From PowerShell on Windows:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-local.ps1
```

From bash/WSL:
```bash
./scripts/verify-local.sh
```

## 2. Targeted Verification

- **Endpoint Health Only:**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\verify-local.ps1 -Target health
  ```
- **Live Auth / Registration Flow Test:**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\verify-local.ps1 -Target auth
  ```
- **Backend Unit Tests (Docker):**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\verify-local.ps1 -Target backend
  # Or directly:
  wsl -e bash -c "docker exec schoolz-api-local pytest -q tests/test_account.py"
  ```
- **Frontend Vitest (WSL):**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\verify-local.ps1 -Target frontend
  # Or directly, from the repo root (wsl inherits the current directory):
  wsl -e bash -c "cd frontend && npx vitest run"
  ```

## 3. Running Services Reference

- **Backend API:** `http://localhost:8000` (Docker container `schoolz-api-local`)
- **Frontend App:** `http://localhost:5173` (Docker container `schoolz-web-local`)
- **Scraper:** `http://localhost:8765` (Docker container `schoolz-scraper-1`)
- **Postgres:** `localhost:5432` (`postgres:postgres`, DB `schoolz`)
