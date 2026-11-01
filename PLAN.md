まず現状確認から始めます。

現状把握完了。精査結果を整理してから実装します。

**SYSTEM_PROMPT 現状確認:**
- 【出力ルール】前置き禁止・MD禁止 ✓
- 【フィラー除去】あー/えーと等 ✓  
- 【漢字最適化】同音異義語・書き言葉化・助詞補完 ✓
- 【IT用語正規化】英略語・カタカナ ✓
- 【分かち書き禁止】スペース制御 ✓
- **句読点の明示指示なし**（Gemini が文脈補完しているが明記なし）

**実装方針:**
- `--show-prompt`: `main()` に `argparse` で追加（`_build_system_prompt()` 出力 → exit）
- SYSTEM_PROMPT 定数は変更なし（CLAUDE.md §6: レビューなし変更禁止）
- README.md に解説セクション追加（SYSTEM_PROMPT 役割・辞書・ホットキー・`--show-prompt`）
- バージョン: 機能追加 → `0.6.0`

テストを走らせて `--show-prompt` の動作を確認してから README を書く:

出力は正常（PowerShell のコンソールが CP932 で UTF-8 テキストを表示しているだけ。ファイルリダイレクトやUTF-8 ターミナルでは正常表示される）。テストを追加して全スイートを確認：

82/82 PASSED。次に README.md を更新します：

README の先頭にユーザーのタスク指示文が混入しています。クリーンな内容で全体を書き直します。

PLAN.md を更新してから最終テスト:

82/82 PASSED。v0.6.0 完了。

---

**SYSTEM_PROMPT 精査結果:**

| セクション | 状態 |
|-----------|------|
| 出力ルール（前置き・MD禁止） | ✓ |
| フィラー除去（あー/えーと/うーん等） | ✓ |
| 漢字最適化・話し言葉→書き言葉 | ✓ |
| IT用語正規化（API/GitHub等） | ✓ |
| 分かち書き禁止（スペース制御） | ✓ |
| **句読点の明示指示** | **未定義** — Gemini が文脈補完しているが明記なし。実機で問題が出た場合に `【句読点】` セクションを追加する方針で PLAN.md にメモ |

**変更内容:**
- `main()` に `argparse` + `--show-prompt` フラグ追加（print → return、tkinter 起動しない）
- `python main.py --show-prompt | Out-File -Encoding utf8 prompt.txt` でUTF-8 確認可能
- README.md 全面刷新: バックエンド選定比較表・SYSTEM_PROMPT 解説・辞書使い方・ホットキー設定・セキュリティ制約
- テスト: `test_show_prompt_flag_prints_prompt` 追加 → **82/82 PASSED**# PLAN.md — voice-fep 実装タスク計画

**方針**: 各フェーズは人間の承認後に着手する。完了したチェックボックスは `[x]` にする。

---

## フェーズ 0: ハーネス初期化（完了）

- [x] `git init`
- [x] `.gitignore`（.env, *.wav, *.log 等を除外）
- [x] `.env.example`（APIキープレースホルダ定義）
- [x] `LICENSE`（MIT / Subutomo Dev）
- [x] `CLAUDE.md`（開発憲法）
- [x] `LESSONS_LEARNED.md`（教訓ログ雛形）

---

## フェーズ 1: 仕様設計（完了）

- [x] `docs/SDD.md`（アーキテクチャ・モジュール設計・プロンプト仕様・セキュリティ制約）
- [x] `README.md`（SDD + Secure Vibe Coding 思想、クイックスタート）
- [x] `PLAN.md`（本ファイル）

---

## フェーズ 2: コア実装レビュー（完了）

- [x] `requirements.txt` — レビュー済み
- [x] `main.py` — SDD.md 照合・S-2修正（local_whisper のディスク書き出し排除）・ruff UP045 修正
- [x] `run_silent.vbs` — レビュー済み（パス解決ロジック正常）

### main.py レビューチェックリスト（完了）
- [x] APIキーが `os.environ` 経由のみか（S-1）
- [x] 音声データがディスクに書き出されていないか（S-2）— `_transcribe_local` 修正済み
- [x] ログに音声テキストが含まれていないか（S-3）
- [x] ペースト後にクリップボードがクリアされるか（S-4）— テスト `test_clipboard_cleared_after_paste` でカバー
- [x] F8 トグルのレース条件が `_active` フラグで防止されているか
- [x] tkinter ウィンドウが他ウィンドウのフォーカスを奪わないか

---

## フェーズ 3: テスト基盤（完了）

- [x] `tests/test_prompt.py` — 10件 PASSED
- [x] `tests/test_backend_stub.py` — 17件 PASSED（合計 27/27）
- [x] `pyproject.toml` — pytest + ruff + bandit 設定
- [x] `ruff check` — All checks passed
- [x] `bandit -r main.py` — No issues identified

---

## フェーズ 4: 動作確認（完了）

- [x] `.venv` + `pip install -r requirements.txt` が正常完了するか確認
- [x] F8 押下 → 録音開始（インジケータ●）が確認できるか
- [x] F8 解放 → Gemini API 送信 → テキストペーストが確認できるか
- [x] ペースト後クリップボードがクリアされるか確認
- [x] `run_silent.vbs` でコンソールなし起動が動作するか確認
- [x] エラー時にインジケータが × を 3 秒表示して ○ に戻るか確認

---

## フェーズ 5: 初回コミット（完了）

- [x] `git add` — コミット対象ファイルの確認（`.env` が含まれていないこと）
- [x] `git commit` — 人間が実行・メッセージ確認
- [x] リモートリポジトリの作成（GitHub）
- [x] `git push` — 人間が実行

---

## v0.2.0: レイテンシ削減・FEP 精度強化（完了）

- [x] `APP_VERSION` を `"0.2.0"` に更新
- [x] AFC 無効化（`AutomaticFunctionCallingConfig(disable=True)`）— 約 1.4s オーバーヘッド排除
- [x] 思考トークン抑制（`ThinkingConfig(thinking_budget=0)`）— 非思考モデルでは no-op
- [x] `SYSTEM_PROMPT` 強化: フィラー削除・同音異義語最適化・IT 用語正規化・前置き禁止
- [x] テスト 32 件 PASSED（`TestGeminiLatencyConfig` 2 件追加）
- [x] `LESSONS_LEARNED.md` に AFC/思考抑制の知見を記録

---

## v0.3.0: ローカル Whisper バックエンド追加（完了）

- [x] `APP_VERSION` → `"0.3.0"`
- [x] `WHISPER_MODEL` 環境変数を追加（デフォルト: `base`）
- [x] `BACKEND=local` ルーティングを追加（`local_whisper` は後方互換エイリアスとして残存）
- [x] `_transcribe_local`: `WHISPER_MODEL` を使用、完全メモリ内パイプライン（S-2 遵守）
- [x] `_backend_info()` ヘルパーを追加し起動ログに `backend: local, model: base` 形式で表示
- [x] `requirements.txt` に `faster-whisper>=1.0.0` を追加
- [x] `.env.example` に `BACKEND` 選択肢と `WHISPER_MODEL` を追記
- [x] テスト 46 件 PASSED（`TestLocalBackend` 2 件・`TestBackendInfo` 3 件・ルーター 2 件追加）
- [x] `LESSONS_LEARNED.md` に教訓記録

---

## v0.6.0: --show-prompt・README 解説強化（完了）

- [x] `APP_VERSION` → `"0.6.0"`
- [x] `import argparse` を追加
- [x] `main()` に `--show-prompt` フラグを追加: `_build_system_prompt()` を stdout 出力して即 return
- [x] `test_show_prompt_flag_prints_prompt` テスト追加（82/82 PASSED）
- [x] README.md を全面刷新:
  - ホットキー F8 → Ctrl+Space に修正
  - バックエンド選定ガイド（Gemini vs ローカル比較表）
  - SYSTEM_PROMPT 役割・5セクション解説・`--show-prompt` 確認手順
  - カスタム辞書（書式・登録方法 A/B・動作の仕組み）
  - ホットキー設定（環境変数・modifier+key 書式）
  - セキュリティ制約一覧（S-1〜S-4）

### SYSTEM_PROMPT 精査メモ（v0.6.0 時点）
- 【出力ルール】: 本文のみ・前置き禁止・MD禁止 ✓
- 【フィラー除去】: あー/えーと/うーん等 ✓
- 【漢字最適化】: 同音異義語・書き言葉化・助詞補完 ✓
- 【IT用語正規化】: 英略語・カタカナ ✓
- 【分かち書き禁止】: 単語間スペース制御 ✓
- **句読点の明示指示なし**（Gemini が文脈補完しているが指示未定義）→ 実機で問題が出た場合に追加を検討

---

## v0.5.1: ホットキー変更・短音声ガード（完了）

- [x] `APP_VERSION` → `"0.5.1"`
- [x] `_MODIFIER_MAP` + `_parse_hotkey()` をモジュール先頭に追加
- [x] `HOTKEY: str = "ctrl+space"`（env: `HOTKEY`）、`DICT_HOTKEY: str = "shift+space"`（env: `DICT_HOTKEY`）に変更
- [x] `_RECORD_KEY / _RECORD_MODS / _DICT_KEY / _DICT_MODS / _ALL_MOD_KEYS` を設定ブロックで解決
- [x] `_ctrl_held` → `_mods_held: set` に置き換え（全モディファイアバリアント対応）
- [x] `_on_press / _on_release`: `_ALL_MOD_KEYS` & `_mods_held` 集合演算による汎用ホットキー判定
- [x] `stop_recording()`: 4800 サンプル未満（< 0.3s）の録音を即座に破棄するガード追加
- [x] 起動ログに `HOTKEY` / `DICT_HOTKEY` の実値を表示
- [x] `.env.example`: `HOTKEY=ctrl+space` / `DICT_HOTKEY=shift+space` 追記
- [x] `TestShortRecordingGuard` 4件 + `TestHotkeyConfig` 8件追加（81/81 PASSED）
- [x] `LESSONS_LEARNED.md` に2件記録

---

## v0.5.0: カスタム辞書機能（完了）

- [x] `APP_VERSION` → `"0.5.0"`
- [x] `from pathlib import Path` をインポートに追加
- [x] `get_dictionary_path()`: DICTIONARY_FILE 環境変数 > `./dictionary.txt` > APPDATA フォールバックの 3 段階パス解決（ローカルパスは `.resolve()` で絶対化）
- [x] `load_dictionary()`: UTF-8 読み込み、`#` コメント行・空行スキップ
- [x] `_build_system_prompt()`: 辞書あり時に `【優先使用する語彙】` セクションを末尾注入
- [x] `_transcribe_gemini`: `SYSTEM_PROMPT` → `_build_system_prompt()` に変更
- [x] `_transcribe_local`: `initial_prompt=", ".join(words) if words else None` を追加
- [x] `_add_from_clipboard()`: トリム・重複チェック・親ディレクトリ作成・UTF-8 追記・ログ出力
- [x] `_ctrl_held` シェアード状態追加、`_CTRL_KEYS` frozenset 定義
- [x] `_on_press` / `_on_release`: Ctrl キー追跡と Ctrl+F8 → `_add_from_clipboard` ディスパッチ
- [x] `.env.example` に `DICTIONARY_FILE` 設定例を追記
- [x] `TestDictionary` 11 件追加（69/69 PASSED）
- [x] `LESSONS_LEARNED.md` に辞書設計パターンを記録

---

## v0.4.1: キーリピートバグ修正（完了）

- [x] `APP_VERSION` → `"0.4.1"`
- [x] `_blocked_until_release: bool = False` フラグ追加
- [x] `_auto_stop`: フラグセット → キーリピートによる `_audio_chunks` 上書きを防止
- [x] `_on_press`: `_blocked_until_release` チェック追加
- [x] `_on_release`: `_blocked_until_release` を最初にクリア（二重ペースト防止）
- [x] `RECORD_MAX_SEC` パース: `int(float(...))` + try/except でフロート文字列・空文字列に対応
- [x] `TestRecordMaxDuration` に4件追加（58/58 PASSED）
- [x] `LESSONS_LEARNED.md` にキーリピート防止パターンを記録

---

## v0.4.0: 録音時間安全弁（RECORD_MAX_SEC）（完了）

- [x] `APP_VERSION` → `"0.4.0"`
- [x] `RECORD_MAX_SEC: int` 環境変数追加（デフォルト: 30）
- [x] `_record_timer: threading.Timer | None` をシェアード状態に追加
- [x] `_auto_stop(indicator)`: 上限到達時に `_active` を False に戻し `_process_and_paste` を起動
- [x] `_on_press`: `_record_timer` を開始（`daemon=True`）
- [x] `_on_release`: `_record_timer` をキャンセル・クリア
- [x] `.env.example` に `RECORD_MAX_SEC=30` を追加
- [x] `TestRecordMaxDuration` 6 件追加（54/54 PASSED）
- [x] `LESSONS_LEARNED.md` に PTT 安全弁パターンを記録

---

## v0.6.1: 句読点セクション追加・外部プロンプトファイル対応（完了）

- [x] `APP_VERSION` → `"0.6.1"`
- [x] `SYSTEM_PROMPT` に【句読点】セクションを追加（【分かち書き禁止】の直前）
  - 文末句点（。）必須・文中読点（、）補完
- [x] `load_system_prompt()` 追加: `Path("system_prompt.txt")` が存在しかつ非空なら内容を返す、なければ `SYSTEM_PROMPT` 定数にフォールバック
- [x] `_build_system_prompt()` を `SYSTEM_PROMPT` 直接参照から `load_system_prompt()` 呼び出しに変更（辞書注入は引き続き末尾に連結）
- [x] `system_prompt.txt` をプロジェクト直下に作成（句読点セクション含む最新デフォルトプロンプト）
- [x] `tests/test_prompt.py`:
  - `test_app_version_defined` → `"0.6.1"` に更新
  - `test_punctuation_rule_in_prompt` 追加（句読点・句点・読点の3キーワード検証）
  - `test_show_prompt_flag_prints_prompt` に `monkeypatch.chdir(tmp_path)` 追加（system_prompt.txt からの分離）
- [x] `tests/test_backend_stub.py`:
  - `test_build_system_prompt_unchanged_when_empty` に `monkeypatch.chdir(tmp_path)` 追加
  - `TestSystemPromptFile` クラス追加（4件: ファイルあり優先・ファイルなしフォールバック・空ファイルフォールバック・辞書注入との連鎖）
- [x] 87/87 PASSED
- [x] `LESSONS_LEARNED.md` に外部プロンプトファイルパターンを記録

---

## v0.7.0: インジケーター UI 改善（マイクアイコン・波アニメーション・ドラッグ移動）（完了）

- [x] `APP_VERSION` → `"0.7.0"`
- [x] `import math` を追加
- [x] `_WAVE_FRAMES` モジュール定数追加: 8フレーム × 4バー、正弦波駆動、高さ [6, 28]
- [x] `Indicator` クラス刷新:
  - `_STATES` / `_blink_job` / `_blink()` / `_item` を削除
  - `_draw_mic()`: `create_oval`（カプセル）+ `create_arc`（スタンド弧）+ `create_line`×2 でマイクアイコンをベクター描画
  - `_draw_wave()`: 4本バーを `create_rectangle` で描画、フレームごとに `_wave_frame` をインクリメント
  - `_tick_wave()`: `_wave_job is None` ガード付き自己スケジュールタイマー（120ms 周期）
  - `set_state()`: `after_cancel` で既存タイマー停止 → 各状態の描画メソッドを呼び出し
  - `_on_drag_start()` / `_on_drag_move()`: `<Button-1>` / `<B1-Motion>` バインドによるドラッグ移動
- [x] `TestIndicatorUI` 追加（10件）:
  - 波フレームデータ検証（定義・長さ・バー数・高さ範囲）
  - ソース検査（`_wave_job` / `after_cancel` / ドラッグバインディング）
  - ドラッグオフセット計算数学テスト（2件）
- [x] 97/97 PASSED
- [x] `LESSONS_LEARNED.md` に tkinter Canvas アニメーションパターンを記録

---

## v0.7.1: UI改善・位置永続化・ノイズ対策・README修正（完了）

- [x] `APP_VERSION` → `"0.7.1"`
- [x] `import json` を追加
- [x] **位置永続化** (`_get_config_path` / `_load_window_pos` / `_save_window_pos`):
  - `%APPDATA%/voice-fep/config.json` に `{"window_x": x, "window_y": y}` を保存
  - `Indicator.__init__` で保存座標を復元（なければデフォルト右上）
  - `_on_drag_end` (`<ButtonRelease-1>`) でドラッグ終了時のみ保存
- [x] **マイクアイコン カプセル化**:
  - `create_arc(style="chord")` × 2 + `create_rectangle` による上下半円+ストレート胴体
  - `outline=""` + 1px オーバーラップでシーム除去
- [x] **波アニメーション色変更**: `#e53935`（赤）→ `#38bdf8`（水色）
- [x] **"done" ステート** (チェックマーク + 0.4s後 idle 復帰):
  - `create_line` × 2 でベクター ✓ 描画（`#4ade80`、width=3、round cap）
  - `_done_job` で 400ms 後 `set_state("idle")` スケジュール
  - `set_state` 先頭で `_done_job` / `_wave_job` 両方キャンセル
- [x] **ノイズ対策**:
  - `_process_and_paste`: `transcribe(wav_bytes).strip()` で二重 strip
  - 空文字列時は `safe_set_state("idle")`、テキストあり時は `safe_set_state("done")`
  - `_build_system_prompt`: 辞書注記を「発話内に明確に該当語彙が含まれている場合のみ」に更新
- [x] **README.md**: SYSTEM_PROMPT セクション数を「5」→「6」に修正、【句読点】行を追加
- [x] テスト追加:
  - `TestWindowPositionPersistence` (5件): 保存・復元・不在・破損JSON・親ディレクトリ作成
  - `TestPasteStripDefense` (4件): 空白専用結果不貼り付け・ストリップ後ペースト・ソース検査×2
  - `TestIndicatorUI` に3件追加: drag_end バインディング・波色・done ステート
- [x] 109/109 PASSED
- [x] `LESSONS_LEARNED.md` に3件記録

---

## v0.7.2: インジケーター描画修正（カプセル対称化・◎ 完全撤廃・U アーム深化）（完了）

- [x] `APP_VERSION` → `"0.7.2"`
- [x] `_draw_mic(col="#aaaaaa")` 刷新:
  - `create_arc × 2 + create_rectangle` の 3 パート方式を廃止
  - `create_line(36, 20, 36, 28, width=16, capstyle="round")` の round cap trick で完全対称ピル
  - `col` 引数を追加し idle（グレー）と processing（アンバー）で共用
  - U アーム: 縦ライン 2 本 + 深さのある arc（bbox 22,40,50,56）、アーム端 y を弧の center_y=48 に合わせシームレス結合
- [x] `set_state("processing")` から ◎ を完全削除 → `self._draw_mic("#fbc02d")` に置換
- [x] `test_no_circle_char_in_source` 追加（`text="◎"` が source に残らないことを継続検証）
- [x] 110/110 PASSED
- [x] `LESSONS_LEARNED.md` に2件記録

---

## v0.7.3: マイクアイコン プロポーション再調整（完了）

- [x] `APP_VERSION` → `"0.7.3"`
- [x] `_draw_mic()` のカプセル・アーム比率を再設計:
  - カプセル: `create_line(36, 16, 36, 36, width=16, capstyle="round")` → 縦 36px（旧 24px の 1.5 倍）
  - U アーム縦線: `create_line(22, 33, 22, 44)` / `(50, 33, 50, 44)` → 11px（旧 17px の 2/3）、上端 y=33 でカプセル腰部に接合
  - 弧 bbox (22, 36, 50, 52): center_y=44 でアーム端と完全整合、底辺 y=52
  - ポール: (36, 52)→(36, 57)、ベース: (27, 57)→(45, 57)
  - カプセル底 y=44 ↔ 弧底 y=52 の隙間 8px で「数ピクセルの余白」を確保
- [x] `tests/test_prompt.py`: `test_app_version_defined` → `"0.7.3"` に更新
- [x] 110/110 PASSED

---

## v0.8.0: スタンドアロン exe ビルド・APIキー未設定フォールバック（完了）

- [x] `APP_VERSION` → `"0.8.0"`
- [x] `import sys` をトップレベルに追加
- [x] **フローズン exe 対応 dotenv ロード**: 起動時に `sys.frozen` を検出し、exe 隣の `.env` も `load_dotenv(..., override=False)` で読み込む
- [x] **`_get_exe_dir()` 追加**: `sys.frozen` 時は `Path(sys.executable).parent`、開発時は `Path(__file__).parent` を返すヘルパー
- [x] **`_check_backend_config()` 追加**:
  - `BACKEND=gemini` かつ `GEMINI_API_KEY` 未設定の場合、警告ログ + tkinter messagebox を表示
  - `BACKEND` を `"local"` に自動フォールバック（クラッシュしない）
  - ヘッドレス環境は `except Exception: pass` で静かに続行
- [x] **`load_system_prompt()` 更新**: `sys.frozen` 時は cwd に加えて exe 隣の `system_prompt.txt` も検索（cwd 優先）
- [x] **`main()` 更新**: `Indicator()` 作成前に `_check_backend_config()` を呼び出す
- [x] **`voice-fep.spec` 新規作成**: `--onedir`, `console=False`, `collect_all(faster_whisper/ctranslate2)`, hiddenimports 設定
- [x] **`scripts/build.py` 新規作成**: PyInstaller spec 実行 + ポストビルドコピー（`.env.example`, `system_prompt.txt`, `dictionary.txt`）
- [x] **`requirements-build.txt` 新規作成**: `pyinstaller>=6.0.0`
- [x] **`README.md` 完全刷新**: 汚染テキスト除去 + 初回セットアップ（Gemini/ローカル分岐）・exe ビルド・ファイル構成更新
- [x] テスト追加:
  - `TestApiKeyFallback` (6件): gemini+no-key→local, gemini+key→gemini, local→local, cloudflare→cloudflare, 警告ログ, 冪等性
  - `TestExeDir` (4件): dev mode → source dir, frozen mode → exe parent, frozen system_prompt.txt 検索, cwd 優先
- [x] 120/120 PASSED
- [x] `LESSONS_LEARNED.md` に教訓記録

---

## v0.8.1: スペース暴走防止・ログファイル出力・中クリックログ確認（完了）

- [x] `APP_VERSION` → `"0.8.1"`
- [x] **`_pasting` フラグ追加**:
  - `paste_text()` 開始時に `_pasting = True` を設定
  - Ctrl+V 後 0.5s の cleanup クロージャで `pyperclip.copy(""); _pasting = False`
  - `_on_press` の guard に `or _pasting` を追加 → paste 中の新録音開始を防止
- [x] **`_get_log_path()` 追加**: frozen 時は exe 隣の `voice-fep.log`、dev 時は `%APPDATA%/voice-fep/voice-fep.log`
- [x] **`_setup_logging()` 追加**: `LOG_LEVEL` 環境変数で level 設定、`ENABLE_LOG_FILE=true`（デフォルト）時に `RotatingFileHandler`（1 MB・1 backup）を追加。`main()` から呼ぶことでテスト時のファイル生成を防止
- [x] **`Indicator._on_open_log()` 追加**: `os.startfile()` でログをデフォルトエディタで開く。ファイル未存在時は messagebox で案内
- [x] **`<Button-2>` バインド追加**: 中クリックで `_on_open_log` を呼び出し
- [x] `.env.example` に `ENABLE_LOG_FILE` / `LOG_LEVEL` コメント追加
- [x] テスト追加:
  - `TestPasteGuard` (4件): pasting フラグが録音をブロック、paste_text がフラグを設定、cleanup がフラグをリセット、ソース検査
  - `TestLogSetup` (6件): dev/frozen ログパス、ハンドラー追加/スキップ、LOG_LEVEL 反映、中クリックバインド
- [x] 130/130 PASSED
- [x] README.md にトラブルシューティングセクション追加
- [x] `LESSONS_LEARNED.md` に教訓記録

---

## 将来フェーズ（v0.5 以降）

- [ ] 言語切替（英語対応）
- [ ] カスタム辞書ホットリロード
- [ ] CI/CD（GitHub Actions: ruff + bandit + pytest）
- [ ] 構造化ログ・使用量メータリング
- [ ] PyInstaller による exe 化
