# tests/01_auth.ps1
# Блок 1: Тесты аутентификации и сессий

Write-Host "=== BLOCK 1: AUTH AND SESSIONS ===" -ForegroundColor Cyan
$base = "http://localhost:8080"
$ok = 0      # Счетчик успешных тестов
$fail = 0    # Счетчик проваленных тестов

# --- Тест 1.1: Попытка входа с неверным паролем ---
Write-Host "`n[Test 1.1] Login with wrong password..." -ForegroundColor Yellow
try {
    # Отправляем запрос. Если сервер ответит 200 OK, значит защита сломана.
    Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"student1","password":"wrong"}' | Out-Null
    Write-Host "FAIL: Server allowed wrong password!" -ForegroundColor Red
    $fail++
} catch {
    # Если сервер выдал ошибку, проверяем, что это именно 401 (Unauthorized)
    if ($_.Exception.Response.StatusCode.value__ -eq 401) {
        Write-Host "OK: Got 401 Unauthorized" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 401, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Тест 1.2: Успешный вход ---
Write-Host "`n[Test 1.2] Login with correct password (student1)..." -ForegroundColor Yellow
# Создаем объект "сессии", чтобы браузер (в нашем случае терминал) сохранил Cookie
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
    $loginResponse = Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"student1","password":"1"}' -WebSession $session
    if ($loginResponse.role -eq "student") {
        Write-Host "OK: Login successful, role = student" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Role is not student" -ForegroundColor Red
        $fail++
    }
} catch {
    Write-Host "FAIL: Login failed. $($_.Exception.Message)" -ForegroundColor Red
    $fail++
}

# --- Тест 1.3: Проверка сессии (GET /auth/me) ---
Write-Host "`n[Test 1.3] GET /auth/me with Cookie..." -ForegroundColor Yellow
try {
    # Передаем $session, чтобы PowerShell автоматически прикрепил Cookie к запросу
    $meResponse = Invoke-RestMethod -Uri "$base/api/v1/auth/me" -Method Get -WebSession $session
    if ($meResponse.username -eq "student1") {
        Write-Host "OK: Server returned correct user" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Wrong user returned" -ForegroundColor Red
        $fail++
    }
} catch {
    Write-Host "FAIL: Session does not work" -ForegroundColor Red
    $fail++
}

# --- Тест 1.4: Выход из системы (Logout) ---
Write-Host "`n[Test 1.4] Logout..." -ForegroundColor Yellow
try {
    $logoutResponse = Invoke-WebRequest -Uri "$base/api/v1/auth/logout" -Method Post -WebSession $session
    if ($logoutResponse.StatusCode -eq 204) {
        Write-Host "OK: Got 204 No Content" -ForegroundColor Green
        $ok++
    }
} catch {
    Write-Host "FAIL: Error on logout" -ForegroundColor Red
    $fail++
}

# --- Тест 1.5: Проверка, что сессия убита ---
Write-Host "`n[Test 1.5] Try to use Cookie after logout..." -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "$base/api/v1/auth/me" -Method Get -WebSession $session | Out-Null
    Write-Host "FAIL: Session still works after logout!" -ForegroundColor Red
    $fail++
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 401) {
        Write-Host "OK: Got 401, session killed" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Unexpected code $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Итоговый результат ---
Write-Host "`n=== BLOCK 1 RESULT ===" -ForegroundColor Cyan
Write-Host "Passed: $ok | Failed: $fail" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
if ($fail -eq 0) { Write-Host "SUCCESS: BLOCK 1 PASSED" -ForegroundColor Green } else { Write-Host "ERROR: BLOCK 1 FAILED" -ForegroundColor Red }