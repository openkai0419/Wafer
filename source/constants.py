from . common import get_or_create_path, data_path, config_path

defualt_db_name = "default"

def get_data_db(name):
    return data_path(f"data/{name}.db")

def get_setting_db(name):
    return data_path(f"dirs/{name}.db")