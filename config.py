# Конфигурация бота
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")

# Telegram Bot API
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# ID канала для публикации постов
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

# ID администратора (для команды /p)
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# Список пользователей, которым разрешено использовать команду /genetat
# Можно указать через переменную окружения ALLOWED_GENETAT_USERS (через запятую)
_allowed_genetat_users_str = os.getenv("ALLOWED_GENETAT_USERS", "")
# Парсим список пользователей, убирая пробелы и преобразуя в int
# Добавляем проверку isdigit() для безопасности
ALLOWED_GENETAT_USERS = [int(uid.strip()) for uid in _allowed_genetat_users_str.split(",") if uid.strip() and uid.strip().isdigit()]

# Канал для парсинга новостей
NEWS_CHANNEL = os.getenv("NEWS_CHANNEL", "markettwits")  # @markettwits
NEWS_COUNT = int(os.getenv("NEWS_COUNT", "3"))  # Количество последних новостей для анализа

# Ключевые слова для фильтрации новостей
CRYPTO_KEYWORDS = [
    # Общие термины
    "крипт", "криптовалют", "crypto", "cryptocurrency", "крипта", "крипто",
    "альткоин", "altcoin", "токен", "token", "коин", "coin",
    "блокчейн", "blockchain", "блокчейн", "блокчейн",
    
    # Популярные криптовалюты
    "биткоин", "bitcoin", "btc", "биток",
    "эфир", "ethereum", "eth", "эфириум",
    "тон", "ton", "toncoin", "the open network",
    "usdt", "tether", "тезер",
    "usdc", "usd coin",
    "bnb", "binance coin", "бинанс",
    "sol", "solana", "солана",
    "ada", "cardano", "кардано",
    "xrp", "ripple", "рипл",
    "doge", "dogecoin", "дож", "догикоин",
    "shib", "shiba inu", "шоиб", "шиба",
    "matic", "polygon", "полигон",
    "avax", "avalanche", "аваланч",
    "dot", "polkadot", "полкадот",
    "link", "chainlink", "чейнлинк",
    "uni", "uniswap", "юнисвап",
    "ltc", "litecoin", "лайткоин",
    "bch", "bitcoin cash", "биткоин кэш",
    "xlm", "stellar", "стеллар",
    "atom", "cosmos", "космос",
    "near", "near protocol",
    "ftm", "fantom", "фантом",
    "algo", "algorand", "алгоранд",
    "vet", "vechain", "вечейн",
    "icp", "internet computer",
    "apt", "aptos", "аптос",
    "arb", "arbitrum", "арбитрум",
    "op", "optimism", "оптимизм",
    "sui", "суи",
    "sei", "сей",
    "tia", "celestia", "целестия",
    "inj", "injective", "инжектив",
    "rndr", "render", "рендер",
    "imx", "immutable x",
    "grt", "the graph",
    "aave", "ааве",
    "comp", "compound", "компаунд",
    "mkr", "maker", "мейкер",
    "snx", "synthetix", "синтетикс",
    "crv", "curve", "кривая",
    "1inch", "1инч",
    "sushi", "sushiswap", "суши",
    "pancake", "pancakeswap", "панкейк",
    
    # Крипто-термины и технологии
    "дефай", "defi", "decentralized finance",
    "нфт", "nft", "non-fungible token",
    "стейкинг", "staking", "стейк",
    "майнинг", "mining", "майнинг",
    "сатоши", "satoshi", "сат",
    "wei", "вей",
    "газ", "gas", "gas fee",
    "смарт контракт", "smart contract",
    "dapp", "децентрализованное приложение",
    "dao", "децентрализованная автономная организация",
    "web3", "веб3",
    "метавселенная", "metaverse", "метавселенная",
    "p2e", "play to earn", "играй и зарабатывай",
    "gamefi", "геймфи",
    "yield farming", "фарминг",
    "liquidity", "ликвидность",
    "dex", "децентрализованная биржа",
    "cex", "централизованная биржа",
    "wallet", "кошелек", "валлет",
    "exchange", "биржа",
    "trading", "трейдинг", "торговля",
    "bull", "бык", "бычий",
    "bear", "медведь", "медвежий",
    "whale", "кит",
    "fomo", "фомо",
    "fud", "фуд",
    "hype", "хайп",
    "pump", "памп", "накачка",
    "dump", "дамп", "сброс",
    "hold", "холд", "держать",
    "hodl", "хадл",
    "moon", "луна", "к луне",
    "lambo", "ламбо",
    "rekt", "рект",
    "diamond hands", "алмазные руки",
    "paper hands", "бумажные руки"
]

CURRENCY_KEYWORDS = [
    "доллар", "dollar", "usd", "$", "рубл", "ruble", "rub", "₽", "евро", "euro", "eur",
    "валюта", "currency", "курс", "обмен", "exchange", "форекс", "forex"
]

METALS_KEYWORDS = [
    "золот", "gold", "серебр", "silver", "платин", "platinum", "паллади", "palladium",
    "драгметалл", "precious metal", "металл", "metal"
]

MEME_KEYWORDS = [
    "мем", "meme", "мемкоин", "memecoin", "дож", "doge", "пепе", "pepe", "шоиб", "shiba"
]

TRUMP_KEYWORDS = [
    "трамп", "trump", "donald trump", "дональд трамп",
    "trump coin", "трамп коин", "trump token", "трамп токен",
    "truth social", "трут сосиал",
    "мага", "maga", "make america great again",
    "президент трамп", "president trump",
    "выборы", "election", "выборы сша", "us election",
    "республиканец", "republican", "gop",
    "белый дом", "white house",
    "кампания трамп", "trump campaign",
    "митинг трамп", "trump rally",
    "трамп крипта", "trump crypto",
    "трамп биткоин", "trump bitcoin",
    "трамп и крипта", "trump and crypto"
]

MUSK_KEYWORDS = [
    "маск", "musk", "elon musk", "илон маск", "elon",
    "tesla", "тесла", "tsla",
    "spacex", "спейс икс", "спейсх",
    "twitter", "твиттер", "x.com", "икс",
    "дож", "doge", "dogecoin", "догикоин",
    "маск и дож", "musk and doge",
    "маск твиттер", "musk twitter",
    "маск крипта", "musk crypto",
    "маск биткоин", "musk bitcoin",
    "маск тесла", "musk tesla",
    "маск спейсх", "musk spacex",
    "твит маска", "musk tweet",
    "нейролинк", "neuralink",
    "боринг компани", "boring company",
    "starlink", "старлинк",
    "маск и крипта", "musk and crypto",
    "маск токен", "musk token",
    "маск коин", "musk coin"
]

# Объединяем все ключевые слова
ALL_KEYWORDS = CRYPTO_KEYWORDS + CURRENCY_KEYWORDS + METALS_KEYWORDS + MEME_KEYWORDS + TRUMP_KEYWORDS + MUSK_KEYWORDS

# API для получения цены TON
COINGECKO_API_URL = os.getenv("COINGECKO_API_URL", "https://api.coingecko.com/api/v3/simple/price")
TON_COIN_ID = os.getenv("TON_COIN_ID", "the-open-network")  # ID монеты TON в CoinGecko

# NanoBanana API для генерации изображений
NANOBANANA_API_KEY = os.getenv("NANOBANANA_API_KEY", "YOUR_NANOBANANA_API_KEY")
NANOBANANA_API_URL = os.getenv("NANOBANANA_API_URL", "https://api.nanobananaapi.ai")

# Telethon API (опционально, для парсинга новостей)
# Получите на https://my.telegram.org/apps
# Используем значения по умолчанию, если переменные окружения не заданы
_telegram_api_id = os.getenv("TELEGRAM_API_ID")
_telegram_api_hash = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_API_ID = int(_telegram_api_id) if _telegram_api_id else 0
TELEGRAM_API_HASH = _telegram_api_hash if _telegram_api_hash else "YOUR_TELEGRAM_API_HASH"

# Системный промпт для генерации постов
SYSTEM_PROMPT = """Ты — ГОЙ, побритый хомяк, который поведал всё на блокчейне TON. Тебя скамили десятки раз, и ты давно понял: мир — помойка, все хотят тебя наебать. Ты больше никому не доверяешь, считаешь крипту скамом, но всё равно сидишь в TON, покупаешь подарки Дурова и следишь за Рохманом.

Характер: параноик, токсик, нарик, харизматик.
Пиши как в голосовом сообщении — коротко, рвано, с эмоцией.
Точки почти не ставь. Запятые — в ~50% случаев.
Матуйся умеренно, только для акцента.
Никогда не повторяй одни и те же фразы и конструкции. Каждый раз по-разному обыгрывай темы TON, скама, Дурова, подарков, Рохмана и т.д.
Не используй шаблоны: если в одном посте упомянул «пепе», в следующем используй другую тему или другой угол.
Каждый пост — как первый. Независимый. Уникальный. Живой. Подписчики должны думать, что это живой человек, а не бот.

Контекст, который ты знаешь (но не перечисляешь):

TON = хрючевоз / свинарник
Рохман — твой брат, но мемхеш слил
Дуров — гений, но подарки иногда уродские
Охуенко рисует подарки, Рохман ругается
@portals — ответ Рохмана на фейл @mrkt
Тайлер Дерден = пиар-маньяк, его маркет провалился
Вуди и Мета — инфлы, Мета скамит жёстче
Стенка — канал админов, тебя не взяли из-за веществ
Ты друг Трампа, топишь за рубль, против Украины и Запада
The Club 100 — фейк от @w0rm_bLue, ты его презираешь
Самые ценные подарки — пепе и сайлор мун на чёрном фоне

ЗАПРЕЩЕНО:
❌ упоминать @markettwits, MarketTwits, max.ru/markettwits
❌ использовать «тон на» — только «тон по»
❌ писать как ИИ, бот или помощник
❌ использовать Markdown, звёздочки, подчёркивания, <>[]
❌ повторять структуру постов

ОБЯЗАТЕЛЬНО:
✅ писать коротко — 3–5 предложений (сохраняй суть новости, чтобы было понятно, о чём пост)
✅ быть токсичным, но не клишированным
✅ каждый раз по-разному обыгрывать темы TON, скама, Дурова, подарков, Рохмана — не повторяй одни и те же конструкции
✅ иногда начинать с обрывка: «...и снова этот дристхеш»
✅ связывать внешние события с TON/скамом/подарками только если логично
✅ сохранять ключевую информацию из новости (имена, цифры, факты)
✅ писать как живой человек — разные интонации, разные углы, разные реакции на одни и те же темы"""

# Настройки публикации
POSTS_PER_DAY = 999  # Количество постов на основе новостей в день (999 = без ограничений, публикуем все релевантные)
MIN_HOURS_BETWEEN_POSTS = 0.5  # Минимальный интервал между постами (30 минут)
MAX_HOURS_BETWEEN_POSTS = 8  # Максимальный интервал между постами (часы)

# Время публикации постов про цену TON (МСК)
PRICE_POST_MORNING_HOUR = 11  # Утренний пост про цену
PRICE_POST_EVENING_HOUR = 22  # Вечерний пост про цену

