import asyncio
import random
import logging
import time
import os
import tempfile
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from functools import partial

import requests
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError

import config

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Отключаем избыточное логирование HTTP-запросов от httpx и telethon
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("telethon.client.updates").setLevel(logging.WARNING)


def escape_markdown(text: str) -> str:
    """Экранирует специальные символы Markdown для Telegram"""
    if not text:
        return text
    
    # Символы, которые нужно экранировать в Telegram Markdown
    # Основные символы разметки: * _ [ ] ( ) ~ ` > # + - = | { }
    # Сначала экранируем обратный слэш, чтобы не экранировать его дважды
    result = text.replace('\\', '\\\\')
    # Затем экранируем остальные символы разметки
    escape_chars = ['*', '_', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}']
    for char in escape_chars:
        result = result.replace(char, f'\\{char}')
    return result


class NewsParser:
    """Парсер новостей из Telegram канала"""
    
    def __init__(self, api_id: Optional[int] = None, api_hash: Optional[str] = None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.client = None
        self.initialized = False
        self.processed_message_ids = self._load_processed_ids()  # ID уже обработанных сообщений
    
    def _load_processed_ids(self) -> set:
        """Загружает ID обработанных сообщений из файла"""
        try:
            if os.path.exists('processed_ids.txt'):
                with open('processed_ids.txt', 'r') as f:
                    ids = {int(line.strip()) for line in f if line.strip().isdigit()}
                    logger.info(f"Загружено {len(ids)} ID обработанных сообщений")
                    return ids
        except Exception as e:
            logger.warning(f"Не удалось загрузить обработанные ID: {e}")
        return set()
    
    def _save_processed_id(self, message_id: int):
        """Сохраняет ID обработанного сообщения в файл"""
        try:
            with open('processed_ids.txt', 'a') as f:
                f.write(f"{message_id}\n")
        except Exception as e:
            logger.warning(f"Не удалось сохранить ID сообщения: {e}")
    
    async def init_client(self):
        """Инициализирует Telegram клиент"""
        if self.initialized:
            return True
            
        try:
            if not self.api_id or not self.api_hash:
                logger.warning("API ID и API Hash не указаны. Парсинг новостей может не работать.")
                logger.warning("Получите их на https://my.telegram.org/apps и добавьте в config.py")
                return False
            
            self.client = TelegramClient('news_session', self.api_id, self.api_hash)
            
            # Пытаемся подключиться, используя существующую сессию (для Railway)
            try:
                # Если файл сессии существует, пытаемся использовать его
                if os.path.exists('news_session.session'):
                    logger.info("Найдена существующая сессия Telethon, загружаю...")
                    # Используем start() без интерактивного ввода, если сессия валидна
                    await self.client.start()
                    
                    if await self.client.is_user_authorized():
                        logger.info("Сессия Telethon успешно загружена и авторизована")
                    else:
                        logger.warning("Сессия найдена, но не авторизована. Парсинг новостей недоступен.")
                        logger.warning("Для авторизации запустите бота локально один раз.")
                        await self.client.disconnect()
                        return False
                else:
                    logger.warning("Файл сессии не найден. Парсинг новостей будет недоступен.")
                    logger.warning("Для авторизации запустите бота локально один раз.")
                    return False
            except EOFError:
                # Ошибка при попытке интерактивного ввода (на Railway)
                logger.warning("Не удалось авторизоваться (нет интерактивного ввода). Парсинг новостей недоступен.")
                logger.warning("Бот продолжит работу без парсинга новостей.")
                return False
            except Exception as e:
                logger.warning(f"Ошибка при подключении Telethon: {e}")
                logger.warning("Парсинг новостей будет недоступен, но бот продолжит работу.")
                return False
            
            logger.info("Telegram клиент для парсинга новостей инициализирован")
            self.initialized = True
            return True
        except SessionPasswordNeededError:
            logger.error("Требуется пароль двухфакторной аутентификации. Отключите 2FA или введите пароль.")
            return False
        except Exception as e:
            logger.error(f"Ошибка инициализации Telegram клиента: {e}")
            return False
    
    def is_relevant_news(self, text: str) -> bool:
        """Проверяет, подходит ли новость по ключевым словам (строгая проверка)"""
        if not text:
            return False
        
        text_lower = text.lower()
        
        # СТРОГИЙ ЗАПРЕТ: Украина и Зеленский - отклоняем на 100%, независимо от крипто-терминов
        ukraine_keywords = ["украин", "ukraine", "зеленск", "zelensky", "зеленский"]
        if any(keyword in text_lower for keyword in ukraine_keywords):
            logger.debug(f"Отклонена новость с упоминанием Украины/Зеленского: {text[:100]}...")
            return False
        
        # ИСКЛЮЧЕНИЕ: Политические темы без крипто-контекста
        # Если новость содержит политические маркеры, но нет строгих крипто-терминов - отклоняем
        political_markers = [
            "геополитика", "geopolitics", "геополитик",
            "россия", "russia", "россий",
            "сша", "usa", "united states", "америк", "вашингтон", "washington",
            "китай", "china", "китайск",
            "тайвань", "taiwan", "тайвань",
            "война", "war", "военн",
            "санкции", "sanctions", "санкци",
            "дипломатия", "diplomacy", "дипломат",
            "президент", "president", "президент",
            "правительство", "government", "правительств",
            "министр", "minister", "министр",
            "премьер", "prime minister", "премьер",
            "парламент", "parliament", "парламент",
            "выборы", "elections", "выбор",
            "референдум", "referendum", "референдум",
            "нато", "nato",
            "ес", "eu", "european union", "евросоюз",
            "венесуэла", "venezuela", "венесуэл",
            "иран", "iran", "иран",
            "израиль", "israel", "израил",
            "палестина", "palestine", "палестин",
            "гренландия", "greenland", "гренланд",
            "ирландия", "ireland", "ирланд",
            "южная корея", "south korea", "южнокорейск",
            "турция", "turkey", "турецк",
            "европа", "europe", "европейск",
            "мадуро", "maduro",
            "си цзиньпин", "xi jinping",
            "трамп", "trump",
            "байден", "biden"
        ]
        
        # Проверяем наличие политических маркеров
        has_political = any(marker in text_lower for marker in political_markers)
        
        # Строгие крипто-термины (гарантированно про крипту)
        strict_crypto_keywords = [
            "крипт", "криптовалют", "crypto", "cryptocurrency", "крипта", "крипто",
            "блокчейн", "blockchain",
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
        
        # Сначала проверяем строгие термины
        has_strict_crypto = False
        for keyword in strict_crypto_keywords:
            keyword_lower = keyword.lower().strip()
            if keyword_lower and keyword_lower in text_lower:
                logger.debug(f"Найдено строгое ключевое слово '{keyword}' в тексте: {text[:100]}...")
                has_strict_crypto = True
                return True
        
        # Если есть политические маркеры, но нет строгих крипто-терминов - отклоняем
        if has_political and not has_strict_crypto:
            logger.debug(f"Отклонена политическая новость без крипто-контекста: {text[:100]}...")
            return False
        
        # Если строгих терминов нет, проверяем комбинации общих терминов
        # (требуем минимум 2 разных ключевых слова из разных категорий)
        general_keywords = [
            "токен", "token", "коин", "coin", "альткоин", "altcoin",
            "liquidity", "ликвидность"
        ]
        
        found_general = []
        for keyword in general_keywords:
            keyword_lower = keyword.lower().strip()
            if keyword_lower and keyword_lower in text_lower:
                found_general.append(keyword)
        
        # Если найдено минимум 2 общих термина, проверяем политику перед возвратом True
        if len(found_general) >= 2:
            # Если есть политические маркеры, но нет строгих крипто-терминов - отклоняем
            if has_political and not has_strict_crypto:
                logger.debug(f"Отклонена политическая новость с общими терминами: {text[:100]}...")
                return False
            logger.debug(f"Найдено {len(found_general)} общих ключевых слов в тексте: {text[:100]}...")
            return True
        
        # Проверяем контекстные комбинации (общий термин + финансовый/технологический контекст)
        financial_context = ["цена", "price", "курс", "rate", "рост", "рост", "падение", "fall", "инвестиц", "invest", "бирж", "exchange", "торговл", "trading"]
        tech_context = ["блокчейн", "blockchain", "технологи", "technology", "протокол", "protocol", "сеть", "network"]
        
        has_general = any(kw in text_lower for kw in general_keywords)
        has_financial = any(ctx in text_lower for ctx in financial_context)
        has_tech = any(ctx in text_lower for ctx in tech_context)
        
        if has_general and (has_financial or has_tech):
            # Если есть политические маркеры, но нет строгих крипто-терминов - отклоняем
            if has_political and not has_strict_crypto:
                logger.debug(f"Отклонена политическая новость с комбинацией терминов: {text[:100]}...")
                return False
            logger.debug(f"Найдена комбинация общий термин + контекст в тексте: {text[:100]}...")
            return True
        
        return False
    
    async def get_new_relevant_news(self, channel: str, limit: int = 100) -> List[dict]:
        """Получает новые релевантные новости из канала (которые ещё не обрабатывались)"""
        if not self.initialized:
            success = await self.init_client()
            if not success:
                return []
        
        if not self.client:
            return []
        
        try:
            new_messages = []
            channel_clean = channel.lstrip('@')
            total_checked = 0
            skipped_processed = 0
            skipped_not_relevant = 0
            skipped_service = 0
            
            logger.info(f"Проверяю последние {limit} сообщений из канала @{channel_clean}...")
            
            async for message in self.client.iter_messages(channel_clean, limit=limit):
                total_checked += 1
                
                # Пропускаем уже обработанные сообщения
                if message.id in self.processed_message_ids:
                    skipped_processed += 1
                    continue
                
                # Получаем текст из сообщения (в Telethon message.text работает и для текста, и для caption медиа)
                text = None
                if message.text:
                    text = message.text.strip()
                
                if not text:
                    # Сообщение без текста (только медиа без caption) - пропускаем
                    continue
                
                # Пропускаем служебные сообщения
                if text.startswith('Download') or (text.startswith('http://') and len(text) < 100) or (text.startswith('https://') and len(text) < 100):
                    skipped_service += 1
                    continue
                
                # Проверяем, подходит ли новость по тематике (без ограничения по длине)
                if self.is_relevant_news(text):
                    new_messages.append({
                        'id': message.id,
                        'text': text,
                        'date': message.date
                    })
                    # Помечаем как обработанное и сохраняем
                    self.processed_message_ids.add(message.id)
                    self._save_processed_id(message.id)
                    logger.info(f"✅ Найдена релевантная новость (ID: {message.id}): {text[:80]}...")
                else:
                    skipped_not_relevant += 1
                    # Логируем примеры нерелевантных новостей для отладки
                    if skipped_not_relevant <= 3:
                        logger.debug(f"❌ Не релевантно (ID: {message.id}): {text[:60]}...")
            
            logger.info(f"📊 Статистика проверки: всего проверено: {total_checked}, "
                       f"обработано ранее: {skipped_processed}, "
                       f"служебных: {skipped_service}, "
                       f"не релевантных: {skipped_not_relevant}, "
                       f"✅ новых релевантных: {len(new_messages)}")
            
            if new_messages:
                logger.info(f"🎯 Найдено {len(new_messages)} новых релевантных новостей из канала {channel}")
            else:
                logger.info("ℹ️ Новых релевантных новостей не найдено (возможно, все уже обработаны или не подходят по тематике)")
            
            return new_messages
        except FloodWaitError as e:
            logger.warning(f"FloodWait: нужно подождать {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении новостей: {e}")
            return []
    
    async def get_latest_news(self, channel: str, count: int = 3) -> List[str]:
        """Получает последние новости из канала (для обратной совместимости)"""
        news = await self.get_new_relevant_news(channel, limit=count * 2)
        return [item['text'] for item in news[:count]]
    
    async def close(self):
        """Закрывает соединение"""
        if self.client:
            await self.client.disconnect()


class NanoBananaImageGenerator:
    """Генератор изображений через NanoBanana API"""
    
    def __init__(self, api_key: str, api_url: str, callback_url: Optional[str] = None):
        self.api_key = api_key
        self.api_url = api_url.rstrip('/')
        # Callback URL для получения уведомлений (обязателен согласно документации)
        # Используем заглушку, так как у нас нет публичного сервера для callback
        # В этом случае будем использовать polling через Get Task Details
        self.callback_url = callback_url or "https://example.com/callback"  # Заглушка
        self.pending_tasks = {}  # {task_id: {'prompt': str, 'created_at': datetime}}
    
    def generate_image(self, prompt: str, mode: str = "generate", image_urls: Optional[List[str]] = None, 
                      num_images: int = 1, image_size: str = "1:1") -> Optional[dict]:
        """
        Генерирует или редактирует изображение
        
        Args:
            prompt: Текстовое описание для генерации или редактирования
            mode: "generate" для генерации, "edit" для редактирования
            image_url: URL изображения для редактирования (только для mode="edit")
        
        Returns:
            dict с task_id или None в случае ошибки
        """
        try:
            # Правильный endpoint согласно документации: /api/v1/nanobanana/generate
            url = f"{self.api_url}/api/v1/nanobanana/generate"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Определяем тип генерации согласно документации
            if mode == "edit":
                generation_type = "IMAGETOIAMGE"
                if not image_urls:
                    logger.error("Для редактирования нужен imageUrls (список URL)")
                    return None
            else:
                generation_type = "TEXTTOIAMGE"
            
            payload = {
                "prompt": prompt,
                "type": generation_type,
                "callBackUrl": self.callback_url,
                "numImages": min(max(num_images, 1), 4),  # Ограничение 1-4
                "image_size": image_size
            }
            
            # Для редактирования добавляем URL изображений
            if mode == "edit" and image_urls:
                payload["imageUrls"] = image_urls
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                # Проверяем формат ответа согласно документации: {code, msg, data: {taskId}}
                if data.get("code") == 200 and data.get("data", {}).get("taskId"):
                    task_id = data["data"]["taskId"]
                    logger.info(f"Изображение поставлено в очередь. Task ID: {task_id}")
                    return {"task_id": task_id, "full_response": data}
                else:
                    logger.error(f"Ошибка в ответе API: {data.get('msg', 'Unknown error')}")
                    return None
            else:
                logger.error(f"Ошибка генерации изображения: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Исключение при генерации изображения: {e}")
            return None
    
    def get_task_status(self, task_id: str) -> Optional[dict]:
        """Проверяет статус задачи генерации"""
        try:
            # Согласно документации: GET /api/v1/nanobanana/record-info?taskId={taskId}
            url = f"{self.api_url}/api/v1/nanobanana/record-info"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            params = {
                "taskId": task_id
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # Проверяем формат ответа согласно документации
                if data.get("code") == 200:
                    task_data = data.get("data", {})
                    logger.debug(f"Статус задачи {task_id}: {task_data}")
                    return task_data
                else:
                    logger.warning(f"API вернул код {data.get('code')}: {data.get('msg', 'Unknown error')}")
                    return None
            elif response.status_code == 404:
                logger.debug(f"Задача {task_id} не найдена (404)")
                return None
            else:
                logger.error(f"Ошибка проверки статуса: {response.status_code} - {response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"Исключение при проверке статуса: {e}")
            logger.exception(e)
            return None
    
    async def generate_image_async(self, prompt: str, mode: str = "generate", 
                                   image_urls: Optional[List[str]] = None) -> Optional[str]:
        """
        Асинхронная генерация изображения с ожиданием результата
        
        Args:
            prompt: Текстовое описание
            mode: "generate" или "edit"
            image_urls: Список URL для редактирования (только для mode="edit")
        
        Returns:
            URL готового изображения или None
        """
        # Запускаем генерацию
        task_data = self.generate_image(prompt, mode, image_urls)
        if not task_data or 'task_id' not in task_data:
            return None
        
        task_id = task_data['task_id']
        logger.info(f"Ожидаю завершения генерации изображения (Task ID: {task_id})...")
        
        # Ждем завершения (максимум 3 минуты, проверяем каждые 5 секунд)
        max_attempts = 36  # 36 * 5 = 180 секунд = 3 минуты
        for attempt in range(max_attempts):
            logger.debug(f"Проверка статуса задачи {task_id}, попытка {attempt + 1}/{max_attempts}")
            await asyncio.sleep(5)
            
            status_data = self.get_task_status(task_id)
            if not status_data:
                logger.debug(f"Не удалось получить статус задачи {task_id}, продолжаю ждать...")
                # Если не удалось получить статус, продолжаем ждать
                continue
            
            logger.debug(f"Статус задачи {task_id}: {status_data}")
            
            # Согласно документации, статус хранится в поле successFlag:
            # 0: GENERATING - задача обрабатывается
            # 1: SUCCESS - задача завершена успешно
            # 2: CREATE_TASK_FAILED - не удалось создать задачу
            # 3: GENERATE_FAILED - создание задачи успешно, но генерация провалилась
            
            success_flag = status_data.get('successFlag')
            
            if success_flag == 1:  # SUCCESS
                logger.info(f"Задача {task_id} завершена успешно. Ищу URL изображения...")
                # Согласно документации, URL изображения в response.resultImageUrl
                # resultImageUrl - наш сервер (дольше доступен)
                # originImageUrl - BFL сервер (валиден только 10 минут)
                response_data = status_data.get('response', {})
                image_url = response_data.get('resultImageUrl') or response_data.get('originImageUrl')
                
                if image_url:
                    logger.info(f"Изображение готово: {image_url}")
                    return image_url
                else:
                    # Если successFlag = 1, но URL нет - это ошибка, не продолжаем ждать
                    logger.error(f"Задача завершена успешно (successFlag=1), но URL изображения не найден. Полный ответ: {status_data}")
                    return None
            elif success_flag == 2:  # CREATE_TASK_FAILED
                error_msg = status_data.get('errorMessage', 'Не удалось создать задачу')
                logger.error(f"Ошибка создания задачи (Task ID: {task_id}): {error_msg}")
                return None
            elif success_flag == 3:  # GENERATE_FAILED
                error_msg = status_data.get('errorMessage', 'Генерация провалилась')
                logger.error(f"Ошибка генерации изображения (Task ID: {task_id}): {error_msg}")
                return None
            elif success_flag == 0:  # GENERATING
                logger.debug(f"Задача {task_id} в процессе генерации (successFlag=0)")
                # Продолжаем ждать
                continue
            else:
                # Если successFlag отсутствует или имеет неожиданное значение
                logger.debug(f"Неизвестный статус successFlag={success_flag} для задачи {task_id}, продолжаю ждать...")
                # Продолжаем ждать
                continue
        
        logger.warning(f"Превышено время ожидания генерации изображения (Task ID: {task_id}) после {max_attempts} попыток")
        return None


class PriceFetcher:
    """Получает цену TON из CoinGecko API"""
    
    def __init__(self, api_url: str, coin_id: str):
        self.api_url = api_url
        self.coin_id = coin_id
    
    def get_ton_price(self) -> Optional[dict]:
        """Получает текущую цену TON в USD и RUB"""
        try:
            params = {
                "ids": self.coin_id,
                "vs_currencies": "usd,rub",
                "include_24hr_change": "true",
                "include_24hr_vol": "true"
            }
            
            response = requests.get(self.api_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if self.coin_id in data:
                    price_data = data[self.coin_id]
                    result = {
                        "usd": price_data.get("usd", 0),
                        "rub": price_data.get("rub", 0),
                        "change_24h": price_data.get("usd_24h_change", 0),
                        "volume_24h": price_data.get("usd_24h_vol", 0)
                    }
                    logger.info(f"Получена цена TON: ${result['usd']:.4f} ({result['change_24h']:+.2f}%)")
                    return result
                else:
                    logger.error(f"Монета {self.coin_id} не найдена в ответе API")
                    return None
            else:
                logger.error(f"Ошибка API CoinGecko: {response.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к CoinGecko API: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении цены: {e}")
            return None


class DeepSeekClient:
    """Клиент для работы с DeepSeek API"""
    
    # Примеры разных стилей обыгрывания для вдохновения (используются во всех промптах с новостями)
    # В стиле русских шуток и анекдотов (из mem-and-russian-jokes-dataset)
    STYLE_EXAMPLES = """Примеры разных стилей и углов в стиле русских шуток (используй как вдохновение, не копируй):

Философские/токсичные размышления:
- "Эти ваши 'подарки Дурова' - просто скам в красивой упаковке, но рука так и тянется купить ещё один"
- "Скамеры в TON уже научились клонировать мои мысли, скоро начнут продавать их за тоны"
- "В мире, где даже блокчейн подставляет, остаётся только верить в свои силы... или в следующий аирдроп"
- "Если мир - помойка, то TON здесь главный мусорщик, который прикрывает это 'децентрализацией'"
- "Блокчейн должен был решить проблемы мира, но почему-то создаёт их больше, чем решает"

Самоирония и паранойя (в стиле русских анекдотов):
- "Каждый раз, когда я думаю выйти из игры, кто-то шлёт мне новый реферал, и я снова попадаюсь"
- "Пока я жду хайпа, мои тоны испаряются, будто их и не было. Жизнь - боль"
- "Сидишь, ждёшь, пока твои тоны взлетят, а они медленно утекают в никуда. Как символично"
- "Каждый раз, открывая кошелёк, надеюсь увидеть там миллионы. Вместо этого - новые комиссии"
- "Продолжаю вкладывать, хотя знаю, что это безумие. Что это, если не зависимость?"

Ирония и сарказм:
- "Говорят, что TON - будущее. Будущее обмана и бессмысленных затрат, видимо"
- "Думаешь, ты умный, потому что нашёл 'крутой проект'? Ой, держите меня семеро, он уже скамнут"
- "Участвовал в аирдропе, получил 10 тонариков, а потом заплатил больше. Ирония судьбы?"

Русские шутки и мемы (в стиле русского юмора):
- "Купил биткоин за 60к, продал за 30к. Теперь жду, когда куплю за 90к и продам за 45к"
- "Мой кошелёк как холодильник: открываю, надеюсь увидеть еду, а там только старые комиссии"
- "Думал, что ходл - это стратегия. Оказалось, это просто неумение продавать"
- "Мой депозит как отношения: чем дольше держу, тем меньше становится"
- "Аирдроп - это как подарок на день рождения: обещают золотые горы, а дают 10 токенов"
- "Трейдинг - это когда ты платишь комиссии за право потерять деньги"
- "Блокчейн должен был быть децентрализованным, а я чувствую себя централизованно обманутым"
- "Купил NFT за 1000$, продал за 10$. Теперь это моя самая дорогая аватарка"
- "Говорят, не клади все яйца в одну корзину. Я положил все в TON и теперь ищу корзину"
- "Мой портфель как диета: начинаю с энтузиазмом, заканчиваю с пустым кошельком"
- "Крипта - это как казино, только ты платишь за вход и ещё не знаешь, что проиграл"
- "Купил на пике, продал на дне. Теперь жду, когда куплю на дне и продам ещё ниже"
- "Мой стоп-лосс работает как сигнализация: срабатывает только после того, как всё уже украли"
- "Говорят, диверсификация - ключ к успеху. Я диверсифицировал убытки по всем токенам"
- "Мой трейдинг как отношения: чем больше вкладываю, тем больше теряю"
- "Купил токен, потому что 'это следующий биткоин'. Теперь жду, когда он станет хотя бы следующим догкоином"
- "Мой график как американские горки: только вниз и без остановок"
- "Крипта научила меня одному: надежда умирает последней, а вместе с ней и мой депозит"
- "Говорят, время в рынке важнее тайминга. Я провёл много времени в рынке и потерял много денег"
- "Мой DCA как подписка: плачу каждый месяц, но ничего не получаю"
- "Купил альткоин, потому что 'у него низкая капитализация'. Теперь у меня низкая капитализация"
- "Мой ходл как диета: держусь неделю, потом срываюсь и продаю всё"
- "Крипта - это когда ты платишь за возможность потерять деньги быстрее, чем в банке"
- "Говорят, не инвестируй больше, чем можешь позволить себе потерять. Я потерял больше, чем мог позволить"
- "Мой стейкинг как брак: запер деньги, не могу выйти, а доходы только обещают"
- "Мой дефай как ресторан: обещают много, а дают мало, и ещё платишь"
- "Крипта научила меня читать графики. Теперь я читаю только графики убытков"
- "Говорят, паника - плохой советчик. Но паника помогла мне продать до того, как потерял ещё больше"
- "Купить токены, продать токены, потерять токены - круговорот денег в природе"
- "Блядь, скоро и мои тоны заморозят, если я не уйду с этой помойки"
- "Мой смарт-контракт как брачный: подписал, не можешь выйти, а деньги утекают"
- "Крипта - это когда ты платишь за обучение, но получаешь только опыт потерь"
- "Говорят, ходл - это терпение. Я терпел так долго, что забыл, зачем покупал"
- "Мой лимит-ордер как мечта: ставишь, ждёшь, а он никогда не исполняется"
- "Крипта научила меня математике: теперь я умею считать только убытки"
- "Говорят, не продавай на эмоциях. Я продал на логике и всё равно потерял"
- "Мой портфель как погода: обещают солнце, а идёт дождь убытков"
- "Купил токен из-за белой бумаги. Оказалось, бумага была белой, потому что там ничего не было"
- "Мой стейкинг как фитнес: обещают результат, но видишь только потери"
- "Крипта - это когда ты платишь за будущее, но получаешь только прошлое"
- "Говорят, не FOMO. Я не FOMO, я просто покупаю всё подряд от страха пропустить"
- "Мой депозит как телефон: чем дольше используешь, тем меньше заряда"
- "Крипта научила меня философии: теперь я знаю, что такое истинная пустота"
- "Говорят, диверсифицируй портфель. Я диверсифицировал и теперь теряю деньги в разных токенах"
- "Мой трейдинг как диета: начинаю с планом, заканчиваю с сожалениями"
- "Купил токен, потому что 'у команды большой опыт'. Опыт оказался в том, как обманывать"
- "Мой график как жизнь: идёт вниз, и я не знаю, когда остановится"
- "Крипта - это когда ты платишь за свободу, но становишься рабом графиков"
- "Купил токен из-за красивой анимации сайта. Оказалось, это всё, что у них было"
- "Мой стейкинг как кредит: запер деньги, плачу проценты, но не могу выйти"
- "Говорят, крипта - это будущее финансов. Видимо, будущее, где я всегда в минусе"
- "Мой дефай как попытка похудеть: обещают результат, но только трачу деньги"
- "Купил токен на слух, продал на слух. Теперь слух, что я идиот"
- "Мой портфель как метеоролог: обещает одно, делает другое, и никто не виноват"
- "Крипта научила меня экономике: теперь я понимаю, что такое инфляция личного кошелька"
- "Говорят, не торгуй на эмоциях. Я торгую на логике и всё равно теряю"
- "Мой ходл как новогодняя диета: начинаю с понедельника, заканчиваю во вторник"
- "Купил токен за 1$, он упал до 0.1$. Теперь жду, когда упадёт до 0.01$, чтобы купить ещё"
- "Мой смарт-контракт как брак по договору: подписал, не можешь выйти, а счастье только обещают"
- "Крипта - это когда ты покупаешь будущее, но получаешь прошлое со скидкой"
- "Говорят, диверсификация - ключ. Я диверсифицировал и теперь теряю разными способами"
- "Мой трейдинг как фитнес: начинаю с мотивации, заканчиваю с оправданиями"
- "Купил альткоин из-за красивой картинки. Теперь у меня красивая картинка и пустой кошелёк"
- "Мой стоп-лосс как будильник: ставишь на 7, просыпаешься в 9"
- "Крипта научила меня психологии: теперь я знаю, что такое стадии принятия убытков"
- "Говорят, время в рынке важнее тайминга. Я провёл много времени и понял, что тайминг всё-таки важен"
- "Мой депозит как батарейка: чем дольше используется, тем меньше остаётся"
- "Купил токен из-за обещаний команды. Команда выполнила обещание - исчезла вместе с токеном"
- "Мой портфель как прогноз погоды: обещают рост, а идёт спад"
- "Крипта - это когда ты платишь за возможность стать богатым, но становишься беднее"
- "Говорят, не инвестируй больше, чем можешь позволить себе потерять. Я потерял больше, чем мог себе позволить потерять"
- "Мой стейкинг как абонемент в фитнес: плачу каждый месяц, но результата не вижу"
- "Купил токен на пике эйфории, продал на дне депрессии. Теперь в постоянной депрессии"
- "Мой график как кардиограмма: показывает жизнь, но только в одну сторону"
- "Крипта научила меня философии стоицизма: теперь я спокойно принимаю любые убытки"
- "Говорят, не FOMO. Я не FOMO, я просто боюсь пропустить убытки"
- "Мой трейдинг как попытка похудеть: начинаю с планом, заканчиваю с пиццей"
- "Купил токен из-за белой бумаги на 100 страниц. Оказалось, 99 страниц были про реферальную программу"
- "Мой кошелёк как рюкзак туриста: чем дальше идёшь, тем легче становится"
- "Крипта - это когда ты платишь за обучение, но получаешь только домашнее задание без ответов"
- "Говорят, ходл - это стратегия. Я ходлю так долго, что забыл, что это была стратегия"
- "Мой лимит-ордер как свидание вслепую: ставишь, ждёшь, но ничего не происходит"
- "Крипта научила меня математике отрицательных чисел: теперь я виртуоз в убытках"
- "Говорят, не продавай на эмоциях. Я продал на холодном расчёте и всё равно проиграл"
- "Мой портфель как русская рулетка: каждый раз надеешься на лучшее, но проигрываешь"
- "Купил токен из-за крутого логотипа. Теперь у меня крутой логотип в памяти и пустой кошелёк"
- "Мой стейкинг как подписка на журнал: плачу регулярно, но полезного контента мало"
- "Крипта - это когда ты покупаешь надежду, но получаешь опыт"
- "Говорят, не клади все яйца в одну корзину. Я разложил по корзинам, но яйца разбились во всех"
- "Мой трейдинг как диета: начинаю с понедельника, срываюсь во вторник, начинаю заново в понедельник"
- "Купил токен на слух от друга. Друг теперь не друг, а токен всё ещё токен"
- "Мой график как жизнь в России: обещают стабильность, но видишь только перемены к худшему"
- "Крипта научила меня терпению: теперь я терпеливо жду, когда вернутся хотя бы вложения"
- "Говорят, диверсифицируй. Я диверсифицировал убытки так хорошо, что теперь теряю везде"

Используй эти примеры как вдохновение для создания РАЗНЫХ стилей и углов в стиле русских шуток про криптовалюту, TON, блокчейн и крипто-экосистему. Каждый пост должен быть уникальным. Можешь использовать юмор, иронию, самоиронию, сарказм, метафоры - но каждый раз по-разному. Все шутки должны быть связаны с криптовалютой, TON, блокчейном, трейдингом, кошельками, дефай, стейкингом, NFT, подарками, Дуровым, Рохманом и т.д."""
    
    def __init__(self, api_key: str, api_url: str):
        self.api_key = api_key
        self.api_url = api_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def generate_post(self, system_prompt: str, news: Optional[List[str]] = None, price_data: Optional[dict] = None, user_prompt: Optional[str] = None) -> Optional[str]:
        """Генерирует пост используя DeepSeek API"""
        try:
            # Если передан user_prompt напрямую, используем его
            if user_prompt:
                final_user_prompt = user_prompt
            # Если есть данные о цене, создаём пост про цену TON
            elif price_data:
                change_sign = "+" if price_data.get("change_24h", 0) >= 0 else ""
                price_text = f"""Текущая цена TON:
- ${price_data.get('usd', 0):.4f} USD
- {price_data.get('rub', 0):.2f} RUB
- Изменение за 24ч: {change_sign}{price_data.get('change_24h', 0):.2f}%
- Объём за 24ч: ${price_data.get('volume_24h', 0):,.0f}"""

                final_user_prompt = f"""Вот данные о цене TON:
{price_text}

Создай пост обязательно по этой структуре:

Укажи цену только с предлогом "по":
- "тон по ${price_data.get('usd', 0):.4f}"
- "цена тона по {price_data.get('rub', 0):.2f} руб"
- никогда не пиши "на"
Укажи изменение за 24ч: ({change_sign}{price_data.get('change_24h', 0):.2f}%)
Добавь 1 предложение токсичной реакции: паранойя, издёвка, усталость, бред - но без финансовых советов

Правила:

Обязательно используй слово "ТОН", "тон" или "TON"
Общий объём: 1-2 предложения
Точки почти не ставь, запятые - в ~50%
Мат - иногда
Никаких шаблонов: каждый раз - новая интонация
Не повторяй фразы вроде "хомяки радуются" или "скоро луна"

Пример:
тон по 6.88 -1.3%
опять сливают когда я собрался купить сайлор муна

Пиши только пост. Без вступлений."""
            # Если есть новости, используем их для генерации поста
            elif news and len(news) > 0:
                # Выбираем только одну случайную новость
                selected_news = random.choice(news)
                
                # Используем общие примеры стилей
                style_examples = self.STYLE_EXAMPLES
                
                final_user_prompt = f"""Вот новость:
{selected_news}

Создай пост в стиле ГОЯ по следующей структуре:

1. НОВОСТЬ (1-2 предложения):
МИНИМАЛЬНО изменяй оригинал новости. Сохрани структуру, стиль, имена, цифры, важные детали. Перескажи максимально близко к оригиналу, только если нужно очень слегка сократить. НЕ перефразируй сильно, НЕ меняй формулировки радикально. Просто немного сократи, если новость очень длинная, но сохрани суть и ключевые факты точно так, как в оригинале.

2. КОММЕНТАРИЙ/ШУТКА (1-2 предложения):
КРИТИЧЕСКИ ВАЖНО - ЭТО САМАЯ ВАЖНАЯ ЧАСТЬ:

ШАГ 1: ВНИМАТЕЛЬНО ПРОЧИТАЙ НОВОСТЬ ВЫШЕ И ОПРЕДЕЛИ ЕЁ СУТЬ
- Что именно произошло? (банк объявил о кошельке? компанию купили? встретились политики? токены выкупают?)
- Кто главные действующие лица? (JPMorgan? Сенат? Coincheck? Сэйлор?)
- Какие конкретные детали? (суммы, сроки, названия, ссылки)

ШАГ 2: СОЗДАЙ ШУТКУ НА ОСНОВЕ КОНКРЕТНО ЭТОЙ НОВОСТИ
- НЕ используй универсальные шаблоны типа "крипта скам" или "все куплено"
- Свяжи шутку С КОНКРЕТНЫМ содержанием новости:
  * Если новость про банки (JPMorgan, Morgan Stanley, Citi) → шутка про то, КАК банки лезут в крипту, пытаются контролировать, делают централизованные кошельки, или как они всегда хотят нажиться
  * Если новость про покупку компании (Coincheck покупает 3iQ) → шутка про то, КАК покупают компании за миллионы, чтобы потом накачать токены и слить, или про манипуляции
  * Если новость про встречи/переговоры (Сэйлор встретился с сенатором) → шутка про то, КАК политики и бизнес договариваются, про коррупцию, обещания, или как все уже решили без нас
  * Если новость про выкуп токенов (Optimism выкупает OP) → шутка про то, КАК выкупают, чтобы манипулировать ценой, или про то, что дегенераты купятся
  * Если новость про Венесуэлу/войну → шутка про то, КАК крипта связана с войной, или про то, что политики используют крипту для своих целей

ШАГ 3: ИСПОЛЬЗУЙ СТИЛЬ РУССКИХ ШУТОК ИЗ ПРИМЕРОВ НИЖЕ
- Философские размышления: "Если банки лезут в крипту, значит они поняли, что контроль теряют. Типично для них."
- Самоирония: "Смотрю на эту новость и думаю - а я до сих пор не могу разобраться с TON Wallet"
- Ирония и сарказм: "Банки делают крипто-кошельки. Скоро они будут взимать плату за каждую транзакцию. Как всегда."
- Метафоры: "Покупка компании за $112 млн в крипте - это как купить квартиру, но не знать, есть ли там вода"

ПРИМЕРЫ ПРАВИЛЬНОЙ СВЯЗИ НОВОСТИ С ШУТКОЙ:
- Новость: "JPMorgan сказал, что крипто-сейл-офф может быть близок к дну"
  → Шутка: "Опять эти банковские аналитики пытаются предсказать, когда я потеряю последние деньги. Классика."
  
- Новость: "Coincheck покупает компанию 3iQ за $112 млн"
  → Шутка: "Купили компанию за миллионы, чтобы потом продать токены на миллиарды. Математика скама в действии."
  
- Новость: "Майкл Сэйлор встретился с сенатором для обсуждения внедрения BTC"
  → Шутка: "Политики обсуждают крипту. Скоро начнут продавать право на майнинг. Или уже продают, просто мы не знаем."
  
- Новость: "Optimism Foundation предложил использовать 50% выручки Superchain для выкупа токенов OP"
  → Шутка: "Выкупают токены, чтобы поднять цену и слить дебилам. Классическая схема, но хомяки все равно купятся."

Правила:

Общий объём: 3-5 предложений (новость + мнение/шутка)
Пиши как в голосовом - рвано, без вылизанности
Точки почти не ставь, запятые - в ~50% случаев
Мат - умеренно, только для акцента

{style_examples}

ВАЖНО: В части "КОММЕНТАРИЙ/ШУТКА":
- Используй стиль русских шуток из примеров выше (философские размышления, самоирония, ирония, метафоры)
- НО: каждый раз создавай НОВУЮ уникальную шутку, связанную именно с ЭТОЙ новостью
- НЕ копируй готовые шутки из примеров - используй их только как вдохновение для стиля
- Анализируй КОНКРЕТНОЕ содержание новости и обыгрывай его

СТРОГО ЗАПРЕЩЕНО:
- Использовать универсальные шаблоны, не связанные с новостью ("крипта скам", "все куплено", "скоро луна")
- Копировать готовые шутки из примеров дословно
- Использовать темы: "пепе", "пепе мем", "pepe", "мемкоины", "мемкоин", "сайлор мун", "sailor moon", "газ", "gas fee", "газовые сборы"
- Упоминать "газ" в любом контексте
- Упоминать "пепе" в любом контексте (кроме случая, когда это имя собственное в новости)
- Повторять одни и те же фразы и конструкции
- Использовать шаблоны типа "хомяки радуются", "скоро луна", "пепе на луну", "газ съел всё"

ОБЯЗАТЕЛЬНО:
- Анализируй КОНКРЕТНО эту новость выше и создавай шутку на её основе
- Используй разные темы и углы: комиссии, аирдропы, скам, блокчейн, дефай, стейкинг, кошельки, трейдинг, NFT, подарки, Дуров, Рохман, банки, коррупция, манипуляции
- Связывай новость с TON/криптой ЛОГИЧНО, но каждый раз по-разному
- Используй юмор, иронию, самоиронию, сарказм, метафоры в стиле русских шуток - но каждый раз НОВЫЕ, связанные с конкретной новостью

Не впихивай TON насильно, если новость про Венесуэлу или ЕС - но можешь связать через страх, иронию или сравнение
Никогда не упоминай @markettwits и производные
Сохраняй ключевую информацию из новости (имена, цифры, факты) - пост должен быть понятным

Пиши только пост в формате: новость, затем мнение/шутка. Без вступлений. Подвал с реакциями добавится автоматически."""
            else:
                # Если новостей нет, генерируем обычный пост
                post_types = [
                    "новости TON",
                    "мем про крипту",
                    "реакция на падение или рост рынка",
                    "умная мысль, но поданная как прикол",
                    "новость про кого-то из твоей памяти (рохман, фриман, тайлер, вуди, мета и тд)",
                    "новость про TON-экосистему или Telegram-боты",
                    "высмеивание скамов и хомяков",
                    "рассказ про что-то из крипты (но короткий)"
                ]
                
                selected_type = random.choice(post_types)
                
                # Случайно решаем, будет ли это короткий пост (1-2 предложения) или рассказ (4-6 предложений)
                is_story = random.random() < 0.2  # 20% вероятность рассказа
                
                if is_story:
                    length_instruction = "рассказ длиной 4-6 предложений"
                else:
                    length_instruction = "1-2 предложения максимум"
                
                final_user_prompt = f"""Создай уникальный пост про TON, крипту, Дурова, Рохмана, подарки, скам или Стенку.
Тип поста: {selected_type}
Длина: {length_instruction}

Правила:

Пиши как в голосовом - коротко, рвано, с эмоцией
3-5 предложений (должно быть понятно, о чём пост)
Точки почти не ставь, запятые - в ~50%
Мат - умеренно
Используй конкретику из контекста, но каждый раз по-разному обыгрывай темы TON, скама, Дурова, подарков
Никогда не повторяй одни и те же конструкции и фразы
Пиши как живой человек - разные интонации, разные углы, разные реакции на одни и те же темы
Каждый пост должен быть уникальным - даже про одну и ту же тему пиши по-разному

Пиши только пост. Без вступлений."""
            
            # Генерируем уникальный идентификатор для нового "чата" (каждый пост - новый разговор)
            chat_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            
            # Добавляем явное указание, что это новый независимый запрос без истории
            independent_prompt = f"""{final_user_prompt}

КРИТИЧЕСКИ ВАЖНО: Это НОВЫЙ независимый запрос (ID: {chat_id}, время: {timestamp}).
НЕ используй информацию из предыдущих постов или разговоров.
Каждая новость обрабатывается в НОВОМ отдельном чате.
Генерируй пост ТОЛЬКО на основе предоставленной новости выше - анализируй ЕЁ конкретное содержание и создавай уникальный комментарий, связанный именно с ЭТОЙ новостью."""
            
            # Добавляем уникальный идентификатор в system prompt для каждого нового "чата"
            unique_system_prompt = f"""{system_prompt}

[ТЕКУЩИЙ РАЗГОВОР]
ID разговора: {chat_id}
Время: {timestamp}
Это НОВЫЙ независимый разговор. Предыдущие посты и разговоры не существуют.

КРИТИЧЕСКИ ВАЖНО:
- Анализируй КОНКРЕТНО ТУ новость, которая указана в запросе пользователя
- Создавай комментарий/шутку на основе СОДЕРЖАНИЯ ЭТОЙ конкретной новости
- НЕ используй универсальные шаблоны или копии из предыдущих ответов
- Каждый комментарий должен быть уникальным и связанным с конкретной новостью"""
            
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": unique_system_prompt},
                    {"role": "user", "content": independent_prompt}
                ],
                "temperature": 1.0,  # Увеличена для большего разнообразия и уникальности комментариев
                "max_tokens": 300
            }
            
            logger.info(f"Генерирую пост в НОВОМ чате (ID: {chat_id}, время: {timestamp})")
            
            logger.info("Отправка запроса к DeepSeek API...")
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                post_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                if post_content:
                    logger.info("Пост успешно сгенерирован")
                    return post_content.strip()
                else:
                    logger.error("Пустой ответ от API")
                    return None
            else:
                logger.error(f"Ошибка API: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к DeepSeek API: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при генерации поста: {e}")
            return None


class TelegramChannelBot:
    """Бот для автоматической публикации постов в Telegram-канал"""
    
    def __init__(self):
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.channel_id = config.CHANNEL_ID
        self.deepseek = DeepSeekClient(
            api_key=config.DEEPSEEK_API_KEY,
            api_url=config.DEEPSEEK_API_URL
        )
        self.news_parser = NewsParser(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH
        )
        self.price_fetcher = PriceFetcher(
            api_url=config.COINGECKO_API_URL,
            coin_id=config.TON_COIN_ID
        )
        self.image_generator = NanoBananaImageGenerator(
            api_key=config.NANOBANANA_API_KEY,
            api_url=config.NANOBANANA_API_URL
        )
        # Загружаем сохраненное состояние
        self._load_state()
        
        self.posts_today = 0
        self.posts_target = config.POSTS_PER_DAY  # Количество постов на основе новостей
        self.reset_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.last_news_check = None
        self.cached_news = []
        self.last_price_post_morning = None  # Время последнего утреннего поста про цену
        self.last_price_post_evening = None  # Время последнего вечернего поста про цену
        self.msk_tz = timezone(timedelta(hours=3))  # МСК (UTC+3)
        
        # Хеши уже опубликованных постов (для предотвращения дубликатов)
        self.published_posts_hashes = set()
        if hasattr(self, '_loaded_hashes'):
            self.published_posts_hashes = self._loaded_hashes
        
        # ID новостей, из которых уже были опубликованы посты (для предотвращения повторной публикации)
        self.published_news_ids = set()
        if hasattr(self, '_loaded_news_ids'):
            self.published_news_ids = self._loaded_news_ids
        
        # Для обработки команды /p
        self.pending_posts = {}  # {user_id: {'original_text': str, 'generated_text': str}}
        # Для обработки команды /genetat
        self.pending_images = {}  # {user_id: {'mode': 'generate'|'edit', 'waiting_for_prompt': bool, 'waiting_for_image': bool}}
        self.application = None  # Application для обработки команд
    
    def generate_image_prompt(self, post_text: str, is_price_post: bool = False, price_data: Optional[dict] = None) -> str:
        """Генерирует промпт для создания изображения на основе текста поста"""
        if is_price_post and price_data:
            # Для постов с ценой - мем с графиком
            change_24h = price_data.get('change_24h', 0)
            price_usd = price_data.get('usd', 0)
            
            if change_24h > 5:
                trend_desc = "steep green upward chart line, bullish momentum"
            elif change_24h > 0:
                trend_desc = "green upward chart line, positive trend"
            elif change_24h < -5:
                trend_desc = "steep red downward chart line, bearish crash"
            elif change_24h < 0:
                trend_desc = "red downward chart line, negative trend"
            else:
                trend_desc = "flat horizontal chart line, stable price"
            
            price_formatted = f"{price_usd:.2f}"
            prompt = f"""CRITICAL: ABSOLUTELY NO TEXT IN ANY LANGUAGE - no words, no letters, no numbers, no writing, no captions, no text overlay, no subtitles, no labels, no signs, no symbols that form words, no Cyrillic, no Latin, no Chinese, no Japanese, no Arabic, no any alphabet characters, no digits, no text on screens, no text on papers, no text on signs, no text on banners, no text on charts, no text anywhere, completely clean image without any text elements whatsoever, pure visual content only. 
realistic photo, cryptocurrency meme, professional trading screen showing TON coin price chart, {trend_desc}, 
trading terminal with multiple monitors, price graphs and financial data, realistic office environment, 
photorealistic, high quality, realistic lighting, no cartoon, no animation, real photography style, 
modern trading desk setup, serious financial meme, cinematic quality, high resolution"""
        else:
            # Для обычных постов - мем на основе текста
            # Упрощаем текст для промпта (убираем лишние символы, ограничиваем длину)
            simplified_text = post_text[:150].replace('\n', ' ').replace('@', '').replace('#', '').strip()
            
            # Извлекаем ключевые слова для более точной генерации
            keywords = simplified_text.split()[:10]  # Берем первые 10 слов
            
            prompt = f"""CRITICAL: ABSOLUTELY NO TEXT IN ANY LANGUAGE - no words, no letters, no numbers, no writing, no captions, no text overlay, no subtitles, no labels, no signs, no symbols that form words, no Cyrillic, no Latin, no Chinese, no Japanese, no Arabic, no any alphabet characters, no digits, no text on screens, no text on papers, no text on signs, no text on banners, no text on charts, no text anywhere, completely clean image without any text elements whatsoever, pure visual content only. 
realistic photo, meme style, {simplified_text}, 
photorealistic, high quality, realistic lighting, no cartoon style, no animation, real photo aesthetic, 
professional photography, cinematic quality, high resolution, detailed, sharp focus"""
        
        return prompt
    
    def _determine_post_tone(self, content: str) -> str:
        """Определяет тон поста и возвращает эмодзи (клоун для негатива/рофла, огонь для позитива)"""
        content_lower = content.lower()
        
        # Ключевые слова для определения тона
        negative_words = ['скам', 'лох', 'пиздец', 'хуй', 'дерьмо', 'говно', 'упал', 'упала', 'крах', 
                         'обман', 'развод', 'слил', 'слила', 'проиграл', 'проиграла', 'плохо', 
                         'плохая', 'плохой', 'плохое', 'ужас', 'кошмар', 'провал', 'провалился',
                         'негатив', 'негативный', 'негативная', 'негативное', 'зло', 'злой', 'злая',
                         'рофл', 'мем', 'прикол', 'шутка', 'смешно', 'смешной', 'смешная']
        positive_words = ['вырос', 'выросла', 'выросли', 'растет', 'растут', 'рост', 'закупился', 
                         'закупилась', 'закупились', 'покупка', 'покупай', 'покупать', 'хорошо',
                         'хорошая', 'хороший', 'хорошее', 'отлично', 'круто', 'крутая', 'крутой',
                         'позитив', 'позитивный', 'позитивная', 'позитивное', 'успех', 'успешный',
                         'победа', 'выиграл', 'выиграла', 'выиграли', 'молодец', 'молодцы']
        
        # Определяем тон поста
        negative_count = sum(1 for word in negative_words if word in content_lower)
        positive_count = sum(1 for word in positive_words if word in content_lower)
        
        # Если больше негативных слов или равное количество - используем 🤡, иначе 🔥
        if negative_count >= positive_count:
            return "🤡"
        else:
            return "🔥"
    
    def _generate_opinion_text(self, content: str, emoji: str) -> Optional[str]:
        """Генерирует текст мнения через DeepSeek на основе содержания поста"""
        try:
            # Генерируем уникальный идентификатор для нового "чата" (каждая реакция - новый разговор)
            chat_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            
            system_prompt = config.SYSTEM_PROMPT
            
            # Добавляем уникальный идентификатор в system prompt для каждого нового "чата"
            unique_system_prompt = f"""{system_prompt}

[ТЕКУЩИЙ РАЗГОВОР]
ID разговора: {chat_id}
Время: {timestamp}
Это НОВЫЙ независимый разговор. Предыдущие посты и разговоры не существуют.
"""
            
            user_prompt = f"""Вот пост:
{content}

Добавь КОРОТКУЮ реакцию (1-5 слов, максимум 7 слов) в стиле ГОЯ:

ВАЖНО: Это НОВЫЙ независимый запрос (ID: {chat_id}, время: {timestamp}). НЕ используй информацию из предыдущих постов или разговоров.

Эмодзи для этого поста: {emoji}
- Если эмодзи клоун - это негативный/рофл пост, реакция должна быть токсичной, ироничной
- Если эмодзи огонь - это позитивный/крутой пост, реакция должна быть более позитивной, но все равно в токсичном стиле

КРИТИЧЕСКИ ВАЖНО:
- Только 1-5 слов (максимум 7)
- Без предложений, только короткая фраза
- БЕЗ ЭМОДЗИ в ответе (эмодзи будет добавлено автоматически)
- Только текст, без символов эмодзи
- Токсично, иронично, но коротко
- Без повторов и шаблонов
- СТРОГО ЗАПРЕЩЕНО использовать: "пепе", "pepe", "мемкоины", "мемкоин", "сайлор мун", "sailor moon", "газ", "gas fee"
- Используй другие темы: комиссии, скам, блокчейн, дефай, стейкинг, NFT, подарки, Дуров, аирдропы, кошельки, трейдинг

Примеры реакций (БЕЗ ЭМОДЗИ, только текст):
- "крипта скам" (2 слова)
- "закупился" (1 слово)
- "скамеры наебали" (2 слова)
- "дроп когда" (2 слова)
- "тон в помойку" (3 слова)
- "комиссии съели" (2 слова)
- "скам как всегда" (3 слова)

Пиши только текст реакции (1-5 слов), БЕЗ эмодзи, БЕЗ вступлений, БЕЗ предложений."""
            
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": unique_system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.9,
                "max_tokens": 15  # Уменьшено до 15 токенов для реакций 1-5 слов
            }
            
            logger.info(f"Генерирую реакцию в НОВОМ чате (ID: {chat_id}, время: {timestamp})")
            
            response = requests.post(
                self.deepseek.api_url,
                headers=self.deepseek.headers,
                json=payload,
                timeout=15
            )
            
            if response.status_code == 200:
                result = response.json()
                generated_text = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                
                logger.info(f"DeepSeek вернул текст мнения: {generated_text}")
                
                # Очищаем текст от лишних символов и кавычек
                generated_text = generated_text.strip('"').strip("'").strip()
                
                # Убираем эмодзи из ответа (мы добавим свое)
                emoji_chars = ['🤡', '🔥', '😎', '😅', '😂', '😭', '😱', '🤔', '😤', '😡', '💀', '🎉', '🚀', '💰', '💸']
                for emoji_char in emoji_chars:
                    generated_text = generated_text.replace(emoji_char, '').strip()
                
                # Убираем точки и другие знаки препинания в конце (реакция должна быть без предложений)
                generated_text = generated_text.rstrip('.,!?;:').strip()
                
                # Убираем тире и другие разделители в начале
                generated_text = generated_text.lstrip('-–—•').strip()
                
                # Обрезаем до максимум 7 слов (для реакций 1-5 слов)
                words = generated_text.split()
                if len(words) > 7:
                    logger.warning(f"Реакция слишком длинная ({len(words)} слов), обрезаю до 7 слов")
                    generated_text = ' '.join(words[:7])
                
                # Проверяем на запрещенные слова (наркотики, вещества)
                forbidden_words = ['метамфетамин', 'мефедрон', 'амфетамин', 'кокаин', 'героин', 'лсд', 'мдма', 
                                 'экстази', 'спайс', 'соль', 'кристалл', 'скорость', 'фен', 'амф', 'меф']
                generated_lower = generated_text.lower()
                
                for word in forbidden_words:
                    if word in generated_lower:
                        logger.warning(f"Обнаружено запрещенное слово '{word}' в тексте мнения, заменяю на нейтральный вариант")
                        # Заменяем на нейтральные варианты в зависимости от эмодзи (короткие варианты)
                        if emoji == "🤡":
                            generated_text = "крипта скам"
                        else:
                            generated_text = "закупился"
                        break
                
                if generated_text:
                    final_text = f"\n\n{emoji} - {generated_text}"
                    logger.info(f"Форматированный текст мнения: {final_text}")
                    return final_text
                else:
                    logger.warning("Сгенерированный текст пустой после очистки")
            else:
                logger.warning(f"DeepSeek вернул статус {response.status_code}: {response.text}")
            
            logger.warning("Не удалось сгенерировать текст мнения через DeepSeek")
            return None
        except Exception as e:
            logger.warning(f"Ошибка при генерации текста мнения: {e}")
            return None
    
    def _add_opinion_text(self, content: str) -> str:
        """Добавляет текст с вариантом мнения в конец поста (клоун для негатива/рофла, огонь для позитива)"""
        logger.info(f"_add_opinion_text вызван. Длина контента: {len(content)}")
        try:
            # Определяем эмодзи на основе тона
            logger.info("Определяю тон поста...")
            emoji = self._determine_post_tone(content)
            logger.info(f"Определен тон поста: {emoji}")
            
            # Генерируем текст мнения через DeepSeek
            opinion_text = self._generate_opinion_text(content, emoji)
            
            # Если не удалось сгенерировать, используем простой вариант (короткий)
            if not opinion_text:
                logger.warning("Не удалось сгенерировать текст мнения через DeepSeek, используем запасной вариант")
                if emoji == "🤡":
                    opinion_text = "\n\n🤡 - крипта скам"  # 2 слова
                else:
                    opinion_text = "\n\n🔥 - закупился"  # 1 слово
            else:
                logger.info(f"Текст мнения успешно сгенерирован: {opinion_text.strip()}")
            
            result = content + opinion_text
            logger.info(f"Добавлен текст мнения к посту. Длина финального поста: {len(result)} символов")
            logger.info(f"Последние 100 символов финального поста: {result[-100:]}")
            return result
        except Exception as e:
            logger.error(f"Ошибка при добавлении текста мнения: {e}", exc_info=True)
            # В случае ошибки возвращаем оригинальный контент без мнения
            logger.warning("Возвращаю оригинальный контент без мнения из-за ошибки")
            return content
    
    def _get_post_hash(self, content: str) -> str:
        """Вычисляет хеш содержимого поста для проверки дубликатов"""
        # Нормализуем текст (убираем лишние пробелы, приводим к нижнему регистру)
        normalized = ' '.join(content.strip().lower().split())
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    def _is_duplicate(self, content: str) -> bool:
        """Проверяет, был ли уже опубликован такой пост"""
        post_hash = self._get_post_hash(content)
        return post_hash in self.published_posts_hashes
    
    def _mark_as_published(self, content: str, news_id: Optional[int] = None):
        """Помечает пост как опубликованный"""
        post_hash = self._get_post_hash(content)
        self.published_posts_hashes.add(post_hash)
        
        # Если указан ID новости, помечаем её как использованную
        if news_id:
            self.published_news_ids.add(news_id)
            logger.debug(f"Новость с ID {news_id} помечена как использованная для публикации")
        
        self._save_state()
    
    def _load_state(self):
        """Загружает сохраненное состояние бота из файла"""
        state_file = 'bot_state.json'
        try:
            if os.path.exists(state_file):
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    
                    # Загружаем время последнего поста
                    if state.get('last_post_time'):
                        try:
                            self.last_post_time = datetime.fromisoformat(state['last_post_time'])
                            logger.info(f"Загружено время последнего поста: {self.last_post_time}")
                        except Exception as e:
                            logger.warning(f"Не удалось загрузить last_post_time: {e}")
                            self.last_post_time = None
                    else:
                        self.last_post_time = None
                    
                    # Загружаем хеши опубликованных постов
                    if state.get('published_posts_hashes'):
                        self._loaded_hashes = set(state['published_posts_hashes'])
                        logger.info(f"Загружено {len(self._loaded_hashes)} хешей опубликованных постов")
                    else:
                        self._loaded_hashes = set()
                    
                    # Загружаем ID новостей, из которых уже были опубликованы посты
                    if state.get('published_news_ids'):
                        self._loaded_news_ids = set(state['published_news_ids'])
                        logger.info(f"Загружено {len(self._loaded_news_ids)} ID новостей, из которых уже были опубликованы посты")
                    else:
                        self._loaded_news_ids = set()
            else:
                self.last_post_time = None
                self._loaded_hashes = set()
                self._loaded_news_ids = set()
                logger.info("Файл состояния не найден, начинаем с чистого листа")
        except Exception as e:
            logger.warning(f"Не удалось загрузить состояние: {e}")
            self.last_post_time = None
            self._loaded_hashes = set()
            self._loaded_news_ids = set()
    
    def _save_state(self):
        """Сохраняет текущее состояние бота в файл"""
        state_file = 'bot_state.json'
        try:
            state = {
                'last_post_time': self.last_post_time.isoformat() if self.last_post_time else None,
                'published_posts_hashes': list(self.published_posts_hashes),
                'published_news_ids': list(self.published_news_ids)
            }
            
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Не удалось сохранить состояние: {e}")
    
    async def publish_post(self, content: str, price_data: Optional[dict] = None, is_price_post: bool = False, news_id: Optional[int] = None) -> bool:
        """Публикует пост в канал с изображением (автоматическая генерация)"""
        # Проверяем на дубликаты по хешу поста
        if self._is_duplicate(content):
            logger.warning(f"Попытка опубликовать дубликат поста. Пропускаю.")
            return False
        
        # Проверяем, не публиковали ли уже пост из этой новости
        if news_id and news_id in self.published_news_ids:
            logger.warning(f"Попытка опубликовать пост из новости, которая уже была использована (ID: {news_id}). Пропускаю.")
            return False
        
        try:
            # Генерируем промпт для изображения
            image_prompt = self.generate_image_prompt(content, is_price_post=is_price_post, price_data=price_data)
            
            logger.info(f"Генерирую изображение для поста. Промпт: {image_prompt[:100]}...")
            
            # Генерируем изображение
            image_url = await self.image_generator.generate_image_async(
                prompt=image_prompt,
                mode='generate',
                image_urls=None
            )
            
            # Добавляем текст с вариантами мнений к посту
            content_with_opinion = self._add_opinion_text(content)
            
            if image_url:
                logger.info(f"Изображение сгенерировано: {image_url}")
                # Отправляем изображение с текстом поста как caption
                await self.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=image_url,
                    caption=content_with_opinion,
                    parse_mode=None
                )
                logger.info("Пост с изображением успешно опубликован в канал")
            else:
                logger.warning("Не удалось сгенерировать изображение, публикую только текст")
                # Если не удалось сгенерировать изображение, отправляем только текст
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=content_with_opinion,
                    parse_mode=None
                )
                logger.info("Пост без изображения успешно опубликован в канал")
            
            # Обновляем last_post_time только для обычных постов, не для постов про цену
            # Посты про цену публикуются в фиксированное время (11:00 и 22:00) и не должны влиять на интервал обычных постов
            if not is_price_post:
                self.last_post_time = datetime.now()
            self.posts_today += 1
            self._mark_as_published(content, news_id=news_id)
            return True
        except TelegramError as e:
            logger.error(f"Ошибка при публикации поста: {e}")
            # Попытка отправить только текст в случае ошибки с изображением
            try:
                content_with_opinion = self._add_opinion_text(content)
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=content_with_opinion,
                    parse_mode=None
                )
                logger.info("Пост опубликован без изображения из-за ошибки")
                # Обновляем last_post_time только для обычных постов, не для постов про цену
                if not is_price_post:
                    self.last_post_time = datetime.now()
                self.posts_today += 1
                self._mark_as_published(content, news_id=news_id)
                return True
            except Exception as e2:
                logger.error(f"Ошибка при публикации поста без изображения: {e2}")
                return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при публикации: {e}")
            # Попытка отправить только текст
            try:
                content_with_opinion = self._add_opinion_text(content)
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=content_with_opinion,
                    parse_mode=None
                )
                logger.info("Пост опубликован без изображения из-за ошибки")
                # Обновляем last_post_time только для обычных постов, не для постов про цену
                if not is_price_post:
                    self.last_post_time = datetime.now()
                self.posts_today += 1
                self._mark_as_published(content)
                return True
            except Exception as e2:
                logger.error(f"Ошибка при публикации поста без изображения: {e2}")
                return False
    
    async def publish_post_manual(self, content: str, image_url: Optional[str] = None) -> bool:
        """Публикует пост в канал (для команды /p, с опциональным изображением)"""
        logger.info(f"publish_post_manual вызван. Длина контента: {len(content)}, есть image_url: {image_url is not None}")
        
        # Проверяем на дубликаты
        if self._is_duplicate(content):
            logger.warning(f"Попытка опубликовать дубликат поста вручную. Пропускаю.")
            return False
        
        try:
            # Добавляем текст с вариантами мнений к посту
            logger.info("Вызываю _add_opinion_text...")
            content_with_opinion = self._add_opinion_text(content)
            logger.info(f"_add_opinion_text вернул текст длиной {len(content_with_opinion)} символов (было {len(content)} символов)")
            
            if image_url:
                # Отправляем изображение с текстом поста как caption
                logger.info(f"Отправляю фото с текстом в канал. Длина текста: {len(content_with_opinion)} символов")
                logger.info(f"Последние 150 символов текста перед отправкой: {content_with_opinion[-150:]}")
                await self.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=image_url,
                    caption=content_with_opinion,
                    parse_mode=None
                )
                logger.info("Пост с изображением успешно опубликован в канал (ручная публикация)")
            else:
                # Отправляем только текст
                logger.info(f"Отправляю текст в канал. Длина текста: {len(content_with_opinion)} символов")
                logger.info(f"Последние 150 символов текста перед отправкой: {content_with_opinion[-150:]}")
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=content_with_opinion,
                    parse_mode=None
                )
                logger.info("Пост без изображения успешно опубликован в канал (ручная публикация)")
            
            self.last_post_time = datetime.now()
            self.posts_today += 1
            self._mark_as_published(content)
            return True
        except TelegramError as e:
            logger.error(f"Ошибка при публикации поста: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при публикации: {e}")
            return False
    
    def should_publish_now(self) -> bool:
        """Проверяет, нужно ли публиковать пост сейчас"""
        now = datetime.now()
        
        # Сброс счётчика постов в начале нового дня
        if now >= self.reset_time + timedelta(days=1):
            self.posts_today = 0
            self.posts_target = config.POSTS_PER_DAY
            self.reset_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            logger.info(f"Новый день. Цель на сегодня: {self.posts_target} постов")
        
        # Проверяем, достигли ли мы цели на сегодня
        if self.posts_today >= self.posts_target:
            return False
        
        # Проверяем интервал между постами
        if self.last_post_time:
            time_since_last = (now - self.last_post_time).total_seconds() / 3600  # в часах
            min_interval = config.MIN_HOURS_BETWEEN_POSTS
            max_interval = config.MAX_HOURS_BETWEEN_POSTS
            
            if time_since_last < min_interval:
                return False
        
        return True
    
    async def get_fresh_news(self) -> List[str]:
        """Получает свежие новости из канала (для обратной совместимости)"""
        news_items = await self.get_new_relevant_news_items()
        return [item['text'] for item in news_items]
    
    async def get_new_relevant_news_items(self) -> List[dict]:
        """Получает новые релевантные новости из канала"""
        try:
            logger.info(f"Проверяю новые посты из канала @{config.NEWS_CHANNEL}...")
            news_items = await self.news_parser.get_new_relevant_news(
                config.NEWS_CHANNEL,
                limit=100  # Проверяем последние 100 постов (увеличено для лучшего покрытия)
            )
            
            if news_items:
                logger.info(f"Найдено {len(news_items)} новых релевантных постов")
            
            return news_items
        except Exception as e:
            logger.error(f"Ошибка при получении новостей: {e}")
            return []
    
    async def check_and_publish_new_news(self) -> bool:
        """Проверяет новые посты и публикует подходящие (без ограничения количества)"""
        # Проверяем только минимальный интервал между постами
        now = datetime.now()
        if self.last_post_time:
            time_since_last = (now - self.last_post_time).total_seconds() / 60  # в минутах
            min_interval_minutes = config.MIN_HOURS_BETWEEN_POSTS * 60
            
            # Используем <= вместо < для небольшого допуска на погрешность времени (0.1 минуты = 6 секунд)
            if time_since_last < (min_interval_minutes - 0.1):
                logger.info(f"⏳ Слишком рано для публикации. Прошло {time_since_last:.1f} минут, нужно минимум {min_interval_minutes} минут")
                return False
            else:
                logger.info(f"✅ Прошло {time_since_last:.1f} минут с последнего поста, можно публиковать (минимум {min_interval_minutes} минут)")
        
        # Получаем новые релевантные новости
        news_items = await self.get_new_relevant_news_items()
        
        if not news_items:
            return False
        
        # Фильтруем новости, из которых уже были опубликованы посты
        fresh_news_items = [item for item in news_items if item.get('id') not in self.published_news_ids]
        
        if not fresh_news_items:
            logger.info("Все найденные новости уже были использованы для публикации постов")
            return False
        
        # Берем самую свежую новость, из которой еще не публиковали
        latest_news = fresh_news_items[0]
        
        logger.info(f"Найдена новая релевантная новость (ID: {latest_news.get('id')}). Публикую...")
        
        # Генерируем пост на основе новости (в executor, чтобы не блокировать event loop)
        try:
            loop = asyncio.get_event_loop()
            generate_func = partial(
                self.deepseek.generate_post,
                config.SYSTEM_PROMPT,
                news=[latest_news['text']]
            )
            post_content = await loop.run_in_executor(None, generate_func)
        except Exception as e:
            logger.error(f"Исключение при генерации поста из новости {latest_news.get('id')}: {e}")
            logger.exception(e)
            return False
        
        if post_content:
            # Дополнительная проверка: сгенерированный пост должен содержать крипто-термины
            if not self.news_parser.is_relevant_news(post_content):
                logger.warning(f"Сгенерированный пост не содержит крипто-терминов, пропускаю публикацию. Пост: {post_content[:200]}...")
                return False
            
            success = await self.publish_post(post_content, news_id=latest_news.get('id'))
            if success:
                logger.info(f"Пост на основе новости опубликован. Всего постов сегодня: {self.posts_today}")
                return True
            else:
                logger.error("Не удалось опубликовать пост")
                return False
        else:
            logger.error("Не удалось сгенерировать пост")
            return False
    
    def get_msk_time(self) -> datetime:
        """Получает текущее время в МСК"""
        return datetime.now(self.msk_tz)
    
    def should_post_price_morning(self) -> bool:
        """Проверяет, нужно ли публиковать утренний пост про цену (11:00 МСК)"""
        msk_now = self.get_msk_time()
        current_hour = msk_now.hour
        current_minute = msk_now.minute
        current_date = msk_now.date()
        
        # Проверяем, что сейчас около 11:00 МСК (с 11:00 до 11:15 для надёжности)
        if current_hour == config.PRICE_POST_MORNING_HOUR and current_minute <= 15:
            # Проверяем, что ещё не публиковали утренний пост сегодня
            if self.last_price_post_morning != current_date:
                logger.info(f"Время для утреннего поста про цену: {current_hour}:{current_minute:02d} МСК")
                return True
        
        return False
    
    def should_post_price_evening(self) -> bool:
        """Проверяет, нужно ли публиковать вечерний пост про цену (22:00 МСК)"""
        msk_now = self.get_msk_time()
        current_hour = msk_now.hour
        current_minute = msk_now.minute
        current_date = msk_now.date()
        
        # Проверяем, что сейчас около 22:00 МСК (с 22:00 до 22:15 для надёжности)
        if current_hour == config.PRICE_POST_EVENING_HOUR and current_minute <= 15:
            # Проверяем, что ещё не публиковали вечерний пост сегодня
            if self.last_price_post_evening != current_date:
                logger.info(f"Время для вечернего поста про цену: {current_hour}:{current_minute:02d} МСК")
                return True
        
        return False
    
    async def generate_and_publish_price(self, is_morning: bool = True) -> bool:
        """Генерирует и публикует пост про цену TON"""
        logger.info(f"Получаю цену TON для генерации {'утреннего' if is_morning else 'вечернего'} поста...")
        price_data = self.price_fetcher.get_ton_price()
        
        if not price_data:
            logger.error("Не удалось получить цену TON")
            return False
        
        logger.info(f"Генерирую {'утренний' if is_morning else 'вечерний'} пост про цену TON...")
        loop = asyncio.get_event_loop()
        generate_func = partial(self.deepseek.generate_post, config.SYSTEM_PROMPT, price_data=price_data)
        post_content = await loop.run_in_executor(None, generate_func)
        
        if post_content:
            success = await self.publish_post(post_content, price_data=price_data, is_price_post=True)
            if success:
                msk_now = self.get_msk_time()
                if is_morning:
                    self.last_price_post_morning = msk_now.date()
                    logger.info("Утренний пост про цену TON успешно опубликован")
                else:
                    self.last_price_post_evening = msk_now.date()
                    logger.info("Вечерний пост про цену TON успешно опубликован")
                return True
            else:
                logger.error("Не удалось опубликовать пост про цену")
                return False
        else:
            logger.error("Не удалось сгенерировать пост про цену")
            return False
    
    async def generate_and_publish(self) -> bool:
        """Генерирует и публикует пост на основе новостей"""
        if not self.should_publish_now():
            return False
        
        logger.info("Начинаю генерацию нового поста на основе новостей...")
        
        # Всегда используем новости для постов
        news = await self.get_fresh_news()
        
        if not news:
            logger.warning("Новости не получены, пропускаю публикацию")
            return False
        
        # Генерируем пост на основе новостей (в executor, чтобы не блокировать event loop)
        loop = asyncio.get_event_loop()
        generate_func = partial(self.deepseek.generate_post, config.SYSTEM_PROMPT, news=news)
        post_content = await loop.run_in_executor(None, generate_func)
        
        if post_content:
            success = await self.publish_post(post_content)
            if success:
                logger.info(f"Пост опубликован. Постов сегодня: {self.posts_today}/{self.posts_target}")
                logger.info("Пост создан на основе актуальных новостей")
                return True
            else:
                logger.error("Не удалось опубликовать пост")
                return False
        else:
            logger.error("Не удалось сгенерировать пост")
            return False
    
    async def run_loop(self):
        """Основной цикл работы бота"""
        msk_now = self.get_msk_time()
        logger.info("Бот запущен и готов к работе!")
        logger.info(f"Текущее время МСК: {msk_now.strftime('%H:%M:%S')}")
        logger.info(f"Цель на сегодня: {self.posts_target} постов на основе новостей")
        logger.info(f"Посты про цену: утром в {config.PRICE_POST_MORNING_HOUR}:00 МСК, вечером в {config.PRICE_POST_EVENING_HOUR}:00 МСК")
        
        # Проверяем и публикуем посты про цену, если нужно
        if self.should_post_price_morning():
            await self.generate_and_publish_price(is_morning=True)
        if self.should_post_price_evening():
            await self.generate_and_publish_price(is_morning=False)
        
        # Проверяем новые посты сразу при запуске
        await self.check_and_publish_new_news()
        
        while True:
            try:
                msk_now = self.get_msk_time()
                current_hour = msk_now.hour
                current_minute = msk_now.minute
                
                # Если приближается время публикации поста про цену, проверяем чаще
                is_near_morning_time = (current_hour == config.PRICE_POST_MORNING_HOUR - 1 and current_minute >= 55) or \
                                      (current_hour == config.PRICE_POST_MORNING_HOUR and current_minute <= 15)
                is_near_evening_time = (current_hour == config.PRICE_POST_EVENING_HOUR - 1 and current_minute >= 55) or \
                                      (current_hour == config.PRICE_POST_EVENING_HOUR and current_minute <= 15)
                
                if is_near_morning_time or is_near_evening_time:
                    # Проверяем каждую минуту в период публикации
                    check_interval = 60  # 1 минута
                    logger.debug(f"Период публикации поста про цену. Проверка каждую минуту. Текущее время МСК: {current_hour}:{current_minute:02d}")
                else:
                    # Проверяем новые посты каждые 30 минут (соответствует MIN_HOURS_BETWEEN_POSTS)
                    check_interval = config.MIN_HOURS_BETWEEN_POSTS * 60  # 30 минут
                
                await asyncio.sleep(check_interval)
                
                # ВАЖНО: Сначала проверяем новые посты, чтобы они не блокировались постами про цену
                # Проверяем новые релевантные посты и публикуем их
                await self.check_and_publish_new_news()
                
                # Затем проверяем, нужно ли опубликовать посты про цену (они имеют приоритет по времени)
                # Проверяем, нужно ли опубликовать утренний пост про цену (11:00 МСК)
                if self.should_post_price_morning():
                    logger.info("Начинаю публикацию утреннего поста про цену TON...")
                    await self.generate_and_publish_price(is_morning=True)
                
                # Проверяем, нужно ли опубликовать вечерний пост про цену (22:00 МСК)
                if self.should_post_price_evening():
                    logger.info("Начинаю публикацию вечернего поста про цену TON...")
                    await self.generate_and_publish_price(is_morning=False)
                
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки. Завершаю работу...")
                break
            except Exception as e:
                logger.error(f"Ошибка в основном цикле: {e}")
                await asyncio.sleep(60)  # Ждём минуту перед повтором
    
    async def test_connection(self):
        """Тестирует подключение к Telegram и DeepSeek"""
        try:
            # Тест Telegram бота
            me = await self.bot.get_me()
            logger.info(f"Telegram бот подключен: @{me.username}")
            
            # Тест получения цены TON
            logger.info("Тестирую получение цены TON...")
            test_price = self.price_fetcher.get_ton_price()
            if test_price:
                logger.info(f"Получение цены работает. TON: ${test_price['usd']:.4f} ({test_price['change_24h']:+.2f}%)")
            else:
                logger.warning("Не удалось получить цену TON (проверьте интернет-соединение)")
            
            # Тест парсера новостей
            logger.info("Тестирую парсинг новостей...")
            test_news = await self.news_parser.get_latest_news(config.NEWS_CHANNEL, 2)
            if test_news:
                logger.info(f"Парсинг новостей работает. Получено {len(test_news)} новостей")
                for i, news_item in enumerate(test_news[:2], 1):
                    logger.info(f"Новость {i} (первые 100 символов): {news_item[:100]}...")
            else:
                logger.warning("Не удалось получить новости (возможно, канал недоступен или требуется авторизация)")
            
            # Тест DeepSeek с ценой
            logger.info("Тестирую DeepSeek API с данными о цене...")
            loop = asyncio.get_event_loop()
            generate_func = partial(self.deepseek.generate_post, config.SYSTEM_PROMPT, price_data=test_price if test_price else None)
            test_post = await loop.run_in_executor(None, generate_func)
            if test_post:
                logger.info("DeepSeek API работает корректно")
                logger.info(f"Тестовый пост (первые 100 символов): {test_post[:100]}...")
                return True
            else:
                logger.error("DeepSeek API не отвечает")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при тестировании: {e}")
            return False
    
    async def test_news_generation(self, count: int = 5):
        """Тестирует генерацию постов из новостей"""
        try:
            logger.info(f"Тестирую генерацию постов из {count} новостей...")
            
            # Получаем новости
            test_news = await self.news_parser.get_latest_news(config.NEWS_CHANNEL, count)
            if not test_news:
                logger.error("Не удалось получить новости для теста")
                return False
            
            logger.info(f"Получено {len(test_news)} новостей для теста")
            
            # Генерируем посты для каждой новости
            loop = asyncio.get_event_loop()
            results = []
            
            for i, news_item in enumerate(test_news[:count], 1):
                logger.info(f"\n{'='*80}")
                logger.info(f"НОВОСТЬ {i}/{count} (ОРИГИНАЛ):")
                logger.info(f"{news_item}")
                logger.info(f"Длина оригинала: {len(news_item)} символов")
                logger.info(f"{'='*80}")
                
                try:
                    # Генерируем пост
                    generate_func = partial(
                        self.deepseek.generate_post,
                        config.SYSTEM_PROMPT,
                        news=[news_item]
                    )
                    post_content = await loop.run_in_executor(None, generate_func)
                    
                    if post_content:
                        # Разделяем новость и комментарий (если есть разделение)
                        post_lines = post_content.split('\n')
                        news_part = post_lines[0] if post_lines else post_content
                        comment_part = '\n'.join(post_lines[1:]) if len(post_lines) > 1 else ""
                        
                        # Добавляем реакцию
                        content_with_reaction = self._add_opinion_text(post_content)
                        
                        logger.info(f"\n✅ СГЕНЕРИРОВАННЫЙ ПОСТ {i}:")
                        logger.info(f"\n📰 НОВОСТЬ (как обработана):")
                        logger.info(f"{news_part}")
                        logger.info(f"\n💬 КОММЕНТАРИЙ/ШУТКА:")
                        logger.info(f"{comment_part if comment_part else '(нет отдельного комментария, всё в одном тексте)'}")
                        logger.info(f"\n🎭 РЕАКЦИЯ:")
                        reaction_line = content_with_reaction.split('\n\n')[-1] if '\n\n' in content_with_reaction else ""
                        logger.info(f"{reaction_line}")
                        logger.info(f"\n📊 ПОЛНЫЙ ПОСТ:")
                        logger.info(f"{content_with_reaction}")
                        logger.info(f"\n📏 Статистика:")
                        logger.info(f"  - Длина оригинала: {len(news_item)} символов")
                        logger.info(f"  - Длина новости в посте: {len(news_part)} символов")
                        logger.info(f"  - Длина комментария: {len(comment_part)} символов")
                        logger.info(f"  - Длина полного поста: {len(content_with_reaction)} символов")
                        logger.info(f"{'='*80}\n")
                        
                        results.append({
                            'news': news_item,
                            'post': content_with_reaction,
                            'news_part': news_part,
                            'comment_part': comment_part,
                            'success': True
                        })
                    else:
                        logger.error(f"❌ Не удалось сгенерировать пост для новости {i}")
                        results.append({
                            'news': news_item,
                            'post': None,
                            'success': False
                        })
                except Exception as e:
                    logger.error(f"❌ Ошибка при генерации поста для новости {i}: {e}", exc_info=True)
                    results.append({
                        'news': news_item,
                        'post': None,
                        'success': False,
                        'error': str(e)
                    })
            
            # Итоговая статистика
            logger.info(f"\n{'='*80}")
            logger.info(f"ИТОГИ ТЕСТА:")
            logger.info(f"Успешно сгенерировано: {sum(1 for r in results if r['success'])}/{len(results)}")
            logger.info(f"Ошибок: {sum(1 for r in results if not r['success'])}/{len(results)}")
            logger.info(f"{'='*80}\n")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при тестировании генерации постов: {e}", exc_info=True)
            return False
    
    def generate_post_from_text(self, original_text: str, user_analysis: Optional[str] = None) -> Optional[str]:
        """Генерирует пост из переданного текста через DeepSeek"""
        try:
            analysis_section = ""
            if user_analysis:
                analysis_section = f"""

ВАЖНО - ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ОТ ПОЛЬЗОВАТЕЛЯ:
{user_analysis}

Учти эти инструкции при генерации поста. Включи указанные мысли, стиль, контекст и фразочки в свой пост."""
            
            user_prompt = f"""Вот пост:
{original_text}
{analysis_section}

Перескажи только суть этого поста в стиле ГОЯ:

Сохрани ключевую информацию (имена, цифры, факты) - должно быть понятно, о чём пост
Добавь 1-2 строки токсичной, параноидальной реакции в стиле русских шуток
Не смешивай с другими новостями
Не выдумывай факты
Каждый раз по-разному обыгрывай темы TON, скама, Дурова, подарков - не используй шаблоны

СТРОГО ЗАПРЕЩЕНО:
- Использовать темы: "пепе", "pepe", "мемкоины", "мемкоин", "сайлор мун", "sailor moon", "газ", "gas fee", "газовые сборы"
- Упоминать "газ" в любом контексте
- Упоминать "пепе" в любом контексте (кроме случая, когда это имя собственное в новости)

Формат:

3-5 предложений (максимум 6, если это рассказ)
Пиши как в голосовом
Точки почти не ставь, запятые - в ~50%
Мат - иногда
Никаких шаблонов и клише - каждый раз новая интонация и угол
Пиши как живой человек - разные реакции на одни и те же темы

ВАЖНО: Используй стиль русских шуток и анекдотов из примеров ниже (философские размышления, самоирония, ирония, метафоры):

{DeepSeekClient.STYLE_EXAMPLES}

Пиши только пост в стиле русских шуток. Без вступлений."""
            
            return self.deepseek.generate_post(config.SYSTEM_PROMPT, user_prompt=user_prompt)
        except Exception as e:
            logger.error(f"Ошибка при генерации поста из текста: {e}")
            return None
    
    async def handle_p_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /p"""
        user_id = update.effective_user.id
        
        logger.info(f"🔔 Команда /p получена от пользователя {user_id}")
        logger.info(f"ADMIN_USER_ID из config: {config.ADMIN_USER_ID}")
        
        if user_id != config.ADMIN_USER_ID:
            logger.warning(f"⚠️ Пользователь {user_id} не является админом (ожидается {config.ADMIN_USER_ID}), доступ запрещен")
            await update.message.reply_text("❌ У тебя нет доступа к этой команде.")
            return
        
        logger.info(f"✅ Пользователь {user_id} является админом, обрабатываю команду /p")
        logger.info(f"Устанавливаю waiting_for_forward=True для пользователя {user_id}")
        self.pending_posts[user_id] = {'waiting_for_forward': True}
        logger.info(f"pending_posts после установки: {self.pending_posts}")
        await update.message.reply_text("📥 Отправь мне репост поста из канала, который нужно обработать.")
    
    async def handle_forwarded_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик репощенного сообщения и редактирования"""
        user_id = update.effective_user.id
        
        logger.info(f"handle_forwarded_message вызван для пользователя {user_id}")
        logger.info(f"Тип сообщения: text={update.message.text is not None}, caption={update.message.caption is not None}, forward={update.message.forward_from_chat is not None}")
        logger.info(f"pending_posts для пользователя: {user_id in self.pending_posts}")
        logger.info(f"pending_images для пользователя: {user_id in self.pending_images}")
        if user_id in self.pending_posts:
            logger.info(f"pending_posts[{user_id}]: {self.pending_posts[user_id]}")
        
        if user_id != config.ADMIN_USER_ID:
            logger.warning(f"Пользователь {user_id} не является админом, пропускаю")
            return
        
        # Если пользователь ожидает работу с изображениями, не обрабатываем здесь
        # (обработчик handle_image_message обработает это)
        if user_id in self.pending_images:
            logger.info(f"Пользователь {user_id} ожидает работу с изображениями, пропускаем в handle_forwarded_message")
            return
        
        # Если пользователь ожидает анализ
        if user_id in self.pending_posts and self.pending_posts[user_id].get('waiting_for_analysis'):
            analysis_text = ""
            if update.message.text:
                analysis_text = update.message.text.strip()
            elif update.message.caption:
                analysis_text = update.message.caption.strip()
            
            # Если текст пустой или слишком короткий, считаем что пропустили
            if not analysis_text or len(analysis_text.strip()) < 3:
                analysis_text = None
            
            # Генерируем пост с учетом анализа (или без него)
            await update.message.reply_text("🤖 Обрабатываю пост через нейросеть...")
            
            # Генерируем в executor, чтобы не блокировать event loop
            loop = asyncio.get_event_loop()
            generate_func = partial(
                self.generate_post_from_text,
                self.pending_posts[user_id]['original_text'],
                user_analysis=analysis_text
            )
            generated_text = await loop.run_in_executor(None, generate_func)
            
            if not generated_text:
                await update.message.reply_text("❌ Ошибка при генерации поста. Попробуй ещё раз или отправь /p для отмены.")
                del self.pending_posts[user_id]
                return
            
            # Сохраняем для подтверждения
            self.pending_posts[user_id] = {
                'waiting_for_analysis': False,
                'original_text': self.pending_posts[user_id]['original_text'],
                'generated_text': generated_text,
                'user_analysis': analysis_text
            }
            
            # Показываем предпросмотр с кнопками
            keyboard = [
                [
                    InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_{user_id}"),
                    InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{user_id}")
                ],
                [
                    InlineKeyboardButton("🎨 Сгенерировать изображение", callback_data=f"generate_image_for_post_{user_id}")
                ],
                [
                    InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            original_text = self.pending_posts[user_id]['original_text']
            # Экранируем пользовательский контент для Markdown
            escaped_generated = escape_markdown(generated_text)
            escaped_original = escape_markdown(original_text[:200])
            preview_text = f"📝 **Предпросмотр поста:**\n\n{escaped_generated}\n\n_Оригинал:_\n{escaped_original}..."
            if analysis_text:
                escaped_analysis = escape_markdown(analysis_text[:100])
                preview_text += f"\n\n_Твой анализ:_\n{escaped_analysis}..."
            await update.message.reply_text(preview_text, reply_markup=reply_markup, parse_mode='Markdown')
            return
        
        # Если пользователь ожидает редактирование
        if user_id in self.pending_posts and self.pending_posts[user_id].get('waiting_for_edit'):
            edited_text = ""
            if update.message.text:
                edited_text = update.message.text.strip()
            elif update.message.caption:
                edited_text = update.message.caption.strip()
            
            if not edited_text or len(edited_text.strip()) < 5:
                await update.message.reply_text("❌ Текст слишком короткий. Отправь отредактированный пост или отправь /p для отмены.")
                return
            
            # Сохраняем отредактированный текст
            self.pending_posts[user_id]['generated_text'] = edited_text
            self.pending_posts[user_id]['waiting_for_edit'] = False
            
            # Показываем новый предпросмотр
            original_text = self.pending_posts[user_id].get('original_text', '')
            keyboard = [
                [
                    InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_{user_id}"),
                    InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{user_id}")
                ],
                [
                    InlineKeyboardButton("🎨 Сгенерировать изображение", callback_data=f"generate_image_for_post_{user_id}")
                ],
                [
                    InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Экранируем пользовательский контент для Markdown
            escaped_edited = escape_markdown(edited_text)
            escaped_original = escape_markdown(original_text[:200])
            preview_text = f"📝 **Предпросмотр поста (отредактирован):**\n\n{escaped_edited}\n\n_Оригинал:_\n{escaped_original}..."
            await update.message.reply_text(preview_text, reply_markup=reply_markup, parse_mode='Markdown')
            return
        
        # Если пользователь ожидает репост
        if user_id not in self.pending_posts or not self.pending_posts[user_id].get('waiting_for_forward'):
            logger.info(f"Пользователь {user_id} не ожидает репост или не в pending_posts")
            return
        
        logger.info(f"Обрабатываю репост/текст для пользователя {user_id}")
        
        # Извлекаем текст из репощенного сообщения
        original_text = ""
        if update.message.forward_from_chat:
            # Это репост из канала
            logger.info(f"Это репост из канала: {update.message.forward_from_chat.title if update.message.forward_from_chat else 'неизвестно'}")
            if update.message.text:
                original_text = update.message.text
            elif update.message.caption:
                original_text = update.message.caption
        elif update.message.text:
            logger.info("Это обычное текстовое сообщение")
            original_text = update.message.text
        elif update.message.caption:
            logger.info("Это сообщение с подписью")
            original_text = update.message.caption
        
        logger.info(f"Извлеченный текст: {original_text[:100] if original_text else 'пусто'}...")
        
        if not original_text or len(original_text.strip()) < 10:
            logger.warning(f"Текст слишком короткий или пустой: {len(original_text) if original_text else 0} символов")
            await update.message.reply_text("❌ Не удалось извлечь текст из сообщения. Попробуй ещё раз или отправь /p для отмены.")
            return
        
        # Сохраняем оригинальный текст и запрашиваем анализ
        self.pending_posts[user_id] = {
            'waiting_for_forward': False,
            'waiting_for_analysis': True,
            'original_text': original_text
        }
        
        # Запрашиваем анализ с кнопкой пропустить
        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустить", callback_data=f"skip_analysis_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📝 **Добавь свой анализ (опционально):**\n\n"
            "Напиши краткий тезисный анализ:\n"
            "• Что ты думаешь об этой ситуации\n"
            "• В каком стиле/контексте нужно написать\n"
            "• Какие фразочки добавить\n\n"
            "Или нажми 'Пропустить', чтобы сгенерировать без дополнительных инструкций.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback кнопок"""
        query = update.callback_query
        user_id = query.from_user.id
        
        await query.answer()
        
        # Обработка команд для генерации изображений (проверяем ДО проверки ADMIN)
        if query.data.startswith("img_generate_") or query.data.startswith("img_edit_") or query.data.startswith("img_cancel_"):
            # Проверяем доступ пользователя для /genetat
            if user_id not in config.ALLOWED_GENETAT_USERS:
                logger.warning(f"Пользователь {user_id} пытается использовать callback для /genetat, но не в списке разрешенных")
                await query.answer("❌ У тебя нет доступа к этой команде.", show_alert=True)
                return
            
            if query.data.startswith("img_generate_"):
                # Режим генерации
                self.pending_images[user_id] = {
                    'mode': 'generate',
                    'waiting_for_prompt': True,
                    'waiting_for_image': False
                }
                logger.info(f"Установлен режим генерации для пользователя {user_id}. pending_images: {self.pending_images}")
                await query.edit_message_text(
                    "🎨 **Режим генерации изображения**\n\n"
                    "Отправь текстовое описание того, что нужно нарисовать.\n"
                    "Например: \"кот в космосе, футуристический стиль\"\n\n"
                    "Или отправь /genetat для отмены.",
                    parse_mode='Markdown'
                )
            
            elif query.data.startswith("img_edit_"):
                # Режим редактирования
                self.pending_images[user_id] = {
                    'mode': 'edit',
                    'waiting_for_prompt': True,
                    'waiting_for_image': False
                }
                await query.edit_message_text(
                    "✏️ **Режим редактирования изображения**\n\n"
                    "Сначала отправь текстовое описание того, как нужно изменить изображение.\n"
                    "Например: \"добавить радугу на небо\"\n\n"
                    "После этого отправь фотографию для редактирования.\n\n"
                    "Или отправь /genetat для отмены."
                )
            
            elif query.data.startswith("img_cancel_"):
                # Отменяем генерацию/редактирование
                await query.edit_message_text("❌ Генерация изображения отменена.")
                if user_id in self.pending_images:
                    del self.pending_images[user_id]
            
            return  # Выходим, так как обработали callback для /genetat
        
        # Проверка доступа для команд /p (только для ADMIN_USER_ID)
        if user_id != config.ADMIN_USER_ID:
            await query.edit_message_text("❌ У тебя нет доступа.")
            return
        
        if query.data.startswith("generate_image_for_post_"):
            # Генерируем изображение для поста
            if user_id not in self.pending_posts or not self.pending_posts[user_id].get('generated_text'):
                await query.edit_message_text("❌ Ошибка: пост не найден. Начни заново с /p")
                return
            
            generated_text = self.pending_posts[user_id]['generated_text']
            
            await query.edit_message_text("🎨 Генерирую изображение для поста... Это может занять несколько секунд.")
            
            try:
                # Генерируем промпт для изображения
                image_prompt = self.generate_image_prompt(generated_text, is_price_post=False, price_data=None)
                
                logger.info(f"Генерирую изображение для поста команды /p. Промпт: {image_prompt[:100]}...")
                
                # Генерируем изображение
                image_url = await self.image_generator.generate_image_async(
                    prompt=image_prompt,
                    mode='generate',
                    image_urls=None
                )
                
                if image_url:
                    # Сохраняем URL изображения в pending_posts
                    self.pending_posts[user_id]['image_url'] = image_url
                    logger.info(f"Изображение сгенерировано: {image_url}")
                    
                    # Показываем предпросмотр с изображением
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Опубликовать с фото", callback_data=f"publish_{user_id}"),
                            InlineKeyboardButton("📝 Опубликовать без фото", callback_data=f"publish_no_image_{user_id}")
                        ],
                        [
                            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{user_id}")
                        ],
                        [
                            InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{user_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    escaped_text = escape_markdown(generated_text)
                    preview_text = f"🎨 **Изображение сгенерировано!**\n\n📝 **Текст поста:**\n{escaped_text}"
                    
                    # Отправляем изображение с текстом
                    await query.message.reply_photo(
                        photo=image_url,
                        caption=preview_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                    await query.message.delete()
                else:
                    await query.edit_message_text("❌ Не удалось сгенерировать изображение. Попробуй ещё раз или опубликуй без фото.")
            except Exception as e:
                logger.error(f"Ошибка при генерации изображения для поста: {e}")
                await query.edit_message_text("❌ Ошибка при генерации изображения. Попробуй ещё раз или опубликуй без фото.")
        
        elif query.data.startswith("publish_no_image_"):
            # Публикуем пост без изображения (удаляем image_url если был)
            if user_id not in self.pending_posts or not self.pending_posts[user_id].get('generated_text'):
                await query.edit_message_text("❌ Ошибка: пост не найден. Начни заново с /p")
                return
            
            generated_text = self.pending_posts[user_id]['generated_text']
            # Удаляем image_url чтобы опубликовать без фото
            if 'image_url' in self.pending_posts[user_id]:
                del self.pending_posts[user_id]['image_url']
            
            # Публикуем в канал
            success = await self.publish_post_manual(generated_text, image_url=None)
            
            if success:
                # Экранируем для безопасного отображения
                escaped_text = escape_markdown(generated_text)
                try:
                    await query.edit_message_text(f"✅ Пост опубликован в канал (без фото)!\n\n{escaped_text}", parse_mode='Markdown')
                    logger.info(f"Пост опубликован через команду /p пользователем {user_id} (без фото)")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение после публикации: {e}. Отправляю новое сообщение.")
                    try:
                        await query.message.reply_text(f"✅ Пост опубликован в канал (без фото)!\n\n{escaped_text}", parse_mode='Markdown')
                    except Exception as e2:
                        logger.error(f"Не удалось отправить сообщение о публикации: {e2}")
            else:
                try:
                    await query.edit_message_text("❌ Ошибка при публикации поста в канал.")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение об ошибке: {e}. Отправляю новое сообщение.")
                    try:
                        await query.message.reply_text("❌ Ошибка при публикации поста в канал.")
                    except Exception as e2:
                        logger.error(f"Не удалось отправить сообщение об ошибке: {e2}")
            
            del self.pending_posts[user_id]
        
        elif query.data.startswith("publish_"):
            # Публикуем пост
            if user_id not in self.pending_posts or not self.pending_posts[user_id].get('generated_text'):
                await query.edit_message_text("❌ Ошибка: пост не найден. Начни заново с /p")
                return
            
            generated_text = self.pending_posts[user_id]['generated_text']
            image_url = self.pending_posts[user_id].get('image_url')  # Может быть None
            
            # Публикуем в канал
            success = await self.publish_post_manual(generated_text, image_url=image_url)
            
            if success:
                # Экранируем для безопасного отображения
                escaped_text = escape_markdown(generated_text)
                try:
                    if image_url:
                        await query.edit_message_text(f"✅ Пост с изображением опубликован в канал!\n\n{escaped_text}", parse_mode='Markdown')
                        logger.info(f"Пост опубликован через команду /p пользователем {user_id} (с фото)")
                    else:
                        await query.edit_message_text(f"✅ Пост опубликован в канал!\n\n{escaped_text}", parse_mode='Markdown')
                        logger.info(f"Пост опубликован через команду /p пользователем {user_id}")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение после публикации: {e}. Отправляю новое сообщение.")
                    try:
                        # Пытаемся отправить новое сообщение вместо редактирования
                        if image_url:
                            await query.message.reply_text(f"✅ Пост с изображением опубликован в канал!\n\n{escaped_text}", parse_mode='Markdown')
                        else:
                            await query.message.reply_text(f"✅ Пост опубликован в канал!\n\n{escaped_text}", parse_mode='Markdown')
                    except Exception as e2:
                        logger.error(f"Не удалось отправить сообщение о публикации: {e2}")
            else:
                try:
                    await query.edit_message_text("❌ Ошибка при публикации поста в канал.")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение об ошибке: {e}. Отправляю новое сообщение.")
                    try:
                        await query.message.reply_text("❌ Ошибка при публикации поста в канал.")
                    except Exception as e2:
                        logger.error(f"Не удалось отправить сообщение об ошибке: {e2}")
            
            del self.pending_posts[user_id]
        
        elif query.data.startswith("edit_"):
            # Редактирование
            if user_id not in self.pending_posts or not self.pending_posts[user_id].get('generated_text'):
                await query.edit_message_text("❌ Ошибка: пост не найден. Начни заново с /p")
                return
            
            # Устанавливаем состояние ожидания редактирования
            self.pending_posts[user_id]['waiting_for_edit'] = True
            current_text = self.pending_posts[user_id]['generated_text']
            
            # Экранируем текущий текст для Markdown
            escaped_text = escape_markdown(current_text)
            await query.edit_message_text(
                f"✏️ **Редактирование поста:**\n\n"
                f"Текущий текст:\n{escaped_text}\n\n"
                f"Отправь мне отредактированный текст сообщением.",
                parse_mode='Markdown'
            )
        
        elif query.data.startswith("skip_analysis_"):
            # Пропускаем анализ и генерируем пост
            if user_id not in self.pending_posts or not self.pending_posts[user_id].get('original_text'):
                await query.edit_message_text("❌ Ошибка: пост не найден. Начни заново с /p")
                return
            
            original_text = self.pending_posts[user_id]['original_text']
            
            await query.edit_message_text("🤖 Обрабатываю пост через нейросеть...")
            
            # Генерируем без анализа (в executor, чтобы не блокировать event loop)
            loop = asyncio.get_event_loop()
            generate_func = partial(self.generate_post_from_text, original_text, user_analysis=None)
            generated_text = await loop.run_in_executor(None, generate_func)
            
            if not generated_text:
                await query.edit_message_text("❌ Ошибка при генерации поста. Попробуй ещё раз или отправь /p для отмены.")
                del self.pending_posts[user_id]
                return
            
            # Сохраняем для подтверждения
            self.pending_posts[user_id] = {
                'waiting_for_analysis': False,
                'original_text': original_text,
                'generated_text': generated_text,
                'user_analysis': None
            }
            
            # Показываем предпросмотр с кнопками
            keyboard = [
                [
                    InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_{user_id}"),
                    InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{user_id}")
                ],
                [
                    InlineKeyboardButton("🎨 Сгенерировать изображение", callback_data=f"generate_image_for_post_{user_id}")
                ],
                [
                    InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Экранируем пользовательский контент для Markdown
            escaped_generated = escape_markdown(generated_text)
            escaped_original = escape_markdown(original_text[:200])
            preview_text = f"📝 **Предпросмотр поста:**\n\n{escaped_generated}\n\n_Оригинал:_\n{escaped_original}..."
            await query.edit_message_text(preview_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        elif query.data.startswith("cancel_"):
            # Отменяем
            await query.edit_message_text("❌ Публикация отменена.")
            if user_id in self.pending_posts:
                del self.pending_posts[user_id]
    
    async def handle_genetat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /genetat - генерация и редактирование изображений"""
        user_id = update.effective_user.id
        
        # Убеждаемся, что user_id - это int (Telegram всегда возвращает int, но на всякий случай)
        if not isinstance(user_id, int):
            try:
                user_id = int(user_id)
            except (ValueError, TypeError):
                logger.error(f"Неверный тип user_id: {type(user_id)} = {user_id}")
                await update.message.reply_text("❌ Ошибка при проверке доступа.")
                return
        
        logger.info(f"Команда /genetat получена от пользователя {user_id} (тип: {type(user_id)})")
        logger.info(f"Список разрешенных пользователей: {config.ALLOWED_GENETAT_USERS} (тип: {type(config.ALLOWED_GENETAT_USERS)})")
        logger.info(f"Типы элементов в списке: {[type(uid) for uid in config.ALLOWED_GENETAT_USERS]}")
        
        # Проверяем, есть ли пользователь в списке разрешенных
        has_access = user_id in config.ALLOWED_GENETAT_USERS
        
        logger.info(f"Проверка доступа: user_id={user_id} (тип: {type(user_id)}) in ALLOWED_GENETAT_USERS={config.ALLOWED_GENETAT_USERS} = {has_access}")
        
        if not has_access:
            logger.warning(f"❌ Пользователь {user_id} (тип: {type(user_id)}) НЕ в списке разрешенных")
            logger.warning(f"   Разрешенные ID: {config.ALLOWED_GENETAT_USERS} (типы: {[type(uid) for uid in config.ALLOWED_GENETAT_USERS]})")
            logger.warning(f"   Сравнение: user_id={user_id} == 1711562784? {user_id == 1711562784}")
            logger.warning(f"   user_id in list? {user_id in config.ALLOWED_GENETAT_USERS}")
            logger.warning(f"   Проверка каждого элемента: {[user_id == uid for uid in config.ALLOWED_GENETAT_USERS]}")
            await update.message.reply_text("❌ У тебя нет доступа к этой команде.")
            return
        
        logger.info(f"✅ Пользователь {user_id} имеет доступ к /genetat")
        
        # Показываем меню выбора режима
        keyboard = [
            [
                InlineKeyboardButton("🎨 Сгенерировать фото", callback_data=f"img_generate_{user_id}"),
                InlineKeyboardButton("✏️ Редактировать фото", callback_data=f"img_edit_{user_id}")
            ],
            [
                InlineKeyboardButton("❌ Отменить", callback_data=f"img_cancel_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🎨 **Генерация и редактирование изображений**\n\n"
            "Выбери режим:\n"
            "• 🎨 **Сгенерировать фото** - создание нового изображения по текстовому описанию\n"
            "• ✏️ **Редактировать фото** - редактирование существующего изображения",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_image_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик сообщений с изображениями и текстом для генерации/редактирования"""
        user_id = update.effective_user.id
        
        logger.info(f"handle_image_message вызван для пользователя {user_id}")
        logger.info(f"pending_images: {user_id in self.pending_images}, pending_posts: {user_id in self.pending_posts}")
        
        # ВАЖНО: ПЕРВАЯ ПРОВЕРКА - Если это репост (forwarded message), сразу пропускаем в handle_forwarded_message
        # Репосты должны обрабатываться только в handle_forwarded_message, независимо от pending_images/pending_posts
        is_forwarded = (
            update.message.forward_from_chat is not None or 
            update.message.forward_from is not None or
            getattr(update.message, 'forward_signature', None) is not None or
            hasattr(update.message, 'forward_sender_name') and update.message.forward_sender_name is not None
        )
        logger.info(f"Проверка репоста для пользователя {user_id}: forward_from_chat={update.message.forward_from_chat}, forward_from={update.message.forward_from}, forward_signature={getattr(update.message, 'forward_signature', None)}, is_forwarded={is_forwarded}")
        
        # ВАЖНО: Также проверяем, если пользователь ожидает репост (waiting_for_forward=True)
        # В этом случае явно вызываем handle_forwarded_message, даже если репост не определен явно
        waiting_for_forward = False
        if user_id in self.pending_posts:
            waiting_for_forward = self.pending_posts[user_id].get('waiting_for_forward', False)
        
        if is_forwarded or waiting_for_forward:
            if is_forwarded:
                logger.info(f"Сообщение от пользователя {user_id} является репостом, передаем в handle_forwarded_message")
            if waiting_for_forward:
                logger.info(f"Пользователь {user_id} ожидает репост (waiting_for_forward=True), передаем в handle_forwarded_message")
            # Явно вызываем handle_forwarded_message вместо простого return
            try:
                logger.info(f"Явно вызываю handle_forwarded_message для пользователя {user_id}...")
                await self.handle_forwarded_message(update, context)
                logger.info(f"handle_forwarded_message завершен для пользователя {user_id}")
            except Exception as e:
                logger.error(f"Ошибка при явном вызове handle_forwarded_message для пользователя {user_id}: {e}")
                logger.exception(e)
            return
        
        # ВАЖНО: Сначала проверяем pending_images (приоритет)
        # Если пользователь ожидает работу с изображениями, обрабатываем здесь (независимо от pending_posts)
        if user_id not in self.pending_images:
            # Если пользователь НЕ в pending_images, пропускаем обработку
            # (это должно обрабатываться в handle_forwarded_message, если нужно)
            if user_id in self.pending_posts:
                waiting_for_analysis = self.pending_posts[user_id].get('waiting_for_analysis', False)
                waiting_for_edit = self.pending_posts[user_id].get('waiting_for_edit', False)
                logger.info(f"Пользователь {user_id} в pending_posts: waiting_for_forward={waiting_for_forward}, waiting_for_analysis={waiting_for_analysis}, waiting_for_edit={waiting_for_edit}")
                if waiting_for_analysis or waiting_for_edit:
                    logger.info(f"Пользователь {user_id} ожидает работу с постами (анализ/редактирование), пропускаем handle_image_message")
                    return
            logger.info(f"Пользователь {user_id} не в pending_images, пропускаем")
            return
        
        pending = self.pending_images[user_id]
        
        # Проверяем доступ пользователя для /genetat
        if user_id not in config.ALLOWED_GENETAT_USERS:
            logger.warning(f"Пользователь {user_id} пытается использовать /genetat, но не в списке разрешенных")
            del self.pending_images[user_id]
            await update.message.reply_text("❌ У тебя нет доступа к этой команде.")
            return
        
        logger.info(f"Обрабатываю сообщение для генерации изображения. Режим: {pending.get('mode')}, waiting_for_prompt: {pending.get('waiting_for_prompt')}")
        
        # Если ожидаем промпт (текст)
        if pending.get('waiting_for_prompt'):
            prompt = ""
            if update.message.text:
                prompt = update.message.text.strip()
            elif update.message.caption:
                prompt = update.message.caption.strip()
            
            if not prompt or len(prompt) < 5:
                await update.message.reply_text("❌ Промпт слишком короткий. Отправь текстовое описание (минимум 5 символов) или /genetat для отмены.")
                return
            
            mode = pending.get('mode', 'generate')
            
            # Если режим редактирования, нужна еще фотография
            if mode == 'edit':
                pending['prompt'] = prompt
                pending['waiting_for_prompt'] = False
                pending['waiting_for_image'] = True
                await update.message.reply_text(
                    f"✅ Промпт сохранен: {prompt[:50]}...\n\n"
                    "📷 Теперь отправь фотографию, которую нужно отредактировать."
                )
                return
            
            # Если режим генерации, сразу генерируем
            await update.message.reply_text(f"🎨 Генерирую изображение по промпту: {prompt[:50]}...\n\n⏳ Это может занять до 3 минут...")
            
            logger.info(f"Начинаю генерацию изображения для пользователя {user_id}. Промпт: {prompt}")
            image_url = await self.image_generator.generate_image_async(prompt, mode='generate')
            
            logger.info(f"Генерация завершена. Результат: {image_url}")
            
            if image_url:
                try:
                    logger.info(f"Пытаюсь отправить изображение пользователю {user_id}. URL: {image_url}")
                    await update.message.reply_photo(photo=image_url, caption=f"✅ Изображение сгенерировано!\n\nПромпт: {prompt}")
                    logger.info(f"Изображение успешно отправлено пользователю {user_id}")
                except Exception as e:
                    logger.error(f"Ошибка отправки изображения через reply_photo: {e}")
                    logger.exception(e)  # Полный traceback
                    try:
                        await update.message.reply_text(f"✅ Изображение готово!\n\n🔗 Ссылка: {image_url}\n\nПромпт: {prompt}")
                    except Exception as e2:
                        logger.error(f"Ошибка отправки текстового сообщения с ссылкой: {e2}")
            else:
                logger.error(f"Генерация изображения вернула None для пользователя {user_id}. Промпт: {prompt}")
                await update.message.reply_text("❌ Ошибка при генерации изображения. Попробуй ещё раз или отправь /genetat для отмены.")
            
            # Очищаем состояние
            del self.pending_images[user_id]
            return
        
        # Если ожидаем изображение (для редактирования)
        if pending.get('waiting_for_image'):
            if not update.message.photo:
                await update.message.reply_text("❌ Отправь фотографию (не документ). Попробуй ещё раз или /genetat для отмены.")
                return
            
            # Получаем самое большое фото
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            
            # Получаем публичный URL изображения из Telegram
            # file.file_path должен содержать относительный путь (например: "photos/file_0.jpg")
            file_path = file.file_path
            
            # Проверяем, не является ли file_path уже полным URL
            if file_path.startswith('http://') or file_path.startswith('https://'):
                # Если это уже полный URL, используем его
                image_url = file_path
                logger.debug(f"file.file_path уже содержит полный URL: {file_path}")
            elif file_path.startswith(f'https://api.telegram.org/file/bot'):
                # Если содержит префикс с токеном, извлекаем только путь
                # Находим позицию после /bot<token>/
                parts = file_path.split('/bot')
                if len(parts) > 1:
                    # Берем часть после /bot<token>/
                    path_part = '/'.join(parts[1].split('/')[1:])
                    image_url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{path_part}"
                else:
                    image_url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{file_path}"
            else:
                # Обычный случай - относительный путь
                image_url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{file_path}"
            
            logger.info(f"Получен URL изображения для редактирования: {image_url}")
            logger.debug(f"Исходный file.file_path = {file_path}")
            
            prompt = pending.get('prompt', '')
            
            if not prompt:
                await update.message.reply_text("❌ Промпт не найден. Начни заново с /genetat.")
                del self.pending_images[user_id]
                return
            
            await update.message.reply_text(f"✏️ Редактирую изображение по промпту: {prompt[:50]}...\n\n⏳ Это может занять до 3 минут...")
            
            logger.info(f"Начинаю редактирование изображения для пользователя {user_id}. Промпт: {prompt}, URL: {image_url}")
            
            # Вызываем API для редактирования изображения
            image_urls = [image_url]  # NanoBanana API ожидает список URL
            result_url = await self.image_generator.generate_image_async(
                prompt=prompt,
                mode='edit',
                image_urls=image_urls
            )
            
            logger.info(f"Редактирование завершено. Результат: {result_url}")
            
            if result_url:
                try:
                    logger.info(f"Пытаюсь отправить отредактированное изображение пользователю {user_id}. URL: {result_url}")
                    await update.message.reply_photo(
                        photo=result_url,
                        caption=f"✅ Изображение отредактировано!\n\nПромпт: {prompt}"
                    )
                    logger.info(f"Отредактированное изображение успешно отправлено пользователю {user_id}")
                except Exception as e:
                    logger.error(f"Ошибка отправки изображения через reply_photo: {e}")
                    logger.exception(e)
                    try:
                        await update.message.reply_text(
                            f"✅ Изображение готово!\n\n🔗 Ссылка: {result_url}\n\nПромпт: {prompt}"
                        )
                    except Exception as e2:
                        logger.error(f"Ошибка отправки текстового сообщения с ссылкой: {e2}")
            else:
                logger.error(f"Редактирование изображения вернуло None для пользователя {user_id}. Промпт: {prompt}")
                await update.message.reply_text(
                    "❌ Ошибка при редактировании изображения. Попробуй ещё раз или отправь /genetat для отмены."
                )
            
            # Очищаем состояние
            del self.pending_images[user_id]
            return
    
    async def setup_command_handlers(self):
        """Настраивает обработчики команд"""
        if not self.application:
            self.application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
            
            # Регистрируем обработчики
            # ВАЖНО: Порядок имеет значение! Более специфичные обработчики должны быть первыми
            logger.info("Регистрирую обработчик команды /p...")
            self.application.add_handler(CommandHandler("p", self.handle_p_command))
            logger.info("Регистрирую обработчик команды /genetat...")
            self.application.add_handler(CommandHandler("genetat", self.handle_genetat_command))
            
            # ВАЖНО: Порядок регистрации имеет значение!
            # handle_image_message должен быть ПЕРВЫМ, чтобы проверка pending_images выполнялась раньше
            # Обрабатываем сообщения с изображениями и текстом для генерации
            logger.info("Регистрирую обработчик сообщений с изображениями...")
            self.application.add_handler(MessageHandler(
                (filters.PHOTO | filters.TEXT) & filters.ChatType.PRIVATE,
                self.handle_image_message
            ))
            
            # Обрабатываем репосты и обычные сообщения (если пользователь ожидает репост)
            # Это должно быть после handle_image_message, чтобы изображения обрабатывались первыми
            logger.info("Регистрирую обработчик репостов и сообщений...")
            self.application.add_handler(MessageHandler(
                (filters.FORWARDED | filters.TEXT) & filters.ChatType.PRIVATE, 
                self.handle_forwarded_message
            ))
            
            logger.info("Регистрирую обработчик callback-запросов...")
            self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
            
            logger.info("✅ Все обработчики команд успешно настроены")
    
    async def start_command_polling(self):
        """Запускает polling для обработки команд"""
        try:
            logger.info("Начинаю запуск polling для команд...")
            if not self.application:
                logger.info("Application не создан, вызываю setup_command_handlers...")
                await self.setup_command_handlers()
            
            if self.application:
                logger.info("Инициализирую application...")
                await self.application.initialize()
                logger.info("Запускаю application...")
                await self.application.start()
                logger.info("Запускаю updater.start_polling()...")
                await self.application.updater.start_polling()
                logger.info("✅ Polling для команд успешно запущен и работает")
            else:
                logger.error("❌ Не удалось создать application для polling")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при запуске polling: {e}", exc_info=True)
            raise
    
    async def cleanup(self):
        """Очистка ресурсов"""
        await self.news_parser.close()
        if self.application:
            await self.application.stop()
            await self.application.shutdown()


async def main():
    """Главная функция"""
    bot = TelegramChannelBot()
    
    try:
        # Тестируем подключения
        logger.info("Тестирую подключения...")
        if not await bot.test_connection():
            logger.error("Ошибка при тестировании подключений. Проверьте конфигурацию.")
            return
        
        # Настраиваем обработчики команд
        await bot.setup_command_handlers()
        
        # Запускаем polling для команд в фоне
        async def polling_with_error_handling():
            try:
                logger.info("🚀 Запускаю фоновую задачу polling...")
                await bot.start_command_polling()
            except asyncio.CancelledError:
                logger.info("Polling задача была отменена")
            except Exception as e:
                logger.error(f"❌ Критическая ошибка в polling задаче: {e}", exc_info=True)
                # Пытаемся перезапустить через некоторое время
                logger.info("Попытка перезапустить polling через 10 секунд...")
                await asyncio.sleep(10)
                # Рекурсивно перезапускаем (но с ограничением, чтобы не было бесконечного цикла)
                try:
                    await bot.start_command_polling()
                except Exception as e2:
                    logger.error(f"❌ Не удалось перезапустить polling: {e2}", exc_info=True)
        
        polling_task = asyncio.create_task(polling_with_error_handling())
        logger.info("✅ Фоновая задача polling создана")
        
        # Запускаем основной цикл
        await bot.run_loop()
    finally:
        await bot.cleanup()


if __name__ == "__main__":
    import sys
    
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1 and sys.argv[1] == "test_news":
        # Режим тестирования новостей
        async def test_main():
            bot = TelegramChannelBot()
            count = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 5
            logger.info(f"Запускаю тест генерации постов из {count} новостей...")
            await bot.test_news_generation(count=count)
        
        try:
            asyncio.run(test_main())
        except KeyboardInterrupt:
            logger.info("Тест остановлен пользователем")
    else:
        # Обычный режим работы
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")

