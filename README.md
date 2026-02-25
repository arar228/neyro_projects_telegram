# 🤖 Neyro Telegram Crypto Bot (TON Ecosystem)

[![EN](https://img.shields.io/badge/Language-EN-green.svg)](#english)
[![RU](https://img.shields.io/badge/Language-RU-blue.svg)](#по-русски)

<a name="english"></a>
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Telegram API](https://img.shields.io/badge/Telegram-API-blue.svg)
![DeepSeek API](https://img.shields.io/badge/DeepSeek-AI-green.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**Neyro Telegram Crypto Bot** is an autonomous AI-powered Telegram bot (using DeepSeek API) designed to manage a cryptocurrency channel. The bot specializes in the TON ecosystem and automatically generates unique, engaging content in a predefined authorial tone of voice.

This project demonstrates the integration of LLMs (Large Language Models) with messengers, asynchronous data parsing, and automated posting. It is an excellent example of content automation for Web3 and crypto communities.

## 🚀 Key Features

- **AI Content Generation:** Uses DeepSeek API to create unique posts with a specific personality and tone of voice.
- **Asynchronous Parsing (Telethon):** Automatically monitors other Telegram channels (e.g., @markettwits) to gather fresh news.
- **Smart Filtering:** Finds relevant news using keywords (cryptocurrencies, fiat, metals, memes, etc.).
- **CoinGecko Integration:** Regularly fetches TON prices and automatically publishes market overviews (morning and evening).
- **Flexible Scheduling System:** Publishes posts at specified (including randomized) intervals to simulate real human behavior.

## 🛠 Tech Stack

- **Programming Language:** Python 3.8+
- **Frameworks & Libraries:**
  - `python-telegram-bot` — Interaction with Telegram Bot API
  - `Telethon` — Asynchronous parsing of Telegram channels
  - `openai` — Interaction with DeepSeek API
  - `requests` — REST API requests (CoinGecko)
- **Infrastructure / Deployment:** Ready for deployment on Railway (Nixpacks) and Heroku (`Procfile`).

## 🗂 Project Architecture

- `bot.py` — The main module containing the bot's business logic, message handlers, and task scheduler.
- `config.py` — Configuration module (environment variables, system prompts, keyword lists).
- `bot_nanobanana_fix.py` — Auxiliary module for integrating third-party media generation APIs.
- `railway.json` / `Procfile` / `DEPLOY.md` — Files for CI/CD setup and cloud platform deployment.

## ⚙️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/arar228/neyro_projects_telegram.git
   cd neyro_projects_telegram
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   The project uses `python-dotenv`. Create a `.env` file in the project root and add your keys:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token
   DEEPSEEK_API_KEY=your_deepseek_key
   CHANNEL_ID=your_channel_id
   TELEGRAM_API_ID=your_api_id
   TELEGRAM_API_HASH=your_api_hash
   ```

4. **Run the bot:**
   ```bash
   python bot.py
   ```

## 🔐 Security

All secret keys, tokens, and private configurations are excluded from the repository using `.gitignore`. This guarantees no leaks of sensitive data. It is highly recommended to use Environment Variables when deploying to a server (Railway, Heroku, VPS).

## 📝 License

This project is licensed under the MIT License. Open source usage is permitted.

---
*Developed and designed as part of a professional portfolio.*

---
<br>

<a name="по-русски"></a>
# 🇷🇺 Описание на русском (Russian Description)

**Neyro Telegram Crypto Bot** — это автономный Telegram-бот на базе искусственного интеллекта (DeepSeek API), предназначенный для ведения криптовалютного канала. Бот специализируется на экосистеме TON и автоматически генерирует уникальный, вовлекающий контент в заданном авторском стиле.

Проект демонстрирует интеграцию LLM (Large Language Models) с мессенджерами, асинхронный парсинг данных и автоматизированный постинг. Отличный пример автоматизации контента для Web3 и крипто-сообществ.

## 🚀 Ключевые особенности

- **AI-Генерация контента:** Использование DeepSeek API для создания уникальных постов с заданным tone of voice (характером).
- **Асинхронный парсинг (Telethon):** Автоматический мониторинг других Telegram-каналов (например, @markettwits) для сбора свежих новостей.
- **Интеллектуальная фильтрация:** Поиск релевантных новостей по ключевым словам (криптовалюты, фиат, металлы, мемы и т.д.).
- **Интеграция с CoinGecko:** Регулярное получение курса TON и автоматическая публикация обзоров рынка (утром и вечером).
- **Гибкая система планирования:** Публикация постов с заданными (в том числе рандомизированными) интервалами для имитации поведения реального человека.

## 🛠 Технологический стек

- **Язык программирования:** Python 3.8+
- **Фреймворки и библиотеки:**
  - `python-telegram-bot` — взаимодействие с Telegram Bot API
  - `Telethon` — асинхронный парсинг Telegram-каналов
  - `openai` — взаимодействие с DeepSeek API
  - `requests` — работа с REST API (CoinGecko)
- **Инфраструктура / Деплой:** Подготовлено для развертывания на Railway (Nixpacks) и Heroku (`Procfile`).

## 🗂 Архитектура проекта

- `bot.py` — Главный модуль, содержащий бизнес-логику бота, обработчики сообщений и планировщик задач.
- `config.py` — Модуль конфигурации (чтение переменных окружения, системные промпты, списки ключевых слов).
- `bot_nanobanana_fix.py` — Вспомогательный модуль интеграции сторонних API генерации медиа.
- `railway.json` / `Procfile` / `DEPLOY.md` — Файлы для настройки CI/CD и деплоя на облачные платформы.

## ⚙️ Установка и запуск

1. **Клонируйте репозиторий:**
   ```bash
   git clone https://github.com/arar228/neyro_projects_telegram.git
   cd neyro_projects_telegram
   ```

2. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Настройте переменные окружения:**
   В проекте используется `python-dotenv`. Создайте файл `.env` в корне проекта и укажите ваши ключи:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token
   DEEPSEEK_API_KEY=your_deepseek_key
   CHANNEL_ID=your_channel_id
   TELEGRAM_API_ID=your_api_id
   TELEGRAM_API_HASH=your_api_hash
   ```

4. **Запуск бота:**
   ```bash
   python bot.py
   ```

## 🔐 Безопасность

Все секретные ключи, токены и приватные конфигурации исключены из репозитория с помощью `.gitignore`. Гарантируется отсутствие утечек конфиденциальных данных. Рекомендуется использовать переменные окружения (Environment Variables) при деплое на сервер (Railway, Heroku, VPS).

## 📝 Лицензия

Этот проект распространяется под лицензией MIT. Использование в открытом доступе разрешено.

