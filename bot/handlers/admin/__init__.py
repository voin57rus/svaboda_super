from aiogram import Router

from bot.handlers.admin.main import router as main_router
from bot.handlers.admin.message_editor import router as message_editor_router
from bot.handlers.admin.servers import router as servers_router
from bot.handlers.admin.payments import router as payments_router
from bot.handlers.admin.tariffs import router as tariffs_router
from bot.handlers.admin.broadcast import router as broadcast_router
from bot.handlers.admin.users_list import router as users_list_router
from bot.handlers.admin.users_manage import router as users_manage_router
from bot.handlers.admin.users_keys import router as users_keys_router
from bot.handlers.admin.users_keys_deleted import router as users_keys_deleted_router
from bot.handlers.admin.system import router as system_router
from bot.handlers.admin.trial import router as trial_router
from bot.handlers.admin.referral import router as referral_router
from bot.handlers.admin.groups import router as groups_router
from bot.handlers.admin.svaboda_admin import router as svaboda_admin_router
from bot.handlers.admin.admin_free_key import router as admin_free_key_router
from bot.handlers.admin.admins_manage import router as admins_manage_router
from bot.handlers.admin.ai_manage import router as ai_manage_router

admin_router = Router()

admin_router.include_routers(
    main_router,
    message_editor_router,
    servers_router,
    payments_router,
    tariffs_router,
    groups_router,
    broadcast_router,
    users_list_router,
    users_manage_router,
    users_keys_router,
    users_keys_deleted_router,
    system_router,
    trial_router,
    referral_router,
    svaboda_admin_router,
    admin_free_key_router,
    admins_manage_router,
    ai_manage_router
)
