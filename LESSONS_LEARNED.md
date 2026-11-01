# LESSONS_LEARNED.md — 教訓・失敗ログ

タスク開始前に必ず読む。同じ失敗を繰り返さないためのログ。  
新しい教訓が得られたら、その場で追記する。

---

## 記録フォーマット

```
### [日付] タイトル（何が起きたか）

**状況**: どのような文脈で発生したか
**失敗内容**: 何をしてしまったか / 何がうまくいかなかったか
**根本原因**: なぜ起きたか
**対策**: 次回どうすれば防げるか
**影響ファイル**: 変更が必要だったファイル
```

---

## 教訓一覧

### [2026-10-31] 計画なしに実装を先行させた

**状況**: プロジェクト初期構築タスクにて  
**失敗内容**: SDD+Secure Vibe Coding の手順（計画→承認→実装）を確認せず、
CLAUDE.md・PLAN.md・LESSONS_LEARNED.md の作成を飛ばして
main.py 等の実装コードを先に生成した  
**根本原因**: ユーザーの指示の優先順位（計画フェーズ先行）を読み飛ばした  
**対策**:
- タスク開始前に必ず CLAUDE.md のチェックリスト（§0）を実行する
- 「計画確認後に実装」という明示的な STOP 指示を見落とさない
- 計画ドキュメント（PLAN.md）が存在しない状態ではコードを生成しない  
**影響ファイル**: CLAUDE.md, PLAN.md, LESSONS_LEARNED.md

---

### [2026-10-31] セキュリティテストの正規表現が区切り線（`---`）を誤検知

**状況**: `test_no_hardcoded_api_key_pattern` でハードコードキーを検出する正規表現 `[A-Za-z0-9_\-]{39}` が、main.py のコメント区切り線（`-` × 39文字）にマッチして誤 FAIL した  
**失敗内容**: 1回目の pytest で 25/26 FAIL  
**根本原因**: APIキーに含まれない `-` 単独の繰り返しをパターンに含めていた  
**対策**: 英数字 `[A-Za-z0-9]{32,}` のみに絞り、コメント行はスキップするロジックに修正（3回ループ以内の1回目で解決）

### [2026-10-31] `_transcribe_local` が S-2（音声ディスク書き出し禁止）に違反

**状況**: SDD.md vs main.py の照合レビュー時に発見  
**失敗内容**: `tempfile.NamedTemporaryFile` で `.wav` をディスクに書き出してから faster-whisper に渡していた  
**根本原因**: faster-whisper がファイルパスのみ受け付けると誤解していた（実際は `np.ndarray` も受け付ける）  
**対策**: WAV bytes → `io.BytesIO` → `wavfile.read()` → `np.float32` 変換 → `model.transcribe(audio_float32, sampling_rate=...)` の完全メモリ内パイプラインに変更

### [2026-11-01] Gemini モデル名の指定ミスによる HTTP 404

**状況**: 実機動作テスト（フェーズ4）で Gemini API 呼び出し時に 404 発生  
**失敗内容**: `GEMINI_MODEL` のデフォルト値を `gemini-2.5-flash` と設定していたが、API 上に該当モデルが存在しなかった  
**根本原因**: 実際の API リリース状況を確認せず「最新っぽい名前」を推測で設定した  
**対策**: デフォルト値を実績ある `gemini-1.5-flash` に変更。モデル名を変更する際は必ず公式ドキュメントか API の実機確認を行い、`.env` の `GEMINI_MODEL` で上書きできる設計を活かして先に検証する  
**影響ファイル**: `main.py`, `.env.example`, `docs/SDD.md`

### [2026-11-01] モデル名の誤指定による 404 が連続し、起動ログが原因特定を遅らせた

**状況**: `gemini-2.5-flash` → `gemini-1.5-flash` と修正したにもかかわらず、実機で再度 404 が発生した  
**失敗内容**: 「どのモデル名で API を呼んでいるか」を起動時ログに出していなかったため、.env の設定が反映されているかの確認に手間がかかった。また `models/` プレフィックス付きで指定した場合の挙動を考慮していなかった  
**根本原因**: モデル名の実API可用性を事前検証せず推測で設定していた。起動ログが「ready」のみで適用設定を可視化していなかった  
**対策**:
- 起動ログに `APP_VERSION` と `_normalize_model(GEMINI_MODEL)` を明示（例: `voice-fep v0.1.0 ready (model: gemini-2.0-flash)`）
- `models/` プレフィックスを自動除去する `_normalize_model()` を追加し、ユーザーのどの設定値でも動作するよう正規化
- デフォルトモデルを `gemini-2.0-flash` に更新（2025年リリースの安定版）
- 今後のモデル変更時は、変更後の最初の起動ログで適用モデル名を目視確認してから本番利用すること  
**影響ファイル**: `main.py`, `.env.example`, `docs/SDD.md`, `tests/test_prompt.py`

### [2026-11-01] _normalize_model() による過剰なプレフィックス除去が 404 を引き起こした

**状況**: `models/` プレフィックスを自動除去する `_normalize_model()` を追加したが、実機で再度 404 が発生  
**失敗内容**: SDK が期待するモデル識別子を意図せず変形させた。`models/gemini-2.0-flash` → `gemini-2.0-flash` と変換した結果、APIが認識できない文字列になるケースが生じた  
**根本原因**: SDK の内部挙動を推測で「補正」しようとした。SDKの公式ドキュメントや `models.list()` で確認した識別子をそのまま渡すのが正しい  
**対策**: `_normalize_model()` を削除し、`GEMINI_MODEL` 環境変数の値を SDK に直接渡す。モデル名を変更する際は `models.list()` 等で取得できた識別子文字列をそのまま `.env` に設定し、加工・推測しない  
**影響ファイル**: `main.py`（関数削除）, `tests/test_prompt.py`（関連テスト削除）

### [2026-11-01] LLM を FEP として使う際のレイテンシ削減策（AFC 無効化・思考抑制）

**状況**: v0.2.0 のレスポンス速度改善タスク  
**知見**:
- `AutomaticFunctionCallingConfig(disable=True)` を `GenerateContentConfig` に渡すことで、AFC の初期化オーバーヘッド（約 1.4 秒）を排除できる。ツール呼び出しを使わない純粋な書き起こし用途では常に無効化すべき。
- `ThinkingConfig(thinking_budget=0)` で思考トークンを抑制できる。思考モデル以外では no-op だが、将来モデルを変更した際も設定しておくことで意図しない遅延を防げる。
- FEP 用途では「速さ」と「正確さ」のトレードオフが重要。AFC・思考無効化は正確さを損なわずレイテンシのみを削減できる有効な手段。  
**How to apply**: `_transcribe_gemini` の `GenerateContentConfig` に両設定を常に含める。モデル変更時も削除しない。

### [2026-11-01] thinking_config / AFC 無効化パラメータがモデルによって 400 を引き起こす

**状況**: v0.2.0 実機テストで `gemini-flash-lite-latest` に対し `ThinkingConfig(thinking_budget=0)` および `AutomaticFunctionCallingConfig(disable=True)` を渡したところ 400 Bad Request が発生  
**失敗内容**: 「どのモデルでも no-op になる」と想定したパラメータが、実際には非対応モデルでは不正引数として弾かれた  
**根本原因**: SDK や各モデルのパラメータ対応状況を公式ドキュメントで確認せずに追加した。エラーログが `type(exc).__name__` のみで詳細を出力しておらず、原因特定に時間がかかった  
**対策**:
- `GenerateContentConfig` は `system_instruction` のみの最小構成を基本とし、追加パラメータは対応モデル・SDK バージョンを確認してから導入する
- エラーログは `"%s: %s", type(exc).__name__, exc` 形式で例外メッセージ本文まで出力する（API エラーの場合は HTTP ステータスとレスポンス本文が含まれる）
- `thinking_config` / AFC 設定は現時点では除外。将来再導入する場合は統合テストで実機確認してから追加する  
**影響ファイル**: `main.py`, `tests/test_prompt.py`

### [2026-11-01] 音声認識 API のレイテンシ短縮には 16kHz モノラル化が有効

**状況**: v0.2.0 レスポンス速度改善タスクにて音声キャプチャ仕様を見直した  
**知見**:
- 16kHz モノラル int16 はSTT API向けの最小ペイロード構成。44.1kHz ステレオに対して転送量が約 1/5 になりアップロード時間が削減される。
- 今回のコードはすでに最適値（`SAMPLE_RATE=16000, channels=1, dtype="int16"`）が設定されていた。将来のリファクタリングで誤って変更されないよう `TestAudioCaptureSpec` でロックした。
- `time.perf_counter()` で API 呼び出し前後を挟むことで、改善効果を数値ログ（`"transcription took X.XXs"`）で継続観察できるようにした。  
**How to apply**: 音声設定の変更は `TestAudioCaptureSpec` が即座に検知する。タイミングログは実機で数回計測して平均を LESSONS_LEARNED に記録すると将来の比較基準になる。

### [2026-11-01] LLM 音声整形時の分かち書き防止と修正ごとのバージョンインクリメント

**状況**: v0.2.0 実機テストで「これ まだ バージョン が 上がっ て ない の ?」のような分かち書き出力が発生。また APP_VERSION が据え置きのまま修正が重なった  
**失敗内容**:
1. SYSTEM_PROMPT に分かち書き禁止ルールがなかったため、モデルが形態素解析結果をそのまま空白区切りで出力した
2. コード修正のたびにバージョンをインクリメントするルールが CLAUDE.md に定義されていなかった  
**対策**:
- SYSTEM_PROMPT の末尾に「分かち書き禁止」セクションを追加し、具体的な NG 例（「これ まだ バージョン が ...」）を明示する
- CLAUDE.md §0a にバージョンインクリメント原則（バグ修正→パッチ / 機能追加→マイナー / 破壊的変更→メジャー）を追加し、コード変更時の必須手順とする
- 起動ログに `vX.Y.Z` を表示しているため、バージョンを上げ忘れると実機起動時に即座に気づける  
**影響ファイル**: `main.py`, `CLAUDE.md`, `tests/test_prompt.py`

### [2026-11-01] ローカル Whisper による低レイテンシ化とメモリ安全性の担保

**状況**: v0.3.0 で faster-whisper をローカルバックエンドとして実装  
**知見**:
- `faster_whisper.WhisperModel.transcribe()` は `np.ndarray` を直接受け付けるため、ディスクへの `.wav` 書き出しが不要（S-2 遵守）
- `io.BytesIO` → `wavfile.read()` → `int16 → float32` 変換で完全なメモリ内パイプラインが実現できる
- `base` モデル（約 150MB）は日本語で 0.5〜1 秒未満の認識が可能。`small` モデルは精度が上がるが 2〜3 秒かかる
- `patch("faster_whisper.WhisperModel", ...)` は当該パッケージが未インストールだと `ModuleNotFoundError` になる。`patch.dict(sys.modules, {"faster_whisper": fake_module})` でパッケージ不要のテストが実現できる（今回の教訓）  
**How to apply**: ローカルバックエンドのテストは `_fake_faster_whisper_module()` ヘルパーを使いパッケージなしでモック注入する。

### [2026-11-01] faster-whisper の WhisperModel.transcribe() に sampling_rate 引数は存在しない

**状況**: v0.3.0 の BACKEND=local 実機テストで `TypeError: WhisperModel.transcribe() got an unexpected keyword argument 'sampling_rate'` が発生  
**失敗内容**: `model.transcribe(audio_float32, language="ja", sampling_rate=SAMPLE_RATE)` と書いていたが、`transcribe()` は `sampling_rate` を受け付けない  
**根本原因**: faster-whisper は内部で常に 16kHz として処理するため、呼び出し側でサンプルレートを指定する仕組みがない。公式 API を確認せず引数を追加した  
**対策**: `sampling_rate=SAMPLE_RATE` を削除し `model.transcribe(audio_float32, language="ja")` のみで呼び出す。テストのモック `transcribe()` シグネチャも合わせて修正した  
**影響ファイル**: `main.py`（引数削除）, `tests/test_backend_stub.py`（モックシグネチャ修正）

### [2026-11-01] モックシグネチャ不整合の防止と自己規律ガードレール

**状況**: v0.3.0/0.3.1 を通じて「存在しない引数を渡すミス」「バージョン上げ忘れ」が人間の指摘で発覚した  
**知見・対策**:
1. **AST 静的解析テスト（`TestWhisperAPICompatibility`）**: `inspect.signature` + AST で「ソースコードが実際に渡している kwarg」と「ライブラリの実シグネチャ」を比較する軽量テストを追加した。`pytest tests/...::TestWhisperAPICompatibility` 1 回で不正引数を即検出できる
2. **フォールバック付き設計**: `faster_whisper` が未インストールの CI 環境では `pytest.skip` でスキップし、インストール済み環境では実シグネチャチェックを実行するため、両環境で壊れない
3. **CLAUDE.md §0a B 項**: 外部ライブラリの引数を追加・変更するときは `inspect.signature()` または公式ドキュメントで事前確認することをルール化。推測で書かない  
4. **バージョン上げ忘れ防止**: CLAUDE.md §0a A 項に「コミット前の自己点検」として明記。テスト `test_app_version_defined` が常に最新バージョンを検証するため、上げ忘れたまま pytest を通すことができない  
**How to apply**: 新しい外部ライブラリを追加する際は同様の `TestXxxAPICompatibility` クラスをその場で追加する。

### [2026-11-01] Push-to-Talk 安全弁タイマーの実装パターン

**状況**: v0.4.0 で `RECORD_MAX_SEC`（録音時間上限）を実装  
**知見**:
- `threading.Timer(RECORD_MAX_SEC, _auto_stop, args=(indicator,))` を `_on_press` で起動し、`_on_release` で `timer.cancel()` するパターンが PTT の安全弁として有効
- `_auto_stop` は `_active` フラグを確認してから処理する二重実行ガードが必須（`_on_release` との競合防止）
- タイマーを `_record_timer` グローバルに保持し、解放後は必ず `None` に戻すことで次回録音が安全に開始できる
- タイマースレッドは `.daemon = True` にしておくことでプロセス終了時に自動回収される
- 上限到達時のログは `"recording stopped: reached max duration (%ds)"` の形式で秒数を含めると .env 変更時の動作確認が容易  
**How to apply**: PTT 操作を持つ機能では常に「押しっぱなし防止タイマー」を実装し、`_active` フラグとセットで管理する。

### [2026-11-01] 上限タイマー発火時のキーリピートによるデータ消去

**状況**: v0.4.0 の実機テストで「recording stopped: reached max duration (30s)」直後に「recording started」→「no audio captured」が連続発生した  
**失敗内容**: `_auto_stop` が `_active=False` にした直後、OSのキーリピートイベントが `_on_press` を再呼び出しし、`_audio_chunks` がリセットされた。`_process_and_paste` が `stop_recording()` を呼んだ時には空リストになっており文字起こしがゼロに  
**根本原因**: PTT の「上限到達後」と「物理キーリリース前」の区間を識別するフラグが存在しなかった。`_active=False` だけでは新規録音を防げない  
**対策**:
- `_blocked_until_release: bool = False` フラグを追加
- `_auto_stop` でセット → `_on_press` でブロック → `_on_release` でクリアの三点セットで管理
- `_on_release` は `_blocked_until_release` を最初にチェックし、True なら即 `return`（`_process_and_paste` の二重起動防止）
- env var `RECORD_MAX_SEC` は `int(float(...))` + try/except で float 文字列・空文字列を安全に処理  
**How to apply**: PTT 機能に上限タイマーを追加する場合、`_active` フラグだけでなく必ず「リリースまでのブロックフラグ」とセットで実装する。

### [2026-11-01] フォールバック付き辞書パス設計と LLM/Whisper へのプロンプト注入

**状況**: v0.5.0 でカスタム辞書機能を実装  
**知見**:
1. **パス解決の優先順位**: 環境変数 > カレントディレクトリ > APPDATA フォールバック の 3 段階設計は、開発中（`./dictionary.txt`）・ポータブル運用（`DICTIONARY_FILE=`）・常駐インストール（`APPDATA`）いずれにも対応できる。ローカルパスは必ず `.resolve()` で絶対パスに変換すること（テストで `chdir` した際の相対パス比較ミスを防ぐ）。
2. **Gemini への注入**: `_build_system_prompt()` で実行時に辞書を読み込み `【優先使用する語彙】` セクションを末尾に追加する。`SYSTEM_PROMPT` 定数は変更しないため、辞書なしの場合は元のプロンプトをそのまま返す。
3. **faster-whisper への注入**: `initial_prompt` 引数（`Optional[str]`）に単語リストをカンマ区切りで渡す。単語がない場合は `None` を渡す（空文字列は挙動が不定なため）。`initial_prompt` を明示的に kwarg として書くことで `TestWhisperAPICompatibility` の AST チェックが有効に機能する。
4. **Ctrl+F8 クイック追加**: `_add_from_clipboard()` はキーリスナースレッドから呼ばず必ず `threading.Thread` 経由で実行する。追記前に `path.parent.mkdir(parents=True, exist_ok=True)` で APPDATA 下のディレクトリを作成する。重複チェックは `load_dictionary()` の返却リストで行う。  
**How to apply**: 辞書は推論ごとに再読み込みされるため、Ctrl+F8 で追記した単語は次回の F8 録音から即座に有効になる。

### [2026-11-01] 0.3秒未満ガードによる Whisper ハルシネーション・誤爆防止

**状況**: v0.5.1 で実装。Ctrl+Space を「押してすぐ離す」操作で Whisper が無音・超短音声に対してハルシネーション出力を生成する問題を防止する  
**知見**:
- `int(0.3 * SAMPLE_RATE) = 4800 samples` をガード閾値として `stop_recording()` に配置するのが最適（サンプル数は既に確定しており WAV 変換前に確認できる）
- 閾値は `<`（strict less-than）: 4800 サンプル（ちょうど 0.3s）は処理対象。4799 以下は破棄
- `"recording ignored: duration too short (< 0.3s)"` のログメッセージで「文字起こしをスキップした」ことをオペレータが即座に判断できる
- `_process_and_paste()` は既に `stop_recording()` の戻り値が None の場合に idle へ戻るルートを持つため、ガードの実装は `stop_recording()` への1行追加のみで済んだ  
**How to apply**: 音声入力系は必ず「極小録音の破棄閾値」を `stop_recording()` 内に持たせる。LLM/Whisper への呼び出しコストとハルシネーションリスクを考慮して閾値は 0.3〜0.5 秒が妥当。

### [2026-11-01] 複合ホットキー対応の汎用設計（modifier + trigger キー）

**状況**: v0.5.1 で F8 単押しから Ctrl+Space/Shift+Space の組み合わせホットキーへ移行  
**知見**:
- `_MODIFIER_MAP` で ctrl/shift/alt それぞれのバリアント（`ctrl`, `ctrl_l`, `ctrl_r`）を frozenset にまとめ、`_parse_hotkey("ctrl+space")` で `(trigger_key, modifier_frozenset)` に分解するパターンが再利用しやすい
- モディファイアの保持状態は `_mods_held: set` に個別キーオブジェクトを保持し、判定は `required_mods & _mods_held` の集合演算で行う（`issubset` ではなく交差の有無）
- `_on_press` では dict ホットキーを先にチェックしてから record ホットキーを確認する（両者が同じトリガーキーを使う場合の優先順位）
- `_on_release` はトリガーキーのリリースのみで録音停止を判定する（モディファイアの解放は無視）  
**How to apply**: 新しいホットキーを追加する場合は `_MODIFIER_MAP` と `_parse_hotkey` を共有し、環境変数名を追加するだけで対応できる。

### [2026-11-01] 外部ファイルによる SYSTEM_PROMPT オーバーライドと空ファイルフォールバック

**状況**: v0.6.1 で `system_prompt.txt` による外部プロンプトファイル読み込みを実装  
**知見**:
1. **空ファイルフォールバック**: `.strip()` 後に空文字列になる場合（空白のみ・改行のみ等）はコード内定数にフォールバックする。単純な `if content:` で判定可能
2. **テスト分離**: `load_system_prompt()` は相対パス `Path("system_prompt.txt")` を参照するため、テストは必ず `monkeypatch.chdir(tmp_path)` でワーキングディレクトリを隔離する。隔離しないとプロジェクト直下の `system_prompt.txt` が読み込まれてテストが汚染される
3. **辞書注入との連鎖**: `_build_system_prompt()` は `load_system_prompt()` を base として使い、辞書語彙を後付けで注入する設計にすることで、外部ファイルを使っても辞書注入が自動的に機能する
4. **定数の役割**: `SYSTEM_PROMPT` 定数はフォールバック値として維持する。`test_no_api_key_in_prompt` 等の既存プロンプトテストは定数を直接検査するため、定数の内容は常に有効な状態を保つ  
**How to apply**: cwd 相対パスを参照する関数のテストは `monkeypatch.chdir(tmp_path)` を必ず追加する。

### [2026-11-01] tkinter Canvas ベクター描画によるアイコン・アニメーション実装パターン

**状況**: v0.7.0 でインジケーター UI をテキスト文字からベクター描画に刷新  
**知見**:
1. **ステート切替に `c.delete("all")` + 全要素再描画**を使うと、`_item` ID の管理が不要になりコードが単純化できる。アニメーション中は毎フレーム同じ処理が走るためパフォーマンス的にも問題ない
2. **マイクアイコン**: `create_oval`（カプセル）+ `create_arc(start=0, extent=-180, style="arc")`（スタンド弧）+ `create_line` 2本（ポール・ベース）の 4 要素で表現できる。`style="arc"` を指定しないと扇形になるので注意
3. **波アニメーション**: `after()` タイマーを自己スケジュールする `_tick_wave()` パターン。`_wave_job is None` のガードで `set_state` 変更後の遅延実行をブロックする。`after_cancel` と `_wave_job = None` をセットで呼ぶことで停止が確実になる
4. **事前計算フレーム**: `math.sin` による 8フレーム × 4バーの高さ配列を `_WAVE_FRAMES` としてモジュール初期化時に計算し、実行時の浮動小数点演算をゼロにする（CPU 負荷ゼロの実現）
5. **ドラッグ移動**: `<Button-1>` でウィンドウ座標を記録し（`event.x_root - self.winfo_x()`）、`<B1-Motion>` で `geometry("+x+y")` を更新する。`overrideredirect(True)` ウィンドウでは標準のドラッグ機能がないため手動実装が必要
6. **テスト可能性**: tkinter は CI 環境でヘッドレス動作しないため、(a) `_WAVE_FRAMES` データの形状・値域をテスト (b) ソースコードの文字列検索でバインディング・メソッドの存在を確認 (c) ドラッグオフセット計算の純粋数学をテスト、という 3 層で品質担保する  
**How to apply**: 新しいアニメーション状態を追加する場合は `_WAVE_FRAMES` と同じパターンで事前計算フレームを定義し、`set_state` に分岐を追加するだけで対応できる。

### [2026-11-01] tkinter で「楕円→カプセル（ピル）形状」への変換と `style="chord"` の注意点

**状況**: v0.7.1 でマイクアイコンを楕円から Gemini 風カプセル型に変更  
**知見**:
1. **カプセル描画**: 上半円 `create_arc(... style="chord")` + 矩形 `create_rectangle` + 下半円 `create_arc` の3要素で実現できる。`style="chord"` は弦（直線）で閉じた半円を塗りつぶす
2. **シームレス結合**: `outline=""` で弦の境界線を消し、矩形を1px 大きめ（18〜28）に重ねることでピクセルギャップをなくす。`outline=col` は ON/OFF で視覚的な差が出るため必ず `""` にする
3. **`style` の誤りやすさ**: `style="arc"` は輪郭線のみ（fill 無効）、`style="chord"` は弦で閉じた領域を塗りつぶす、`style="pieslice"` は扇形。マイクスタンド弧のような「線だけ必要」な場合は `style="arc"` を使う

### [2026-11-01] 推論結果の whitespace 防衛と "done" 状態分岐

**状況**: v0.7.1 でノイズ/無音時の誤貼り付け対策と完了演出を実装  
**知見**:
1. **二重 strip**: 各バックエンドの `return ... .strip()` に加え `_process_and_paste` でも `transcribe(wav_bytes).strip()` を適用する。バックエンドを追加・変更した際に `.strip()` 忘れがあっても最終防衛ラインで空文字判定が効く
2. **"done" ステート分岐**: `if text: ... safe_set_state("done")` / `else: ... safe_set_state("idle")` に分岐することで、空文字列（ノイズ・無音）では完了演出（チェックマーク）を出さない自然な UI になる
3. **done ジョブの二重キャンセル防止**: `set_state` の先頭で `_done_job` と `_wave_job` の両方を `after_cancel` してから進める。どのステート遷移でも必ずクリーンアップされる

### [2026-11-01] ウィンドウ座標の JSON 永続化とドラッグ終了トリガー

**状況**: v0.7.1 でインジケーター位置の再起動間永続化を実装  
**知見**:
1. **保存タイミング**: `<ButtonRelease-1>` でドラッグ終了時のみ `_save_window_pos` を呼ぶ。`<B1-Motion>` ごとに保存するとファイル書き込みが連続して不要な I/O が発生する
2. **`winfo_x()` / `winfo_y()`**: これらはウィンドウマネージャ上の絶対座標を返す。`event.x_root` はカーソルのスクリーン座標なので、ドラッグ終了時は `winfo_x/y` を使うのが正確
3. **フォールバック**: `_load_window_pos()` は `try/except Exception` で全例外を吸収して `None` を返す。破損した JSON や型エラーがあっても起動がブロックされない
4. **テスト**: `monkeypatch.setenv("APPDATA", str(tmp_path))` で書き込み先を隔離するパターンで辞書パスと同様に対応できる

### [2026-11-01] tkinter の `create_line + capstyle="round"` でシームレスなピル形状を描画する

**状況**: v0.7.2 で 3 パート arc+rect アプローチを廃止し、create_line による完全対称カプセルに変更  
**知見**:
1. **ピル描画の最善解**: `create_line(cx, y1, cx, y2, width=W, capstyle="round")` は上端に `W/2` の半円、下端にも `W/2` の半円が自動付与された完全対称ピルになる。アルゴリズム上シームが生じない唯一の手法
2. **arc+chord 方式の問題点**: 3 パート（上弧 + 矩形 + 下弧）はピクセル境界で薄いギャップが生じやすく、特に奇数 width では補正が困難。capstyle="round" ならこれらが一切発生しない
3. **多用途化のコツ**: `col` を引数で受け取り `def _draw_mic(self, col="#aaaaaa")` とすると、アイドル（グレー）・処理中（アンバー）で同一描画関数を再利用でき DRY になる
4. **深 U アーム**: `create_line` 2 本（左右縦）+ `create_arc(start=180, extent=180, style="arc")` の組み合わせで、浅い弧より深く包み込む U アームが実現できる。アーム終端 y と弧の center_y を一致させると接合部がシームレスになる

### [2026-11-01] 状態遷移での「◎ 一瞬表示」バグと processing 状態の統合

**状況**: v0.7.2 で「processing 中に ◎ が出る」不具合を修正  
**根本原因**: キーリリース → `safe_set_state("processing")` → API 呼び出し → `safe_set_state("done")` の流れで、API 呼び出し時間分だけ ◎ が表示されていた。ユーザーには「一瞬表示」に見える  
**対策**: processing 状態を `_draw_mic("#fbc02d")` に統一。処理中はアンバー色のマイクアイコンを表示するため ◎ が一切出ない。`set_state("done")` になったときに初めてチェックマークが描画される  
**How to apply**: 新しい遷移状態を追加する際は「その状態で何かを表示してからすぐ別状態に遷移する」設計を避ける。各状態はその滞在時間中ずっと表示されるものを描く。

### [2026-11-01] tkinter マイクアイコンのプロポーション調整：アーム長さとカプセルサイズの比率設計

**状況**: v0.7.3 でカプセル縦 1.5 倍・U アーム縦線 2/3 化を実施  
**要点**: カプセルの寸法変更とアーム・弧の接合点は連動して計算する必要がある。  
- `create_line(cx, y1, cx, y2, width=W, capstyle="round")` の場合、ピルの top = y1 - W/2、bottom = y2 + W/2  
- 弧 bbox (x1, y1, x2, y2) の場合、アームの端 y = (y1 + y2) / 2（bbox の垂直中心）に合わせることでシームレスに接合できる  
- カプセル bottom とアーム top の間の「腰部ギャップ」は視覚的な一体感を左右する；今回は capsule_bottom (y44) と arm_top (y33) で 11px の重なり（弧が capsule の中に食い込むように見える）を設定し自然なシルエットにした  
**How to apply**: マイクアイコン比率を変更する際は先に全座標を図示してから edit すること。接合点の不整合は実機でないと見えにくい。

### [2026-11-01] PyInstaller フローズン exe でのリソースパス解決と dotenv ロード

**状況**: v0.8.0 で exe ビルド対応を追加  
**要点**:
- `sys.frozen == True` かつ `hasattr(sys, "_MEIPASS")` でフローズン実行を検出できる（`_MEIPASS` は `--onefile` のみ。`--onedir` は `sys.frozen` だけ確認すれば十分）
- ユーザー設定ファイル（`.env`, `system_prompt.txt`, `dictionary.txt`）は `sys._MEIPASS` ではなく `Path(sys.executable).parent` で解決する。`_MEIPASS` は一時展開ディレクトリであり、ユーザーが編集できない
- `load_dotenv()` は cwd を起点にするため、フローズン時は `load_dotenv(exe_dir / ".env", override=False)` を追加呼び出しする（`override=False` で cwd の .env を優先させる）
- faster-whisper / ctranslate2 は `collect_all()` でバイナリ・データも含めて収集する必要がある  
**How to apply**: フローズン exe での設定ファイル参照は常に `_get_exe_dir()` ヘルパー経由で行う。`Path(__file__).parent` は開発時のみ有効でフローズン時は `_MEIPASS` 内の一時パスになる。

### [2026-11-01] 起動時のバックエンド設定バリデーションと安全なフォールバック

**状況**: v0.8.0 で APIキー未設定時のクラッシュ問題を解消  
**根本原因**: `_transcribe_gemini` が `GEMINI_API_KEY` 未設定時に `RuntimeError` を投げ、ユーザーには録音後にエラーが表示されるだけで設定方法が分からなかった  
**対策**: 起動時（tkinter ループ開始前）に `_check_backend_config()` を呼び出し、設定不備をダイアログで案内してフォールバックする  
**How to apply**: バックエンド設定の検証は「使う直前」ではなく「起動時」に行う。遅延エラーより早期フォールバックの方がユーザー体験が良い。

### [2026-11-01] pyautogui の合成 Ctrl イベントが pynput の modifier 状態を汚染する

**状況**: v0.8.1 でスペース暴走バグを調査  
**根本原因**: `pyautogui.hotkey("ctrl", "v")` は Ctrl key_down/key_up の合成イベントを発行する。これを pynput の global hook が受け取り `_mods_held` を更新する。ペースト直後にユーザーが Space を押すと、Ctrl が `_mods_held` に残ったまま新録音が開始される競合が起きる  
**対策**: `paste_text()` の開始から 0.5s cleanup 完了まで `_pasting = True` フラグを立て、`_on_press` でガードする。合成イベントの影響を受ける時間窓を完全にブロックする  
**How to apply**: pyautogui で modifier キー（Ctrl/Alt/Shift）を送信する処理は、pynput の状態機械と競合するリスクがある。送信前後でフラグを立てて listener 側をガードすること。

### [2026-11-01] GUI アプリのログはファイルに書かない状態がデフォルトになる問題

**状況**: v0.8.1 でコンソール非表示 exe のログ不可視問題を解消  
**根本原因**: `--noconsole` exe では `logging.basicConfig` の StreamHandler が書き込む stdout/stderr が捨てられる。エラーが起きても外から一切見えない  
**対策**: `_setup_logging()` を `main()` から呼び出し専用にし、`ENABLE_LOG_FILE=true`（デフォルト）時に `RotatingFileHandler` を追加。中クリックで即座にログ確認できる UI も提供する  
**How to apply**: `_setup_logging()` をモジュール import 時でなく `main()` から呼ぶことで、テスト実行時のファイル生成副作用を防げる。

### [2026-11-01] 初回リリース直前の「Git 未コミット」事件と開発ガードレール

**事象**:
- Claude Code 主導でテスト（130件パス）や exe ビルド、仕様書・教訓更新を進めた結果、Git のコミットが1度も行われないまま作業ディレクトリ内だけで完結していた
- 初回コミットがいきなり「v0.8.1」という怪奇現象が発生した
- README.md に開発者向け憲法や内部作法が垂れ流しになり、一般利用者向けドキュメントと混ざり合う歪みが生じた

**教訓**:
- 「テスト全通＋AI作業メモ更新」は開発の健全性を保証しない。Git コミットこそが唯一の客観的履歴
- AI 駆動開発（Vibe Coding）では、AI 側の「やった気（ローカル編集の連打）」に流されず、タスク境界でコミットを強制する規律が必須

**今後の開発ガードレール（開発スキル化要件）**:
1. **コミット・ファースト**: 1タスク完了（テスト全パス）ごとに必ず適切な粒度で `git commit` を実行してから次のタスクへ進む
2. **ドキュメント分離**: 開発憲法・内部教訓は `docs/` などの内部領域に限定し、配布用 README.md には侵食させない
3. **バージョン整合性**: Git タグとプロジェクト内 `APP_VERSION` を連動させる

### [2026-11-02] ハーネス影響ゼロの変更は確認なしで即 push する

**事象**:
- HTML/CSS のテキスト修正（`<br>` 挿入など）を実施後、push するかどうか一度ユーザーに判断を仰いでいた
- ユーザーから「影響のないものはすぐ push まで徹底するように」と指摘を受けた

**教訓**:
- テストハーネス（pytest）・静的解析（ruff/bandit）が通ること、かつ Python ロジックに一切触れない変更は「機能への影響ゼロ」と判断できる
- その判断ができた時点で `git add → commit → push` まで自律実行するのが正しい動き方

**ハーネス影響ゼロの定義（即 push 可）**:
| 変更種別 | 判断基準 |
|---------|---------|
| HTML/CSS のコンテンツ・スタイル修正 | `*.py` を変更していない |
| README / ドキュメントのみの変更 | `*.py` を変更していない |
| `<br>` 挿入・テキスト修正・リンク追加 | pytest 対象外、ロジック無変更 |
| 設定ファイル（`.env.example` コメント等）の追記 | セキュリティ制約 S-1〜S-5 に非抵触 |

**逆に必ず人間に確認すること**:
- `main.py` や `tests/` を変更するもの
- 依存パッケージ（`requirements.txt`）の追加・変更
- セキュリティ制約（S-1〜S-5）に関わる変更
- git の破壊的操作（`--force` push、履歴の書き換えなど）

**How to apply**: 変更後に「pytest 対象か？`*.py` を触ったか？」を自問する。Noなら即 `git add → commit → push` まで実行する。確認を挟まない。

<!-- 新しい教訓はここに追記 -->
