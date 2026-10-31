# PLAN.md — voice-fep 実装タスク計画

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

- [x] `tests/test_prompt.py` — 9件 PASSED
- [x] `tests/test_backend_stub.py` — 17件 PASSED（合計 26/26）
- [x] `pyproject.toml` — pytest + ruff + bandit 設定
- [x] `ruff check` — All checks passed
- [x] `bandit -r main.py` — No issues identified

---

## フェーズ 4: 動作確認

- [ ] `.venv` + `pip install -r requirements.txt` が正常完了するか確認
- [ ] F8 押下 → 録音開始（インジケータ●）が確認できるか
- [ ] F8 解放 → Gemini API 送信 → テキストペーストが確認できるか
- [ ] ペースト後クリップボードがクリアされるか確認
- [ ] `run_silent.vbs` でコンソールなし起動が動作するか確認
- [ ] エラー時にインジケータが × を 3 秒表示して ○ に戻るか確認

---

## フェーズ 5: 初回コミット（人間が実行）

- [ ] `git add` — コミット対象ファイルの確認（`.env` が含まれていないこと）
- [ ] `git commit` — 人間が実行・メッセージ確認
- [ ] リモートリポジトリの作成（GitHub）
- [ ] `git push` — 人間が実行

---

## 将来フェーズ（v0.2 以降）

- [ ] 言語切替（英語対応）
- [ ] 録音時間上限設定（RECORD_MAX_SEC）
- [ ] カスタム辞書ホットリロード
- [ ] CI/CD（GitHub Actions: ruff + bandit + pytest）
- [ ] 構造化ログ・使用量メータリング
- [ ] PyInstaller による exe 化
