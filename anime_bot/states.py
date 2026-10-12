from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    waiting_title = State()
    waiting_code = State()


class VipPaymentStates(StatesGroup):
    waiting_screenshot = State()


class AddAnimeStates(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_poster = State()
    waiting_genres = State()


class EditAnimeStates(StatesGroup):
    waiting_new_title = State()
    waiting_new_description = State()
    waiting_genres = State()
    waiting_new_country = State()
    waiting_new_year = State()
    waiting_new_language = State()
    waiting_new_poster = State()


class AddEpisodeStates(StatesGroup):
    waiting_video = State()
    waiting_filler_count = State()


class BroadcastStates(StatesGroup):
    waiting_content = State()


class AdminTextStates(StatesGroup):
    waiting_start_text = State()
    waiting_start_photo = State()
    waiting_help_text = State()
    waiting_help_admin_username = State()
    waiting_vip_price_1 = State()
    waiting_vip_price_2 = State()
    waiting_vip_price_3 = State()
    waiting_card_number = State()
    waiting_card_holder = State()
    waiting_required_channel = State()
    waiting_grant_vip_search = State()
    waiting_user_search = State()
    waiting_backup_file = State()


class OptionStates(StatesGroup):
    """Anime qo'shish/tahrirlashda davlat, til, subtitr, yilni inline tugma bilan tanlash."""
    picking = State()         # inline tugmalardan tanlash
    waiting_custom = State()  # "✍️ Boshqa" bosilganda qo'lda yozish


class GenreStates(StatesGroup):
    waiting_new_name = State()
    waiting_new_emoji = State()
    waiting_edit_name = State()
    waiting_edit_emoji = State()


class DailyPostStates(StatesGroup):
    waiting_time = State()


class ReferralAdminStates(StatesGroup):
    waiting_value = State()
