"""Тестирование обработки конкретных новостей"""
import asyncio
import sys
import os
from functools import partial

# Добавляем путь к текущей директории для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import DeepSeekClient, TelegramChannelBot
import config

# Новости для обработки
TEST_NEWS = [
    "CNBC: Сенат сегодня проголосует по запрету Трампу наносить дальнейшие военные удары по Венесуэле",
    "JPMorgan считает, (https://www.coindesk.com/markets/2026/01/08/jpmorgan-says-the-crypto-selloff-may-be-nearing-a-bottom-as-etf-outflows-ease) что распродажа на крипторынке, возможно, близится к завершению.\n\nCiti придерживается своего таргета по BTC в $143 000 в ближайшие 12 месяцев",
    "Майкл Сэйлор встретился с сенатором Джимом Джастисом для обсуждения внедрения BTC",
    "Optimism Foundation предложил использовать 50% выручки Superchain для выкупа токенов OP",
    "Coincheck покупает компанию 3iQ за $112 млн, чтобы расширить свою линейку крипто-сервисов"
]

async def test_news():
    """Тестирует обработку конкретных новостей"""
    # Инициализируем клиент DeepSeek
    deepseek = DeepSeekClient(config.DEEPSEEK_API_KEY, config.DEEPSEEK_API_URL)
    
    # Инициализируем бота (для функции _add_opinion_text)
    bot = TelegramChannelBot()
    
    results = []
    
    for i, news_item in enumerate(TEST_NEWS, 1):
        print(f"\n{'='*80}")
        print(f"НОВОСТЬ {i}/5")
        print(f"{'='*80}\n")
        
        # Безопасный вывод для Windows
        def safe_print_orig(text):
            try:
                print(text)
            except UnicodeEncodeError:
                safe_text = text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                print(safe_text)
        
        safe_print_orig(f"ОРИГИНАЛ ({len(news_item)} символов):")
        safe_print_orig(f"{news_item}\n")
        
        try:
            # Генерируем пост через executor
            loop = asyncio.get_event_loop()
            generate_func = partial(
                deepseek.generate_post,
                config.SYSTEM_PROMPT,
                news=[news_item]
            )
            post_content = await loop.run_in_executor(None, generate_func)
            
            if post_content:
                # Разделяем новость и комментарий (если есть разделение)
                post_lines = post_content.split('\n')
                news_part = post_lines[0] if post_lines else post_content
                comment_part = '\n'.join(post_lines[1:]).strip() if len(post_lines) > 1 else ""
                
                # Добавляем реакцию
                content_with_reaction = bot._add_opinion_text(post_content)
                
                # Извлекаем реакцию
                reaction_line = ""
                if '\n\n' in content_with_reaction:
                    reaction_parts = content_with_reaction.split('\n\n')
                    reaction_line = reaction_parts[-1] if reaction_parts else ""
                
                # Безопасный вывод в консоль (исправляем функцию safe_print)
                def safe_print(text):
                    try:
                        # Пытаемся вывести напрямую
                        print(text, flush=True)
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        # Если не получается, заменяем проблемные символы
                        try:
                            # Удаляем эмодзи и другие проблемные символы для консоли Windows
                            import re
                            safe_text = re.sub(r'[\U00010000-\U0010ffff]', '?', text)
                            safe_text = safe_text.encode('cp1251', errors='replace').decode('cp1251', errors='replace')
                            print(safe_text, flush=True)
                        except:
                            # Если и это не работает, просто выводим замену
                            print(text.encode('utf-8', errors='replace').decode('utf-8', errors='replace'), flush=True)
                
                safe_print(f"ОБРАБОТАННАЯ НОВОСТЬ ({len(news_part)} символов):")
                safe_print(f"{news_part}\n")
                
                if comment_part:
                    safe_print(f"КОММЕНТАРИЙ/ШУТКА ({len(comment_part)} символов):")
                    safe_print(f"{comment_part}\n")
                else:
                    safe_print(f"КОММЕНТАРИЙ/ШУТКА: (встроен в текст новости)")
                    safe_print(f"{post_content}\n")
                
                safe_print(f"РЕАКЦИЯ:")
                safe_print(f"{reaction_line}\n")
                
                safe_print(f"ПОЛНЫЙ ПОСТ ({len(content_with_reaction)} символов):")
                safe_print(f"{content_with_reaction}\n")
                
                results.append({
                    'number': i,
                    'original': news_item,
                    'news_part': news_part,
                    'comment_part': comment_part if comment_part else post_content,
                    'reaction': reaction_line,
                    'full_post': content_with_reaction,
                    'success': True
                })
            else:
                print("ОШИБКА: Не удалось сгенерировать пост\n")
                results.append({
                    'number': i,
                    'original': news_item,
                    'success': False
                })
        except UnicodeEncodeError as e:
            # Это ошибка только при выводе в консоль, не при обработке
            # Пытаемся сохранить результаты, если они были
            if 'results' in locals() and len(results) < i:
                # Если данные уже были собраны, сохраняем их
                try:
                    if 'post_content' in locals() and post_content:
                        safe_print(f"\n⚠ Предупреждение: проблема с выводом эмодзи в консоль, но данные обработаны\n")
                        # Пытаемся сохранить результат
                        if 'content_with_reaction' in locals():
                            post_lines = post_content.split('\n')
                            news_part = post_lines[0] if post_lines else post_content
                            comment_part = '\n'.join(post_lines[1:]).strip() if len(post_lines) > 1 else ""
                            reaction_line = ""
                            if '\n\n' in content_with_reaction:
                                reaction_parts = content_with_reaction.split('\n\n')
                                reaction_line = reaction_parts[-1] if reaction_parts else ""
                            
                            results.append({
                                'number': i,
                                'original': news_item,
                                'news_part': news_part,
                                'comment_part': comment_part if comment_part else post_content,
                                'reaction': reaction_line,
                                'full_post': content_with_reaction,
                                'success': True
                            })
                        else:
                            results.append({
                                'number': i,
                                'original': news_item,
                                'success': False,
                                'error': 'Ошибка кодировки при выводе'
                            })
                    else:
                        results.append({
                            'number': i,
                            'original': news_item,
                            'success': False,
                            'error': 'Ошибка кодировки: ' + str(e)
                        })
                except:
                    results.append({
                        'number': i,
                        'original': news_item,
                        'success': False,
                        'error': 'Ошибка кодировки: ' + str(e)
                    })
            else:
                results.append({
                    'number': i,
                    'original': news_item,
                    'success': False,
                    'error': 'Ошибка кодировки: ' + str(e)
                })
        except Exception as e:
            print(f"ОШИБКА: {e}\n")
            import traceback
            traceback.print_exc()
            results.append({
                'number': i,
                'original': news_item,
                'success': False,
                'error': str(e)
            })
    
    # Сохраняем результаты в файл
    output_file = "test_news_results.txt"
    with open(output_file, 'w', encoding='utf-8', errors='replace') as f:
        f.write("="*80 + "\n")
        f.write("РЕЗУЛЬТАТЫ ОБРАБОТКИ НОВОСТЕЙ\n")
        f.write("="*80 + "\n\n")
        
        for result in results:
            f.write(f"{'='*80}\n")
            f.write(f"НОВОСТЬ {result['number']}/5\n")
            f.write(f"{'='*80}\n\n")
            
            f.write(f"ОРИГИНАЛ ({len(result['original'])} символов):\n")
            f.write(f"{result['original']}\n\n")
            
            if result['success']:
                f.write(f"ОБРАБОТАННАЯ НОВОСТЬ ({len(result['news_part'])} символов):\n")
                f.write(f"{result['news_part']}\n\n")
                
                f.write(f"КОММЕНТАРИЙ/ШУТКА ({len(result['comment_part'])} символов):\n")
                f.write(f"{result['comment_part']}\n\n")
                
                f.write(f"РЕАКЦИЯ:\n")
                f.write(f"{result['reaction']}\n\n")
                
                f.write(f"ПОЛНЫЙ ПОСТ ({len(result['full_post'])} символов):\n")
                f.write(f"{result['full_post']}\n\n")
            else:
                f.write(f"ОШИБКА: {result.get('error', 'Не удалось сгенерировать пост')}\n\n")
            
            f.write(f"{'='*80}\n\n")
    
    print(f"\n{'='*80}")
    print(f"ИТОГИ:")
    print(f"Успешно: {sum(1 for r in results if r['success'])}/5")
    print(f"Ошибок: {sum(1 for r in results if not r['success'])}/5")
    print(f"\nРезультаты сохранены в файл: {output_file}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    asyncio.run(test_news())

