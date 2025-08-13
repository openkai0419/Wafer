import os
import sys
import tempfile

import requests
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def save_text(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

def save_image(path, qimage: QImage):
    qimage.save(path)

def download_url_to_file(url, path):
    r = requests.get(url)
    r.raise_for_status()
    with open(path, 'wb') as f:
        f.write(r.content)

class PasteWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.label = QLabel("クリップボードからペーストして保存")
        self.label.setAlignment(Qt.AlignCenter)

        self.button = QPushButton("ペーストして保存")
        self.button.clicked.connect(self.paste_clipboard)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.button)
        self.setLayout(layout)

        self.target_dir = self.select_target_directory()

    def select_target_directory(self):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        if dlg.exec():
            return dlg.selectedFiles()[0]
        return tempfile.gettempdir()

    def paste_clipboard(self):
        clipboard = QApplication.clipboard()
        md = clipboard.mimeData()

        if md.hasImage():
            # 画像データ
            qimage = clipboard.image()
            path = os.path.join(self.target_dir, "pasted_image.png")
            save_image(path, qimage)
            self.label.setText(f"画像を保存しました:\n{path}")
            print(f"Saved image: {path}")

        elif md.hasUrls():
            urls = md.urls()
            for i, url in enumerate(urls):
                url_str = url.toString()
                if url.isLocalFile():
                    # ローカルファイルをコピー
                    src = url.toLocalFile()
                    dst = os.path.join(self.target_dir, os.path.basename(src))
                    with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:
                        fdst.write(fsrc.read())
                    print(f"Copied local file: {dst}")
                else:
                    # リモートURLをダウンロード
                    filename = f"downloaded_{i}.bin"
                    path = os.path.join(self.target_dir, filename)
                    try:
                        download_url_to_file(url_str, path)
                        print(f"Downloaded {url_str} → {path}")
                    except Exception as e:
                        print(f"Failed to download {url_str}: {e}")
            self.label.setText(f"URLを処理しました。\n{self.target_dir}")

        elif md.hasText():
            # テキストデータ
            text = md.text()
            # URLっぽければダウンロード
            if text.startswith("http"):
                path = os.path.join(self.target_dir, "downloaded_from_text.bin")
                try:
                    download_url_to_file(text, path)
                    self.label.setText(f"URLからダウンロードしました:\n{path}")
                    print(f"Downloaded {text} → {path}")
                except Exception as e:
                    self.label.setText(f"URLダウンロード失敗:\n{e}")
            else:
                path = os.path.join(self.target_dir, "pasted_text.txt")
                save_text(path, text)
                self.label.setText(f"テキストを保存しました:\n{path}")
                print(f"Saved text: {path}")

        else:
            self.label.setText("画像・URL・テキストがクリップボードにありません。")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = PasteWidget()
    w.setWindowTitle("クリップボード ペースト サンプル")
    w.resize(500, 300)
    w.show()
    sys.exit(app.exec())
