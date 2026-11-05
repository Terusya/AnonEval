# tests/03_security.ps1
# Блок 3: Тесты безопасности (BOLA, Mass Assignment, RBAC)

Write-Host "=== BLOCK 3: SECURITY TESTS ===" -ForegroundColor Cyan
$base = "http://localhost:8080"
$ok = 0
$fail = 0

# --- Подготовка: Вход всех ролей ---
# Нам нужно три независимые сессии, чтобы имитировать разных людей
$student1Session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"student1","password":"1"}' -WebSession $student1Session | Out-Null

$student2Session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"student2","password":"2"}' -WebSession $student2Session | Out-Null

$staffSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"staff","password":"0"}' -WebSession $staffSession | Out-Null


# --- Тест 3.1: BOLA (IDOR) ---
# Ситуация: Студент 2 пытается прочитать опрос Студента 1 (ID = 1)
Write-Host "`n[Test 3.1] BOLA: Student2 tries to read Student1's survey..." -ForegroundColor Yellow
try {
    # Если сервер ответит 200 OK, значит любой студент может читать чужие данные
    Invoke-RestMethod -Uri "$base/api/v1/surveys/1" -Method Get -WebSession $student2Session | Out-Null
    Write-Host "FAIL: Student2 read someone else's survey!" -ForegroundColor Red
    $fail++
} catch {
    # Наш код проверяет таблицу enrollments и должен вернуть 403
    if ($_.Exception.Response.StatusCode.value__ -eq 403) {
        Write-Host "OK: Got 403 Forbidden (not enrolled)" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 403, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Тест 3.2: Mass Assignment (Лишние поля) ---
# Ситуация: Сотрудник создает опрос и тайком подкидывает поля status="closed" и created_by=999
Write-Host "`n[Test 3.2] Mass Assignment: Staff tries to inject 'status' and 'created_by'..." -ForegroundColor Yellow
$maliciousBody = '{"subject_id":1,"teacher_id":1,"period_start":"2027-01-01","period_end":"2027-06-01","status":"closed","created_by":999}'
try {
    $created = Invoke-RestMethod -Uri "$base/api/v1/surveys" -Method Post -ContentType "application/json" -Body $maliciousBody -WebSession $staffSession
    # Проверяем, что сервер проигнорировал status="closed" и создал draft
    if ($created.status -eq "draft") {
        Write-Host "OK: Server ignored injected fields, status is 'draft'" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Injected status was applied! Status is $($created.status)" -ForegroundColor Red
        $fail++
    }
} catch {
    Write-Host "FAIL: Request failed. $($_.Exception.Message)" -ForegroundColor Red
    $fail++
}

# --- Тест 3.3: RBAC (Разграничение ролей) ---
# Ситуация: Студент пытается вызвать админский эндпоинт (результаты)
Write-Host "`n[Test 3.3] RBAC: Student1 tries to access admin results endpoint..." -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "$base/api/v1/surveys/1/results" -Method Get -WebSession $student1Session | Out-Null
    Write-Host "FAIL: Student accessed admin endpoint!" -ForegroundColor Red
    $fail++
} catch {
    # Эндпоинт закрыт функцией require_staff, должен вернуть 403
    if ($_.Exception.Response.StatusCode.value__ -eq 403) {
        Write-Host "OK: Got 403 Forbidden (insufficient role)" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 403, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Итоговый результат ---
Write-Host "`n=== BLOCK 3 RESULT ===" -ForegroundColor Cyan
Write-Host "Passed: $ok | Failed: $fail" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
if ($fail -eq 0) { Write-Host "SUCCESS: BLOCK 3 PASSED" -ForegroundColor Green } else { Write-Host "ERROR: BLOCK 3 FAILED" -ForegroundColor Red }