import asyncio
import logging
import json
import time
import random
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.ext import Application, CommandHandler
import re
from urllib.parse import quote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import os
import hashlib
import subprocess
import sys

def install_dependencies():
    """Автоматическая установка всех необходимых зависимостей"""
    required_packages = [
        'requests',
        'beautifulsoup4',
        'python-telegram-bot',
        'selenium',
        'webdriver-manager',
        'lxml'
    ]
    
    for package in required_packages:
        try:
            if package == 'beautifulsoup4':
                __import__('bs4')
            elif package == 'python-telegram-bot':
                __import__('telegram')
            elif package == 'webdriver-manager':
                __import__('webdriver_manager')
            else:
                __import__(package)
            print(f"✓ {package} уже установлен")
        except ImportError:
            print(f"⏳ Устанавливаю {package}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                print(f"✓ {package} успешно установлен")
            except subprocess.CalledProcessError:
                print(f"✗ Ошибка установки {package}")
                return False
    
    print("✓ Все зависимости установлены!")
    return True

# Проверяем и устанавливаем зависимости перед запуском
if __name__ == '__main__':
    print("Проверка зависимостей...")
    if install_dependencies():
        print("Зависимости готовы, запускаем бота...")
    else:
        print("Не удалось установить все зависимости. Проверьте подключение к интернету.")
        sys.exit(1)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class MarketplaceParser:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=bot_token)
        
        self.wildberries_file = 'wildberries_products.json'
        self.yandex_file = 'yandex_products.json'
        self.ozon_file = 'ozon_products.json'
        
        self.html_dump_dir = 'html_dumps'
        if not os.path.exists(self.html_dump_dir):
            os.makedirs(self.html_dump_dir)
        
        self.wildberries_products = self.load_products(self.wildberries_file)
        self.yandex_products = self.load_products(self.yandex_file)
        self.ozon_products = self.load_products(self.ozon_file)
        
        self.first_run = {
            "yandex": len(self.yandex_products) == 0,
            "wildberries": len(self.wildberries_products) == 0,
            "ozon": len(self.ozon_products) == 0
        }

    def normalize_product_name(self, text):
        if not text:
            return ""
        
        text = text.lower()
        
        text = re.sub(r'\s+', ' ', text).strip()
        
        text = re.sub(r'[^\w\sа-яё]', '', text)
        
        text = re.sub(r'\s+', ' ', text)
        
        return text

    def generate_product_id(self, text):
        normalized = self.normalize_product_name(text)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()[:16]

    def save_html_dump(self, html_content, filename):
        try:
            filepath = os.path.join(self.html_dump_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"HTML сохранен: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Ошибка сохранения HTML: {e}")
            return None

    def load_products(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_products(self, filename, products):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)

    async def send_notification(self, message):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"Notification sent: {message}")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")

    def clean_product_text(self, text, marketplace):
        if not text:
            return ""
        
        clean_text = text
        
        if marketplace == "wildberries":
            clean_text = re.sub(r'^[^A-Za-zА-Яа-я/]*', '', clean_text)
            clean_text = re.sub(r'−\d+%\s*\d+\s*₽\s*\d+\s*₽\s*−\d+%', '', clean_text)
            clean_text = re.sub(r'\d+\s*оценок?\s*\d*\s*После$', '', clean_text)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
        elif marketplace == "ozon":
            clean_text = re.sub(r'^мтс сим карта\s*-\s*купить на\s*', '', clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r'^мтс тариф\s*-\s*купить на\s*', '', clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r'\s*-\s*купить на$', '', clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r'^купить на\s*', '', clean_text, flags=re.IGNORECASE)
            
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        return clean_text

    def is_valid_mts_product(self, text):
        if not text or len(text) < 10 or len(text) > 200:
            return False
        
        text_lower = text.lower()
        
        if not any(keyword in text_lower for keyword in ['мтс', 'mts']):
            return False
        
        product_keywords = [
            'сим', 'sim', 'карт', 'тариф', 'tariff', 'телеком', 'связ', 
            'номер', 'mobile', 'плюс', 'plus', 'баланс', 'интернет', 'пакет',
            'звонк', 'минут', 'гигабайт', 'гб', 'gb', 'трафик', 'риил', 'реал',
            'больше', 'джуниор', 'мембрана', 'супер', 'ноутбук', 'устройств'
        ]
        if not any(keyword in text_lower for keyword in product_keywords):
            return False
        
        strict_exclude_keywords = [
            'сбер', 'sber', 'теле2', 'tele2', 'билайн', 'beeline', 'мегафон', 'megafon',
            'тинькофф', 'tinkoff', 'яндекс', 'yandex', 'оплата', 'пополнен', 'доставк',
            'отзыв', 'реценз', 'комментар', 'опрос', 'акция', 'скидк', 'распродаж',
            'чехол', 'наушник', 'powerbank', 'зарядк', 'баллов', 'cashback', 'роутер',
            'модем', 'рация', 'радио', 'каталог', 'интернет-магазин', 'ассортимент',
            'вы найдете', 'в каталоге', 'пао мтс', ' кошелек'
        ]
        
        if any(exclude in text_lower for exclude in strict_exclude_keywords):
            return False
        
        return True

    async def human_delay(self, min_sec=2, max_sec=5):
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    def setup_selenium_driver(self):
        try:
            chrome_options = Options()
            
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-plugins')
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            return driver
        except Exception as e:
            logger.error(f"Ошибка настройки Selenium: {e}")
            return None

    async def parse_yandex_market_selenium(self):
        driver = None
        try:
            current_products = {}
            
            driver = self.setup_selenium_driver()
            if not driver:
                return False
            
            url = "https://market.yandex.ru/business--pao-mts/5336359"
            
            try:
                logger.info(f"Yandex Market: загрузка {url}")
                driver.get(url)
                
                WebDriverWait(driver, 25).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                await asyncio.sleep(5)
                
                for i in range(3):
                    driver.execute_script(f"window.scrollTo(0, {i * 800});")
                    await asyncio.sleep(3)
                
                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                
                product_elements = soup.select('[data-autotest-id="product-snippet"]')
                for product in product_elements:
                    name_element = product.select_one('[data-autotest-id="product-title"]')
                    if name_element:
                        product_name = name_element.get_text(strip=True)
                        clean_name = self.clean_product_text(product_name, "yandex")
                        if clean_name and self.is_valid_mts_product(clean_name):
                            product_id = self.generate_product_id(clean_name)
                            current_products[product_id] = clean_name
                            logger.info(f"Найден товар Яндекс: {clean_name}")
                
                class_selectors = ['._6yVOX', '.XqR4A', '.cia-cs', '.cia-vs']
                for selector in class_selectors:
                    elements = soup.select(selector)
                    for element in elements:
                        text = element.get_text(strip=True)
                        clean_text = self.clean_product_text(text, "yandex")
                        if clean_text and self.is_valid_mts_product(clean_text):
                            product_id = self.generate_product_id(clean_text)
                            current_products[product_id] = clean_text
                
                text_elements = soup.find_all(string=re.compile(r'мтс|mts|сим|sim|тариф|плюс|plus', re.I))
                for element in text_elements:
                    if element.parent and element.parent.name not in ['script', 'style']:
                        text = element.strip()
                        clean_text = self.clean_product_text(text, "yandex")
                        if clean_text and self.is_valid_mts_product(clean_text):
                            product_id = self.generate_product_id(clean_text)
                            current_products[product_id] = clean_text
                
                await self.human_delay(2, 4)
                
            except Exception as e:
                logger.error(f"Ошибка Яндекс Маркет: {e}")
                return False
            
            logger.info(f"Яндекс Маркет: найдено {len(current_products)} товаров")
            
            await self.check_changes(current_products, self.yandex_products, "Яндекс Маркет", "yandex")
            self.yandex_products = current_products
            self.save_products(self.yandex_file, current_products)
            
            return len(current_products) > 0
            
        except Exception as e:
            logger.error(f"Ошибка парсинга Яндекс Маркет: {e}")
            return False
        finally:
            if driver:
                driver.quit()

    async def parse_wildberries_selenium(self):
        driver = None
        try:
            current_products = {}
            
            driver = self.setup_selenium_driver()
            if not driver:
                return False
            
            url = "https://www.wildberries.ru/seller/2980#c494811627"
            
            try:
                logger.info(f"Wildberries: загрузка {url}")
                driver.get(url)
                
                try:
                    WebDriverWait(driver, 25).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".product-card__name"))
                    )
                except:
                    try:
                        WebDriverWait(driver, 25).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".card-product"))
                        )
                    except:
                        WebDriverWait(driver, 25).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                
                await asyncio.sleep(8)
                
                for i in range(8):
                    driver.execute_script(f"window.scrollTo(0, {i * 1000});")
                    await asyncio.sleep(2)
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                await asyncio.sleep(3)
                driver.execute_script("window.scrollTo(0, 0);")
                await asyncio.sleep(1)
                
                page_source = driver.page_source
                
                self.save_html_dump(page_source, f"wildberries_debug_{int(time.time())}.html")
                
                soup = BeautifulSoup(page_source, 'html.parser')
                
                product_selectors = [
                    '.product-card__name',
                    '.goods-name',
                    '.card-product__name',
                    '.product-card .product-card__name',
                ]
                
                seen_products = set()
                
                for selector in product_selectors:
                    elements = soup.select(selector)
                    for element in elements:
                        text = element.get_text(strip=True)
                        clean_text = self.clean_product_text(text, "wildberries")
                        
                        if clean_text and self.is_valid_mts_product(clean_text):
                            normalized = self.normalize_product_name(clean_text)
                            if normalized not in seen_products:
                                seen_products.add(normalized)
                                product_id = self.generate_product_id(clean_text)
                                current_products[product_id] = clean_text
                                logger.info(f"Найден товар Wildberries: {clean_text}")
                
                await self.human_delay(2, 3)
                
            except Exception as e:
                logger.error(f"Ошибка Wildberries: {e}")
                return False
            
            logger.info(f"Wildberries: найдено {len(current_products)} товаров")
            
            await self.check_changes(current_products, self.wildberries_products, "Wildberries", "wildberries")
            self.wildberries_products = current_products
            self.save_products(self.wildberries_file, current_products)
            
            return len(current_products) > 0
            
        except Exception as e:
            logger.error(f"Ошибка парсинга Wildberries: {e}")
            return False
        finally:
            if driver:
                driver.quit()

    async def parse_ozon_selenium(self):
        driver = None
        try:
            current_products = {}
            
            driver = self.setup_selenium_driver()
            if not driver:
                return False
            
            urls = [
                "https://www.ozon.ru/seller/mts-55913/products/"
            ]
            
            for url_index, url in enumerate(urls):
                try:
                    logger.info(f"Ozon: загрузка {url}")
                    driver.get(url)
                    
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    
                    await asyncio.sleep(8)
                    
                    for i in range(4):
                        driver.execute_script(f"window.scrollTo(0, {i * 800});")
                        await asyncio.sleep(3)
                    
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    await asyncio.sleep(4)
                    
                    page_source = driver.page_source
                    
                    self.save_html_dump(page_source, f"ozon_debug_{int(time.time())}.html")
                    
                    soup = BeautifulSoup(page_source, 'html.parser')
                    
                    product_selectors = [
                        '.tile-root .tsBody500',
                        '.tile-root .tsHeadline500',
                        '.tile-root .tsBodyL',
                        '.tile-root .tsHeadlineL',
                        '[data-widget="searchResultsV2"] .tsBody500',
                        '[data-widget="searchResultsV2"] .tsHeadline500',
                        '.x2h .tsBody500',
                        '.x2h .tsHeadline500',
                        '.i9x6 .tsBody500',
                        '.i9x6 .tsHeadline500',
                        '.product-card .title',
                        '.product-card .name',
                    ]
                    
                    seen_products = set()
                    
                    for selector in product_selectors:
                        try:
                            elements = soup.select(selector)
                            for element in elements:
                                text = element.get_text(strip=True)
                                clean_text = self.clean_product_text(text, "ozon")
                                if (clean_text and len(clean_text) > 15 and 
                                    self.is_valid_mts_product(clean_text)):
                                    normalized = self.normalize_product_name(clean_text)
                                    if normalized not in seen_products:
                                        seen_products.add(normalized)
                                        product_id = self.generate_product_id(clean_text)
                                        current_products[product_id] = clean_text
                                        logger.info(f"Найден товар Ozon (селектор): {clean_text}")
                        except Exception as e:
                            logger.error(f"Ошибка в селекторе {selector}: {e}")
                            continue
                    
                    keywords = ['сим-карта мтс', 'sim-карта мтс', 'мтс тариф', 'мтс баланс']
                    for keyword in keywords:
                        text_elements = soup.find_all(string=re.compile(re.escape(keyword), re.I))
                        for element in text_elements:
                            if element.parent and element.parent.name not in ['script', 'style']:
                                text = element.strip()
                                clean_text = self.clean_product_text(text, "ozon")
                                if (clean_text and len(clean_text) > 15 and 
                                    self.is_valid_mts_product(clean_text)):
                                    normalized = self.normalize_product_name(clean_text)
                                    if normalized not in seen_products:
                                        seen_products.add(normalized)
                                        product_id = self.generate_product_id(clean_text)
                                        current_products[product_id] = clean_text
                                        logger.info(f"Найден товар Ozon (ключ): {clean_text}")
                    
                    await self.human_delay(3, 5)
                    
                except Exception as e:
                    logger.error(f"Ошибка Ozon для {url}: {e}")
                    continue
            
            logger.info(f"Ozon: найдено {len(current_products)} товаров")
            
            if current_products:
                await self.check_changes(current_products, self.ozon_products, "Ozon", "ozon")
                self.ozon_products.update(current_products)
                self.save_products(self.ozon_file, self.ozon_products)
            
            return len(current_products) > 0
            
        except Exception as e:
            logger.error(f"Ошибка парсинга Ozon: {e}")
            return False
        finally:
            if driver:
                driver.quit()

    async def check_changes(self, current_products, previous_products, marketplace_name, marketplace_key):
        if self.first_run[marketplace_key]:
            if current_products:
                logger.info(f"{marketplace_name}: первый запуск, сохранено {len(current_products)} товаров")
                message = f"🎯 <b>Начато отслеживание {marketplace_name}</b>\n\n" \
                         f"📦 Найдено товаров: {len(current_products)}\n" \
                         f"🕒 {datetime.now().strftime('%H:%M:%S')}"
                await self.send_notification(message)
                self.first_run[marketplace_key] = False
            return
        
        if not previous_products:
            return
        
        current_ids = set(current_products.keys())
        previous_ids = set(previous_products.keys())
        
        new_products = current_ids - previous_ids
        if new_products:
            logger.info(f"{marketplace_name}: найдено {len(new_products)} новых товаров")
            for product_id in list(new_products)[:3]:
                product_name = current_products[product_id]
                message = f"🆕 <b>Новый товар на {marketplace_name}</b>\n\n" \
                         f"📦 {product_name}\n" \
                         f"🕒 {datetime.now().strftime('%H:%M:%S')}"
                await self.send_notification(message)
                await asyncio.sleep(1)
        
        removed_products = previous_ids - current_ids
        if removed_products and len(current_products) > 0:
            logger.info(f"{marketplace_name}: {len(removed_products)} товаров пропало")
            for product_id in list(removed_products)[:2]:
                product_name = previous_products[product_id]
                message = f"❌ <b>Товар раскупили на {marketplace_name}</b>\n\n" \
                         f"📦 {product_name}\n" \
                         f"🕒 {datetime.now().strftime('%H:%M:%S')}"
                await self.send_notification(message)
                await asyncio.sleep(1)

    async def run_complete_parsing(self):
        logger.info("Starting complete parsing cycle...")
        
        results = []
        
        ym_start = time.time()
        ym_success = await self.parse_yandex_market_selenium()
        ym_time = time.time() - ym_start
        results.append(f"Яндекс Маркет: {'OK' if ym_success else 'FAILED'} ({ym_time:.1f}с)")
        
        await asyncio.sleep(5)
        
        wb_start = time.time()
        wb_success = await self.parse_wildberries_selenium()
        wb_time = time.time() - wb_start
        results.append(f"Wildberries: {'OK' if wb_success else 'FAILED'} ({wb_time:.1f}с)")
        
        await asyncio.sleep(5)
        
        oz_start = time.time()
        oz_success = await self.parse_ozon_selenium()
        oz_time = time.time() - oz_start
        results.append(f"Ozon: {'OK' if oz_success else 'FAILED'} ({oz_time:.1f}с)")
        
        logger.info(f"Complete parsing completed: {', '.join(results)}")
        
        total_products = len(self.yandex_products) + len(self.wildberries_products) + len(self.ozon_products)
        logger.info(f"Всего отслеживается товаров: {total_products}")
        
        stats_message = f"📊 <b>Итоги проверки</b>\n\n" \
                       f"🛍 Яндекс Маркет: {len(self.yandex_products)} товаров\n" \
                       f"🛒 Wildberries: {len(self.wildberries_products)} товаров\n" \
                       f"📦 Ozon: {len(self.ozon_products)} товаров\n\n" \
                       f"🎯 Всего: {total_products} товаров\n" \
                       f"🕒 Время: {datetime.now().strftime('%H:%M:%S')}"
        await self.send_notification(stats_message)

async def stats_command(update, context):
    parser = context.bot_data['parser']
    
    message = "📈 <b>Статистика работы</b>\n\n"
    message += f"🔧 <b>Отслеживаемые магазины:</b>\n"
    message += f"• Яндекс Маркет: магазин МТС\n"
    message += f"• Wildberries: продавец 2980\n"
    message += f"• Ozon: продавец 55913\n\n"
    
    message += f"📦 <b>Статистика товаров:</b>\n"
    message += f"• Яндекс Маркет: {len(parser.yandex_products)} товаров\n"
    message += f"• Wildberries: {len(parser.wildberries_products)} товаров\n"
    message += f"• Ozon: {len(parser.ozon_products)} товаров\n\n"
    
    message += f"🔄 <b>Интервал проверки:</b> 90 секунд\n"
    message += f"🕒 <b>Время работы:</b> {datetime.now().strftime('%H:%M:%S')}"
    
    await update.message.reply_text(message, parse_mode='HTML')

async def sp_command(update, context):
    parser = context.bot_data['parser']
    
    ozon_message = "🛒 <b>Ozon - список товаров:</b>\n\n"
    if parser.ozon_products:
        for i, (product_id, product_name) in enumerate(list(parser.ozon_products.items())[:20], 1):
            ozon_message += f"{i}. {product_name}\n"
        if len(parser.ozon_products) > 20:
            ozon_message += f"\n... и еще {len(parser.ozon_products) - 20} товаров"
    else:
        ozon_message += "Товаров не найдено"
    
    wb_message = "📦 <b>Wildberries - список товаров:</b>\n\n"
    if parser.wildberries_products:
        for i, (product_id, product_name) in enumerate(list(parser.wildberries_products.items())[:20], 1):
            wb_message += f"{i}. {product_name}\n"
        if len(parser.wildberries_products) > 20:
            wb_message += f"\n... и еще {len(parser.wildberries_products) - 20} товаров"
    else:
        wb_message += "Товаров не найдено"
    
    market_message = "🛍 <b>Яндекс Маркет - список товаров:</b>\n\n"
    if parser.yandex_products:
        for i, (product_id, product_name) in enumerate(list(parser.yandex_products.items())[:20], 1):
            market_message += f"{i}. {product_name}\n"
        if len(parser.yandex_products) > 20:
            market_message += f"\n... и еще {len(parser.yandex_products) - 20} товаров"
    else:
        market_message += "Товаров не найдено"
    
    await update.message.reply_text(ozon_message, parse_mode='HTML')
    await asyncio.sleep(1)
    await update.message.reply_text(wb_message, parse_mode='HTML')
    await asyncio.sleep(1)
    await update.message.reply_text(market_message, parse_mode='HTML')

async def parsing_job(context):
    try:
        parser = context.job.data
        await parser.run_complete_parsing()
    except Exception as e:
        logger.error(f"Ошибка в фоновой задаче: {e}")

def main():
    BOT_TOKEN = "8518469225:AAHEhAmmjKO6aB-pIi_EPjptyRx4mU-v638"
    CHAT_ID = "5847809132"
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    parser = MarketplaceParser(BOT_TOKEN, CHAT_ID)
    application.bot_data['parser'] = parser
    
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("sp", sp_command))
    
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            callback=parsing_job,
            interval=90,
            first=10,
            data=parser
        )
        logger.info("Периодическая проверка настроена (каждые 90 секунд)")
    
    logger.info("Бот запущен с бережной очисткой товаров")
    
    try:
        application.run_polling()
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")

if __name__ == '__main__':
    main()
