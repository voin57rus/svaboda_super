@router.callback_query(F.data == "admin_ai_tariffs_toggle")
async def admin_ai_tariffs_toggle(callback: CallbackQuery, state: FSMContext):
    from database.db_settings import is_ai_tariffs_enabled, set_ai_tariffs_enabled
    new_value = not is_ai_tariffs_enabled()
    set_ai_tariffs_enabled(new_value)
    await callback.answer(f"✅ ИИ-тарифы {'включены' if new_value else 'выключены'}", show_alert=True)
    await show_bot_settings(callback, state)

@router.callback_query(F.data == "admin_ai_standard_toggle")
async def admin_ai_standard_toggle(callback: CallbackQuery, state: FSMContext):
    from database.db_settings import is_ai_standard_enabled, set_ai_standard_enabled
    new_value = not is_ai_standard_enabled()
    set_ai_standard_enabled(new_value)
    await callback.answer(f"✅ ИИ-тариф Standard {'включён' if new_value else 'выключен'}", show_alert=True)
    await show_bot_settings(callback, state)

@router.callback_query(F.data == "admin_ai_premium_toggle")
async def admin_ai_premium_toggle(callback: CallbackQuery, state: FSMContext):
    from database.db_settings import is_ai_premium_enabled, set_ai_premium_enabled
    new_value = not is_ai_premium_enabled()
    set_ai_premium_enabled(new_value)
    await callback.answer(f"✅ ИИ-тариф Premium {'включён' if new_value else 'выключен'}", show_alert=True)
    await show_bot_settings(callback, state)

@router.callback_query(F.data == "admin_ai_vip_toggle")
async def admin_ai_vip_toggle(callback: CallbackQuery, state: FSMContext):
    from database.db_settings import is_ai_vip_enabled, set_ai_vip_enabled
    new_value = not is_ai_vip_enabled()
    set_ai_vip_enabled(new_value)
    await callback.answer(f"✅ ИИ-тариф VIP {'включён' if new_value else 'выключен'}", show_alert=True)
    await show_bot_settings(callback, state)
