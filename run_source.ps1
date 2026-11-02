# 未署名 exe を使わずに Python スクリプトとして voice-fep を起動するためのラッパー。
# インストーラ不要で開発環境を再現できるよう、初回実行時に仮想環境とパッケージを自動セットアップする。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# スクリプト自身の場所をベースにすることで、起動元ディレクトリに依存しない
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not (Test-Path ".\.venv")) {
    Write-Host "初回セットアップを開始します（仮想環境を作成中...）" -ForegroundColor Cyan

    # python コマンドが存在しない環境でもエラーを握り潰さず終了するため Stop を維持しつつ catch する
    try {
        python -m venv .venv
    } catch {
        Write-Host "エラー: Python が見つかりません。Python 3.11 以上をインストールしてください。" -ForegroundColor Red
        exit 1
    }
    if (-not $?) {
        Write-Host "エラー: Python が見つかりません。Python 3.11 以上をインストールしてください。" -ForegroundColor Red
        exit 1
    }

    .\.venv\Scripts\pip install -r requirements.txt
    if (-not $?) {
        Write-Host "エラー: パッケージのインストールに失敗しました。" -ForegroundColor Red
        exit 1
    }

    # .env が無く .env.example がある場合のみコピー（既存の .env を上書きしないため）
    if ((-not (Test-Path ".\.env")) -and (Test-Path ".\.env.example")) {
        Copy-Item ".\.env.example" ".\.env"
        Write-Host ".env.example を .env にコピーしました。必要に応じて GEMINI_API_KEY を設定してください。" -ForegroundColor Yellow
    }
}

Write-Host "voice-fep を起動します..." -ForegroundColor Green
.\.venv\Scripts\python main.py
