# tests/02_surveys.ps1
# Блок 2: Тесты создания опросов, голосования и защиты от накрутки

Write-Host "=== BLOCK 2: SURVEY LIFECYCLE & VOTING ===" -ForegroundColor Cyan
$base = "http://localhost:8080"
$ok = 0
$fail = 0

# --- Подготовка: Вход сотрудника ---
# Создаем сессию и логинимся под staff (пароль "0")
$staffSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"staff","password":"0"}' -WebSession $staffSession | Out-Null

# --- Тест 2.1: Создание опроса ---
Write-Host "`n[Test 2.1] Staff creates a survey..." -ForegroundColor Yellow
# Отправляем только subject_id, teacher_id и даты. Статус и владельца сервер ставит сам.
$createBody = '{"subject_id":1,"teacher_id":1,"period_start":"2026-01-01","period_end":"2026-06-01"}'
$newSurvey = Invoke-RestMethod -Uri "$base/api/v1/surveys" -Method Post -ContentType "application/json" -Body $createBody -WebSession $staffSession
$surveyId = $newSurvey.id  # Запоминаем ID созданного опроса для следующих тестов

# Проверяем, что сервер по умолчанию сделал его черновиком (draft)
if ($newSurvey.status -eq "draft") {
    Write-Host "OK: Survey created with status 'draft' (ID: $surveyId)" -ForegroundColor Green
    $ok++
} else {
    Write-Host "FAIL: Status is not draft" -ForegroundColor Red
    $fail++
}

# --- Тест 2.2: Создание опроса с неверными датами ---
Write-Host "`n[Test 2.2] Create survey with invalid dates (end < start)..." -ForegroundColor Yellow
# Пытаемся закрыть опрос до его начала
$badBody = '{"subject_id":1,"teacher_id":1,"period_start":"2026-06-01","period_end":"2026-01-01"}'
try {
    Invoke-RestMethod -Uri "$base/api/v1/surveys" -Method Post -ContentType "application/json" -Body $badBody -WebSession $staffSession | Out-Null
    Write-Host "FAIL: Server accepted invalid dates!" -ForegroundColor Red
    $fail++
} catch {
    # Если даты некорректны, сервер должен вернуть 400 (Bad Request)
    if ($_.Exception.Response.StatusCode.value__ -eq 400) {
        Write-Host "OK: Got 400 Bad Request" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 400, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Тест 2.3: Публикация опроса ---
Write-Host "`n[Test 2.3] Publish survey (draft -> active)..." -ForegroundColor Yellow
$publishBody = '{"status":"active"}'
$published = Invoke-RestMethod -Uri "$base/api/v1/surveys/$surveyId/status" -Method Patch -ContentType "application/json" -Body $publishBody -WebSession $staffSession
if ($published.status -eq "active") {
    Write-Host "OK: Survey published" -ForegroundColor Green
    $ok++
} else {
    Write-Host "FAIL: Status is not active" -ForegroundColor Red
    $fail++
}

# --- Подготовка: Вход студента ---
$studentSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"student1","password":"1"}' -WebSession $studentSession | Out-Null

# --- Тест 2.4: Попытка голосования с недопустимой оценкой ---
Write-Host "`n[Test 2.4] Vote with invalid rating (6)..." -ForegroundColor Yellow
# Оценки должны быть от 2 до 5. Отправляем 6.
$badVote = '{"rating_materials":6,"rating_clarity":4,"rating_engagement":4}'
try {
    Invoke-RestMethod -Uri "$base/api/v1/surveys/$surveyId/responses" -Method Post -ContentType "application/json" -Body $badVote -WebSession $studentSession | Out-Null
    Write-Host "FAIL: Server accepted rating 6!" -ForegroundColor Red
    $fail++
} catch {
    # Pydantic на сервере должен заблокировать это и вернуть 400
    if ($_.Exception.Response.StatusCode.value__ -eq 400) {
        Write-Host "OK: Got 400 (Pydantic validation)" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 400, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Тест 2.5: Успешное голосование ---
Write-Host "`n[Test 2.5] Successful vote (5, 4, 5)..." -ForegroundColor Yellow
$goodVote = '{"rating_materials":5,"rating_clarity":4,"rating_engagement":5}'
try {
    Invoke-RestMethod -Uri "$base/api/v1/surveys/$surveyId/responses" -Method Post -ContentType "application/json" -Body $goodVote -WebSession $studentSession | Out-Null
    Write-Host "OK: Vote accepted" -ForegroundColor Green
    $ok++
} catch {
    Write-Host "FAIL: Vote rejected. $($_.Exception.Message)" -ForegroundColor Red
    $fail++
}

# --- Тест 2.6: Защита от накрутки (повторное голосование) ---
Write-Host "`n[Test 2.6] Double voting (expect 409)..." -ForegroundColor Yellow
# Тот же студент пытается проголосовать еще раз в тот же опрос
try {
    Invoke-RestMethod -Uri "$base/api/v1/surveys/$surveyId/responses" -Method Post -ContentType "application/json" -Body $goodVote -WebSession $studentSession | Out-Null
    Write-Host "FAIL: Student voted twice!" -ForegroundColor Red
    $fail++
} catch {
    # В БД стоит UNIQUE (user_id, survey_id), поэтому сервер должен вернуть 409 (Conflict)
    if ($_.Exception.Response.StatusCode.value__ -eq 409) {
        Write-Host "OK: Got 409 Conflict (anti-cheat)" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 409, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Тест 2.7: Запрос результатов для активного опроса ---
Write-Host "`n[Test 2.7] Request results while survey is active (expect 409)..." -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "$base/api/v1/surveys/$surveyId/results" -Method Get -WebSession $staffSession | Out-Null
    Write-Host "FAIL: Server returned results for active survey!" -ForegroundColor Red
    $fail++
} catch {
    # Результаты можно смотреть только после закрытия опроса (иначе 409)
    if ($_.Exception.Response.StatusCode.value__ -eq 409) {
        Write-Host "OK: Got 409 (survey not closed)" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 409, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Тест 2.8: Закрытие опроса ---
Write-Host "`n[Test 2.8] Close survey (active -> closed)..." -ForegroundColor Yellow
$closeBody = '{"status":"closed"}'
$closed = Invoke-RestMethod -Uri "$base/api/v1/surveys/$surveyId/status" -Method Patch -ContentType "application/json" -Body $closeBody -WebSession $staffSession
if ($closed.status -eq "closed") {
    Write-Host "OK: Survey closed" -ForegroundColor Green
    $ok++
} else {
    Write-Host "FAIL: Status is not closed" -ForegroundColor Red
    $fail++
}

# --- Тест 2.9: Защита от деанонимизации (мало голосов) ---
Write-Host "`n[Test 2.9] Request results on closed survey with < 5 votes (expect 409)..." -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "$base/api/v1/surveys/$surveyId/results" -Method Get -WebSession $staffSession | Out-Null
    Write-Host "FAIL: Server returned results with < 5 votes!" -ForegroundColor Red
    $fail++
} catch {
    # Так как мы создали новый опрос и проголосовали только 1 раз, ответов < 5.
    # Сервер обязан скрыть результаты (код 409).
    if ($_.Exception.Response.StatusCode.value__ -eq 409) {
        Write-Host "OK: Got 409 (de-anonymization protection)" -ForegroundColor Green
        $ok++
    } else {
        Write-Host "FAIL: Expected 409, got $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        $fail++
    }
}

# --- Итоговый результат ---
Write-Host "`n=== BLOCK 2 RESULT ===" -ForegroundColor Cyan
Write-Host "Passed: $ok | Failed: $fail" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
if ($fail -eq 0) { Write-Host "SUCCESS: BLOCK 2 PASSED" -ForegroundColor Green } else { Write-Host "ERROR: BLOCK 2 FAILED" -ForegroundColor Red }