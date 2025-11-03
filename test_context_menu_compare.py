import sys
from PySide6 import QtWidgets, QtCore
from source.actions.actions import ContextMenuBuilder as OldContextMenuBuilder
from source.actions.context_menu import ContextMenuBuilder as NewContextMenuBuilder

class MockParent:
    def __init__(self):
        self.content = MockContent()
        self.folder_view = MockFolderView()

class MockContent:
    def get_selected_sources(self):
        return ["C:/test/file1.jpg", "C:/test/file2.jpg"]

class MockFolderView:
    def expand_and_select_path(self, path):
        print(f"expand_and_select_path called with: {path}")

def compare_menus():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    
    parent = MockParent()
    test_path = "C:/test/sample.jpg"
    
    old_builder = OldContextMenuBuilder(parent)
    old_menu = old_builder.build_menu(test_path)
    
    new_builder = NewContextMenuBuilder(parent)
    new_menu = new_builder.build_menu(test_path)
    
    print("=== 旧メニュー構造 ===")
    for i, action in enumerate(old_menu.actions()):
        if action.isSeparator():
            print(f"{i}: [SEPARATOR] {action.text()}")
        else:
            print(f"{i}: {action.text()} | shortcut: {action.shortcut().toString()}")
    
    print("\n=== 新メニュー構造 ===")
    for i, action in enumerate(new_menu.actions()):
        if action.isSeparator():
            print(f"{i}: [SEPARATOR] {action.text()}")
        else:
            shortcut = action.shortcut().toString() if action.shortcut() else ""
            data = action.data() if action.data() else ""
            print(f"{i}: {action.text()} | shortcut: {shortcut} | data: {data}")
    
    print("\n=== 比較結果 ===")
    old_actions = [a for a in old_menu.actions()]
    new_actions = [a for a in new_menu.actions()]
    
    if len(old_actions) != len(new_actions):
        print(f"❌ アクション数が異なります: 旧={len(old_actions)}, 新={len(new_actions)}")
    else:
        print(f"✓ アクション数一致: {len(old_actions)}")
    
    for i in range(min(len(old_actions), len(new_actions))):
        old_action = old_actions[i]
        new_action = new_actions[i]
        
        if old_action.text() != new_action.text():
            print(f"❌ [{i}] テキスト不一致: 旧='{old_action.text()}' vs 新='{new_action.text()}'")
        
        if old_action.shortcut().toString() != new_action.shortcut().toString():
            print(f"❌ [{i}] ショートカット不一致: 旧='{old_action.shortcut().toString()}' vs 新='{new_action.shortcut().toString()}'")
    
    print("\n完了")

if __name__ == "__main__":
    compare_menus()
