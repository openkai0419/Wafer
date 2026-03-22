# コードレビュー指摘事項（2026-03-22）

全体を精査した結果をまとめる。段階的に修正する際のチェックリスト。

---

## 優先度: 致命的（OSS公開前に必須）

### 1. バージョニングの完全な欠如
- `__version__` が未定義。git tag も未使用
- `pyproject.toml` にパッケージメタデータ（`[project]`セクション）がない
- ビルド成果物の .exe にもバージョン情報が埋まらない
- **対策**:
  - `wafer/__init__.py` に `__version__ = "0.1.0"` を定義
  - `pyproject.toml` に `[project]` セクション（name, version, description, python-requires）を追加
  - `main.spec` の `EXE` に version リソースを渡す
  - リリース時に git tag を打つ運用を確立

### 2. LICENSE ファイルの欠如
- ライセンス未明記 = 法的に全権利留保と解釈される
- フォークもコントリビュートも法的に不可能な状態
- **対策**: MIT / Apache-2.0 / GPL 等を選定し `LICENSE` ファイルを追加

### 3. `DEV_MODE = True` がデフォルト
- ファイル: `wafer/constants.py` L8
- `--dev` 引数なしで起動してもDEV_MODEがTrueのまま
- プロダクションビルドでも開発モードが有効になる
- **対策**: デフォルトを `False` に変更

---

## 優先度: 高（品質・信頼性に直結）

### 4. CI/CDパイプラインの不在
- `.github/workflows/` が存在しない
- テストは全て手動実行に依存
- pre-commit hook、linter/formatter の設定も一切なし
- **対策**:
  - GitHub Actions で最低限 `ruff` lint + `pytest` を自動実行
  - `.pre-commit-config.yaml` を追加
  - `ruff` を `requirements-dev.txt` に追加

### 5. `except Exception` の過剰使用
- wafer/ 以下だけで60箇所以上
- 特にIPC層（node.py, outbox.py, transport.py）で変数名すら取らない `except Exception:` が散見
- copilot-instructions.md に「エラー握りつぶし禁止」と明記されているのに実コードが非準拠
- **対策**:
  - 全箇所を精査し、キャッチすべき具体的な例外型に変更
  - 最低でも `except Exception as e:` + `AppLogger.warning/error` でのログ記録を保証
  - 本当に無視すべきケースのみコメントで理由を明記
- **該当ファイル（特に問題が大きいもの）**:
  - `wafer/core/ipc/transport.py` (4箇所、変数名なし)
  - `wafer/core/ipc/node.py` (3箇所、変数名なし)
  - `wafer/core/ipc/outbox.py` (2箇所、変数名なし)
  - `wafer/utils/paths.py` (1箇所、変数名なし)
  - `wafer/utils/helpers.py` (1箇所、変数名なし)
  - `wafer/utils/logs.py` (1箇所、変数名なし)
  - `wafer/app/viewer/preview/meta_viewer.py` (2箇所、変数名なし)
  - `wafer/core/platform/thumbnails.py` (1箇所、変数名なし)

### 6. スレッドセーフティの不徹底
- ロックが必要な箇所に不在:
  - `wafer/core/ipc/node.py`: `_last_recv`, `_last_connect_time` がロック無しで複数スレッドからアクセス
  - `wafer/plugin/loader.py`: `_deferred_commands` リストが保護されていない
  - `wafer/core/db/indexer.py`: `exclude_paths` のset/getがスレッド間で非同期
- **対策**: 各箇所にロックを追加し、アクセスパターンを文書化

### 7. コード重複: SQL エスケープ処理
- `wafer/core/db/query.py` と `wafer/builtins/filters.py` で `_escape_like()` / `_match_clause()` が重複
- バグ修正時に片方だけ修正される温床
- **対策**: `wafer/core/db/` 以下に共通ユーティリティとして一元化

---

## 優先度: 中（プロフェッショナリズム・一貫性）

### 8. typing の新旧記法混在
- 多くのファイルが `from __future__ import annotations` でモダン記法を使用
- 一部のファイルだけ古い `Dict`, `List`, `Optional`, `Tuple` をインポート
- **該当ファイル**:
  - `wafer/core/qt/file_conflict_resolver.py`: `Dict, Iterable, List`
  - `wafer/core/platform/file_operations.py`: `Dict, List, Literal, Optional, Tuple`
  - `wafer/core/platform/paste.py`: `Dict, List, Literal, Optional`
  - `wafer/plugin/grid/cell_job.py`: `Optional`
  - `wafer/core/qt/dispatcher.py`: `Optional`
  - `wafer/app/viewer/grid/pipeline.py`: `Optional`
  - `wafer/app/viewer/commands/file_commands.py`: `List`
- **対策**: `from __future__ import annotations` を追加し、ビルトイン型の小文字記法に統一

### 9. `print()` がプロダクションコードに残存
- `wafer/app/viewer/widgets/combo_with_buttons.py` L97-99（`if __name__ == '__main__':` ブロック内）
- 同様の `if __name__` デバッグブロックが3ファイルに存在:
  - `wafer/core/setting/widgets/foldersetting.py` L84
  - `wafer/app/viewer/widgets/progress_bar.py` L232
  - `wafer/app/viewer/widgets/combo_with_buttons.py` L93
- **対策**: ライブラリモジュール内の `if __name__` ブロックは削除するか、
  別の `examples/` ディレクトリに移動

### 10. テストカバレッジの可視性がゼロ
- `pytest-cov` が `requirements-dev.txt` に含まれていない
- カバレッジ計測の仕組みがない
- **対策**:
  - `pytest-cov` を `requirements-dev.txt` に追加
  - `pyproject.toml` に `[tool.coverage]` セクションを追加
  - CI でカバレッジレポートを生成

### 11. OSS標準ファイルの欠如
- `CHANGELOG.md`: リリース履歴がない
- `CONTRIBUTING.md`: コントリビューションガイドがない
- `SECURITY.md`: 脆弱性報告プロセスがない
- **対策**: 各ファイルを作成。最低でも CHANGELOG は必須

### 12. リポジトリ名 `NAI_image_viewer` とプロジェクト名 `Wafer` の不一致
- コード内・README・UIは全て「Wafer」で統一済み
- リポジトリ名だけが旧名のまま
- **対策**: パブリックリポジトリ名を `wafer` に変更

---

## 優先度: 低（改善推奨）

### 13. ビルドスクリプトのポータビリティ
- `export_public.bat` に `F:\codes\` がハードコード
- 全スクリプトが `.bat` (Windows限定)
- **対策**:
  - パスを相対パスまたは環境変数化
  - `export_public.bat` はpublicリポジトリに含めない、または `.gitignore` に追加

### 14. msgpack デシリアライズの入力検証不足
- ファイル: `wafer/core/ipc/message.py` L46-49
- `msgpack.unpackb()` に `strict_map_key=True` や `max_*_len` 制限が未設定
- 同一マシン内IPCとはいえ、防御的プログラミングが不足
- **対策**: `strict_map_key=True` を追加。サイズ制限の検討

### 15. ダウンロードサイズ検証のタイミング
- ファイル: `wafer/plugin/installer.py` L67-81
- Content-Length チェック後も、受信バイト数で再チェックしているが、  
  ファイル書き込み開始後にサイズ超過に気づく構造
- **対策**: Content-Length ヘッダが max_bytes を超えた時点で resp を閉じ、  
  ファイルを開く前にリターンする

### 16. `pyproject.toml` にパッケージメタデータがない
- pytest 設定のみで `[project]` セクションが不在
- **対策**: #1 のバージョニング対応と合わせて追加

---

## 良い点（維持すべき設計）

- wafer/extensions の二層アーキテクチャは明確で拡張性が高い
- IPCブローカー/ノードモデルは本格的
- rule.md / memory.md による内部ドキュメントが充実
- テスト構造（unit/integration/smoke/benchmark の分離）が優秀
- .gitignore が適切
- セキュリティ意識（URL ホワイトリスト、ZIPパス検証、SQLパラメータ化）が全体的に高い
- プラグインインストーラーの SHA256 検証は堅実
- requirements.txt の全依存バージョンピン留めが適切

---

## 総評

> 中身はプロだが、玄関がない家

コードの設計力は高いが、プロジェクト運営の成熟度（バージョニング、CI/CD、ライセンス、
コードフォーマッタ）が追いついていない。コードの質に対して、外から見たときに
想像以上にアマチュアに見えてしまう状態。

修正の推奨順序:
1. LICENSE + DEV_MODE（即座に対応可能）
2. バージョニング + pyproject.toml メタデータ
3. CI/CD（GitHub Actions）
4. except Exception の精査
5. typing 統一 + print 削除
6. スレッドセーフティ修正
7. OSS標準ファイル追加
