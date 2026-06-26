with open('bot/handlers/admin/system.py', 'r') as f:
    content = f.read()

# Add "Стартовая картинка" button to admin_edit_texts menu
old_menu = '    builder.row(InlineKeyboardButton(text="📢 Ссылка: Мой канал", callback_data="edit_link:channel"))\n    \n    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_bot_settings"))'

new_menu = '    builder.row(InlineKeyboardButton(text="📢 Ссылка: Мой канал", callback_data="edit_link:channel"))\n    builder.row(InlineKeyboardButton(text="🖼️ Стартовая картинка", callback_data="edit_image:main"))\n    \n    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_bot_settings"))'

content = content.replace(old_menu, new_menu)

# Add edit_image handler before edit_text_start
handler_code = '''
@router.callback_query(F.data.startswith("edit_image:"))
async def edit_image_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования картинки страницы."""
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
    
    from aiogram.filters import StateFilter as _sf
    state_obj = await state.get_state()
    
    await state.set_state('wait_edit_image')
    await state.update_data(editing_image_page=page_key)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_edit_texts"))
    
    if current_image:
        text = "🖼️ <b>Редактирование картинки: {}</b>\n\nТекущая картинка:\n<code>{}</code>\n\n👇 Отправьте ссылку на новую картинку (http/https):".format(page_key, current_image)
    else:
        text = "🖼️ <b>Редактирование картинки: {}</b>\n\nКартинка не установлена (используется дефолтная).\n\n👇 Отправьте ссылку на картинку (http/https):".format(page_key)
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.message(StateFilter('wait_edit_image'), ~F.text.startswith('/'))
async def save_image(message: Message, state: FSMContext):
    """Сохранение новой ссылки картинки."""
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
            "❌ <b>Ошибка:</b> Ссылка должна начинаться с <code>http://</code> или <code>https://</code>\n\nВы ввели: <code>{}</code>\n\nПопробуйте ещё раз или нажмите /start для отмены.".format(new_value),
            parse_mode="HTML"
        )
        return
    
    import sqlite3
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    sql = "UPDATE pages SET image_custom = ?, updated_at = CURRENT_TIMESTAMP WHERE page_key = ?"
    c.execute(sql, (new_value, page_key))
    conn.commit()
    conn.close()
    
    await state.clear()
    
    try:
        await message.delete()
    except Exception:
        pass
    
    await message.answer(
        "✅ <b>Картинка обновлена!</b>\n\n<code>{}</code>".format(new_value),
        parse_mode="HTML",
        reply_markup=back_and_home_kb("admin_edit_texts")
    )

'''

marker = '@router.callback_query(F.data.startswith("edit_text:"))'
pos = content.find(marker)
if pos == -1:
    print("Marker not found!")
else:
    content = content[:pos] + handler_code + content[pos:]
    print("Handler added!")

with open('bot/handlers/admin/system.py', 'w') as f:
    f.write(content)

print("Done!")
