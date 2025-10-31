

from PySide6 import QtCore, QtGui, QtWidgets

from ..common.funcs import uipx


def create_labeled_separator(label, parent):
    action = QtWidgets.QWidgetAction(parent)
    widget = QtWidgets.QWidget(parent)
    layout = QtWidgets.QHBoxLayout(widget)
    space = uipx(10)
    layout.setContentsMargins(space * 1.6, space / 4, space * 1.6, 0)
    lbl = QtWidgets.QLabel(label)
    lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    lbl.setStyleSheet('color: gray; font-size: {}px;'.format(space))
    lbl.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
    layout.addWidget(lbl)
    action.setDefaultWidget(widget)
    return action


class MenuBuilder:

    def build(self, root_menu, definitions, parent):
        actions = {}
        menus = {}
        for item in definitions:
            path = item['path'].split('/')
            name = path[-1]
            parent_path = '/'.join(path[:-1])
            menu = self._get_or_create_menu(root_menu, parent_path, menus, parent)
            action = QtGui.QAction(name, parent)
            if item.get('separator'):
                if name == '':
                    menu.addSeparator()
                else:
                    sep_action = create_labeled_separator(name, parent)
                    menu.addAction(sep_action)
                continue
            if 'shortcut' in item:
                action.setShortcut(item['shortcut'])
            if 'checkable' in item:
                action.setCheckable(True)
            if 'callback' in item:
                action.triggered.connect(item['callback'])
            menu.addAction(action)
            actions[item['path']] = action
        return (actions, menus)

    def _get_or_create_menu(self, root_menu, path, menus, parent):
        if not path:
            return root_menu
        if path in menus:
            return menus[path]
        parts = path.split('/')
        cur_path = ''
        parent_menu = root_menu
        for part in parts:
            cur_path = (cur_path + '/' + part).lstrip('/')
            if cur_path not in menus:
                menu = QtWidgets.QMenu(part, parent)
                parent_menu.addMenu(menu)
                menus[cur_path] = menu
            parent_menu = menus[cur_path]
        return menus[path]


def add_menu_actions_recursively(widget, menu):
    for action in menu.actions():
        if action.menu():
            add_menu_actions_recursively(widget, action.menu())
        else:
            widget.addAction(action)