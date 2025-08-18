from source.db.collector import ImageIndexer
from source.common.funcs import get_data_db
from source.constants import default_db_name

if __name__ == "__main__":
    db = ImageIndexer(get_data_db(default_db_name))
    with db as d:
        d.dump_json()