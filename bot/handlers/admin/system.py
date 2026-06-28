"""
Обработчики раздела «Настройки бота».

Управление обновлением, остановкой бота и редактированием текстов.
"""
import asyncio
import logging
import os
import re
import subprocess
import sys
from aiogram import Router, F
from aiogram import types
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter

from config import GITHUB_REPO_URL, UPDATE_SCRIPT_PATH, BASE_DIR
from bot.utils.admin import is_admin
from bot.utils.git_utils import (
    check_git_available,
    get_current_commit,
    get_current_branch,
    get_remote_url,
    set_remote_url,
    check_for_updates,
    pull_updates,
    pull_to_commit,
    force_pull_updates,
    get_last_commit_info,
    get_previous_commits_info,
    install_requirements,
    restart_bot,
)
from bot.keyboards.admin import (
    bot_settings_kb,
    bot_mode_toggle_confirm_kb,
    update_confirm_kb,
    force_overwrite_confirm_kb,
    stop_bot_confirm_kb,
    back_and_home_kb,
    admin_logs_menu_kb,
)

logger = logging.getLogger(__name__)

from bot.utils.text import safe_edit_or_send
from bot.utils.update_block import is_update_blocked, get_blocked_message, try_unblock, set_update_blocked

router = Router()


# ============================================================================
# ГЛАВНОЕ МЕНЮ НАСТРОЕК
# ============================================================================

@router.callback_query(F.data == "admin_bot_settings")
async def show_bot_settings(callback: CallbackQuery, state: FSMContext):
    """Показывает меню настроек бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.services.vpn_api import get_bot_mode
    mode = get_bot_mode()
    if mode == 'subscription':
        mode_label = "📡 Подписка"
        mode_desc = (
            "Бот выдаёт пользователю одну <b>subscription-ссылку</b> — "
            "клиент сам подтягивает все протоколы сервера."
        )
    else:
        mode_label = "🔑 Ключи"
        mode_desc = (
            "Бот создаёт один VLESS/VMess-клиент в одном inbound "
            "и выдаёт ссылку + JSON-конфиг."
        )

    text = (
        "⚙️ <b>Настройки бота</b>\n\n"
        f"<b>Режим работы:</b> {mode_label}\n"
        f"<i>{mode_desc}</i>\n\n"
        "Выберите действие:"
    )

    await safe_edit_or_send(callback.message,
        text,
        reply_markup=bot_settings_kb(mode)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_toggle_bot_mode")
async def admin_toggle_bot_mode(callback: CallbackQuery, state: FSMContext):
    """Показывает экран подтверждения переключения режима работы бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.services.vpn_api import get_bot_mode
    current = get_bot_mode()
    target = 'key' if current == 'subscription' else 'subscription'

    if target == 'subscription':
        warning = (
            "⚠️ <b>Переключение в режим Подписка</b>\n\n"
            "При ближайших синхронизациях (≈раз в 30 минут) бот:\n"
            "• создаст клиентов во всех inbound каждого сервера для существующих ключей "
            "(с единым subId и email);\n"
            "• новые ключи будут выдаваться как <b>subscription URL</b>.\n\n"
            "Текущие пользователи продолжат работать со старыми ссылками "
            "до их замены или продления.\n\n"
            "Продолжить?"
        )
    else:
        warning = (
            "⚠️ <b>Переключение в режим Ключи</b>\n\n"
            "При ближайших синхронизациях бот:\n"
            "• оставит на каждом сервере по одному клиенту (в inbound с минимальным id) "
            "на каждый ключ;\n"
            "• остальных клиентов с тем же email — <b>удалит</b>;\n"
            "• новые ключи будут выдаваться как одна VLESS/VMess-ссылка.\n\n"
            "<b>Subscription URL у пользователей перестанут работать.</b>\n\n"
            "Продолжить?"
        )

    await safe_edit_or_send(callback.message, warning,
                            reply_markup=bot_mode_toggle_confirm_kb(target))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set_bot_mode:"))
async def admin_set_bot_mode(callback: CallbackQuery, state: FSMContext):
    """Сохраняет новый режим работы бота в settings."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    target = callback.data.split(":", 1)[1]
    if target not in ('subscription', 'key'):
        await callback.answer("⛔ Недопустимое значение", show_alert=True)
        return

    from database.db_settings import set_setting
    set_setting('bot_mode', target)
    logger.info(
        f"Bot mode переключён в '{target}' администратором {callback.from_user.id}"
    )
    label = "📡 Подписка" if target == 'subscription' else "🔑 Ключи"
    await callback.answer(f"✅ Режим установлен: {label}", show_alert=True)
    await show_bot_settings(callback, state)






# ============================================================================
# РУЧНОЕ ОБНОВЛЕНИЕ БОТА (КОМАНДОЙ /UPDATE)
# ============================================================================

@router.message(Command("update"))
async def admin_update_cmd(message: Message, state: FSMContext):
    """Скрытая команда экстренного обновления для администраторов."""
    if not is_admin(message.from_user.id):
        return
        
    # Проверяем и обновляем remote URL если нужно
    current_remote = get_remote_url()
    if current_remote != GITHUB_REPO_URL and GITHUB_REPO_URL:
        set_remote_url(GITHUB_REPO_URL)
        
    await safe_edit_or_send(message,
        "🔄 <b>Экстренное обновление...</b>\n\n"
        "Загружаю изменения с GitHub..."
    )
    
    success, log_message = pull_updates()
    
    if not success:
        await safe_edit_or_send(message,
            f"❌ <b>Ошибка обновления</b>\n\n{log_message}"
        )
        return
        
    logger.info(f"🔄 Бот экстренно обновлён администратором {message.from_user.id} через команду /update")
    
    await safe_edit_or_send(message,
        f"✅ <b>Обновление завершено!</b>\n\n{log_message}\n\n"
        "🔄 Перезапуск бота. Нажмите /start",
        force_new=True
    )
    
    await state.clear()
    await asyncio.sleep(2)
    
    # Устанавливаем/обновляем зависимости
    success, req_message = install_requirements()
    if not success:
        logger.error(f"Ошибка установки зависимостей: {req_message}")
        await safe_edit_or_send(message,
            f"⚠️ <b>Ошибка установки зависимостей</b>\n\n{req_message}\n\n"
            "Бот не будет перезапущен. Проверьте requirements.txt и попробуйте снова.",
            force_new=True
        )
        return
    
    restart_bot()


# ============================================================================
# ОБНОВЛЕНИЕ БОТА (ИНТЕРФЕЙС)
# ============================================================================

@router.callback_query(F.data == "admin_update_bot")
async def show_update_confirm(callback: CallbackQuery, state: FSMContext):
    """Показывает подтверждение обновления."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    # Проверяем настроен ли GitHub
    if not GITHUB_REPO_URL:
        await safe_edit_or_send(callback.message, 
            "❌ <b>GitHub не настроен</b>\n\n"
            "Укажите URL репозитория в файле <code>config.py</code>:\n"
            "<code>GITHUB_REPO_URL = \"https://github.com/user/repo.git\"</code>",
            reply_markup=back_and_home_kb("admin_bot_settings")
        )
        await callback.answer()
        return
    
    # Проверяем и обновляем remote URL если нужно
    current_remote = get_remote_url()
    if current_remote != GITHUB_REPO_URL:
        set_remote_url(GITHUB_REPO_URL)

    # Проверяем условия разблокировки
    try_unblock()

    if is_update_blocked():
        await safe_edit_or_send(callback.message,
            get_blocked_message(),
            reply_markup=back_and_home_kb("admin_bot_settings")
        )
        await callback.answer()
        return
    
    # Показываем сообщение о проверке
    await safe_edit_or_send(callback.message, 
        "🔍 <b>Проверка обновлений...</b>\n\n"
        "Подключаюсь к GitHub..."
    )
    
    # Проверяем наличие обновлений
    success, commits_behind, log_text, has_blocking, blocking_commit, is_beta_only = check_for_updates()
    
    if not success:
        await safe_edit_or_send(callback.message, 
            f"❌ <b>Ошибка проверки</b>\n\n{log_text}",
            reply_markup=back_and_home_kb("admin_bot_settings")
        )
        await callback.answer()
        return
    
    commit_hash = get_current_commit() or "неизвестно"
    
    if commits_behind > 0:
        branch = get_current_branch() or "main"
        target_rev = f"origin/{branch}"
    else:
        target_rev = "HEAD"
        
    last_commit = get_last_commit_info(target_rev)
    previous_commits = get_previous_commits_info(5, target_rev)
    
    # Формируем текст с коммитами
    commits_text = f"🔹 <b>Последний коммит:</b>\n``<code>\n{last_commit}\n</code>``\n"
    if previous_commits != "Нет предыдущих коммитов":
         commits_text += f"\n🔸 <b>Предыдущие 5 коммитов:</b>\n``<code>\n{previous_commits}\n</code>``"
    
    # Сохраняем данные о блокирующем коммите в FSM state
    await state.update_data(
        has_blocking=has_blocking,
        blocking_commit=blocking_commit
    )
    
    # Если обновлений нет
    if commits_behind == 0:
        await safe_edit_or_send(callback.message, 
            "✅ <b>Обновление не требуется, у вас последняя версия</b>\n\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n"
            f"{commits_text}",
            reply_markup=update_confirm_kb(has_updates=False)
        )
    elif has_blocking and blocking_commit:
        # Есть блокирующее обновление — показываем предупреждение
        # Убираем маркер ! из сообщения при отображении
        blocking_msg = blocking_commit['message'].lstrip('!')
        blocking_hash = blocking_commit['hash'][:8]
        
        await safe_edit_or_send(callback.message, 
            f"⚠️ <b>Блокирующее обновление!</b>\n\n"
            f"📦 <b>Доступно обновлений:</b> {commits_behind}\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n"
            f"🚫 Среди обновлений найден <b>блокирующий коммит</b> <code>{blocking_hash}</code>:\n"
            f"``<code>\n{blocking_msg}\n</code>``\n\n"
            f"Будет установлен <b>только этот коммит</b>. "
            f"После перезапуска вам потребуется выполнить требуемые действия, "
            f"прежде чем обновляться дальше.\n\n"
            f"{commits_text}",
            reply_markup=update_confirm_kb(has_updates=True, has_blocking=True)
        )
    elif is_beta_only:
        # Только бета-обновления
        await safe_edit_or_send(callback.message, 
            f"🧪 <b>Доступна бета-версия!</b>\n\n"
            f"📦 <b>Доступно бета-коммитов:</b> {commits_behind}\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n"
            f"{commits_text}\n\n"
            "⚠️ Это тестовая версия. Устанавливайте на свой страх и риск.",
            reply_markup=update_confirm_kb(has_updates=True, has_blocking=False, is_beta_only=True)
        )
    else:
        # Есть обычные обновления
        await safe_edit_or_send(callback.message, 
            f"📦 <b>Доступно обновлений:</b> {commits_behind}\n\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n"
            f"{commits_text}\n\n"
            "⚠️ После обновления бот автоматически перезапустится.\n"
            "Это займёт несколько секунд.",
            reply_markup=update_confirm_kb(has_updates=True, has_blocking=False, is_beta_only=False)
        )
    
    await callback.answer()


@router.callback_query(F.data == "admin_update_bot_confirm")
async def update_bot_confirmed(callback: CallbackQuery, state: FSMContext):
    """Выполняет обновление и перезапуск бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    # Проверяем и обновляем remote URL если нужно
    current_remote = get_remote_url()
    if current_remote != GITHUB_REPO_URL:
        set_remote_url(GITHUB_REPO_URL)
    
    # Получаем данные о блокирующем коммите из FSM state
    data = await state.get_data()
    has_blocking = data.get('has_blocking', False)
    blocking_commit = data.get('blocking_commit')
    
    if has_blocking and blocking_commit:
        # Блокирующее обновление — обновляем до конкретного коммита
        await safe_edit_or_send(callback.message, 
            "🔄 <b>Блокирующее обновление...</b>\n\n"
            f"Обновляю до коммита <code>{blocking_commit['hash'][:8]}</code>..."
        )
        
        success, message = pull_to_commit(blocking_commit['hash'])
    else:
        # Обычное обновление — git pull
        await safe_edit_or_send(callback.message, 
            "🔄 <b>Обновление...</b>\n\n"
            "Загружаю изменения с GitHub..."
        )
        
        success, message = pull_updates()
    
    if not success:
        await safe_edit_or_send(callback.message, 
            f"❌ <b>Ошибка обновления</b>\n\n{message}",
            reply_markup=back_and_home_kb("admin_bot_settings")
        )
        await callback.answer()
        return
    
    # Успешное обновление — показываем лог и перезапускаем
    logger.info(f"🔄 Бот обновлён администратором {callback.from_user.id}")
    
    if has_blocking:
        set_update_blocked()
        await safe_edit_or_send(callback.message, 
            f"✅ <b>Блокирующее обновление завершено!</b>\n\n{message}\n\n"
            "⚠️ После перезапуска выполните требуемые действия перед следующим обновлением.\n\n"
            "🔄 Перезапуск бота. Нажмите /start"
        )
    else:
        await safe_edit_or_send(callback.message, 
            f"✅ <b>Обновление завершено!</b>\n\n{message}\n\n"
            "🔄 Перезапуск бота. Нажмите /start"
        )
    
    await callback.answer("Бот перезапускается...", show_alert=True)
    
    # Очищаем FSM state
    await state.clear()
    
    # Даём время на отправку сообщения
    await asyncio.sleep(2)
    
    # Устанавливаем/обновляем зависимости
    success, req_message = install_requirements()
    if not success:
        logger.error(f"Ошибка установки зависимостей: {req_message}")
        await safe_edit_or_send(callback.message,
            f"⚠️ <b>Ошибка установки зависимостей</b>\n\n{req_message}\n\n"
            "Бот не будет перезапущен. Проверьте requirements.txt и попробуйте снова."
        )
        return
    
    # Перезапускаем бота
    restart_bot()



@router.callback_query(F.data == "admin_force_overwrite")
async def show_force_overwrite(callback: CallbackQuery, state: FSMContext):
    """Показывает предупреждение перед принудительной перезаписью."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    # Проверяем настроен ли GitHub
    if not GITHUB_REPO_URL:
        await safe_edit_or_send(callback.message, 
            "❌ <b>GitHub не настроен</b>\n\n"
            "Укажите URL репозитория в файле <code>config.py</code>:\n"
            "<code>GITHUB_REPO_URL = \"https://github.com/user/repo.git\"</code>",
            reply_markup=back_and_home_kb("admin_bot_settings")
        )
        await callback.answer()
        return
        
    await safe_edit_or_send(callback.message, 
        "⚠️ <b>ПРИНУДИТЕЛЬНАЯ ПЕРЕЗАПИСЬ</b>\n\n"
        f"Все файлы бота (кроме конфигурации и баз данных) будут перезаписаны оригинальными файлами из репозитория:\n<code>{GITHUB_REPO_URL}</code>\n\n"
        "🛑 *Внимание: Все ваши локальные изменения в коде будут безвозвратно потеряны!*\n\n"
        "Вы действительно хотите продолжить?",
        reply_markup=force_overwrite_confirm_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_force_overwrite_confirm")
async def force_overwrite_confirmed(callback: CallbackQuery, state: FSMContext):
    """Выполняет принудительную перезапись и перезапуск бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    # Проверяем и обновляем remote URL если нужно
    current_remote = get_remote_url()
    if current_remote != GITHUB_REPO_URL and GITHUB_REPO_URL:
        set_remote_url(GITHUB_REPO_URL)
    
    await safe_edit_or_send(callback.message, 
        "🔄 <b>Принудительная перезапись...</b>\n\n"
        "Связываюсь с репозиторием и проверяю обновления..."
    )
    
    # Проверяем наличие блокирующих коммитов перед перезаписью
    from bot.utils.git_utils import get_pending_commits_list, find_first_blocking_commit
    
    success_fetch, pending_commits = get_pending_commits_list()
    blocking_commit = find_first_blocking_commit(pending_commits) if success_fetch else None
    
    if blocking_commit:
        # Есть блокирующий коммит — обновляемся только до него (через reset --hard)
        success, message = pull_to_commit(blocking_commit['hash'])
        
        if not success:
            await safe_edit_or_send(callback.message, 
                f"❌ <b>Ошибка перезаписи</b>\n\n{message}",
                reply_markup=back_and_home_kb("admin_bot_settings")
            )
            await callback.answer()
            return
        
        # Ставим блокировку обновлений
        set_update_blocked()
        
        blocking_msg = blocking_commit['message'].lstrip('!')
        blocking_hash = blocking_commit['hash'][:8]
        
        logger.info(f"🔄 Принудительная перезапись до блокирующего коммита {blocking_hash} администратором {callback.from_user.id}")
        
        await safe_edit_or_send(callback.message, 
            f"✅ <b>Обновлено до блокирующего коммита!</b>\n\n{message}\n\n"
            f"🚫 Среди обновлений найден <b>блокирующий коммит</b> <code>{blocking_hash}</code>:\n"
            f"<code>\n{blocking_msg}\n</code>\n\n"
            "⚠️ После перезапуска выполните требуемые действия перед следующим обновлением.\n\n"
            "🔄 Перезапуск бота. Нажмите /start"
        )
    else:
        # Нет блокирующих коммитов — полная перезапись
        success, message = force_pull_updates()
        
        if not success:
            await safe_edit_or_send(callback.message, 
                f"❌ <b>Ошибка перезаписи</b>\n\n{message}",
                reply_markup=back_and_home_kb("admin_bot_settings")
            )
            await callback.answer()
            return
        
        logger.info(f"🔄 Бот принудительно перезаписан администратором {callback.from_user.id}")
        
        await safe_edit_or_send(callback.message, 
            f"✅ <b>Успешно!</b>\n\n{message}\n\n"
            "🔄 Перезапуск бота. Нажмите /start"
        )
    
    await callback.answer("Бот перезапускается...", show_alert=True)
    
    # Очищаем FSM state
    await state.clear()
    
    # Даём время на отправку сообщения
    await asyncio.sleep(2)
    
    # Устанавливаем/обновляем зависимости
    success, req_message = install_requirements()
    if not success:
        logger.error(f"Ошибка установки зависимостей: {req_message}")
        await safe_edit_or_send(callback.message,
            f"⚠️ <b>Ошибка установки зависимостей</b>\n\n{req_message}\n\n"
            "Бот не будет перезапущен. Проверьте requirements.txt и попробуйте снова."
        )
        return
    
    # Перезапускаем бота
    restart_bot()


# ============================================================================
# ИЗМЕНЕНИЕ ТЕКСТОВ (ЗАГЛУШКА)
# ============================================================================

# ============================================================================
# ИЗМЕНЕНИЕ ТЕКСТОВ
# ============================================================================

from bot.states.admin_states import AdminStates

@router.callback_query(F.data == "admin_edit_texts")
async def edit_texts_menu(callback: CallbackQuery, state: FSMContext):
    """Меню выбора текста для редактирования."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from bot.keyboards.admin import back_and_home_kb
    
    builder = InlineKeyboardBuilder()
    
    builder.row(InlineKeyboardButton(text="📝 Главная страница", callback_data="edit_text:main"))
    builder.row(InlineKeyboardButton(text="📝 Справка (текст)", callback_data="edit_text:help"))
    builder.row(InlineKeyboardButton(text="📝 Справка (название кнопки)", callback_data="edit_text:help_btn_label"))
    builder.row(InlineKeyboardButton(text="📝 Инфо (текст)", callback_data="edit_text:info"))
    builder.row(InlineKeyboardButton(text="📝 Текст перед оплатой", callback_data="edit_text:prepayment"))
    builder.row(InlineKeyboardButton(text="📝 Текст выдачи ключа", callback_data="edit_text:key_delivery"))
    builder.row(InlineKeyboardButton(text="📢 Ссылка: Новости", callback_data="edit_link:news"))
    builder.row(InlineKeyboardButton(text="💬 Ссылка: Поддержка", callback_data="edit_link:support"))
    builder.row(InlineKeyboardButton(text="📢 Ссылка: Мой канал", callback_data="edit_link:channel"))
    builder.row(InlineKeyboardButton(text="🖼️ Стартовая картинка", callback_data="edit_image:main"))
    builder.row(InlineKeyboardButton(text="🔑 Выдача AI-ключа", callback_data="edit_text:ai_key_instructions"))
    builder.row(InlineKeyboardButton(text="🤖 AI тариф S", callback_data="edit_text:ai_tariff_user_text_s"))
    builder.row(InlineKeyboardButton(text="🤖 AI тариф P", callback_data="edit_text:ai_tariff_user_text_p"))
    builder.row(InlineKeyboardButton(text="🤖 AI тариф V", callback_data="edit_text:ai_tariff_user_text_v"))
    builder.row(InlineKeyboardButton(text="💰 Текст пополнения токенов", callback_data="edit_text:prepayment"))
    builder.row(InlineKeyboardButton(text="🔄 Обновить с сервера", callback_data="admin_server_update"))
    builder.row(InlineKeyboardButton(text="🤖 AI доступ", callback_data="admin_ai_access"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить ключ по ID", callback_data="admin_delete_key"))
    
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_bot_settings"))
    
    await safe_edit_or_send(callback.message, 
        "✏️ <b>Редактирование текстов</b>\n\n"
        "Выберите, что хотите изменить:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_server_update")
async def admin_server_update(callback: CallbackQuery, state: FSMContext):
    """Сразу запускает обновление с сервера через updatebot.sh."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    script_path = UPDATE_SCRIPT_PATH or "/root/svaboda_super/updatebot.sh"

    if not os.path.exists(script_path):
        await safe_edit_or_send(callback.message,
            f"❌ <b>Скрипт не найден</b>\n\n"
            f"Путь: <code>{script_path}</code>\n\n"
            f"Укажите правильный путь в config.py:\n"
            f'<code>UPDATE_SCRIPT_PATH = "/root/svaboda_super/updatebot.sh"</code>',
            reply_markup=back_and_home_kb("admin_edit_texts")
        )
        await callback.answer()
        return

    await safe_edit_or_send(callback.message,
        "⚙️ <b>Начинаю обновление системы.</b>\n\n"
        "Этой командой вручную можно обновить на своём сервере\n\n"
        "Команда обновления:\n"
        f"<code>bash {script_path}</code>\n\n"
        "Во время обновления бот может быть временно недоступен.\n\n"
        "✅ После завершения просто отправьте команду:\n\n"
        "/start\n\n"
        "Спасибо за ожидание!",
        reply_markup=back_and_home_kb("admin_edit_texts")
    )
    await callback.answer()

    # Даём боту 1 секунду на отправку ответа, потом запускаем скрипт
    await asyncio.sleep(1)
    try:
        subprocess.Popen(
            ["nohup", "bash", script_path],
            stdout=open("/dev/null", "w"),
            stderr=open("/dev/null", "w"),
            cwd="/root/svaboda_super",
            start_new_session=True
        )
    except Exception as e:
        logger.error(f"server update callback error: {e}", exc_info=True)







@router.callback_query(F.data.startswith("edit_image:"))
async def edit_image_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    page_key = callback.data.split(":")[1]
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT image_custom, image_default FROM pages WHERE page_key=?", (page_key,))
    row = c.fetchone()
    conn.close()
    
    current_image = row[0] if row and row[0] else (row[1] if row and row[1] else None)
    
    await state.set_state('wait_edit_image')
    await state.update_data(editing_image_page=page_key)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_edit_texts"))
    
    if current_image:
        text = "🖼️ <b>Редактирование картинки: " + page_key + "</b>\n\nТекущая картинка:\n<code>" + str(current_image) + "</code>\n\n👇 Отправьте ссылку на новую картинку (http/https):"
    else:
        text = "🖼️ <b>Редактирование картинки: " + page_key + "</b>\n\nКартинка не установлена (используется дефолтная).\n\n👇 Отправьте ссылку на картинку (http/https):"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.message(StateFilter('wait_edit_image'), ~F.text.startswith('/'))
async def save_image(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    from bot.keyboards.admin import back_and_home_kb
    from bot.utils.text import get_message_text_for_storage
    
    data = await state.get_data()
    page_key = data.get('editing_image_page')
    
    if not page_key:
        await state.clear()
        await message.reply("❌ Ошибка состояния.", reply_markup=back_and_home_kb("admin_edit_texts"))
        return
    
    new_value = get_message_text_for_storage(message, 'plain')
    if not new_value.startswith(('http://', 'https://')):
        await message.reply(
            "❌ <b>Ошибка:</b> Ссылка должна начинаться с <code>http://</code> или <code>https://</code>\n\nВы ввели: <code>" + new_value + "</code>\n\nПопробуйте ещё раз или нажмите /start для отмены.",
            parse_mode="HTML"
        )
        return
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("UPDATE pages SET image_custom = ?, updated_at = CURRENT_TIMESTAMP WHERE page_key = ?", (new_value, page_key))
    conn.commit()
    conn.close()
    
    await state.clear()
    
    try:
        await message.delete()
    except Exception:
        pass
    
    await message.answer(
        "✅ <b>Картинка обновлена!</b>\n\n<code>" + new_value + "</code>",
        parse_mode="HTML",
        reply_markup=back_and_home_kb("admin_edit_texts")
    )
@router.callback_query(F.data.startswith("edit_text:"))
async def edit_text_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования конкретного текста через универсальный редактор."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.handlers.admin.message_editor import show_message_editor
    
    key = callback.data.split(":")[1]
    
    # Белый список допустимых ключей — защита от инъекции произвольного ключа настроек
    ALLOWED_KEYS = {
        'main',
        'help',
        'help_btn_label',
        'info',
        'prepayment',
        'key_delivery',
        'ai_key_instructions',
        'ai_tokens',
        'ai_tariff_user_text_s',
        'ai_tariff_user_text_p',
        'ai_tariff_user_text_v',
        'ai_key_instructions',
    }
    
    if key not in ALLOWED_KEYS:
        await callback.answer("⛔ Недопустимый параметр", show_alert=True)
        return
    
    # Специальная обработка для названия кнопки справки
    if key == 'help_btn_label':
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        import sqlite3, json as _json
        conn = sqlite3.connect('database/vpn_bot.db')
        cur = conn.cursor()
        cur.execute("SELECT buttons_default FROM pages WHERE page_key='main'")
        row = cur.fetchone()
        buttons = _json.loads(row[0]) if row and row[0] else []
        current_label = '❓ Справка'
        for b in buttons:
            if b.get('id') == 'btn_help':
                current_label = b.get('label', current_label)
                break
        conn.close()
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_edit_texts"))
        
        await callback.message.edit_text(
            f"📝 <b>Название кнопки справки</b>\n\n"
            f"Текущее название: <b>{current_label}</b>\n\n"
            f"Отправьте новое название для кнопки (например: ℹ️ Инфо)",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        await state.set_state('edit_help_btn_label')
        await callback.answer()
        return
    
    # Тексты справки для каждого ключа
    help_texts = {
        'main': (
            "📝 <b>Справка: Текст главной страницы</b>\n\n"
            "Чтобы изменить текст, вернитесь и просто отправьте боту новое сообщение с нужным текстом.\n"
            "Вы можете прикрепить фото/видео.\n\n"
            "Переменные:\n"
            "• <code>%тарифы%</code> — список тарифов с ценами\n"
            "• <code>%без_тарифов%</code> — не добавлять тарифы"
        ),
        'key_delivery': (
            "📝 <b>Справка: Текст выдачи ключа</b>\n\n"
            "Формат: <b>только текст</b> (без фото).\n\n"
            "Переменные:\n"
            "• <code>%ключ%</code> — ссылка или ключ в моноширинном виде для копирования\n"
            "• <code>%ссылка%</code> — чистая ссылка без code/pre, кликабельная для HTTP/HTTPS подписки\n\n"
            "Можно использовать один тег или оба сразу."
        ),
        'info': (
            "📝 <b>Справка: Инфо (текст)</b>\n\n"
            "Этот текст показывается при нажатии кнопки «Справка» в главном меню.\n"
            "Отправьте новый текст для редактирования."
        ),
    }
    
    current_allowed_types = ['text'] if key == 'key_delivery' else ['text', 'photo']
    
    await show_message_editor(
        callback.message, state,
        key=key,
        back_callback='admin_edit_texts',
        help_text=help_texts.get(key),
        allowed_types=current_allowed_types,
    )
    await callback.answer()


# ============================================================================
# РЕДАКТИРОВАНИЕ КНОПОК-ССЫЛОК (НОВОСТИ, ПОДДЕРЖКА) в JSON страницы help
# ============================================================================

import json

def _get_page_buttons(page_key: str) -> str:
    from database.requests import get_page
    row = get_page(page_key)
    if not row:
        return 'NO_PAGE'
    return row.get('buttons_custom') or row.get('buttons_default', '[]')

def _get_help_button(btn_id: str, page_key: str = 'help') -> dict:
    from database.requests import get_page
    row = get_page(page_key)
    if not row:
        return {}
    buttons_json = row.get('buttons_custom') or row.get('buttons_default', '[]')
    if not buttons_json:
        buttons_json = '[]'
    try:
        buttons = json.loads(buttons_json)
        for btn in buttons:
            if btn.get('id') == btn_id:
                return btn
    except Exception:
        pass
    return {}

def _update_help_button(btn_id: str, updates: dict, page_key: str = 'help') -> None:
    from database.requests import get_page, update_page_custom
    row = get_page(page_key)
    if not row:
        return
    buttons_json = row.get('buttons_custom') or row.get('buttons_default', '[]')
    if not buttons_json:
        buttons_json = '[]'
    try:
        buttons = json.loads(buttons_json)
        found = False
        for btn in buttons:
            if btn.get('id') == btn_id:
                btn.update(updates)
                found = True
                break
        if found:
            update_page_custom(page_key, buttons=json.dumps(buttons, ensure_ascii=False))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error updating help button: {e}")


@router.callback_query(F.data.startswith("edit_link:"))
async def edit_link_menu(callback: CallbackQuery, state: FSMContext):
    """Меню редактирования кнопки-ссылки."""
    import logging
    logging.getLogger(__name__).info("DEBUG edit_link_menu called: %s", callback.data)
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    link_type = callback.data.split(":")[1]
    
    if link_type not in ('news', 'support', 'channel'):
        await callback.answer("⛔ Недопустимый параметр", show_alert=True)
        return
    
    btn_id = f"btn_{link_type}"
    _page = 'main' if link_type == 'channel' else 'help'
    btn_data = _get_help_button(btn_id, _page)
    
    current_url = btn_data.get('action_value', 'Не задано')
    is_hidden = btn_data.get('is_hidden', False)
    
    # Label хранится с эмодзи '📢 ' или '💬 ', попробуем отрезать, если есть
    _defaults = {'news': 'Новости', 'support': 'Поддержка', 'channel': 'Мой канал'}
    raw_label = btn_data.get('label', _defaults.get(link_type, link_type.title()))
    button_name = raw_label[2:] if raw_label.startswith('📢 ') or raw_label.startswith('💬 ') else raw_label
    
    # Названия для заголовка
    titles = {
        'news': 'Новости',
        'support': 'Поддержка',
        'channel': 'Мой канал'
    }
    
    hidden_status = "🔴 Скрыта" if is_hidden else "🟢 Видимая"
    
    builder = InlineKeyboardBuilder()
    
    builder.row(InlineKeyboardButton(
        text="🔗 Изменить ссылку",
        callback_data=f"edit_link_url:{link_type}"
    ))
    builder.row(InlineKeyboardButton(
        text=f"{'🟢 Показать' if is_hidden else '🔴 Скрыть'} кнопку",
        callback_data=f"toggle_link_hidden:{link_type}"
    ))
    builder.row(InlineKeyboardButton(
        text=f"✏️ Название: {button_name}",
        callback_data=f"edit_link_name:{link_type}"
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="admin_edit_texts"
    ))
    
    await safe_edit_or_send(callback.message, 
        f"🔗 <b>Редактирование: {titles[link_type]}</b>\n\n"
        f"📍 <b>Ссылка:</b> <code>{current_url}</code>\n"
        f"🏷 <b>Название кнопки:</b> {button_name}\n"
        f"👀 <b>Статус:</b> {hidden_status}",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_link_url:"))
async def edit_link_url_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования URL ссылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    from bot.keyboards.admin import cancel_kb
    
    link_type = callback.data.split(":")[1]
    
    if link_type not in ('news', 'support', 'channel'):
        await callback.answer("⛔ Недопустимый параметр", show_alert=True)
        return
    
    btn_id = f"btn_{link_type}"
    _page = 'main' if link_type == 'channel' else 'help'
    btn_data = _get_help_button(btn_id, _page)
    current_url = btn_data.get('action_value', 'Не задано')
    
    titles = {
        'news': 'Новости',
        'support': 'Поддержка',
        'channel': 'Мой канал'
    }
    
    await state.set_state(AdminStates.waiting_for_link_url)
    await state.update_data(editing_btn_id=btn_id, return_to=f"edit_link:{link_type}", editing_message=callback.message, editing_page=_page)
    
    await safe_edit_or_send(callback.message, 
        f"🔗 <b>Изменение ссылки: {titles[link_type]}</b>\n\n"
        f"📜 <b>Текущая ссылка:</b>\n<code>{current_url}</code>\n\n"
        f"👇 Отправьте новую ссылку (должна начинаться с http:// или https://):",
        reply_markup=cancel_kb(f"edit_link:{link_type}")
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_link_url, ~F.text.startswith('/'))
async def edit_link_url_save(message: Message, state: FSMContext):
    """Сохранение новой ссылки."""
    if not is_admin(message.from_user.id):
        return
    
    from bot.keyboards.admin import back_and_home_kb, cancel_kb
    from bot.utils.text import get_message_text_for_storage
    
    data = await state.get_data()
    btn_id = data.get('editing_btn_id')
    return_to = data.get('return_to', 'admin_edit_texts')
    editing_message = data.get('editing_message')
    
    if not btn_id:
        await state.clear()
        await safe_edit_or_send(message, "❌ Ошибка состояния.", force_new=True)
        return
    
    new_value = get_message_text_for_storage(message, 'plain')
    
    # Валидация URL
    if not new_value.startswith(('http://', 'https://')):
        await safe_edit_or_send(message,
            "❌ <b>Ошибка:</b> Ссылка должна начинаться с <code>http://</code> или <code>https://</code>\n\n"
            f"Вы ввели: <code>{new_value}</code>\n\n"
            "Попробуйте ещё раз или нажмите Отмена.",
            reply_markup=cancel_kb(return_to)
        )
        return
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    _page = data.get('editing_page', 'help')
    _update_help_button(btn_id, {'action_type': 'url', 'action_value': new_value}, page_key=_page)
    await state.clear()
    
    # Перерисовываем сообщение
    if editing_message:
        try:
            await safe_edit_or_send(editing_message,
                f"✅ <b>Ссылка сохранена!</b>\n\n<code>{new_value}</code>",
                reply_markup=back_and_home_kb(return_to)
            )
        except Exception:
            await safe_edit_or_send(message,
                f"✅ <b>Ссылка сохранена!</b>\n\n<code>{new_value}</code>",
                reply_markup=back_and_home_kb(return_to),
                force_new=True
            )
    else:
        await safe_edit_or_send(message,
            f"✅ <b>Ссылка сохранена!</b>\n\n<code>{new_value}</code>",
            reply_markup=back_and_home_kb(return_to),
            force_new=True
        )


@router.callback_query(F.data.startswith("toggle_link_hidden:"))
async def toggle_link_hidden(callback: CallbackQuery, state: FSMContext):
    """Переключение видимости кнопки-ссылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    link_type = callback.data.split(":")[1]
    
    if link_type not in ('news', 'support', 'channel'):
        await callback.answer("⛔ Недопустимый параметр", show_alert=True)
        return
    
    btn_id = f"btn_{link_type}"
    _page = 'main' if link_type == 'channel' else 'help'
    btn_data = _get_help_button(btn_id, _page)
    current_status = btn_data.get('is_hidden', False)
    
    new_status = not current_status
    _update_help_button(btn_id, {'is_hidden': new_status}, page_key=_page)
    import logging
    logging.getLogger(__name__).info("TOGGLE channel: %s -> %s", current_status, new_status)
    await callback.answer("Скрыто: {}".format(new_status))
    await edit_link_menu(callback, state)


@router.callback_query(F.data.startswith("edit_link_name:"))
async def edit_link_name_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования названия кнопки-ссылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    from bot.keyboards.admin import cancel_kb
    
    link_type = callback.data.split(":")[1]
    
    if link_type not in ('news', 'support', 'channel'):
        await callback.answer("⛔ Недопустимый параметр", show_alert=True)
        return
    
    btn_id = f"btn_{link_type}"
    _page = 'main' if link_type == 'channel' else 'help'
    btn_data = _get_help_button(btn_id, _page)
    _defaults = {'news': 'Новости', 'support': 'Поддержка', 'channel': 'Мой канал'}
    raw_label = btn_data.get('label', _defaults.get(link_type, link_type.title()))
    current_name = raw_label[2:] if raw_label.startswith('📢 ') or raw_label.startswith('💬 ') else raw_label
    
    titles = {
        'news': 'Новости',
        'support': 'Поддержка',
        'channel': 'Мой канал'
    }
    
    await state.set_state(AdminStates.waiting_for_link_button_name)
    await state.update_data(editing_btn_id=btn_id, link_type=link_type, editing_page=_page)
    
    await safe_edit_or_send(callback.message, 
        f"✏️ <b>Изменение названия кнопки: {titles[link_type]}</b>\n\n"
        f"🏷 <b>Текущее название:</b> {current_name}\n\n"
        f"👇 Отправьте новое название для кнопки (максимум 30 символов):",
        reply_markup=cancel_kb(f"edit_link:{link_type}")
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_link_button_name)
async def edit_link_name_save(message: Message, state: FSMContext):
    """Сохранение нового названия кнопки-ссылки."""
    from bot.keyboards.admin import back_and_home_kb
    
    data = await state.get_data()
    btn_id = data.get('editing_btn_id')
    link_type = data.get('link_type')
    
    if not btn_id:
        await state.clear()
        await safe_edit_or_send(message, "❌ Ошибка состояния.", force_new=True)
        return
    
    from bot.utils.text import get_message_text_for_storage
    
    new_name = get_message_text_for_storage(message, 'plain')[:30]
    
    if len(new_name) < 1:
        await safe_edit_or_send(message,
            "❌ <b>Название не может быть пустым</b>\n\n"
            "Попробуйте ещё раз или нажмите Отмена.",
            reply_markup=back_and_home_kb(f"edit_link:{link_type}" if link_type else "admin_edit_texts")
        )
        return
    
    if link_type == 'news':
        new_label = f"📢 {new_name}"
    elif link_type == 'channel':
        new_label = f"📢 {new_name}"
    else:
        new_label = f"💬 {new_name}"
    _page = data.get('editing_page', 'help')
    _update_help_button(btn_id, {'label': new_label}, page_key=_page)
    
    await state.clear()
    
    await safe_edit_or_send(message,
        f"✅ <b>Название сохранено!</b>\n\n{new_name}",
        reply_markup=back_and_home_kb(f"edit_link:{link_type}" if link_type else "admin_edit_texts"),
        force_new=True
    )




# ============================================================================
# ОСТАНОВКА БОТА
# ============================================================================

@router.callback_query(F.data == "admin_stop_bot")
async def show_stop_bot_confirm(callback: CallbackQuery, state: FSMContext):
    """Показывает окно подтверждения остановки бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await safe_edit_or_send(callback.message, 
        "🛑 <b>Остановка бота</b>\n\n"
        "Вы уверены, что хотите остановить бот?\n\n"
        "⚠️ Бот перестанет отвечать на сообщения пользователей "
        "до следующего ручного запуска.",
        reply_markup=stop_bot_confirm_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stop_bot_confirm")
async def stop_bot_confirmed(callback: CallbackQuery, state: FSMContext):
    """Подтверждение остановки бота — останавливает polling."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await safe_edit_or_send(callback.message, 
        "🛑 <b>Бот останавливается...</b>\n\n"
        "Спасибо за использование!"
    )
    await callback.answer("Бот останавливается...", show_alert=True)
    
    logger.info(f"🛑 Бот остановлен администратором {callback.from_user.id}")
    
    # Даём время на отправку сообщения
    await asyncio.sleep(1)
    
    # Завершаем работу скрипта
    sys.exit(0)


# ============================================================================
# СКАЧИВАНИЕ ЛОГОВ
# ============================================================================

@router.callback_query(F.data == "admin_logs_menu")
async def show_logs_menu(callback: CallbackQuery, state: FSMContext):
    """Меню скачивания логов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
        
    await safe_edit_or_send(callback.message, 
        "📥 <b>Скачивание логов</b>\n\n"
        "Выберите какие логи хотите скачать:",
        reply_markup=admin_logs_menu_kb()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_download_log_full")
async def download_log_full(callback: CallbackQuery, state: FSMContext):
    """Скачивание полного лога."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    log_path = "logs/bot.log"
    if not os.path.exists(log_path):
        await callback.answer("Файл логов не найден.", show_alert=True)
        return
    
    # Отвечаем на коллбек до отправки файла, чтобы избежать таймаута
    await callback.answer()
    
    await callback.message.answer_document(
        document=FSInputFile(log_path, filename="bot.log"),
        caption="📄 Полный лог бота"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_download_log_errors")
async def download_log_errors(callback: CallbackQuery, state: FSMContext):
    """Скачивание лога с ошибками."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    log_path = "logs/bot.log"
    error_log_path = "logs/errors.log"
    
    if not os.path.exists(log_path):
        await callback.answer("Файл логов не найден.", show_alert=True)
        return
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f_in, open(error_log_path, 'w', encoding='utf-8') as f_out:
            capturing = False
            for line in f_in:
                # Начало новой записи в логе формата [2026-...
                if line.startswith('['):
                    if ' [ERROR] ' in line or ' [WARNING] ' in line or ' [CRITICAL] ' in line or ' [EXCEPTION] ' in line:
                        capturing = True
                        f_out.write(line)
                    else:
                        capturing = False
                elif capturing:
                    # Строки traceback
                    f_out.write(line)
    except Exception as e:
        logger.error(f"Ошибка при формировании лога ошибок: {e}")
        await callback.answer("Ошибка при обработке логов.", show_alert=True)
        return
    
    if not os.path.exists(error_log_path) or os.path.getsize(error_log_path) == 0:
        await callback.answer("Ошибок не найдено! 🎉", show_alert=True)
        return
    
    # Отвечаем на коллбек до отправки файла, чтобы избежать таймаута
    await callback.answer()
        
    await callback.message.answer_document(
        document=FSInputFile(error_log_path, filename="errors.log"),
        caption="⚠️ Лог ошибок и предупреждений"
    )

@router.callback_query(F.data == "admin_clear_logs_confirm")
async def confirm_clear_logs(callback: CallbackQuery, state: FSMContext):
    """Показывает предупреждение перед очисткой логов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from bot.keyboards.admin import back_button
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Да, очистить", callback_data="admin_clear_logs_do"))
    builder.row(back_button("admin_logs_menu"))
    
    await safe_edit_or_send(callback.message,
        "🧹 <b>Очистка логов</b>\n\n"
        "Вы уверены, что хотите полностью стереть старые файлы логов и очистить текущие <code>bot.log</code> и <code>errors.log</code>?\n"
        "Это безвозвратное действие.",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_clear_logs_do")
async def do_clear_logs(callback: CallbackQuery, state: FSMContext):
    """Очищает файлы логов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        import glob
        
        # Очищаем текущие файлы
        for log_path in ["logs/bot.log", "logs/errors.log"]:
            if os.path.exists(log_path):
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write("") 
                    
        # Удаляем старые лог-файлы (bot.log.1, bot.log.2, и т.д.)
        for old_log in glob.glob("logs/bot.log.*"):
            if os.path.exists(old_log):
                try:
                    os.remove(old_log)
                except Exception as e:
                    logger.error(f"Не удалось удалить старый лог {old_log}: {e}")
                
        await callback.answer("🧹 Логи успешно очищены!", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при очистке логов: {e}")
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    
    await show_logs_menu(callback, state)



@router.message(F.text & ~F.text.startswith('/'), StateFilter('edit_help_btn_label'))
async def save_help_btn_label(message: types.Message, state: FSMContext):
    """Сохраняет новое название кнопки справки."""
    if not is_admin(message.from_user.id):
        return
    
    new_label = message.text.strip()
    if not new_label:
        await message.answer("❌ Название не может быть пустым")
        return
    
    import sqlite3, json
    conn = sqlite3.connect('database/vpn_bot.db')
    cur = conn.cursor()
    cur.execute("SELECT buttons_default FROM pages WHERE page_key='main'")
    row = cur.fetchone()
    buttons = json.loads(row[0]) if row and row[0] else []
    
    found = False
    for b in buttons:
        if b.get('id') == 'btn_help':
            b['label'] = new_label
            found = True
            break
    
    if not found:
        buttons.append({
            'id': 'btn_help',
            'label': new_label,
            'color': 'secondary',
            'row': 2,
            'col': 1,
            'is_hidden': False,
            'action_type': 'internal',
            'action_value': 'cmd_help'
        })
    
    cur.execute("UPDATE pages SET buttons_default=? WHERE page_key='main'", (json.dumps(buttons, ensure_ascii=False),))
    conn.commit()
    conn.close()
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_edit_texts"))
    
    await message.answer(
        f"✅ Название кнопки изменено на: <b>{new_label}</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.clear()


@router.callback_query(F.data == "admin_ai_access")
async def admin_ai_access_menu(callback: CallbackQuery, state: FSMContext):
    """Управление AI-доступом пользователей."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    import sqlite3
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT telegram_id, username, ai_access, ai_tokens, ai_key FROM users WHERE ai_access=1 ORDER BY id DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    
    builder = InlineKeyboardBuilder()
    
    if rows:
        text = "🤖 <b>Пользователи с AI-доступом:</b>\n\n"
        for row in rows:
            tg_id, username, ai_acc, ai_tok, ai_k = row
            text += f"• <code>{tg_id}</code> @{username or '—'} | 💰 {ai_tok} токенов | 🔑 {ai_k or '—'}\n"
    else:
        text = "🤖 <b>Управление AI-доступом</b>\n\nПока нет пользователей с AI-доступом."
    
    builder.row(InlineKeyboardButton(text="🔑 Выдать AI-ключ", callback_data="admin_ai_give_key"))
    builder.row(InlineKeyboardButton(text="💰 Пополнить токены", callback_data="admin_ai_add_tokens"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_edit_texts"))
    
    await safe_edit_or_send(callback.message, text, reply_markup=builder.as_markup())
    await callback.answer()


# ============================================================================
# УДАЛЕНИЕ КЛЮЧА ПО ID
# ============================================================================

@router.callback_query(F.data == "admin_delete_key")
async def admin_delete_key_start(callback: CallbackQuery, state: FSMContext):
    """Показываем список ключей с кнопками удаления."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    import sqlite3
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, key, tokens, tariff, activated_by, is_active FROM ai_keys ORDER BY id DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await safe_edit_or_send(
            callback.message,
            "📋 <b>Удаление ключа</b>\n\nКлючи не найдены.",
            reply_markup=back_and_home_kb("admin_edit_texts"),
        )
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for row in rows:
        key_id, key_str, tokens, tariff, activated_by, is_active = row
        status = "✅" if is_active else "🔴"
        user = f" → {activated_by}" if activated_by else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{status} ID {key_id}: {key_str} | {tariff} | {tokens:,} ток.{user}",
                callback_data=f"admin_delete_key_confirm:{key_id}"
            )
        )
    
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_edit_texts"))
    
    await safe_edit_or_send(
        callback.message,
        "🗑 <b>Удаление ключа</b>\n\nВыбери ключ для удаления:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_delete_key_confirm:"))
async def admin_delete_key_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтверждаем и удаляем ключ."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    key_id = int(callback.data.split(":")[1])
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    
    c.execute("SELECT id, key, tokens, tariff, activated_by FROM ai_keys WHERE id=?", (key_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        await callback.answer("❌ Ключ не найден.", show_alert=True)
        return
    
    key_id, key_str, tokens, tariff, activated_by = row
    
    c.execute("DELETE FROM ai_keys WHERE id=?", (key_id,))
    
    if activated_by:
        c.execute("UPDATE users SET ai_access=0, ai_tokens=0, ai_key=NULL, ai_tariff=NULL WHERE telegram_id=?", (activated_by,))
    
    conn.commit()
    conn.close()
    
    user_info = f" (юзер <code>{activated_by}</code>)" if activated_by else ""
    await safe_edit_or_send(
        callback.message,
        f"✅ <b>Ключ удалён!</b>\n\n"
        f"ID: <code>{key_id}</code>\n"
        f"Ключ: <code>{key_str}</code>\n"
        f"Тариф: <b>{tariff}</b>\n"
        f"Токенов: {tokens:,}\n"
        f"{user_info}\n\n"
        "AI-доступ у пользователя отозван.",
        reply_markup=back_and_home_kb("admin_edit_texts"),
    )
    await callback.answer()


@router.message(Command("delete_key"))
async def delete_key_cmd(message: Message, state: FSMContext):
    """Удалить ключ по ID. Формат: /delete_key <id>"""
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.reply(
            "🗑 <b>Удаление ключа</b>\n\n"
            "Формат: <code>/delete_key [id]</code>\n\n"
            "Посмотреть ключи: /list_ai_keys",
            parse_mode="HTML"
        )
        return
    
    try:
        key_id = int(args[1])
    except ValueError:
        await message.reply("❌ Неверный формат ID. Укажите число.", parse_mode="HTML")
        return
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    
    c.execute("SELECT id, key, tokens, tariff, activated_by FROM ai_keys WHERE id=?", (key_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        await message.reply(f"❌ Ключ с ID <code>{key_id}</code> не найден.", parse_mode="HTML")
        return
    
    key_id, key_str, tokens, tariff, activated_by = row
    
    c.execute("DELETE FROM ai_keys WHERE id=?", (key_id,))
    
    if activated_by:
        c.execute("UPDATE users SET ai_access=0, ai_tokens=0, ai_key=NULL, ai_tariff=NULL WHERE telegram_id=?", (activated_by,))
    
    conn.commit()
    conn.close()
    
    user_info = f" (юзер <code>{activated_by}</code>)" if activated_by else ""
    await message.reply(
        f"✅ <b>Ключ удалён!</b>\n\n"
        f"ID: <code>{key_id}</code>\n"
        f"Ключ: <code>{key_str}</code>\n"
        f"Тариф: <b>{tariff}</b>\n"
        f"Токенов: {tokens:,}\n"
        f"{user_info}\n\n"
        f"AI-доступ у пользователя отозван.",
        parse_mode="HTML"
    )


@router.message(Command("list_ai_keys"))
async def list_ai_keys(message: Message, state: FSMContext):
    """Показать все AI-ключи с кнопками удаления."""
    if not is_admin(message.from_user.id):
        return
    
    import sqlite3
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, key, tokens, tariff, activated_by, is_active FROM ai_keys ORDER BY id DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await message.reply("📋 Ключи не найдены.")
        return
    
    builder = InlineKeyboardBuilder()
    text = "📋 <b>AI-ключи:</b>\n\n"
    
    for row in rows:
        key_id, key_str, tokens, tariff, activated_by, is_active = row
        status = "✅" if is_active else "🔴"
        user = f" → <code>{activated_by}</code>" if activated_by else ""
        text += f"{status} <b>ID {key_id}</b>: <code>{key_str}</code> | {tariff} | {tokens:,} ток.{user}\n"
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 Удалить ID {key_id}",
                callback_data=f"admin_delete_key_confirm:{key_id}"
            )
        )
    
    await message.reply(text, parse_mode="HTML", reply_markup=builder.as_markup())


# ============================================================================
# ПОШАГОВАЯ ГЕНЕРАЦИЯ AI КЛЮЧА
# ============================================================================

@router.callback_query(F.data == "admin_ai_give_key")
async def ai_give_key_start(callback: CallbackQuery, state: FSMContext):
    """Выбор тарифа для генерации AI-ключа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 S — 10,000 токенов", callback_data="admin_ai_gen:S"))
    builder.row(InlineKeyboardButton(text="🤖 P — 20,000 токенов", callback_data="admin_ai_gen:P"))
    builder.row(InlineKeyboardButton(text="🤖 V — 50,000 токенов", callback_data="admin_ai_gen:V"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_ai_access"))

    await safe_edit_or_send(
        callback.message,
        "🔑 <b>Выдача AI-ключа</b>\n\n"
        "Выберите тариф — бот сгенерирует ключ.\n"
        "Отдайте ключ юзеру, он вставит: <code>/ai_key [ключ]</code>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ai_gen:"))
async def ai_give_key_generate(callback: CallbackQuery, state: FSMContext):
    """Генерирует AI-ключ по выбранному тарифу."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    import sqlite3
    import random
    import string

    tariff = callback.data.split(":")[1]
    tariff_map = {'S': 10000, 'P': 20000, 'V': 50000}
    tokens = tariff_map.get(tariff, 10000)

    # Генерируем случайный код ключа
    code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    full_key = f"{tariff}-{code}"

    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO ai_keys (key, tokens, created_by, tariff, is_active) VALUES (?, ?, ?, ?, 1)",
        (full_key, tokens, callback.from_user.id, tariff)
    )
    conn.commit()
    key_id = c.lastrowid
    conn.close()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔑 Ещё ключ", callback_data=f"admin_ai_gen:{tariff}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_ai_give_key"))

    await safe_edit_or_send(
        callback.message,
        f"✅ <b>AI-ключ сгенерирован!</b>\n\n"
        f"📦 Тариф: <b>{tariff}</b>\n"
        f"💰 Токенов: {tokens:,}\n"
        f"🔑 Ключ: <code>{full_key}</code>\n\n"
        f"Отдайте ключ юзеру — он вставит: <code>/ai_key {full_key}</code>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ============================================================================
# ПОШАГОВОЕ ПОПОЛНЕНИЕ ТОКЕНОВ
# ============================================================================

@router.callback_query(F.data == "admin_ai_add_tokens")
async def ai_add_tokens_start(callback: CallbackQuery, state: FSMContext):
    """Шаг 1: Запрашиваем telegram_id для пополнения."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.ai_waiting_add_tokens_user_id)
    await state.update_data(ai_add_tokens_msg=callback.message)
    
    await safe_edit_or_send(
        callback.message,
        "💰 <b>Пополнение токенов</b>\n\n"
        "Шаг 1/2: Отправьте <b>telegram_id</b> пользователя.\n\n"
        "Можно отправить @username — бот найдёт ID автоматически.",
        reply_markup=back_and_home_kb("admin_ai_access"),
    )
    await callback.answer()


@router.message(AdminStates.ai_waiting_add_tokens_user_id, F.text, ~F.text.startswith('/'))
async def ai_add_tokens_user_id(message: Message, state: FSMContext):
    """Шаг 2: Получаем ID, запрашиваем количество."""
    if not is_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    
    if text.startswith('@'):
        username = text[1:]
        import sqlite3
        conn = sqlite3.connect('database/vpn_bot.db')
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM users WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if not row:
            await safe_edit_or_send(
                message,
                f"❌ Пользователь @{username} не найден в базе.",
                reply_markup=back_and_home_kb("admin_ai_access"),
                force_new=True,
            )
            return
        tg_id = row[0]
    else:
        try:
            tg_id = int(text)
        except ValueError:
            await safe_edit_or_send(
                message,
                "❌ Неверный формат. Отправьте telegram_id или @username.",
                reply_markup=back_and_home_kb("admin_ai_access"),
                force_new=True,
            )
            return
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT username, ai_access, ai_tokens FROM users WHERE telegram_id=?", (tg_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await safe_edit_or_send(
            message,
            f"❌ Пользователь <code>{tg_id}</code> не найден в базе.",
            reply_markup=back_and_home_kb("admin_ai_access"),
            force_new=True,
        )
        return
    
    username, ai_access, current_tokens = row
    
    if not ai_access:
        await safe_edit_or_send(
            message,
            f"❌ У пользователя <code>{tg_id}</code> нет AI-доступа.\n"
            "Сначала выдайте ему AI-ключ.",
            reply_markup=back_and_home_kb("admin_ai_access"),
            force_new=True,
        )
        return
    
    await state.set_state(AdminStates.ai_waiting_add_tokens_amount)
    await state.update_data(ai_add_tokens_tg_id=tg_id)
    
    await safe_edit_or_send(
        message,
        f"💰 <b>Пополнение токенов</b>\n\n"
        f"👤 Пользователь: <code>{tg_id}</code> @{username or '—'}\n"
        f"📊 Текущих токенов: <b>{current_tokens:,}</b>\n\n"
        f"Шаг 2/2: Отправьте <b>количество</b> для пополнения.\n\n"
        f"Примеры: 1000, 5000, 10000",
        reply_markup=back_and_home_kb("admin_ai_access"),
        force_new=True,
    )


@router.message(AdminStates.ai_waiting_add_tokens_amount, F.text, ~F.text.startswith('/'))
async def ai_add_tokens_amount(message: Message, state: FSMContext):
    """Шаг 3: Пополняем токены."""
    if not is_admin(message.from_user.id):
        return
    
    try:
        amount = int(message.text.strip().replace(' ', '').replace(',', ''))
    except ValueError:
        await safe_edit_or_send(
            message,
            "❌ Неверный формат. Отправьте число.",
            reply_markup=back_and_home_kb("admin_ai_access"),
            force_new=True,
        )
        return
    
    if amount <= 0:
        await safe_edit_or_send(
            message,
            "❌ Количество должно быть больше 0.",
            reply_markup=back_and_home_kb("admin_ai_access"),
            force_new=True,
        )
        return
    
    data = await state.get_data()
    tg_id = data['ai_add_tokens_tg_id']
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET ai_tokens = ai_tokens + ? WHERE telegram_id=?", (amount, tg_id))
    c.execute("SELECT ai_tokens FROM users WHERE telegram_id=?", (tg_id,))
    new_total = c.fetchone()[0]
    conn.commit()
    conn.close()
    
    await state.clear()
    
    await safe_edit_or_send(
        message,
        f"✅ <b>Токены пополнены!</b>\n\n"
        f"👤 Пользователь: <code>{tg_id}</code>\n"
        f"💰 Добавлено: {amount:,}\n"
        f"📊 Всего токенов: {new_total:,}",
        reply_markup=back_and_home_kb("admin_ai_access"),
        force_new=True,
    )


@router.message(Command("revoke_ai"))
async def revoke_ai(message: Message, state: FSMContext):
    """Отозвать AI-доступ у пользователя. Формат: /revoke_ai [telegram_id]"""
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.reply(
            "🚫 <b>Отзыв AI-доступа</b>\n\n"
            "Формат: <code>/revoke_ai [telegram_id]</code>\n\n"
            "Пример: <code>/revoke_ai 5191406344</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        tg_id = int(args[1])
    except ValueError:
        await message.reply("❌ Неверный формат ID.", parse_mode="HTML")
        return
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    
    c.execute("SELECT username, ai_access, ai_tokens, ai_tariff FROM users WHERE telegram_id=?", (tg_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        await message.reply(f"❌ Пользователь <code>{tg_id}</code> не найден.", parse_mode="HTML")
        return
    
    username, ai_access, ai_tokens, ai_tariff = row
    
    if ai_access != 1:
        conn.close()
        await message.reply(f"⭕ У пользователя <code>{tg_id}</code> нет AI-доступа.", parse_mode="HTML")
        return
    
    c.execute("UPDATE users SET ai_access=0, ai_tokens=0, ai_key=NULL, ai_tariff=NULL WHERE telegram_id=?", (tg_id,))
    conn.commit()
    conn.close()
    
    await message.reply(
        f"✅ <b>AI-доступ отозван!</b>\n\n"
        f"👤 ID: <code>{tg_id}</code>\n"
        f"📛 Ник: @{username or 'нет'}\n"
        f"📦 Был тариф: <b>{ai_tariff or '—'}</b>\n"
        f"💰 Было токенов: {ai_tokens:,}",
        parse_mode="HTML"
    )


@router.message(Command("edit_info"))
async def edit_info(message: Message, state: FSMContext):
    """Редактировать текст справки. Формат: /edit_info [новый текст]"""
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        import sqlite3
        conn = sqlite3.connect('database/vpn_bot.db')
        c = conn.cursor()
        c.execute("SELECT text_default FROM pages WHERE page_key='info'")
        row = c.fetchone()
        conn.close()
        
        current = row[0] if row else "(пусто)"
        await message.reply(
            f"📋 <b>Текущий текст справки:</b>\n\n{current}\n\n"
            f"Для изменения отправьте:\n"
            f"<code>/edit_info [новый текст]</code>",
            parse_mode="HTML"
        )
        return
    
    new_text = args[1].strip()
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO pages (page_key, text_default, updated_at) VALUES ('info', ?, CURRENT_TIMESTAMP)", (new_text,))
    conn.commit()
    conn.close()
    
    await message.reply(
        f"✅ <b>Текст справки обновлён!</b>\n\n"
        f"Новый текст:\n\n{new_text}",
        parse_mode="HTML"
    )


@router.message(Command("gen_ai_key"))
async def gen_ai_key(message: Message, state: FSMContext):
    """Генерация AI-ключа с привязкой к юзеру. Формат: /gen_ai_key [tariff] [tg_id] [код] [токены]"""
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 4:
        await message.reply(
            "🔑 <b>Генерация AI-ключа</b>\n\n"
            "Формат: <code>/gen_ai_key [тариф] [id] [код] [токены]</code>\n\n"
            "Тарифы по умолчанию: <b>S</b> (10К), <b>P</b> (20К), <b>V</b> (50К)\n"
            "Токены — опционально, если не указать — по тарифу\n\n"
            "Примеры:\n"
            "• <code>/gen_ai_key S 5191406344 123455</code> — 10К токенов\n"
            "• <code>/gen_ai_key P 5191406344 client1 50000</code> — 50К токенов\n"
            "• <code>/gen_ai_key V 5191406344 vipkey 1000000</code> — 1М токенов",
            parse_mode="HTML"
        )
        return
    
    tariff = args[1].upper().strip()
    tariff_map = {'S': 10000, 'P': 20000, 'V': 50000}
    
    if tariff not in tariff_map:
        await message.reply(
            "❌ Неверный тариф.\n\n"
            "Доступные: <b>S</b> (10К), <b>P</b> (20К), <b>V</b> (50К)",
            parse_mode="HTML"
        )
        return
    
    try:
        tg_id = int(args[2])
    except ValueError:
        await message.reply("❌ Неверный ID пользователя.", parse_mode="HTML")
        return
    
    custom_id = args[3].strip()
    key = tariff + "-" + custom_id
    
    # Токены — 5-й аргумент (опциональный)
    if len(args) >= 5:
        try:
            tokens = int(args[4])
        except ValueError:
            await message.reply("❌ Неверное количество токенов. Укажите число.", parse_mode="HTML")
            return
    else:
        tokens = tariff_map[tariff]
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    
    c.execute("SELECT username, ai_access, ai_tokens FROM users WHERE telegram_id=?", (tg_id,))
    row = c.fetchone()

    if not row:
        # Создаём пользователя если его нет
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)", (tg_id, f"user_{tg_id}"))
        username = f"user_{tg_id}"
        ai_access = 0
        ai_tokens = 0
        print(f"[gen_ai_key] Создан новый пользователь telegram_id={tg_id}")
    else:
        username, ai_access, ai_tokens = row
    
    # Маппинг короткого тарифа в полный формат для БД
    _tmap = {'S': 'standard', 'P': 'premium', 'V': 'vip'}
    tariff_full = _tmap.get(tariff, tariff)

    c.execute("INSERT INTO ai_keys (key, tokens, created_by, tariff, activated_by, activated_at, is_active) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0)",
              (key, tokens, message.from_user.id, tariff, tg_id))
    
    c.execute("UPDATE users SET ai_access=1, ai_tokens=?, ai_key=?, ai_tariff=? WHERE telegram_id=?",
              (tokens, key, tariff_full, tg_id))
    
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ <b>Ключ сгенерирован и активирован!</b>\n\n"
        f"👤 Пользователь: <code>{tg_id}</code> @{username or '—'}\n"
        f"📦 Тариф: <b>{tariff}</b>\n"
        f"🔑 Ключ: <code>{key}</code>\n"
        f"💰 Токенов: {tokens:,}\n\n"
        f"Юзер может сразу писать в AI-чат.",
        parse_mode="HTML"
    )


@router.message(Command("add_ai_tokens"))
async def add_ai_tokens(message: Message, state: FSMContext):
    """Пополнение токенов AI-доступа. Формат: /add_ai_tokens [telegram_id] [tariff] [tokens]"""
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    import logging
    logging.getLogger("bot.ai").info(f"add_ai_tokens raw: {message.text!r} args={args}")

    # Гибкий парсинг: убираем лишние пробелы, нормализуем
    # Поддерживаем форматы:
    #   /add_ai_tokens 5191406344 S 1000
    #   /add_ai_tokens 5191406344 S1000
    #   /add_ai_tokens 5191406344S1000
    normalized = message.text.strip()
    # Убираем дублирующие пробелы
    import re
    normalized = re.sub(r'\s+', ' ', normalized)
    # Разделяем по пробелу
    parts = normalized.split(' ', 3)  # /add_ai_tokens, id, tariff+amount

    if len(parts) < 3:
        await message.reply(
            "💰 <b>Пополнение токенов</b>\n\n"
            "Формат: <code>/add_ai_tokens [id] [tariff] [tokens]</code>\n\n"
            "Тарифы: <b>S</b> (10К), <b>P</b> (20К), <b>V</b> (50К)\n\n"
            "Примеры:\n"
            "• <code>/add_ai_tokens 5191406344 S 1000</code>\n"
            "• <code>/add_ai_tokens 5191406344 P 5000</code>\n"
            "• <code>/add_ai_tokens 5191406344 V 10000</code>",
            parse_mode="HTML"
        )
        return

    # Парсим telegram_id — может быть приклеен к тарифу
    # Форматы: "5191406344" или "5191406344S" или "5191406344S1000"
    raw_id = parts[1]

    # Пробуем извлечь ID (цифры в начале)
    id_match = re.match(r'^(\d+)', raw_id)
    if not id_match:
        await message.reply("❌ Неверный telegram_id", parse_mode="HTML")
        return
    tg_id = int(id_match.group(1))

    # Остаток после ID — может содержать тариф и токены
    remainder = raw_id[id_match.end():].strip()

    # Если тариф и токены отдельно
    if len(parts) >= 3:
        tariff_part = parts[2].upper().strip()
        # Пробуем извлечь тариф (первая буква S/P/V)
        tariff_match = re.match(r'^([SPV])', tariff_part)
        if not tariff_match:
            await message.reply("❌ Неверный тариф. Доступные: S, P, V", parse_mode="HTML")
            return
        tariff = tariff_match.group(1)
        # Остаток после тарифа — токены
        tokens_str = tariff_part[1:].strip()
        if not tokens_str and len(parts) >= 4:
            tokens_str = parts[3].strip()
        if not tokens_str:
            # Если токенов нет — используем дефолт по тарифу
            tariff_defaults = {'S': 10000, 'P': 20000, 'V': 50000}
            tokens = tariff_defaults[tariff]
        else:
            try:
                tokens = int(tokens_str)
            except ValueError:
                await message.reply("❌ Неверное количество токенов. Введите число.", parse_mode="HTML")
                return
    elif remainder:
        # Тариф и возможно токены в остатке
        tariff_match = re.match(r'^([SPV])(\d*)$', remainder.upper())
        if not tariff_match:
            await message.reply("❌ Неверный тариф. Доступные: S, P, V", parse_mode="HTML")
            return
        tariff = tariff_match.group(1)
        tokens_str = tariff_match.group(2)
        if tokens_str:
            tokens = int(tokens_str)
        else:
            tariff_defaults = {'S': 10000, 'P': 20000, 'V': 50000}
            tokens = tariff_defaults[tariff]
    else:
        await message.reply("❌ Укажите тариф: S, P или V", parse_mode="HTML")
        return

    if tokens <= 0:
        await message.reply("❌ Количество должно быть больше 0", parse_mode="HTML")
        return
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT ai_access, ai_tokens FROM users WHERE telegram_id=?", (tg_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        await message.answer(f"❌ Пользователь <code>{tg_id}</code> не найден.", parse_mode="HTML")
        return
    if not row[0]:
        conn.close()
        await message.answer(f"❌ У пользователя <code>{tg_id}</code> нет AI-доступа.", parse_mode="HTML")
        return
    
    _tmap2 = {'S': 'standard', 'P': 'premium', 'V': 'vip'}
    c.execute("UPDATE users SET ai_tokens = ai_tokens + ?, ai_tariff = ? WHERE telegram_id=?", (tokens, _tmap2.get(tariff, tariff), tg_id))
    c.execute("SELECT ai_tokens FROM users WHERE telegram_id=?", (tg_id,))
    new_total = c.fetchone()[0]
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ <b>Токены пополнены!</b>\n\n"
        f"👤 Пользователь: <code>{tg_id}</code>\n"
        f"📦 Тариф: <b>{tariff}</b>\n"
        f"💰 Добавлено: {tokens:,}\n"
        f"📊 Всего: {new_total:,}",
        parse_mode="HTML"
    )


# ============================================================================
# НАСТРОЙКА AI API КЛЮЧА
# ============================================================================

@router.callback_query(F.data == "admin_add_tokens")
async def show_add_tokens(callback: CallbackQuery, state: FSMContext):
    """Показывает инструкцию пополнения токенов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    text = (
        "💰 <b>Пополнение AI-токенов</b>\n\n"
        "Используйте команду:\n"
        "<code>/add_ai_tokens [telegram_id] [тариф] [токены]</code>\n\n"
        "Тарифы:\n"
        "• S — подпись S\n"
        "• P — подпись P\n"
        "• V — подпись V\n\n"
        "Примеры:\n"
        "• <code>/add_ai_tokens 5191406344 S 1000</code>\n"
        "• <code>/add_ai_tokens 5191406344 P 5000</code>\n"
        "• <code>/add_ai_tokens 5191406344 V 20000</code>\n\n"
        "Токены зачисляются на баланс пользователя."
    )

    await safe_edit_or_send(callback.message, text, reply_markup=back_and_home_kb("admin_bot_settings"))
    await callback.answer()


@router.callback_query(F.data == "admin_ai_key")
async def show_ai_key_settings(callback: CallbackQuery, state: FSMContext):
    """Показывает текущий AI API ключ и кнопку для изменения."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from database.db_settings import get_ai_api_key
    current_key = get_ai_api_key()

    if current_key:
        masked = current_key[:8] + "..." + current_key[-4:]
        text = (
            "🤖 <b>AI API ключ</b>\n\n"
            f"Текущий ключ: <code>{masked}</code>\n\n"
            "AI-чат работает через OpenRouter.\n"
            "Ключ хранится в базе данных бота."
        )
    else:
        text = (
            "🤖 <b>AI API ключ</b>\n\n"
            "❌ Ключ не установлен.\n\n"
            "AI-чат не будет работать пока вы не вставите API ключ.\n"
            "Получить ключ: <a href=\"https://openrouter.ai/keys\">openrouter.ai/keys</a>"
        )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Вставить API ключ", callback_data="admin_ai_key_set")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_bot_settings")],
    ])

    await safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_ai_key_set")
async def start_ai_key_input(callback: CallbackQuery, state: FSMContext):
    """Переводит администратора в режим ввода AI API ключа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.ai_waiting_api_key)
    await state.update_data(
        ai_key_editing_message=callback.message,
        ai_key_editing_message_id=callback.message.message_id,
    )
    await safe_edit_or_send(
        callback.message,
        "🔑 <b>Вставьте AI API ключ</b>\n\n"
        "Отправьте ваш OpenRouter API ключ сообщением.\n"
        "Формат: <code>sk-or-...xxxx</code>\n\n"
        "Получить ключ: <a href=\"https://openrouter.ai/keys\">openrouter.ai/keys</a>",
        reply_markup=back_and_home_kb("admin_ai_key"),
    )
    await callback.answer()


@router.message(AdminStates.ai_waiting_api_key, F.text, ~F.text.startswith('/'))
async def save_ai_key(message: Message, state: FSMContext):
    """Сохраняет AI API ключ и возвращает в настройки."""
    if not is_admin(message.from_user.id):
        return

    api_key = message.text.strip()
    if not api_key:
        await safe_edit_or_send(
            message,
            "❌ <b>Ключ пустой</b>\n\nОтправьте непустой API ключ.",
            reply_markup=back_and_home_kb("admin_ai_key"),
            force_new=True,
        )
        return

    data = await state.get_data()
    editing_message = data.get('ai_key_editing_message')

    try:
        await message.delete()
    except Exception:
        pass

    from database.db_settings import set_ai_api_key
    set_ai_api_key(api_key)

    await state.clear()
    target = editing_message or message
    masked = api_key[:8] + "..." + api_key[-4:]
    await safe_edit_or_send(
        target,
        "✅ <b>AI API ключ сохранён!</b>\n\n"
        f"Ключ: <code>{masked}</code>\n\n"
        "AI-чат теперь будет использовать этот ключ.\n"
        "Пользователи смогут активировать AI-доступ.",
        reply_markup=back_and_home_kb("admin_ai_key"),
        force_new=editing_message is None,
    )


# ============================================================================
# КОМАНДА /updatebot — обновление с сервера через  Telegram
# ============================================================================

@router.message(Command("updatebot"))
async def updatebot_command(message: Message, state: FSMContext):
    """Обновляет бота с сервера через updatebot.sh по команде из Telegram."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    script_path = UPDATE_SCRIPT_PATH or "/root/svaboda_super/updatebot.sh"

    if not os.path.exists(script_path):
        await message.answer(
            f"❌ <b>Скрипт не найден</b>\n\n"
            f"Путь: <code>{script_path}</code>\n\n"
            f"Укажите правильный путь в config.py:\n"
            f'<code>UPDATE_SCRIPT_PATH = "/root/svaboda_super/updatebot.sh"</code>',
            parse_mode="HTML"
        )
        return

    import subprocess

    status_msg = await message.answer(
        "⚙️ <b>Начинаю обновление системы.</b>\n\n"
        "Этой командой вручную можно обновить на своём сервере\n\n"
        "Команда обновления:\n"
        f"<code>bash {script_path}</code>\n\n"
        "Во время обновления бот может быть временно недоступен.\n\n"
        "✅ После завершения просто отправьте команду:\n\n"
        "/start\n\n"
        "Спасибо за ожидание!",
        parse_mode="HTML"
    )

    # Даём боту 1 секунду на отправку ответа, потом запускаем скрипт
    await asyncio.sleep(1)
    try:
        subprocess.Popen(
            ["nohup", "bash", script_path],
            stdout=open("/dev/null", "w"),
            stderr=open("/dev/null", "w"),
            cwd="/root/svaboda_super",
            start_new_session=True
        )
    except Exception as e:
        logger.error(f"updatebot command error: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Ошибка запуска:</b> <code>{str(e)[:200]}</code>",
            parse_mode="HTML"
        )



