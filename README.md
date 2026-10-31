# voice-fep

Windows 常駐型・音声入力 FEP ツール。  
ホットキー **F8** を押している間だけ録音し、離すと Gemini API が書き起こして  
アクティブウィンドウにそのままペーストする。

---

## クイックスタート

```powershell
# 1. Python 3.11+ が必要
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 依存パッケージのインストール
pip install -r requirements.txt

# 3. 環境変数の設定
copy .env.example .env
# .env を開いて GEMINI_API_KEY を記入する

# 4. 起動
python main.py
# または コンソール非表示で起動:
# wscript run_silent.vbs
```

F8 を押して話し、離すと書き起こしがアクティブウィンドウにペーストされます。  
終了するにはインジケータを右クリック → 終了、または Ctrl+C。

---

## 設計思想: SDD + Secure Vibe Coding

### SDD（仕様駆動開発）
仕様（`docs/SDD.md`）を先に合意し、実装はその仕様に従う。  
仕様変更は必ずドキュメントを先に更新してからコードを変更する。

### Secure Vibe Coding（CC Terminal 版）
Claude Code（AI コーディング）を活用しながら、人間がセキュリティゲートキーパーとして機能する運用スタイル。

| 役割 | 担当 |
|------|------|
| 提案・実装・テスト | Claude Code |
| セキュリティレビュー・承認 | 人間（Subutomo Dev） |
| コミット/Push の最終決定 | 人間（必須） |

開発規律の詳細は `CLAUDE.md` を参照。

---

## ファイル構成

```
voice-fep/
├── CLAUDE.md            # 開発憲法（タスク開始前に必読）
├── LESSONS_LEARNED.md   # 失敗・教訓ログ
├── PLAN.md              # 実装タスクチェックリスト
├── main.py              # エントリポイント
├── requirements.txt     # 依存パッケージ
├── run_silent.vbs       # コンソールなし起動スクリプト
├── .env.example         # 環境変数テンプレート（.env は gitignore）
├── .gitignore
├── LICENSE
├── docs/
│   └── SDD.md           # 仕様駆動設計書
└── tests/               # テスト（フェーズ3で追加）
```

---

## バックエンド切替

`.env` の `BACKEND` 変数で切り替え可能:

| 値 | バックエンド | 備考 |
|----|------------|------|
| `gemini`（デフォルト） | Gemini 2.5 Flash | 高精度・低コスト |
| `cloudflare` | Cloudflare Workers AI Whisper | エッジ処理 |
| `local_whisper` | faster-whisper (ローカル) | オフライン・プライバシー優先 |

---

*Copyright (c) 2026 Subutomo Dev — MIT License*
