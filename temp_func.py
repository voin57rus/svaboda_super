async def _render_main_page(target, force_new: bool = False):
    from bot.utils.page_renderer import render_page
    from database.requests import (
        is_trial_enabled, get_trial_tariff_id, has_used_trial,
        is_ai_tariffs_enabled, is_ai_standard_enabled,
        is_ai_premium_enabled, is_ai_vip_enabled
    )
    from bot.utils.admin import is_admin

    if isinstance(target, CallbackQuery):
        user_id = target.from_user.id
    else:
        user_id = target.from_user.id if hasattr(target, 'from_user') and target.from_user else 0
        
    is_admin_user = is_admin(user_id)
    ai_enabled = is_ai_tariffs_enabled()
    
    tariff_text = '' if is_admin_user else _build_tariff_text()
    show_trial = is_trial_enabled() and get_trial_tariff_id() is not None and (not has_used_trial(user_id))
    show_referral = is_referral_enabled()
    
    visibility = {
        'btn_trial': show_trial,
        'btn_referral': show_referral,
        'btn_ai_standard': ai_enabled and is_ai_standard_enabled(),
        'btn_ai_premium': ai_enabled and is_ai_premium_enabled(),
        'btn_ai_vip': ai_enabled and is_ai_vip_enabled(),
    }
    
    text_replacements = {'%тарифы%': tariff_text, '%без_тарифов%': ''}
    append_buttons = None
    if is_admin_user:
        append_buttons = [[InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel", style="success")]]
    await render_page(target, page_key='main', visibility=visibility, text_replacements=text_replacements, append_buttons=append_buttons, force_new=force_new)
