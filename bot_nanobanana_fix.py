# Временный файл с правильной реализацией NanoBananaImageGenerator
# Скопируйте этот код в bot.py, заменив старый класс

class NanoBananaImageGenerator:
    """Генератор изображений через NanoBanana API"""
    
    def __init__(self, api_key: str, api_url: str, callback_url: Optional[str] = None):
        self.api_key = api_key
        self.api_url = api_url.rstrip('/')
        # Callback URL для получения уведомлений (опционально, можно использовать polling)
        self.callback_url = callback_url or "https://example.com/callback"  # Заглушка, если не указан
    
    def generate_image(self, prompt: str, mode: str = "generate", image_urls: Optional[List[str]] = None, 
                      num_images: int = 1, image_size: str = "1:1") -> Optional[dict]:
        """
        Генерирует или редактирует изображение
        
        Args:
            prompt: Текстовое описание для генерации или редактирования
            mode: "generate" для генерации, "edit" для редактирования
            image_urls: Список URL изображений для редактирования (только для mode="edit")
            num_images: Количество изображений (1-4)
            image_size: Размер изображения (1:1, 16:9, 9:16 и т.д.)
        
        Returns:
            dict с taskId или None в случае ошибки
        """
        try:
            # Правильный endpoint согласно документации
            url = f"{self.api_url}/api/v1/nanobanana/generate"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Определяем тип генерации
            if mode == "edit":
                generation_type = "IMAGETOIAMGE"
                if not image_urls:
                    logger.error("Для редактирования нужен imageUrls")
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
                # Проверяем формат ответа согласно документации
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
            # Согласно документации, endpoint для проверки статуса
            url = f"{self.api_url}/api/v1/nanobanana/task/{task_id}"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # Проверяем формат ответа
                if data.get("code") == 200:
                    return data.get("data", {})
                else:
                    logger.error(f"Ошибка в ответе API: {data.get('msg', 'Unknown error')}")
                    return None
            else:
                logger.error(f"Ошибка проверки статуса: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Исключение при проверке статуса: {e}")
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
            await asyncio.sleep(5)
            
            status_data = self.get_task_status(task_id)
            if not status_data:
                # Если не удалось получить статус, продолжаем ждать
                continue
            
            # Проверяем различные возможные поля статуса
            status = status_data.get('status', '').lower()
            state = status_data.get('state', '').lower()
            
            # Проверяем завершение
            if status == 'completed' or state == 'completed' or status == 'success' or state == 'success':
                # Ищем URL изображения в различных возможных полях
                image_url = (status_data.get('imageUrl') or 
                           status_data.get('image_url') or 
                           status_data.get('resultUrl') or 
                           status_data.get('result_url') or
                           status_data.get('url'))
                
                # Если это массив изображений, берем первое
                if isinstance(image_url, list) and len(image_url) > 0:
                    image_url = image_url[0]
                
                if image_url:
                    logger.info(f"Изображение готово: {image_url}")
                    return image_url
                else:
                    logger.warning("Задача завершена, но URL изображения не найден в ответе")
                    logger.debug(f"Полный ответ: {status_data}")
                    # Продолжаем ждать, возможно изображение еще обрабатывается
                    continue
            elif status == 'failed' or state == 'failed' or status == 'error' or state == 'error':
                error_msg = status_data.get('error', status_data.get('message', 'Неизвестная ошибка'))
                logger.error(f"Ошибка генерации изображения: {error_msg}")
                return None
            # Если статус "processing", "pending", "running" и т.д., продолжаем ждать
        
        logger.warning(f"Превышено время ожидания генерации изображения (Task ID: {task_id})")
        return None

