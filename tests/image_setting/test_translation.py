import py_compile


def test_compile():
    py_compile.compile('source/image_setting/__init__.py')
    py_compile.compile('source/image_setting/base_setting.py')
    py_compile.compile('source/image_setting/db_settings.py')
    py_compile.compile('source/image_setting/setting_window.py')
