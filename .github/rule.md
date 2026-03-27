■ このファイルについて
- 設計上・思想上の絶対ルール。違反するとバグや設計崩壊を招く項目のみ記載
- copilot-instructions.md と同じ内容は書かない
- 実装前/実装後に必ず確認し、ルールに反していないか検証する

■ メモの原則
- メモには特定の実測結果や個別のAPI仕様ではなく、問題解決に至るまでの考え方・判断プロセスを記録する
- 「何が起きたか」ではなく「なぜそのアプローチを取るべきか」「どういう思考で問題を回避できるか」を書く
- コードを読めば分かる事実や、特定の関数の戻り値のような細かい仕様はメモしない。次回も同じ状況になったときに再現・再検証すればよい

■ 問題解決の原則
- 推論やコード上の確認だけで原因を断定しない。実際に処理を実行し、値や挙動を実測してから特定する
- 特に外部ライブラリやフレームワークのAPIは、ドキュメントや型定義と実際の挙動が異なることがある。想定通りに動くか必ず実測スクリプトで検証する
- 「コードを読んで正しそう」は根拠にならない。再現できない問題ほど、一時ログやデバッグスクリプトで事実を確かめることが最優先

■ dpix() の適用ルール
- ウィジェットサイズ、icon.pixmap、setContentsMargins、setSpacing等 → dpix()必須
- スタイルシート内のpx値もdpix()でf-string化
- QSizeデフォルト引数はNone→関数内でdpix()解決
- 除外: QGraphicsScene内シーン座標、QPixmap内描画座標、0px、1px極小ボーダー

■ 例外処理
- error()はログのみ。raiseは呼び出し側が明示的に行う
- 元の例外型を保持（RuntimeErrorへの変換禁止）。raise from exc を使う
- try/exceptの代わりに型・存在確認で安全に動かすことを基本とする
- ctx.get_instance/pos等の前提崩壊時はコマンド側で握りつぶさず例外で落とす

■ コマンド設計
- 汎用コマンドはevent非依存。キー/マウス/メニュー/別Widget全経路で動作すること
- Command.runのargsは一時的。get_args/set_argsと独立
- UI関連を直接操作するコマンドの場合、状態の真実のソースはWidget/Pluginの実状態。コマンド関数内で状態変更したら必ずCommand.set_checked()でメニュー表示を同期する。
- コマンドは"UI/設定をその値に変更する"責任のみを負う。再起動時に再現する等、実態の保存と再現はStateやOption等の別の設定を利用すること。
- action_groupのIDはコマンドのpath末尾と完全一致。表示用ラベルを含めない
- シングルトン: actions以下は全てinstance()パターンに統一。__new__やdict pattern禁止。テストでは_instance=Noneでリセット
- CommandOptionStore.configure()はinstance()前に必ず呼ぶ。テストではtmp_pathで初期化し、finally内で_instance/_default_pathを復元
- re-exportだけのファイル(ui.py等)は作らず実モジュールから直接importさせる
- KeyCombo/KeyChordSpec等の型エイリアスもcombo.pyに一元化
- modifier_keys_from_qt()でQt修飾キー→Key_*変換を一元管理（combo.py）
- @require デコレータ（wafer.core.commands.command.require）でインスタンス注入。@require_v でctx.get()値注入。Ctxクラスは廃止
- path/pathsのようなフォールバックロジックがあるctx値は補助関数（_ctx_path等）で関数内から直接呼ぶ。デコレータ化しない
- CommandMeta.priorityフィールドで同一IDの上書き優先度を制御（高い方が勝つ、同値は後勝ち）
- stored args解決とrequiredチェックはCommand.invoke()に集約。メニュー/キーバインドはctxを構築してinvoke()に委譲

■ メニュー/バインディング
- ホットキー解決は_resolve_hotkeys_batchでバッチ取得。ループ内個別呼出禁止
- CommandMenuRowのdpix値はクラスレベルキャッシュ(_px)で再利用
- findChildはコスト高。保持済み属性参照を使う
- actions以下のバインディング周りのクラス、コマンドを外部から使う場合は必ずbridgeを経由

■ GridView (QGraphicsView)
- index_at_pos()はView座標を受取り、内部でmapToScene()変換
- rect_selectの座標はto_scene_pos()でScene座標に変換して保存
- scene.setSceneRect()でスクロール範囲を制御

■ プラグインインターフェース規約
- WidgetViewerPlugin.render(path)はwidget引数を取らない。__init__でWIDGET_CLASS()から自動生成されたself.widgetでアクセスする。メインスレッドで呼ばれる
- WidgetGridPlugin.render(widget, path, size)はwidget引数を取る（プール管理で複数Widgetが存在するため）。メインスレッドで呼ばれる
- WidgetViewerPlugin.clear()とWidgetGridPlugin.release(widget)は異なるセマンティクス（clear=コンテンツリセット、release=リソース解放）のため名前は別
- BaseGridPlugin.release(widget)は画面外スクロール時にAdditionalWidgetPoolから呼ばれる。GPUリソース等重い資源はsuspend/resume方式。cleanup()は完全破壊のみ
- Grid/ViewerのWIDGET_CLASSとload()は排他。ViewerPluginのWidget生成は__init__で自動、GridのWidget生成はシステム管理
- Collectorはmeta_info+statusのみ返す。name/aspect/file_hashはPhase1で設定
- PRIORITY大=高優先。EXTENSIONS=()は全ファイルマッチ
- render(widget, path, size)は戻り値なし。フォールバックはresolve_chain内のcan_handle()で制御。BGワークが必要なプラグインはDispatcher.post()を自分で呼ぶ
- BaseGridPlugin.select(widget, path) / deselect(widget)はGridResolverがGridView._on_selection_changed内の差分計算で呼び出す
- プラグインのGrid/View/Commandは個別に登録・登録解除できる設計を前提とする
- 汎用的な機能をプラグイン専用のインターフェースで提供しない。wafer側でも使う仕組みはwafer側に汎用的に定義し、プラグイン基底クラスはそれを利用する形にする
- コマンドはctx経由で取得し、UIがコマンド状態を参照する時はコマンド不在を考慮する
- プラグインが読み込まれていなくてもアプリが落ちないこと（直接importしたファイル不在はエラーで可）

■ ビルトインとExtensionの二層構成
- 全プラグイン基底クラスはPluginBase（wafer/plugin/registry.py）を継承する
  - BasePlugin(PluginBase, ABC): Grid/Viewer/Collector用
  - BaseFilterPlugin / BaseSortPlugin(PluginBase, ABC): Query用
  - BaseLayoutPlugin(PluginBase, ABC): Layout用
- ビルトイン実装はwafer/builtins/に配置。extensionと同じプラグインインターフェースを使う
- ビルトインとextensionの唯一の違いはexe化時にwafer/builtins/が自動同梱される点。設計・インターフェースは同一
- フォールバックはビルトインプラグイン（EXTENSIONS=(), PRIORITY=-100）として登録。Resolverにフォールバックロジックをハードコードしない
- コマンドはCommandMeta/ActionKit系で別体系のためbuiltinsに含めない。wafer/app/以下とextensions/に分散

■ 未登録コマンドへのフォールバック
- 未登録コマンドはValueErrorを投げず、warningログ+None返却で安全に処理する
- メニュー構築は未知コマンドIDをスキップ。バインディング実行時はNotifier.warningでユーザー通知
- bridge.pyのCommand.get_checked()は未登録コマンドでFalse返却

■ プラグインローダー規約
- extensionsはwafer.plugin（公開API）、wafer.utils、wafer.coreを直接import可能。wafer.appへの依存は非推奨
- wafer.plugin.__init__.pyがextension向け公開API
- extension側のMenuGroupはプラグインロード時に一時保持され、viewer commands登録後に登録される
- MenuGroup.PRIORITYでAllMenuのルート表示順を制御。昇順ソート。viewer標準は10刻み(10-110)、extensionは1000台を推奨
- extension側のMenuGroupはGrid/View別に分離する（例: VideoGridCommands, 将来のVideoViewCommands）
- frozen環境でのpip実行にはEmbeddedPython使用。pip._internal直呼出は禁止
- setup_menu()ではSettings.configure()をコマンド登録より先に実行する
- _setup_dll_directoryは_load_oneで初回呼出+post_install後に再呼出の2箇所。両方必要

■ プロトタイプの方針
- プロトタイプは完全な状態まで持っていき、そのままメイン側に統合できる品質にする
- 複雑なOSレベルのハック（Win32 ColorKey透過等）はプロトタイプに不適。シンプルで強力な設計を選ぶ
- テスト中に本番の統合先（GridView、OverlayStack等）との互換性も検証する

■ セッション管理
- 匿名セッションは廃止。全ウィンドウは必ず名前付きセッション
- デフォルト名はDEFAULT_SESSION_NAME("Wafer")。連番は1始まり
- セッション管理コマンドはSessionCommandsを廃止しWindowCommandsに統合
- CommandParamにchoices_fn(callable value)とrequiredを追加。required未充足時はCommandOptionsDialogを自動表示

■ テストルール

● 実行コマンド
- venvを必ず使用: .venv\Scripts\python.exe -m pytest
- 個別テスト: .venv\Scripts\python.exe -m pytest tests/path/to/test_file.py -x -q
- フルテスト: .venv\Scripts\python.exe -m pytest tests/ -p no:cacheprovider -q
- オプションはpyproject.tomlのaddoptsで固定済み（--tb=short含む）。コマンドラインで追加指定しない
- -q（quiet）を付けて出力量を抑える。-v は個別調査時のみ使う

● 結果の確認方法
- 実行後 tests/test_summary.txt に結果サマリーが自動生成される。FAILED/ERRORの一覧と原因が全て含まれる
- このファイルを1回読めば全失敗を把握できるため、結果確認のための追加テスト実行は不要
- フロー: (1) pytest実行 → (2) tests/test_summary.txt読む → (3) 修正 → (4) pytest再実行で検証。最小2回
- failed: 0 かつ error: 0 であれば成功

● 出力の注意
- フルテストの出力をSelect-Object, Where-Object等のPowerShellパイプで加工しない。パイプ処理はexit codeを変えるため誤判定の原因になる
- 出力が長くてもパイプで切り取らず、そのまま実行する

● キャッシュ管理
- フルテスト時は -p no:cacheprovider で前回のlastfailedキャッシュの影響を回避する
- __pycache__ の手動削除は原則不要。テストファイルの大規模リネーム時のみ検討する

● タイムアウト
- pyproject.toml で timeout=30（秒）設定済み
- 30秒を超えるテストは @pytest.mark.slow を付与し、-m "not slow" で除外可能にする
- テスト内で固定sleepを使わない。条件付きポーリング（タイムアウト付きwhileループやQtBot.waitUntil）を使う

● テスト環境
- tests/conftest.pyでload_plugins(skip_install=True)を呼んでextensionレジストリを初期化する
- extensionのvendored numpyがsys.modulesを汚染する。conftest.pyでプラグインロード後にnumpy関連モジュールを除去すること
- Qtウィジェットテストでviewportリサイズを検証する場合はshow()を呼んでから検証する
- IPCテストはconftest.pyで_PORT_FILEをtmp_pathに隔離
- GridViewを実インスタンス化するテストはCommandOptionStore.configure()をmodule-scoped fixtureで初期化する
- テストの重複ファイル・重複メソッド名に注意。Pythonは同名メソッドを後勝ちで上書きし、pytestは1つしか収集しない
- QApplicationはpytest-qtが管理する。テスト内でQApplication()を直接生成しない
- conftest.pyが各テスト後にQWidgetを自動クリーンアップする。ただしshow()したウィンドウが残る場合はテスト内でclose()を呼ぶこと

● 二層構成
- ユニットテスト（tests/wafer/, tests/extensions/）: 個々のモジュールを単体で検証。ソースのディレクトリ構成とファイル名を対応させる
- 統合テスト（tests/ 直下）: 複数モジュールを跨ぐプロセス全体のフローを検証。実際のアプリ動作に近い条件で

● 統合テストの原則
1. 実ファイル・実DBで検証する。モックで内部を置き換えない
2. プロセス単位で切り出す。アプリの主要パイプラインごとにテストスイートを用意
3. 正常系だけでなく境界を検証する。未対応拡張子、プラグイン未登録、空ファイル、リネーム・削除後の整合性
4. DBへの書込はソースの公開APIを直接使う
5. 非同期パイプラインは固定sleepではなく条件付きタイムアウトで待つ

● テスト用データセット (.sample/)
- dataset_downloader.pyは目視デバッグ・ストレステスト用。自動テストは自前でPIL画像を生成する
- 新しいextensionを追加したらdataset_downloader.pyにもそのファイル形式の生成/DLを追加する
- 対応するextensionが存在しないファイル形式はdataset_downloaderに含めない
