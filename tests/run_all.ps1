# tests/run_all.ps1
# Запуск всех тестов одной командой

Write-Host "=========================================" -ForegroundColor Magenta
Write-Host "   STARTING FULL E2E TEST SUITE" -ForegroundColor Magenta
Write-Host "=========================================" -ForegroundColor Magenta

# Запускаем каждый скрипт в его собственном процессе
& "$PSScriptRoot\01_auth.ps1"
& "$PSScriptRoot\02_surveys.ps1"
& "$PSScriptRoot\03_security.ps1"

Write-Host "`n=========================================" -ForegroundColor Magenta
Write-Host "   ALL TESTS FINISHED" -ForegroundColor Magenta
Write-Host "=========================================" -ForegroundColor Magenta