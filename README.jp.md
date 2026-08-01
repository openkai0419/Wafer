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

Wafer は **PySide6**・**SQLite**・**ZMQ** をベースとした多機能ファイルビューアーです。
ローカルファイルをバックグラウンドで収集・DB化し、大量のファイルを高速に閲覧・検索・フィルタする事ができます。
拡張機能として、UI表示、メタデータ収集、AI解析、検索、レイアウト、アーカイブの対応などを動的に管理できます。

対応OS: Windows（現時点のみ）

## 使い方

1. [Releases](https://github.com/openkai0419/Wafer/releases/latest) から .zip をダウンロード＆展開して `Wafer.exe` を実行
2. Plugin Manager で利用したい拡張機能を有効化してプロセスを再起動
3. 拡張機能のインストールを待つ
4. 左上メニューからフォルダを追加
5. ファイルの収集を待つ

### アンインストール

`Uninstaller.exe` を実行する事でアンインストールが可能です。

データベース、設定、ログ、キャッシュなどのデータを個別に削除したい場合、
Windows ではデフォルトで `C:/Users/[ユーザー名]/AppData/Local/Wafer` 配下に配置されますので、手動で削除する事も可能です。

### プロセスについて (Tray と Viewer)

Wafer では `Tray` と `Viewer` の2つのプロセスが主になっています。

| 種類 | 役割 |
|---|---|
| `Tray` | Viewer、Database、バックグラウンド処理、再起動などを管理する常駐プロセス。 |
| `Viewer` | ファイルを閲覧・検索するウィンドウ。複数起動可。 |

Tray 起動中はファイル更新も即時検知されるため、バックグラウンドで起動しておけば常にデータベースを最新に保つことが可能です。

### Plugin Manager について

`Plugin Manager` では、extension の状態と、収集・解析機能の割り当てを管理します。

- **Install Extensions**: extension のインストールと有効/無効の切り替え。例:

| 拡張タイプ | 追加するもの | 代表的な extension |
|---|---|---|
| Viewer / Grid | ファイルの表示、サムネイル、ビューア操作等 | `image`, `animated`, `video` |
| Collector / Parser | メタデータ収集やAIタグ付けでファイルを検索可能にする拡張 | `exiftool`, `ffmpeg`, `color`, `wd14`, `florence` |
| Search / Filter | 日付範囲、正規表現、色距離など、探し方や絞り込み方法を追加 | `additional_filters`, `color` |
| Layout / UI | グリッドレイアウト、カスタムパネルなど | `additional_layout`, extension 設定パネル |
| Archive Support | 特定ファイルの中身を論理的な子パスとして扱い、表示を既存 plugin へ委譲する | `zip` |

- **Enable Extensions**: 上のタブでインストールした拡張機能を有効にし、下のタブでメタデータの収集を有効にするデータベースを選択します。

設定変更後は再起動が必要です。

## 開発方法

##### 要件

- Python 3.11+（.exe は Python 3.11.9 を同梱）

##### セットアップ

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

アンインストールは `cleanup.bat` を実行後、clone したフォルダを丸ごと削除してください。

### コード設計

Wafer は **「共通基盤 + extension」** を基礎デザインとしています。

- **`wafer/`** は共通基盤です。ファイル収集、DB、検索、描画、プロセス連携、プラグイン登録など、ファイル形式に依存しない土台を提供します。
- **`extensions/`** はフォルダ単位の独立した拡張です。画像、動画、メタデータ抽出、AI解析、検索フィルタ、レイアウトなどを追加します。

基盤は共通に保ち、ファイル形式や解析機能は extension 側で自由に追加できます。

### Extension

Extension は表示形式を増やすだけではありません。収集、検索、表示、UI、アーカイブ処理など、さまざまな領域を拡張します。
`extensions` フォルダ以下に Python ファイルを配置することで機能を追加できます。
サンプルは `wafer/builtins` や同梱の extension を参照してください。

## ライセンス

このプロジェクトは [GNU Lesser General Public License v2.1 or later](LICENSE) の下で公開されています。

このリポジトリ内のソースコード（`wafer/`, `extensions/`）は LGPL-2.1-or-later です。
このプロジェクトを改変して配布する場合は、改変部分の対応ソースコードを LGPL-2.1-or-later の条件で提供し、変更内容を明示してください。

一部の extension は、実行時にダウンロードされる外部バイナリやモデルを利用します。これらは本リポジトリには含まれず、それぞれ独自のライセンスに従います。
詳細は各 extension の `README.md` および `THIRD_PARTY_LICENSE`（存在する場合）を参照してください。
