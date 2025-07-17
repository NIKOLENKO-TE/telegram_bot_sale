import asyncio
import collections
import json
import os
import pip  # Needed for GitHub Actions console
import pytz
import sys
import time
import traceback
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import config

class CategoryManager:
    def __init__(self, path: str):
        self.path = path
        self.categories = self.load_categories()

    def load_categories(self) -> dict:
        if not os.path.exists(self.path):
            print(f"❌ Categories file `{self.path}` not found.")
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error loading categories: {type(e).__name__}: {e}")
            traceback.print_exc()
            return {}

    def print_categories(self) -> None:
        print(f"📂 Всего категорий загружено: {len(self.categories)}")
        for key, name in self.categories.items():
            print(f"  └── {key}: {name}")

class ProductManager:
    def __init__(self, folder: str):
        self.folder = folder
        self.products = self.load_all_lots()
        self.process_product_names()

    def load_all_lots(self) -> dict:
        lots = {}
        category_files = collections.defaultdict(list)
        if not os.path.exists(self.folder):
            print(f"❌ Folder '{self.folder}' not found.")
            return lots
        for root, _, files in os.walk(self.folder):
            for filename in files:
                if filename.endswith(".json"):
                    path = os.path.join(root, filename)
                    try:
                        with open(path, encoding="utf-8") as f:
                            data = json.load(f)
                            lots[filename[:-5]] = data
                            rel_path = os.path.relpath(path, self.folder)
                            category = os.path.relpath(root, self.folder)
                            category_files[category].append(filename)
                    except Exception as e:
                        print(f"❌ Error in: {path}: {type(e).__name__}: {e}")
                        traceback.print_exc()
        print(f"\n📦 Всего товаров загружено: {len(lots)}")
        for cat, files in category_files.items():
            print(f"  └── 📦 {cat}: {len(files)}")
            for fname in files:
                print(f"      └── {fname}")
        return lots

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
        if not os.path.exists(self.folder):
            print(f"❌ Folder '{self.folder}' not found.")
            return ""
        path = os.path.join(self.folder, f"{name}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data["text"]
        except Exception as e:
            print(f"❌ Error in: {path}: {type(e).__name__}: {e}")
            traceback.print_exc()
            return ""

TOKEN = config.TOKEN
CONTACT_URL = config.CONTACT_URL

category_manager = CategoryManager(config.CATEGORIES_PATH)
categories = category_manager.categories
category_manager.print_categories()

product_manager = ProductManager(config.PRODUCTS_FOLDER)
products = product_manager.products

text_manager = TextManager(config.TEXTS_FOLDER)
warranty_text = text_manager.load_text("warranty")
delivery_text = text_manager.load_text("delivery")
payment_text = text_manager.load_text("payment")
about_text = text_manager.load_text("about")
services_text = text_manager.load_text("services")

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ℹ️ Обо мне", callback_data="about"),
            InlineKeyboardButton("🛡️ Гарантия", callback_data="warranty")
        ],
        [
            InlineKeyboardButton("🚚 Доставка", callback_data="delivery"),
            InlineKeyboardButton("💰 Оплата", callback_data="payment")
        ],
        [
            InlineKeyboardButton("🛠️ Услуги", callback_data="services")
        ],
        [
            InlineKeyboardButton("🛒 Товары в наличии", callback_data="available")
        ],
        [
            InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)
        ]
    ])

def category_keyboard(categories):
    cat_buttons = [
        InlineKeyboardButton(name, callback_data=f"cat_{key}")
        for key, name in categories.items()
    ]
    cat_buttons = [cat_buttons[i:i + 2] for i in range(0, len(cat_buttons), 2)]
    nav_buttons = [
        [
            InlineKeyboardButton("🔙 Назад", callback_data="home"),
            InlineKeyboardButton("🏠 На главную", callback_data="home")
        ],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]
    ]
    return InlineKeyboardMarkup(cat_buttons + nav_buttons)

def product_keyboard(product):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💶 €{product['price']}", callback_data="noop")],
        [
            InlineKeyboardButton("🔙 Назад", callback_data=f"cat_{product['category']}"),
            InlineKeyboardButton("🏠 На главную", callback_data="home")
        ],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]
    ])

def default_nav_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Назад", callback_data="home"),
            InlineKeyboardButton("🏠 На главную", callback_data="home")
        ],
        [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    print(f"▶️ `/start` от {user.username} (ID: {user.id}) в {datetime.now()}")
    await update.message.reply_text(
        "👋 Добро пожаловать! \nВы на главной странице. \nВыберите действие:",
        reply_markup=main_menu_keyboard()
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    print(
        f"🟢 `{query.data}` от `@{user.username}` (ID: {user.id}) в `Europe/Berlin` time `{datetime.now(pytz.timezone('Europe/Berlin'))}`")
    await query.answer()

    if query.data == "noop":
        await query.answer("Это просто цена, действие не требуется.")
        return

    album = context.user_data.pop("last_album", [])
    for msg_id in album:
        try:
            await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_id)
        except Exception:
            pass

    if query.data == "available":
        await query.edit_message_text(
            "📂 Выберите категорию:",
            reply_markup=category_keyboard(categories)
        )
    elif query.data.startswith("cat_"):
        cat_key = query.data[4:]
        product_buttons = [
            [InlineKeyboardButton(p["name"], callback_data=k)]
            for k, p in products.items() if p.get("category") == cat_key
        ]
        if not product_buttons:
            product_buttons = [[InlineKeyboardButton("❌ Нет товаров в этой категории", callback_data="available")]]
        nav_buttons = [
            [
                InlineKeyboardButton("🔙 Назад", callback_data="available"),
                InlineKeyboardButton("🏠 На главную", callback_data="home")
            ],
            [InlineKeyboardButton("📩 Связаться с продавцом", url=CONTACT_URL)]
        ]
        await query.edit_message_text(
            f"📦 Товары в категории: {categories.get(cat_key, 'неизвестно')}",
            reply_markup=InlineKeyboardMarkup(product_buttons + nav_buttons)
        )
    elif query.data in products:
        product = products[query.data]
        if not product.get("photos"):
            print(f"🖼️ У товара '{product['name']}' нет фото")
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text="🖼️ У этого товара нет фотографий.",
                reply_markup=product_keyboard(product),
                parse_mode="HTML"
            )
        else:
            print(
                f"📸 Отправка {len(product['photos'])} фото по товару '{product['name']}' пользователю `@{user.username}`")
            media = [InputMediaPhoto(url) for url in product["photos"]]
            sent = await context.bot.send_media_group(chat_id=query.message.chat.id, media=media)
            context.user_data["last_album"] = [m.message_id for m in sent]
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=product["description"],
                reply_markup=product_keyboard(product),
                parse_mode="HTML"
            )
        await query.delete_message()
    elif query.data == "about":
        await query.edit_message_text(
            about_text,
            reply_markup=default_nav_keyboard()
        )
    elif query.data == "delivery":
        await query.edit_message_text(
            delivery_text,
            reply_markup=default_nav_keyboard(),
            parse_mode="HTML"
        )
    elif query.data == "payment":
        await query.edit_message_text(
            payment_text,
            reply_markup=default_nav_keyboard(),
            parse_mode="HTML"
        )
    elif query.data == "services":
        await query.edit_message_text(
            services_text,
            reply_markup=default_nav_keyboard(),
            parse_mode="HTML"
        )
    elif query.data == "warranty":
        await query.edit_message_text(
            warranty_text,
            reply_markup=default_nav_keyboard(),
            parse_mode="HTML"
        )
    elif query.data == "home":
        await query.edit_message_text(
            "👋 Вы снова на главной странице. \n👉 Выберите действие:",
            reply_markup=main_menu_keyboard()
        )

if __name__ == "__main__":
    start_time = time.time()
    try:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(handle_buttons))
        print(f"🕒 Bot started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        app.run_polling()
    except Exception as e:
        uptime = time.time() - start_time
        print(f"⛔ Ошибка при запуске бота через {uptime:.2f} секунд: {type(e).__name__}: {e}")
        traceback.print_exc()
        time.sleep(10)
        input("Press any key to exit...")
