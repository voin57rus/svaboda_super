async def _render_main_page(target, force_new: bool = False):
    from bot.utils.page_renderer import render_page
    from database.requests import (
        is_trial_enabled, get_trial_tariff_id, has_used_trial,
        is_ai_tariffs_enabled, is_ai_standard_enabled,
        is_ai_premium_enabled, is_ai_vip_enabled
    )
    from bot.utils.admin import is_admin
    from aiogram.types import InlineKeyboardButton

    user_id = target.from_user.id if hasattr(target, 'from_user') and target.from_user else 0
    is_admin_user = is_admin(user_id)
    
    tariff_text = '' if is_admin_user else _build_tariff_text()
    show_trial = is_trial_enabled() and get_trial_tariff_id() is not None and (not has_used_trial(user_id))
    show_referral = is_referral_enabled()
    
    # Общее включение ИИ-тарифов
    show_ai_tariffs = is_ai_tariffs_enabled()
    
    # Индивидуальные настройки для каждого тарифа
    show_standard = show_ai_tariffs and is_ai_standard_enabled()
    show_premium = show_ai_tariffs and is_ai_premium_enabled()
    show_vip = show_ai_tariffs and is_ai_vip_enabled()
    
    visibility = {
        'btn_trial': show_trial,
        'btn_referral': show_referral,
        'btn_ai_standard': show_standard,
        'btn_ai_premium': show_premium,
        'btn_ai_vip': show_vip,
    }
    text_replacements = {'%тарифы%': tariff_text, '%без_тарифов%': ''}
    append_buttons = None
    if is_admin_user:
        append_buttons = [[InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")]]
    await render_page(target, page_key='main', visibility=visibility, text_replacements=text_replacements, append_buttons=append_buttons, force_new=force_new)
