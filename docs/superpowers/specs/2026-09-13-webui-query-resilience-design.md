# WebUI: Backend再起動耐性のあるクエリナビゲーション + 接続状態表示

## 背景・問題

WebUIを開いたままBackendプロセスを再起動すると、画像/サムネイル表示は問題なく動くが、Viewerの次/戻る（prev/next）が反応しなくなる。

根本原因は2つ:

1. `wafer/app/webui/backend/session.py` の `QueryService._sessions` はプロセス内メモリのみに存在し、Backend再起動で消える。
2. `frontend/js/viewer.js` の `Viewer.step()`/`Viewer.open()` は常に `getItems(this.queryId, index, 1)` でBackendに問い合わせるが（Gridのキャッシュを見ない）、セッション消失時に返る404を **catchしていない**。Promiseが単に reject されるだけで、ユーザーには何も表示されず無反応に見える。

加えて、Backendが無応答になったこと自体を画面上で明示する仕組みが無い（`ws.js` は自動再接続するのみで状態を外部に通知しない）。

## 方針

- Backend側の `QuerySession`（インメモリ・TTL/LRU）は変更しない。1クエリの結果件数が数十万〜100万件になる使い方が頻繁にあるため、Frontendに全件のpath配列を保持する設計は転送量の観点で採用しない。
- Frontend側に「クエリの正体（db/filters/sort/ascending）と現在のquery_idをまとめて持ち、セッション切れ時は自分の情報で黙って再クエリして復旧する」`QueryClient` を新設し、Grid/Viewerはこれ経由でのみBackendに問い合わせる。
- 接続状態表示は `ws.js` の再接続ロジックの状態をそのままUIに橋渡しするだけ（リトライ方式自体は変更しない）。

## コンポーネント設計

### `frontend/js/api.js`
- `getJson`/`getItems`/`getAspects` が投げる例外を `ApiError extends Error`（`status` プロパティ保持）に統一する。404判定に使う。

### `frontend/js/query.js`（新規）
```
class QueryClient {
  constructor()              // db/filters/sort/ascending/queryId/total を空で初期化
  async run(db, filters, sort, ascending)  // postQuery実行、db/filters/sort/ascending/queryId/totalを保持して結果を返す
  async items(offset, limit) // 404なら保持条件で自動再postQueryし1回だけ再試行
  async aspects()            // 同上
}
```
- 1つの `QueryClient` インスタンス = 1つの論理的な「現在の検索」を表す。フォルダ切り替え等で検索条件が変わる場合は **新しいインスタンスを作る**（同一インスタンスのqueryIdを使い回さない）。これによりGrid/Viewer側のstale判定は文字列比較ではなく「保持している`client`オブジェクトと同一か」の同一性比較で済む。
- 再試行は404の場合のみ1回。それ以外のエラー（400等）はそのまま投げる。再試行後も失敗した場合はそのまま例外を投げる（無限ループ防止）。

### `frontend/js/grid.js`
- `this.db`/`this.queryId` フィールドを廃止し `this.client` を保持。
- `fetchMissing`: `getItems(queryId, ...)` 直呼びを `this.client.items(...)` に置き換え。stale判定は `queryId !== this.queryId` → `client !== this.client` に変更。
- サムネイルURL生成は `thumbUrl(this.client.db, item.path)`（既存通りセッション非依存）。

### `frontend/js/viewer.js`
- 同様に `this.client` を保持。`open()` 内の `getItems` 直呼びを `this.client.items(index, 1)` に置き換え。
- **バグ修正の核**: 取得処理を try/catch し、失敗時は `this.caption.textContent` にエラーを表示して安全に終了する（現状は無捕捉のPromise rejectionで無反応）。indexやstageは変更せず、次の正常な操作に備える。

### `frontend/js/ws.js`
- `connectEvents(onEvent, onStatusChange)` に拡張。`onopen` で `onStatusChange('open')`、`onclose` で `onStatusChange('closed')` を呼ぶ。再接続バックオフのロジック自体は変更しない。

### `frontend/js/app.js`
- `runQuery()`: `postQuery`/`getAspects` の直接呼び出しをやめ、`new QueryClient()` を作って `.run()`→`.aspects()` を呼び、`grid.setQuery(client, aspects)` / `viewer.setQuery(client, result.total)` に渡す。
- `connectEvents(onEvent, onStatusChange)` の第2引数で接続状態を受け取り、新設の `#conn-banner` 要素の表示/非表示を切り替える。

### `frontend/index.html` / `frontend/css/app.css`
- 画面上部に常設バナー `#conn-banner`（初期状態 `hidden`）を追加。文言は「Backend未応答」のみ（極限まで簡潔に）。`#status` とは独立した要素にする（`#status` は検索件数等の一時表示と兼用のため常設表示には使えない）。

## データフロー（Next/Prevの場合）

1. ユーザーが次へを押す → `viewer.step(1)` → `viewer.open(index)` → `this.client.items(index, 1)`。
2. `queryId` が生きていれば通常通り取得・表示。
3. Backend再起動等でセッションが消えていれば404 → `QueryClient` が保持する `db/filters/sort/ascending` で自動的に `postQuery` をやり直し、新しい `queryId` で再取得 → ユーザーには「一瞬待って進んだ」程度にしか見えない。
4. 再クエリ自体も失敗する（Backend本当に無応答）場合は例外が `viewer.open()` まで伝播し、catchでキャプションにエラー表示。このときは同時に `#conn-banner` も「切断」表示になっているはず（WebSocketも同時に切れているため）。

## 受け入れる妥協点

- 再クエリ後、Backend再起動中にファイルが増減していた場合、インデックス番号がわずかにズレる可能性がある（許容）。
- 再クエリ発生後も `total`/`aspects`（グリッドのレイアウト）は更新しない。表示件数のズレが気になる場合はユーザーがDB切り替え等で `runQuery()` をやり直せば解消する。
- 接続バナーは `ws.js` の open/closed のみを見る。個々の `fetch()` 失敗を横断的に監視する仕組みは追加しない（YAGNI。WebSocket切断とBackend無応答はほぼ同時に起きるため十分）。

## テスト方針

このプロジェクトのJSは独立ユニットテストを持たず、`tests/webui/*_e2e.py`（pytest-playwright + 実aiohttpサーバ）でのE2Eのみ。既存の `tests/webui/conftest.py` の `webui_base_url` はセッションスコープで共有サーバを使うため、サーバプロセスそのものを落とすテストは他テストに影響する。

- **セッション切れからの自動復旧**: `tests/webui/conftest.py` の `webui_base_url` フィクスチャは現状 base_url の文字列しか返さないため、テストから `QueryService` インスタンス（`app[QUERY_SERVICE]`）に触れられるよう、フィクスチャが `(base_url, query_service)` のタプル（または同等のアクセサ）を返すよう拡張する。新規テストで `ready_page` を使い、Viewerで1枚開いた後、この `query_service._sessions` を直接クリアして「Backend再起動でセッションが消えた」状態を模擬し、`#viewer-next` クリックでも正しく次の画像に進むことを確認する。
- **接続バナー**: 別途、専用の使い捨てサーバ（既存共有サーバに影響しない）を立てて接続→サーバ停止→バナー表示→サーバ再起動→バナー非表示、を確認するテストを追加する（`tests/webui/test_connection_banner_e2e.py` 等、新規fixtureとして用意）。
