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

Wafer は **PySide6**・**SQLite**・**ZMQ** を元にした多機能なファイルビューアーです。
ローカルファイルをバックグラウンドで収集・DB化し、Viewer 上で大量のファイルを高速に閲覧、検索、フィルタリングすることが可能です。
表示、メタデータ収集、AI解析、検索、レイアウト、アーカイブ対応などを extension としてユーザーが動的に管理できる構造になっています。

対応OS: Windows

## インストールとデータ

### Zip (Python環境のない人)

1. [Releases](https://github.com/openkai0419/Wafer/releases/latest) ページを開く
2. `Wafer-vX.X.X.zip` をダウンロード
3. 任意のフォルダに展開（SSD 推奨）
4. `Wafer.exe` を実行

Python 同梱のため、Python のインストールは不要です。

### ソースから (Python環境のある人)

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
main.bat
# もしくは
python main.py

```
### アンインストール

Windows ではデフォルトで `C:/Users/[ユーザー名]/AppData/Local/Wafer` 配下にDatabase、設定、ログ、キャッシュなどのアプリケーションデータが作成されます。
アンインストールの際は `cleanup.bat` でアプリケーションデータを削除した後、本体をフォルダごと削除してください。

## Tray と Viewer

Wafer では `Tray` と `Viewer` の2つのプロセスが主になっています。

| 種類 | 役割 |
|---|---|
| `Tray` | 常駐管理プロセス。Viewer、Database、バックグラウンド処理、再起動などの全体管理を担当。 |
| `Viewer` | ファイルを閲覧・検索するウィンドウ。複数起動＆別のウィンドウ状態を持つ事ができます。 |

収集や解析は Tray 配下のバックグラウンド処理として動くため、複数の Viewer で複数のデータベースを管理しながら管理することができます。
Tray起動中はファイルの更新も即時検知されるため、Trayを起動しておく事で常にDBを最新の状態に保つ事が可能です。

## コード設計

Wafer は **「共通基盤 + extension」** を基礎デザインとしています。

- **`wafer/`** は共通基盤です。ファイル収集、DB、検索、描画、プロセス連携、プラグイン登録など、ファイル形式に依存しない土台を提供します。
- **`extensions/`** はフォルダ単位の独立した拡張です。画像、動画、メタデータ抽出、AI解析、検索フィルタ、レイアウトなどの機能を追加します。

基盤は共通に保ち、具体的なファイル形式や解析機能は extension 側で自由に追加できることを重視しています。

## Extension

Extension は表示形式を増やすだけのものではありません。収集、検索、表示、UI、アーカイブ処理など、アプリのさまざまな領域を拡張します。
また、`extensions`フォルダ以下に適切なpythonファイルを配置することで動的に機能を追加する事ができます。

| 拡張ポイント | できること | 代表的な extension |
|---|---|---|
| Viewer / Grid | ファイルの表示、サムネイル、ビューア操作を追加する | `image`, `animated`, `video` |
| Metadata & AI Collection | EXIF、動画/音声情報、色、タグ、キャプションなどを収集し、検索や表示に使えるデータを増やす | `exiftool`, `ffmpeg`, `color`, `wd14`, `florence` |
| Search / Filter | 日付範囲、正規表現、色距離など、探し方や絞り込み方法を追加する | `additional_filters`, `color` |
| Layout / UI | グリッドレイアウト、設定パネル、補助UIなどを追加する | `additional_layout`, プラグイン設定UI等 |
| Archive Support | 1つのアーカイブから中身を論理的な子パスとして扱い、表示を既存pluginへ委譲する | `zip` |

### Plugin Manager

`Plugin Manager` では、読み込まれた extension の状態と、収集・解析機能の割り当てを管理します。

- **Extensions**: extension ごとインストールや、有効/無効の切り替えをここから切り替えます。切り替えた後はプロセス全体の再起動が必要です。
- **Collectors**: メタデータ収集やAI解析などのExtensionはどのDatabaseに保存するかを選択可能です。


## ライセンス

このプロジェクトは [GNU Lesser General Public License v2.1 or later](LICENSE) の下で公開されています。

このリポジトリ内の Python ソースコード（`wafer/` と `extensions/`）は LGPL-2.1-or-later です。
このプロジェクトを改変して配布する場合は、改変部分の対応ソースコードを LGPL-2.1-or-later の条件で提供し、変更内容を明示してください。

一部の extension は、実行時にダウンロードされる外部バイナリやモデルを利用します。これらは本リポジトリには含まれず、それぞれ独自のライセンスに従います。
詳細は各 extension の `README.md` および `THIRD_PARTY_LICENSE`（存在する場合）を参照してください。
