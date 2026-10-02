<#
.SYNOPSIS
    Self-verification script for schoolz local development stack.
.DESCRIPTION
    Verifies that the local Docker stack is healthy, tests live API auth/registration,
    runs backend pytest inside the Docker container, and runs frontend vitest in WSL.
.PARAMETER Target
    all      - Run health checks, live auth test, backend unit tests, and frontend tests (default).
    health   - Only verify container and HTTP endpoint availability.
    auth     - Test live registration, login, profile fetch, and account cleanup against http://localhost:8000.
    backend  - Run backend pytest in the schoolz-api-local container.
    frontend - Run frontend vitest in WSL.
.EXAMPLE
    .\scripts\verify-local.ps1
    .\scripts\verify-local.ps1 -Target auth
    .\scripts\verify-local.ps1 -Target backend -TestPath "tests/test_account.py"
#>
param (
    [ValidateSet("all", "health", "auth", "backend", "frontend")]
    [string]$Target = "all",

    [string]$TestPath = ""
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host "`n=== $msg ===" -ForegroundColor Cyan
}

function Write-Success([string]$msg) {
    Write-Host "[PASS] $msg" -ForegroundColor Green
}

function Write-Failure([string]$msg) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
}

function Test-HealthChecks {
    Write-Step "Checking Running Local Stack Endpoints"
    
    # 1. Backend API
    try {
        $backend = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5
        if ($backend.status -eq "ok") {
            Write-Success "Backend API healthy (http://localhost:8000/health, mode: $($backend.auth_mode))"
        } else {
            Write-Failure "Backend returned non-ok status: $($backend.status)"
        }
    } catch {
        Write-Failure "Backend unreachable on http://localhost:8000/health - is schoolz-api-local container running?"
    }

    # 2. Frontend Web
    try {
        $frontend = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 5
        if ($frontend.StatusCode -eq 200) {
            Write-Success "Frontend Web healthy (http://localhost:5173, status: 200)"
        } else {
            Write-Failure "Frontend returned status: $($frontend.StatusCode)"
        }
    } catch {
        Write-Failure "Frontend unreachable on http://localhost:5173 - is schoolz-web-local container running?"
    }

    # 3. Scraper
    try {
        $scraper = Invoke-RestMethod -Uri "http://localhost:8765/health" -TimeoutSec 5
        if ($scraper.status -eq "ok") {
            Write-Success "Scraper healthy (http://localhost:8765/health)"
        } else {
            Write-Failure "Scraper returned non-ok status"
        }
    } catch {
        Write-Failure "Scraper unreachable on http://localhost:8765/health"
    }
}

function Test-LiveAuthFlow {
    Write-Step "Testing Live Registration & Auth Flows (http://localhost:8000)"

    $tag = [System.Guid]::NewGuid().ToString().Substring(0, 8)
    $email = "verify_$tag@example.com"
    $username = "verify_$tag"
    $password = "VerifyPass123!"

    try {
        # 1. Register
        $regBody = @{ email = $email; username = $username; password = $password } | ConvertTo-Json
        $reg = Invoke-RestMethod -Uri "http://localhost:8000/auth/register" -Method Post -Body $regBody -ContentType "application/json"
        if (-not $reg.access_token) { throw "No access token in registration response" }
        Write-Success "POST /auth/register: User created ($username)"
        $token = $reg.access_token

        # 2. Get /auth/me with bearer token
        $me = Invoke-RestMethod -Uri "http://localhost:8000/auth/me" -Headers @{ Authorization = "Bearer $token" }
        if ($me.email -ne $email -or $me.username -ne $username) {
            throw "Profile mismatch in /auth/me"
        }
        Write-Success "GET /auth/me: Verified user profile ($($me.id))"

        # 3. Login with credentials
        $loginBody = @{ username_or_email = $email; password = $password } | ConvertTo-Json
        $login = Invoke-RestMethod -Uri "http://localhost:8000/auth/login" -Method Post -Body $loginBody -ContentType "application/json"
        if (-not $login.access_token) { throw "No access token in login response" }
        Write-Success "POST /auth/login: Verified credential exchange"

        # 4. Clean up user via DELETE /auth/me
        $delBody = @{ confirm = "DELETE"; password = $password } | ConvertTo-Json
        Invoke-RestMethod -Uri "http://localhost:8000/auth/me" -Method Delete -Body $delBody -ContentType "application/json" -Headers @{ Authorization = "Bearer $token" }
        Write-Success "DELETE /auth/me: Test account cleanly removed"

    } catch {
        Write-Failure "Auth flow failed: $_"
        throw
    }
}

function Test-BackendPytest {
    Write-Step "Running Backend Unit Tests (Docker container: schoolz-api-local)"
    $cmd = "pytest -q"
    if ($TestPath) {
        $cmd += " $TestPath"
    } else {
        $cmd += " tests/test_account.py tests/test_students.py"
    }

    wsl -e bash -c "docker exec schoolz-api-local $cmd"
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Backend tests passed"
    } else {
        Write-Failure "Backend tests failed with exit code $LASTEXITCODE"
    }
}

function Test-FrontendVitest {
    Write-Step "Running Frontend Vitest (via WSL)"
    $cmd = "cd /mnt/c/Users/ellio/OneDrive/Documents/claude/code/schoolz/frontend && npx vitest run"
    if ($TestPath) {
        $cmd += " $TestPath"
    } else {
        $cmd += " src/pages/LoginPage.test.ts src/authConfig.test.ts src/lib/pendingInvite.test.ts"
    }

    wsl -e bash -c "$cmd"
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Frontend tests passed"
    } else {
        Write-Failure "Frontend tests failed with exit code $LASTEXITCODE"
    }
}

switch ($Target) {
    "health" {
        Test-HealthChecks
    }
    "auth" {
        Test-LiveAuthFlow
    }
    "backend" {
        Test-BackendPytest
    }
    "frontend" {
        Test-FrontendVitest
    }
    "all" {
        Test-HealthChecks
        Test-LiveAuthFlow
        Test-BackendPytest
        Test-FrontendVitest
        Write-Host "`nAll verification checks completed successfully!`n" -ForegroundColor Green
    }
}
