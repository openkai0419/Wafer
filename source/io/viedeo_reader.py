import os
from PySide6 import QtCore, QtGui, QtWidgets

from ..common.profiling import logger
from ..common.hashes import fast_sig_hash
from .manager import BaseLoader, BaseReader


class LabelWidget(QtWidgets.QLabel):
    def __init__(self, path=None, image=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path = path
        self.image = image
        self.setPixmap(QtGui.QPixmap.fromImage(self.image))
        self.show()
    
    def delete(self):
        self.hide()
        self.deleteLater()

    def resizeEvent(self, event, *args, **kwargs):
        logger.info(self.path)
        logger.info(self.size())
        self.setPixmap(QtGui.QPixmap.fromImage())
        return super().resizeEvent(event, *args, **kwargs)
