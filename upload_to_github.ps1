# Скрипт для загрузки проекта на GitHub
# Выполните этот скрипт в PowerShell после перезапуска терминала

Write-Host "Инициализация Git репозитория..." -ForegroundColor Green
git init

Write-Host "`nДобавление файлов..." -ForegroundColor Green
git add .

Write-Host "`nСоздание первого коммита..." -ForegroundColor Green
git commit -m "Initial commit: Telegram bot for TON channel"

Write-Host "`nДобавление удаленного репозитория..." -ForegroundColor Green
git remote add origin https://github.com/arar228/neyrobot.git

Write-Host "`nПереименование ветки в main..." -ForegroundColor Green
git branch -M main

Write-Host "`nЗагрузка проекта на GitHub..." -ForegroundColor Green
Write-Host "Введите ваш GitHub username и пароль (или Personal Access Token)" -ForegroundColor Yellow
git push -u origin main

Write-Host "`nГотово! Проект загружен на GitHub." -ForegroundColor Green

