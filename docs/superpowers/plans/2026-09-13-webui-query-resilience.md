# WebUI Query Resilience + Connection Banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUIのViewerで次/戻るがBackend再起動後も動くようにし（セッション切れを自動復旧）、Backend無応答時に画面上へ常設バナーで表示する。

**Architecture:** Backend側の`QuerySession`（インメモリ）は変更しない。Frontendに`QueryClient`（db/filters/sort/ascending/queryIdをまとめて持ち、404時に自動で同条件で再クエリして復旧するクラス）を新設し、Grid/Viewerはこれ経由でのみBackendに問い合わせる。`ws.js`の再接続状態をコールバックで`app.js`に伝搬し、常設バナー`#conn-banner`で表示する。

**Tech Stack:** aiohttp（Backend、変更なし）、素のES Modules JS（Frontend）、pytest + Playwright（E2E、既存の`tests/webui/`規約に準拠）。

**Spec:** [docs/superpowers/specs/2026-09-13-webui-query-resilience-design.md](../specs/2026-09-13-webui-query-resilience-design.md)

## Global Constraints

- コメントは基本書かない。状態はログ・関数名/変数名で伝える（JS側にAppLoggerは無いので該当なし、Python側の変更もこのプランには無い）。
- UIの文言は極限まで簡潔にする。バナー文言は「Backend未応答」のみ。
- 既存コードのパターンに合わせる（`api.js`のfetchラッパー方式、`grid.js`/`viewer.js`のクラス構成、テストは`tests/webui/*_e2e.py`のPlaywrightスタイル）。
- テストに合わせてソースを変えない。テストが不備ならテスト側を直す。
- 実装前後で意図しない挙動変化がないか確認する（既存の`tests/webui`E2Eスイート全体をリグレッションとして必ず流す）。
- venvは`.venv`。テスト実行は`.venv\Scripts\python.exe -m pytest ...`。

---

## Task 1: テストインフラ拡張 + 失敗するE2Eテストを先に書く

**Files:**
- Modify: `tests/webui/conftest.py`
- Modify: `tests/webui/test_viewer_e2e.py`
- Create: `tests/webui/test_connection_banner_e2e.py`

**Interfaces:**
- Consumes: 既存の `webui_base_url`（session-scoped fixture, `tests/webui/conftest.py:33`）、既存の `_open_first(page)` ヘルパー（`tests/webui/test_viewer_e2e.py:1`）。
- Produces: 新規fixture `webui_query_service`（`QueryService`インスタンスを返す、`tests/webui/conftest.py`）。Task 2はこのタスクで追加した2つのテストを green にする。

- [ ] **Step 1: `conftest.py` に `webui_query_service` フィクスチャを追加する**

`tests/webui/conftest.py` の先頭 import ブロックに `QUERY_SERVICE` の import を追加し、`serve()` 内で `QueryService` インスタンスをモジュールレベルの辞書に保存、`webui_base_url` 実行後に取り出す新規フィクスチャを追加する。

`tests/webui/conftest.py` 冒頭の import に1行追加:

```python
from wafer.app.webui.backend.session import QUERY_SERVICE
```

`webui_base_url` フィクスチャ内、`async def serve():` の中身（`tests/webui/conftest.py:66-76`）を次のように変更する（`app = create_app(...)` の直後に1行追加するだけ）:

```python
        async def serve():
            app = create_app(with_events=False, allowed_hosts=allowed_hosts_for(host, port))
            _webui_state["query_service"] = app[QUERY_SERVICE]
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, host, port).start()
            stop = asyncio.Event()
            state["stop"] = stop
            ready.set()
            await stop.wait()
            await runner.cleanup()
```

ファイル冒頭、`DB_NAME, build_webui_dataset` の import の下あたりにモジュールレベルの辞書を追加する:

```python
_webui_state: dict = {}
```

`webui_base_url` フィクスチャの直後（`ready_page` フィクスチャの前）に新規フィクスチャを追加する:

```python
@pytest.fixture(scope="session")
def webui_query_service(webui_base_url):
    return _webui_state["query_service"]
```

（`webui_base_url` を引数に取ることでサーバ起動が先に完了していることを保証する。戻り値自体は使わない。）

- [ ] **Step 2: Viewerのセッション自動復旧テストを追加する**

`tests/webui/test_viewer_e2e.py` の末尾に追記する:

```python
def test_viewer_next_survives_backend_session_loss(ready_page, webui_query_service):
    page = ready_page
    _open_first(page)
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('1/')")

    webui_query_service._sessions.clear()

    page.click("#viewer-next")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('2/')")
```

- [ ] **Step 3: このテストを実行し、現状の実装で失敗することを確認する**

Run: `.venv\Scripts\python.exe -m pytest tests/webui/test_viewer_e2e.py::test_viewer_next_survives_backend_session_loss -v`

Expected: FAIL（`page.wait_for_function` がタイムアウトする。`viewer.js` の `open()` が404を投げっぱなしで caption が `2/` に進まないため）。

- [ ] **Step 4: 接続バナーの新規E2Eテストファイルを作成する**

`tests/webui/test_connection_banner_e2e.py` を新規作成する:

```python
from __future__ import annotations

import asyncio
import socket
import threading

import pytest

pytest.importorskip("playwright.sync_api")

from aiohttp import web

from wafer.app.webui.backend import session
from wafer.app.webui.backend.server import allowed_hosts_for, create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


@pytest.fixture
def restartable_webui_server():
    mp = pytest.MonkeyPatch()
    mp.setattr(session, "list_data_db_names", lambda: [])

    host, port = "127.0.0.1", _free_port()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop, args=(loop,), name="conn-banner-e2e-loop", daemon=True)
    thread.start()

    state: dict = {}

    def start():
        async def _start():
            app = create_app(with_events=False, allowed_hosts=allowed_hosts_for(host, port))
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, host, port).start()
            state["runner"] = runner

        asyncio.run_coroutine_threadsafe(_start(), loop).result(timeout=20)

    def stop():
        async def _stop():
            await state["runner"].cleanup()

        asyncio.run_coroutine_threadsafe(_stop(), loop).result(timeout=20)
        del state["runner"]

    start()

    yield f"http://{host}:{port}", start, stop

    if "runner" in state:
        stop()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=10)
    mp.undo()


def test_connection_banner_shows_on_disconnect_and_hides_on_reconnect(page, restartable_webui_server):
    base_url, start, stop = restartable_webui_server
    page.goto(base_url)
    page.wait_for_selector("#conn-banner", state="attached")
    assert page.eval_on_selector("#conn-banner", "el => el.classList.contains('hidden')")

    stop()
    page.wait_for_function(
        "!document.querySelector('#conn-banner').classList.contains('hidden')",
        timeout=15000,
    )

    start()
    page.wait_for_function(
        "document.querySelector('#conn-banner').classList.contains('hidden')",
        timeout=15000,
    )
```

- [ ] **Step 5: このテストを実行し、現状の実装で失敗することを確認する**

Run: `.venv\Scripts\python.exe -m pytest tests/webui/test_connection_banner_e2e.py -v`

Expected: FAIL（`#conn-banner` 要素が存在しないため `page.wait_for_selector` がタイムアウトする）。

- [ ] **Step 6: 既存のE2Eスイートに影響が無いことを確認する**

Run: `.venv\Scripts\python.exe -m pytest tests/webui -v --deselect tests/webui/test_viewer_e2e.py::test_viewer_next_survives_backend_session_loss --deselect tests/webui/test_connection_banner_e2e.py::test_connection_banner_shows_on_disconnect_and_hides_on_reconnect`

Expected: PASS（今追加した2つの新規テスト以外は全てグリーンのまま）。

- [ ] **Step 7: コミット**

```bash
git add tests/webui/conftest.py tests/webui/test_viewer_e2e.py tests/webui/test_connection_banner_e2e.py
git commit -m "$(cat <<'EOF'
test(webui): add failing e2e tests for session-loss recovery and connection banner

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `QueryClient` の実装 + Grid/Viewer/接続バナーの配線

**Files:**
- Modify: `wafer/app/webui/frontend/js/api.js`
- Create: `wafer/app/webui/frontend/js/query.js`
- Modify: `wafer/app/webui/frontend/js/grid.js`
- Modify: `wafer/app/webui/frontend/js/viewer.js`
- Modify: `wafer/app/webui/frontend/js/ws.js`
- Modify: `wafer/app/webui/frontend/js/app.js`
- Modify: `wafer/app/webui/frontend/index.html`
- Modify: `wafer/app/webui/frontend/css/app.css`
- Test: `tests/webui/test_viewer_e2e.py`, `tests/webui/test_connection_banner_e2e.py`（Task 1で追加済み。ここではpassさせる）

**Interfaces:**
- Consumes: Task 1で追加した2つのE2Eテスト（`webui_query_service._sessions.clear()`、`#conn-banner`セレクタ）。
- Produces: `QueryClient`（`query.js`）— `run(db, filters, sort, ascending)`, `items(offset, limit)`, `aspects()`, プロパティ `db`/`total`/`id`。`connectEvents(onEvent, onStatusChange)`（`ws.js`）— `onStatusChange('open' | 'closed')` を呼ぶ。

- [ ] **Step 1: `api.js` に `ApiError` を追加し、既存の例外を統一する**

`wafer/app/webui/frontend/js/api.js` 全体を次の内容に置き換える:

```javascript
import { load } from './store.js';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function getJson(path, params) {
  const url = params ? `${path}?${new URLSearchParams(params)}` : path;
  const res = await fetch(url);
  if (!res.ok) throw new ApiError(`${path}: ${res.status}`, res.status);
  return res.json();
}

export async function postQuery(db, filters, sort, ascending) {
  const res = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ db, filters, sort, ascending }),
  });
  if (!res.ok) throw new ApiError(`query: ${res.status}`, res.status);
  return res.json();
}

export async function getAspects(queryId) {
  const res = await fetch(`/api/query/${queryId}/aspects`);
  if (!res.ok) throw new ApiError(`aspects: ${res.status}`, res.status);
  return new Float32Array(await res.arrayBuffer());
}

export function getItems(queryId, offset, limit) {
  return getJson(`/api/query/${queryId}/items`, { offset, limit });
}

export function fileUrl(db, path) {
  return `/api/file?${new URLSearchParams({ db, path })}`;
}

export const THUMB_SIZE_DEFAULT = 256;

export function thumbUrl(db, path, size = load('thumbSize', THUMB_SIZE_DEFAULT)) {
  return `/api/thumb?${new URLSearchParams({ db, path, size })}`;
}

export function getKeys(db) {
  return getJson('/api/keys', { db });
}
```

（変更点は `ApiError` クラスの追加と、3箇所の `throw new Error(...)` を `throw new ApiError(..., res.status)` に変えただけ。他は元のまま。）

- [ ] **Step 2: `QueryClient` を新規作成する**

`wafer/app/webui/frontend/js/query.js` を新規作成する:

```javascript
import { getAspects, getItems, postQuery, ApiError } from './api.js';

let nextClientId = 1;

export class QueryClient {
  constructor() {
    this.id = nextClientId++;
    this.db = '';
    this.filters = [];
    this.sort = 'name';
    this.ascending = true;
    this.queryId = '';
    this.total = 0;
  }

  async run(db, filters, sort, ascending) {
    this.db = db;
    this.filters = filters;
    this.sort = sort;
    this.ascending = ascending;
    const result = await postQuery(db, filters, sort, ascending);
    this.queryId = result.query_id;
    this.total = result.total;
    return result;
  }

  async _withRetry(fn) {
    try {
      return await fn(this.queryId);
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 404) throw e;
      const result = await postQuery(this.db, this.filters, this.sort, this.ascending);
      this.queryId = result.query_id;
      this.total = result.total;
      return fn(this.queryId);
    }
  }

  items(offset, limit) {
    return this._withRetry((queryId) => getItems(queryId, offset, limit));
  }

  aspects() {
    return this._withRetry((queryId) => getAspects(queryId));
  }
}
```

- [ ] **Step 3: `grid.js` を `QueryClient` 経由に変更する**

`wafer/app/webui/frontend/js/grid.js` の以下の箇所を変更する。

コンストラクタ（`grid.js:9-27`）の `this.db = ''; this.queryId = '';` を削除し、代わりに `this.client = null;` を追加:

```javascript
  constructor(scrollEl, canvasEl, onOpen) {
    this.scroll = scrollEl;
    this.canvas = canvasEl;
    this.onOpen = onOpen;
    this.client = null;
    this.total = 0;
    this.rows = [];
    this.items = new Map();
    this.pending = new Set();
    this.cells = new Map();
    this._renderScheduled = false;
    this.scroll.addEventListener('scroll', () => this.scheduleRender());
    new ResizeObserver(() => this.relayout()).observe(this.scroll);
    this.canvas.addEventListener('click', (e) => {
      const cell = e.target.closest('.cell');
      if (cell) this.onOpen(Number(cell.dataset.i));
    });
  }
```

`setQuery`（`grid.js:29-38`）のシグネチャを `(client, aspects)` に変更:

```javascript
  setQuery(client, aspects) {
    this.client = client;
    this.aspects = aspects;
    this.total = aspects.length;
    this.items.clear();
    this.pending.clear();
    this.scroll.scrollTop = 0;
    this.relayout();
  }
```

`fillCell`（`grid.js:121-136`）の `this.queryId` 参照と `thumbUrl` の db引数を差し替え:

```javascript
  fillCell(cell, i) {
    const item = this.items.get(i);
    if (!item || cell.dataset.filled === `${this.client.id}:${i}`) return;
    cell.dataset.filled = `${this.client.id}:${i}`;
    cell.title = item.name;
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.src = thumbUrl(this.client.db, item.path);
    img.onerror = () => {
      const label = document.createElement('div');
      label.className = `placeholder ${item.kind}`;
      label.textContent = item.name;
      cell.replaceChildren(label);
    };
    cell.replaceChildren(img);
  }
```

`fetchMissing`（`grid.js:138-158`）を `client.items(...)` 経由・同一性比較に変更し、`getItems` の import を削除:

```javascript
  async fetchMissing(wanted) {
    const pages = new Set();
    for (const i of wanted) {
      if (!this.items.has(i)) pages.add(Math.floor(i / PAGE));
    }
    for (const page of pages) {
      if (this.pending.has(page)) continue;
      this.pending.add(page);
      const client = this.client;
      try {
        const data = await client.items(page * PAGE, PAGE);
        if (client !== this.client) continue;
        for (const item of data.items) this.items.set(item.i, item);
        this.render();
      } catch (e) {
        console.error(e);
      } finally {
        this.pending.delete(page);
      }
    }
  }
```

ファイル冒頭の import 行（`grid.js:1`）を次のように変更する（`getItems` を削除）:

```javascript
import { thumbUrl, THUMB_SIZE_DEFAULT } from './api.js';
```

- [ ] **Step 4: `viewer.js` を `QueryClient` 経由に変更し、失敗時のエラー表示を追加する**

`wafer/app/webui/frontend/js/viewer.js` の以下の箇所を変更する。

コンストラクタ（`viewer.js:7-45`）の `this.db = ''; this.queryId = '';` を `this.client = null;` に変更:

```javascript
  constructor(onIndexChange, onInfo, onSelectFolder) {
    this.el = document.getElementById('viewer');
    this.stage = document.getElementById('viewer-stage');
    this.caption = document.getElementById('viewer-caption');
    this.onIndexChange = onIndexChange;
    this.onSelectFolder = onSelectFolder;
    this.index = -1;
    this.item = null;
    this.total = 0;
    this.client = null;
    this.slideshow = false;
    this.interval = load('slideshowInterval', 3);
    this.timer = null;
    this.token = 0;
    const close = document.getElementById('viewer-close');
    const prev = document.getElementById('viewer-prev');
    const next = document.getElementById('viewer-next');
    const info = document.getElementById('viewer-info');
    setIcon(close, 'close');
    setIcon(prev, 'chevron-left');
    setIcon(next, 'chevron-right');
    setIcon(info, 'info');
    close.addEventListener('click', () => this.close());
    prev.addEventListener('click', () => this.step(-1));
    next.addEventListener('click', () => this.step(1));
    info.addEventListener('click', () => onInfo());
    this.setupMenu();
    this.el.addEventListener('click', (e) => {
      if (e.target === this.el || e.target === this.stage) this.close();
    });
    document.addEventListener('keydown', (e) => {
      if (this.el.classList.contains('hidden')) return;
      if (e.key === 'Escape') this.close();
      else if (e.key === 'ArrowLeft') this.step(-1);
      else if (e.key === 'ArrowRight') this.step(1);
    });
  }
```

`setQuery`（`viewer.js:142-147`）のシグネチャを `(client, total)` に変更:

```javascript
  setQuery(client, total) {
    this.client = client;
    this.total = total;
    this.close();
  }
```

`open`（`viewer.js:149-184`）の `getItems` 直呼びを `this.client.items(...)` に置き換え、try/catchでエラー表示を追加。`fileUrl` の db引数も差し替え:

```javascript
  async open(index, item) {
    if (index < 0 || index >= this.total) return;
    this.clearTimer();
    this.token++;
    this.index = index;
    this.el.classList.remove('hidden');
    if (!item) {
      try {
        const data = await this.client.items(index, 1);
        item = data.items[0];
      } catch (e) {
        if (this.index !== index) return;
        this.caption.textContent = `error: ${e.message}`;
        return;
      }
    }
    if (!item || this.index !== index) return;
    this.item = item;
    this.caption.textContent = `${index + 1}/${this.total}  ${item.name}`;
    const url = fileUrl(this.client.db, item.path);
    if (item.kind === 'image') {
      const img = document.createElement('img');
      img.src = url;
      this.stage.replaceChildren(img);
    } else if (item.kind === 'video') {
      const video = document.createElement('video');
      video.src = url;
      video.controls = true;
      video.autoplay = true;
      video.volume = load('volume', 1);
      video.addEventListener('volumechange', () => save('volume', video.volume));
      this.stage.replaceChildren(video);
    } else {
      const link = document.createElement('a');
      link.href = url;
      link.textContent = `download: ${item.name}`;
      link.download = item.name;
      this.stage.replaceChildren(link);
    }
    this.onIndexChange(index, item);
    this.armSlideshow();
  }
```

ファイル冒頭の import 行（`viewer.js:1`）はそのまま（`fileUrl`/`getItems` のうち `getItems` は使わなくなるので削除）:

```javascript
import { fileUrl } from './api.js';
```

- [ ] **Step 5: `ws.js` に接続状態コールバックを追加する**

`wafer/app/webui/frontend/js/ws.js` 全体を次の内容に置き換える:

```javascript
export function connectEvents(onEvent, onStatusChange) {
  let ws = null;
  let retry = 1000;

  function connect() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${scheme}://${location.host}/ws`);
    ws.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data));
      } catch (err) {
        console.error('invalid event', err);
      }
    };
    ws.onopen = () => {
      retry = 1000;
      if (onStatusChange) onStatusChange('open');
    };
    ws.onclose = () => {
      if (onStatusChange) onStatusChange('closed');
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 30000);
    };
  }

  connect();
}
```

- [ ] **Step 6: `app.js` を `QueryClient` + 接続バナーの配線に変更する**

`wafer/app/webui/frontend/js/app.js` の import 行（`app.js:1-9`）に `QueryClient` を追加:

```javascript
import { getAspects, getJson, postQuery, THUMB_SIZE_DEFAULT } from './api.js';
```
を
```javascript
import { getJson } from './api.js';
import { QueryClient } from './query.js';
```
に変更する（`postQuery`/`getAspects`/`THUMB_SIZE_DEFAULT` は `runQuery`/設定パネルから `QueryClient` や後述の直接参照に置き換わるため、実際に使うものだけ残す。`THUMB_SIZE_DEFAULT` は `setupSettings` 内で使用しているため `./api.js` からの import に残す）。

最終的な import ブロック（`app.js:1-9`）:

```javascript
import { getJson, THUMB_SIZE_DEFAULT } from './api.js';
import { QueryClient } from './query.js';
import { FolderTree } from './foldertree.js';
import { Grid } from './grid.js';
import { KeyPicker } from './keypicker.js';
import { MetaPanel } from './meta.js';
import { Viewer } from './viewer.js';
import { connectEvents } from './ws.js';
import { load, save } from './store.js';
import { setIcon } from './icons.js';
```

`state` オブジェクト（`app.js:11-20`）から未使用になる `queryId`/`total` フィールドを削除する:

```javascript
const state = {
  db: load('db', ''),
  folder: load('folder', null),
  keywords: load('keywords', ''),
  keys: load('searchKeys', []),
  sort: load('sort', 'name'),
  ascending: load('ascending', true),
};
```

`runQuery`（`app.js:74-92`）を `QueryClient` 経由に変更する:

```javascript
let queryToken = 0;
async function runQuery() {
  if (!state.db) return;
  const token = ++queryToken;
  status.textContent = 'searching...';
  try {
    const client = new QueryClient();
    const result = await client.run(state.db, buildFilters(), state.sort, state.ascending);
    if (token !== queryToken) return;
    const aspects = await client.aspects();
    if (token !== queryToken) return;
    grid.setQuery(client, aspects);
    viewer.setQuery(client, result.total);
    status.textContent = `${result.total} files`;
  } catch (e) {
    if (token === queryToken) status.textContent = `error: ${e.message}`;
  }
}
```

接続バナーの配線として、`app.js` 末尾の `connectEvents(...)` 呼び出し（`app.js:211-220`）の直前に banner 要素の取得を追加し、呼び出し自体を2引数版に変更する:

```javascript
const connBanner = document.getElementById('conn-banner');

let refreshTimer = null;
connectEvents(
  (event) => {
    if (event.topic === 'update' && event.db === state.db) {
      keyPicker.invalidate();
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(runQuery, 1500);
    } else if (event.topic === 'db.created' || event.topic === 'db.deleted') {
      location.reload();
    }
  },
  (status) => {
    connBanner.classList.toggle('hidden', status !== 'closed');
  },
);

init();
```

- [ ] **Step 7: `index.html` に接続バナーの要素を追加する**

`wafer/app/webui/frontend/index.html` の `<body>` 直後（`index.html:10-11`）に1行追加する:

```html
<body>
<div id="conn-banner" class="hidden">Backend未応答</div>
<div id="app">
```

- [ ] **Step 8: `app.css` に接続バナーのスタイルを追加する**

`wafer/app/webui/frontend/css/app.css` の末尾に追記する:

```css
#conn-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 200;
  background: #b23b3b;
  color: #fff;
  text-align: center;
  padding: 4px;
  font-size: 12px;
}
#conn-banner.hidden { display: none; }
```

- [ ] **Step 9: Task 1で追加した2つのE2Eテストを実行し、passすることを確認する**

Run: `.venv\Scripts\python.exe -m pytest tests/webui/test_viewer_e2e.py::test_viewer_next_survives_backend_session_loss tests/webui/test_connection_banner_e2e.py -v`

Expected: PASS

- [ ] **Step 10: `tests/webui` 全体をリグレッションとして実行する**

Run: `.venv\Scripts\python.exe -m pytest tests/webui -v`

Expected: 全件PASS（既存のGrid/Viewer/FolderTree/Search/Sidebar E2Eテストが `client` への変更で壊れていないことを確認する）。

- [ ] **Step 11: プロジェクトのテストランナー経由で `webui` レイヤーを最終確認する**

`scripts/test.py` の `LAYERS` には `tests/webui/` 用の `webui` レイヤーが定義されている（`unit`/`smoke`とは別レイヤー）。

Run: `python scripts/test.py webui`

Expected: `tests/test_summary.txt` で `failed: 0`、`error: 0`、CRASHED LAYERSなし。

- [ ] **Step 12: コミット**

```bash
git add wafer/app/webui/frontend
git commit -m "$(cat <<'EOF'
fix(webui): recover viewer navigation after backend session loss, show connection banner

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
