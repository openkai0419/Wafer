<div align="center">

# Wafer

![Wafer Screenshot](_docs/wafer_screenshot.png)

[![License](https://img.shields.io/badge/License-LGPL_2.1_or_later-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)
[![Release](https://img.shields.io/github/v/release/openkai0419/Wafer?style=flat-square)](https://github.com/openkai0419/Wafer/releases/latest)
[![Release Date](https://img.shields.io/github/release-date/openkai0419/Wafer?style=flat-square)](https://github.com/openkai0419/Wafer/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/openkai0419/Wafer/total?style=flat-square)](https://github.com/openkai0419/Wafer/releases)

[English](README.md)

</div>

Wafer は **PySide6**・**SQLite**・**ZMQ** を元にした大量管理向けのローカルファイルビューアーです。
プラグイン方式の extension をベースにする事によって高い拡張性を持ち、バックグラウンドプロセスでファイルを収集・DB化し、大量のファイルを高速に検索・閲覧する事を目標としています。
対応OS: Windows

## インストール

### Zip (python環境の無い人)

1. [Releases](https://github.com/openkai0419/Wafer/releases/latest) ページから
2. `Wafer-vX.X.X.zip` をダウンロード
3. 任意のフォルダに展開（SSD 推奨）
4. `Wafer.exe` を実行

Python 同梱のため、別途 Python のインストールは不要です。

アンインストールの際は `cleanup.bat` で `%LOCALAPPDATA%\Wafer` のアプリデータを削除した後、本体をフォルダごと削除してください。

### ソースから (python環境のある人)

#### 要件

- Python 3.11+
- Windows（現時点唯一の開発環境）

#### セットアップ

```bash
git clone https://github.com/openkai0419/Wafer.git
cd Wafer

# venv 作成と依存関係のインストール
setup.bat

# アプリ実行
python main.py

# テスト実行（レイヤー別ランナー: unit → smoke → benchmark）
scripts\test.bat

# または pytest を直接実行（pyproject.toml の設定が適用されます）
.venv\Scripts\python.exe -m pytest
```

## 設計

Wafer は **「共通基盤＋拡張プラグイン」** を基礎デザインとしています。

- **`wafer/`** は共通基盤 — ファイルの収集、DB化、検索、描画に必要なインフラを提供します。特定のファイル形式には依存しません。
- **`extensions/`** はフォルダ単位の独立した拡張 — 画像、動画、音声等の具体的なファイル形式への対応を実装します。

設計の3原則:

1. **基盤は共有、拡張は自由** 基盤は共通の土台。拡張は誰でも追加・変更可能。
2. **拡張こそが本体** extension は `wafer` の内部パッケージを直接 import して利用可能。API 越しの間接アクセスに制限されません。
3. **拡張同士は独立** 各拡張は `wafer/` という共通言語のみを通じて基盤と対話します。

extension は `extensions/` フォルダに配置するだけで `PluginLoader` が自動検出・登録します。

## 対応 Extension 一覧

#### ビューア / グリッド

| Extension | 対応形式 | 説明 |
|---|---|---|
| **image** | jpg, png, bmp, gif, webp | 静止画グリッド表示・ビューア（ズーム/パン） |
| **animated** | gif, apng, webp（アニメーション） | フレーム単位のアニメーション再生 |
| **video** | mp4, mkv, webm, avi, mov 等 | mpv による動画再生（OpenGL レンダリング） |

#### メタデータ / コレクション

| Extension | 対応形式 | 説明 |
|---|---|---|
| **exiftool** | jpg, png, webp, tiff, heic, avif, jxl, raw, psd 等 | ExifTool による汎用メタデータ抽出 |
| **ffmpeg** | mp4, mkv, webm, mp3, flac, wav 等 | ffprobe による動画/音声メタデータ抽出 |
| **wd14** | *（画像）* | WD14 モデルによる自動タグ付け（ONNX, GPU 対応） |
| **florence** | *（画像）* | Florence-2 による画像キャプション／タグ生成（GPU 対応） |
| **text_generation** | *（EXIF 付き画像）* | NovelAI 生成パラメータの抽出（デフォルト無効） |

#### UI

| Extension | 説明 |
|---|---|
| **additional_filters** | 日付範囲・正規表現クエリフィルタ |
| **additional_layout** | マルチスパン・均等配置・有機パーティション等のグリッドレイアウト |

### 仕組み

1. extension フォルダに `requirements.txt` がある場合、依存パッケージを `extensions/.packages/` に自動インストール
2. `.packages/` を `sys.path` に追加
3. `lib/` を DLL 検索パスに追加
4. `*.py` を import し、基底クラスの継承によりプラグインを自動検出

### Extension の実装例

`wafer.plugin` から基底クラスを import して利用してください。※基盤は現状安定していないため、外部プラグインはアップデートで壊れる可能性があります。ご承知ください。

```python
from wafer.plugin import BaseCollectorPlugin, CollectorResult

class MyCollector(BaseCollectorPlugin):
    NAME = "my_ext"
    EXTENSIONS = (".custom",)

    def process(self, path: str, file_info: tuple[float, int]) -> CollectorResult:
        return CollectorResult(source=path, status=True, meta_info={"key": "value"})
```

## データファイル

アプリケーションデータは `platformdirs` 経由（Windows では `AppData/Local`）に保存されます。
`_resources/` には UI アセットやバインディングプリセットが含まれており、置き換えによるカスタマイズが可能です。

## ライセンス

このプロジェクトは [GNU Lesser General Public License v2.1 or later](LICENSE) の下で公開されています。

このプロジェクトを改変して配布する場合は、改変部分の対応ソースコードを LGPL-2.1-or-later の条件で提供し、変更内容を明示してください。

このリポジトリ内の Python ソースコード（`wafer/` と `extensions/`）は LGPL-2.1-or-later です。

一部の extension は実行時にダウンロードされる外部バイナリやモデルを利用し、それらは独自のライセンスに従います。これらのバイナリ／モデルは本リポジトリには含まれません（`extensions/*/lib/` は `.gitignore` 対象）。詳細は各 extension の `README.md` および `THIRD_PARTY_LICENSE`（存在する場合）を参照してください。

| コンポーネント | Python コード | 実行時ダウンロードされるバイナリ／モデル |
|---|---|---|
| `wafer/`（コア） | LGPL-2.1-or-later | — |
| `extensions/video/` | LGPL-2.1-or-later | `libmpv-2.dll` — GPL-2.0+（または LGPL-2.1+） |
| `extensions/exiftool/` | LGPL-2.1-or-later | `exiftool.exe` — Artistic License / GPL（"Perl と同条件"） |
| `extensions/ffmpeg/` | LGPL-2.1-or-later | `ffmpeg.exe`, `ffprobe.exe` — GPL-3.0（gyan.dev essentials ビルド） |
| `extensions/wd14/` | LGPL-2.1-or-later | WD SwinV2 Tagger v3 — Apache-2.0 |
| `extensions/florence/` | LGPL-2.1-or-later | Florence-2 モデル（Microsoft）— MIT |
| その他の extension | LGPL-2.1-or-later | — |