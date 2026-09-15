from __future__ import annotations

from PySide6 import QtGui, QtWidgets

from ....utils.logs import AppLogger


class MenuSession:
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        seed_ctx=None,
        maker=None,
        pos=None,
    ):
        from .maker import MenuMaker
        from .menu_builder import MenuBuilder

        self.parent = parent
        self.seed_ctx = seed_ctx
        self.pos = pos
        self.maker = maker if maker is not None else MenuMaker()
        self.builder = MenuBuilder(self.maker, parent, seed_ctx=seed_ctx)

    def menu(self, items: list[str]):
        try:
            plan = self.maker.menu(items)
        except Exception as e:
            AppLogger.warning(str(e), exc=e)
            return None
        return MenuSpec(self, plan)

    def from_folder(self, folder: str):
        try:
            plan = self.maker.from_folder(str(folder))
        except Exception as e:
            AppLogger.warning(str(e), exc=e)
            return None
        return MenuSpec(self, plan)

    def all_roots(self):
        try:
            plan = self.maker.all_roots()
        except Exception as e:
            AppLogger.warning(str(e), exc=e)
            return None
        return MenuSpec(self, plan)

    def build(
        self,
        plan,
        *,
        selection_callback=None,
        allow_options_with_selection: bool = False,
    ):
        try:
            return self.builder.build(
                plan,
                selection_callback=selection_callback,
                allow_options_with_selection=allow_options_with_selection,
            )
        except Exception as e:
            AppLogger.warning(str(e), exc=e)
            return None


class MenuSpec:
    def __init__(self, session: MenuSession, plan):
        self._session = session
        self._plan = plan

    def hide(self, targets):
        try:
            self._plan = self._plan.hide(targets)
        except Exception as e:
            AppLogger.warning(str(e), exc=e)
        return self

    def add(self, items):
        try:
            self._plan = self._plan.add(items)
        except Exception as e:
            AppLogger.warning(str(e), exc=e)
        return self

    def insert(self, target: str, items):
        try:
            self._plan = self._plan.insert(target, items)
        except Exception as e:
            AppLogger.warning(str(e), exc=e)
        return self

    def build(
        self,
        *,
        selection_callback=None,
        allow_options_with_selection: bool = False,
    ):
        return self._session.build(
            self._plan,
            selection_callback=selection_callback,
            allow_options_with_selection=allow_options_with_selection,
        )

    def exec(
        self,
        pos=None,
        *,
        selection_callback=None,
        allow_options_with_selection: bool = False,
    ):
        m = self.build(
            selection_callback=selection_callback,
            allow_options_with_selection=allow_options_with_selection,
        )
        if m is None:
            return None
        p = pos if pos is not None else (self._session.pos if self._session.pos is not None else QtGui.QCursor.pos())
        return m.exec(p)
