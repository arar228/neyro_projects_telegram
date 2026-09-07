# Neyro — Telegram Editorial Automation

A Python application that connects Telegram news collection, AI-assisted writing, image generation, and scheduled channel publishing. The implementation focuses on a TON/market-news editorial workflow with configurable prompts, source filtering, and duplicate tracking.

[Architecture](#architecture) · [Setup](#setup-requirements) · [Русский](docs/README.ru.md) · [Historical Railway notes](DEPLOY.md)

## Engineering focus

- **Input pipeline:** Telethon retrieves channel posts; filtering selects relevant material for the editorial flow.
- **Content pipeline:** DeepSeek generates text; a separate image-generation adapter handles media requests.
- **Publishing lifecycle:** command handlers, scheduling, processed IDs, and post hashes coordinate automated and operator-triggered publishing.
- **Market context:** CoinGecko price data supports scheduled TON market summaries.

## Architecture

```text
Telegram sources / operator commands → filtering → text and image generation
                                                         ↓
                                  duplicate checks → Telegram channel publishing
```

| Source | Responsibility |
|---|---|
| [bot.py](bot.py) — `NewsParser` | Telethon collection and processed-item tracking |
| [bot.py](bot.py) — `DeepSeekClient`, `PriceFetcher` | Text generation and market-data integration |
| [bot.py](bot.py) — `NanoBananaImageGenerator` | Image-generation requests and task polling |
| [bot.py](bot.py) — `TelegramChannelBot` | Publication state, scheduling, and command handling |
| [config.py](config.py) | Environment readers, prompts, filters, and timing settings |
| [Procfile](Procfile), [railway.json](railway.json) | Retained worker entry-point declarations; Railway configuration is historical |

**Declared stack:** Python, `python-telegram-bot==20.7`, `Telethon==1.34.0`, Requests, and python-dotenv. The current implementation calls providers through Requests; an OpenAI SDK is not declared in this snapshot.

## Setup requirements

```bash
git clone https://github.com/arar228/neyro_projects_telegram.git
cd neyro_projects_telegram
python -m venv .venv
# Activate .venv using your shell's activation command.
python -m pip install -r requirements.txt
```

Provision your own environment or ignored local `.env`, which `config.py` loads. Review these names according to the enabled workflow:

| Area | Configuration names |
|---|---|
| Publishing | `TELEGRAM_BOT_TOKEN`, `CHANNEL_ID`, `ADMIN_USER_ID`, `ALLOWED_GENETAT_USERS` |
| Source account | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `NEWS_CHANNEL`, `NEWS_COUNT` |
| Text generation | `DEEPSEEK_API_KEY`, `DEEPSEEK_API_URL` |
| Image generation | `NANOBANANA_API_KEY`, `NANOBANANA_API_URL` |
| Market data | `COINGECKO_API_URL`, `TON_COIN_ID` |

Keep the existing spelling `ALLOWED_GENETAT_USERS` when configuring this revision. Review prompts and permitted source material, authorize the source account, and grant the bot publishing rights only to the intended test channel.

`python bot.py` is the worker command declared by both deployment files. Starting it can publish posts and incur provider usage. Scripts with `test` in their names can also call providers or publish; inspect their behavior before running them.

`DEPLOY.md` preserves historical Railway instructions. Use the current VPS service definition to confirm the working directory, interpreter, and environment source before operating the worker.

## Review status

Source review: **2026-09-07**. This pass changed documentation only and did not authenticate accounts, call providers, publish messages, or confirm an active deployment. Deployment declarations are present; a GitHub Actions workflow and verified offline test suite are not included in this snapshot.

Retain Telegram sessions, processed-item state, credentials, and logs privately. Historical credentials require separate review; `.gitignore` is not a security audit. See the [Russian overview](docs/README.ru.md) for the same operating boundaries. No license file is included in this snapshot; this README adds no licensing grant.
