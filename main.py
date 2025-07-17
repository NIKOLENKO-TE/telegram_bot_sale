import asyncio
import collections
import json
import logging
import os
import sys
import time
from datetime import datetime

import pytz
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import config

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.FileHandler("bot.log", mode="w", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.ERROR)

# --- Timezone helper ---
berlin_timezone = pytz.timezone("Europe/Berlin")


def get_berlin_timestamp():
    now = datetime.now(berlin_timezone)
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")


def log_button_event(user, chat_id, data, lang):
    date, time = get_berlin_timestamp()
    logger.info(
        f"BUTTON=[{data}] | USER=[@{user.username} ({user.id})] | CHAT_ID=[{chat_id}] | DATE={date} | TIME={time} | ZONE=[Europe/Berlin] | USER_LANG=[{lang}]")


def log_photo_event(user, chat_id, product, count, lang):
    date, time = get_berlin_timestamp()
    logger.info(
        f"PHOTOS_SENT=[{count}] | PRODUCT=[{product['name']}] | USER=[@{user.username} ({user.id})] | CHAT_ID=[{chat_id}] | DATE={date} | TIME={time} | ZONE=[Europe/Berlin] | USER_LANG=[{lang}]")

def log_categories_with_products(categories: dict, products: dict):
    # Группируем товары по категориям
    category_to_products = collections.defaultdict(list)
    for _, product in products.items():
        category = product.get("category", "other")
        category_to_products[category].append(product)

    total_products = sum(len(v) for v in category_to_products.values())
    logger.info(f"📂 Всего [{len(categories)}] категорий и [{total_products}] товаров загружено:")

    for key, name in categories.items():
        products_in_cat = category_to_products.get(key, [])
        if products_in_cat:
            logger.info(f" └─ [{key}]  {len(products_in_cat)} товар{'ов' if len(products_in_cat) != 1 else ''}")
            for product in products_in_cat:
                logger.info(f"     └─ {product['name']}")
        else:
            logger.info(f" └─ [{key}]")


# --- Managers ---
class CategoryManager:
    def __init__(self, path: str):
        self.path = path
        self.categories = self.load_categories()

    def load_categories(self) -> dict:
        if not os.path.exists(self.path):
            logger.error(f"❌ Categories file `{self.path}` not found.")
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.exception(f"❌ Error loading categories: {type(e).__name__}: {e}")
            return {}

class ProductManager:
    def __init__(self, folder: str):
        self.folder = folder
        self.products = self.load_all_lots()
        self.process_product_names()

    def load_all_lots(self) -> dict:
        lots = {}
        category_files = collections.defaultdict(list)
        if not os.path.exists(self.folder):
            logger.error(f"❌ Folder '{self.folder}' not found.")
            return lots
        for root, _, files in os.walk(self.folder):
            for filename in files:
                if filename.endswith(".json"):
                    path = os.path.join(root, filename)
                    try:
                        with open(path, encoding="utf-8") as f:
                            data = json.load(f)
                            lots[filename[:-5]] = data
                            category = os.path.relpath(root, self.folder)
                            category_files[category].append(filename)
                    except Exception as e:
                        logger.exception(f"❌ Error in: {path}: {type(e).__name__}: {e}")
        return lots

    # Process product names to ensure they follow the correct format
    def process_product_names(self):
        for product in self.products.values():
            price = product.get("price", "")
            name = product.get("name", "")
            if name.startswith("✅ €") and "|" in name:
                name = name.split("|", 1)[-1].strip()
            product["name"] = f"✅ €{price} | {name}"


class TextManager:
    def __init__(self, folder: str):
        self.folder = folder

    def load_text(self, name: str) -> str:
        path = os.path.join(self.folder, f"{name}.json")
        if not os.path.exists(path):
            logger.error(f"❌ Text file '{path}' not found.")
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("text", "")
        except Exception as e:
            logger.exception(f"❌ Error in: {path}: {type(e).__name__}: {e}")
            return ""


# --- Load config ---
TOKEN = config.TOKEN
CONTACT_URL = config.CONTACT_URL

category_manager = CategoryManager(config.CATEGORIES_PATH)
categories = category_manager.categories

product_manager = ProductManager(config.PRODUCTS_FOLDER)
products = product_manager.products
log_categories_with_products(categories, products)

text_manager = TextManager(config.TEXTS_FOLDER)
warranty_text = text_manager.load_text("warranty")
delivery_text = text_manager.load_text("delivery")
payment_text = text_manager.load_text("payment")
about_text = text_manager.load_text("about")
services_text = text_manager.load_text("services")


# --- Keyboards ---
def main_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("ℹ️ Обо мне", callback_data="about"),
        InlineKeyboardButton("🛡️ Гарантия", callback_data="warranty")],
        [InlineKeyboardButton("🚚 Доставка", callback_data="delivery"),
            InlineKeyboardButton("💰 Оплата", callback_data="payment")],
        [InlineKeyboardButton("🧰 Услуги", callback_data="services")],
        [InlineKeyboardButton("🛒 Товары в наличии", callback_data="available")],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]])


def category_keyboard(categories):
    cat_buttons = [InlineKeyboardButton(name, callback_data=f"cat_{key}") for key, name in categories.items()]
    cat_buttons = [cat_buttons[i:i + 2] for i in range(0, len(cat_buttons), 2)]
    nav_buttons = [[InlineKeyboardButton("🔙 Назад", callback_data="home"),
        InlineKeyboardButton("🏠 На главную", callback_data="home")],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]]
    return InlineKeyboardMarkup(cat_buttons + nav_buttons)


def product_keyboard(product):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"💶 €{product['price']}", callback_data="noop")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"cat_{product['category']}"),
            InlineKeyboardButton("🏠 На главную", callback_data="home")],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]])


def default_nav_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="home"),
        InlineKeyboardButton("🏠 На главную", callback_data="home")],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]])


# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    date, time_ = get_berlin_timestamp()
    logger.info(f"/start от @{user.username} ({user.id}) | DATE={date} | TIME={time_}")
    await update.message.reply_text("👋 Добро пожаловать! Выберите действие:", reply_markup=main_menu_keyboard())


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    log_button_event(user, query.message.chat.id, query.data, user.language_code)
    await query.answer()

    if query.data == "noop":
        return await query.answer("Это просто цена, действие не требуется.")

    await clear_last_album(context, query)

    if query.data == "available":
        await show_categories(query)
    elif query.data.startswith("cat_"):
        await show_category_products(query, query.data[4:])
    elif query.data in products:
        await show_product(query, context, products[query.data])
    elif query.data in ["about", "delivery", "payment", "services", "warranty"]:
        await show_text_page(query, query.data)
    elif query.data == "home":
        await show_home(query)


async def clear_last_album(context, query):
    album = context.user_data.pop("last_album", [])
    for msg_id in album:
        try:
            await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_id)
        except Exception:
            pass


async def show_categories(query):
    await (query.edit_message_text("📂 Выберите категорию:", reply_markup=category_keyboard(categories)))


async def show_category_products(query, cat_key):
    buttons = [[InlineKeyboardButton(p["name"], callback_data=k)] for k, p in products.items() if
                  p.get("category") == cat_key] or [
                  [InlineKeyboardButton("❌ Нет товаров в этой категории", callback_data="available")]]

    nav = [[InlineKeyboardButton("🔙 Назад", callback_data="available"),
        InlineKeyboardButton("🏠 На главную", callback_data="home")],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]]

    await query.edit_message_text(f"📦 Категория: {categories.get(cat_key, 'неизвестно')}",
        reply_markup=InlineKeyboardMarkup(buttons + nav))


async def show_product(query, context, product):
    user = query.from_user
    if not product.get("photos"):
        logger.warning(f"🖼️ У товара '{product['name']}' нет фото")
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=product.get("description", "Нет описания."),
            reply_markup=product_keyboard(product),
            parse_mode="HTML"
        )
    else:
        log_photo_event(user, query.message.chat.id, product, len(product["photos"]), user.language_code)
        media = [InputMediaPhoto(url) for url in product["photos"]]
        sent = await context.bot.send_media_group(chat_id=query.message.chat.id, media=media)
        context.user_data["last_album"] = [m.message_id for m in sent]
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=product.get("description", "Нет описания."),
            reply_markup=product_keyboard(product),
            parse_mode="HTML"
        )
    await query.delete_message()

async def show_text_page(query, page_key):
    page_map = {"about": about_text, "delivery": delivery_text, "payment": payment_text, "services": services_text,
        "warranty": warranty_text}
    await query.edit_message_text(page_map[page_key], reply_markup=default_nav_keyboard(), parse_mode="HTML")


async def show_home(query):
    await query.edit_message_text("👋 Вы снова на главной странице. \n👉 Выберите действие:",
        reply_markup=main_menu_keyboard())


if __name__ == "__main__":
    start_time = time.time()
    try:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(handle_buttons))
        logger.info(f"🕒 Bot started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        app.run_polling()
    except Exception as e:
        uptime = time.time() - start_time
        logger.exception(f"⛔ Ошибка при запуске бота через {uptime:.2f} секунд: {type(e).__name__}: {e}")
        time.sleep(10)
        input("Press any key to exit...")
