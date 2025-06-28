from . common import get_or_create_path

setting_db_name = get_or_create_path("data/settings.db")
data_db_name = get_or_create_path("data/index.db")