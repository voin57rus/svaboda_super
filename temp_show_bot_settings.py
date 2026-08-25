async def show_bot_settings(callback: CallbackQuery, state: FSMContext):
    """Показывает меню настроек бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.services.vpn_api import get_bot_mode
    from bot.keyboards.admin_settings import bot_settings_kb
    
    mode = get_bot_mode()
    if mode == 'subscription':
        mode_label = "📡 Подписка"
        mode_desc = ("Бот выдаёт пользователю одну <b>subscription-ссылку</b> — "
                     "клиент сам подтягивает все протоколы сервера.")
    else:
        mode_label = "🔑 Ключи"
        mode_desc = ("Бот создаёт один VLESS/VMess-клиент в одном inbound "
                     "и выдаёт ссылку + JSON-конфиг.")

    text = (
        "⚙️ <b>Настройки бота</b>\n\n"
        f"<b>Режим работы:</b> {mode_label}\n"
        f"<i>{mode_desc}</i>\n\n"
        "Выберите действие:"
    )

    # Используем edit_text для принудительного обновления клавиатуры
    await callback.message.edit_text(
        text,
        reply_markup=bot_settings_kb(mode),
        parse_mode="HTML"
    )
    await callback.answer()
