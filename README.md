# Vet Lit Radar

PubMedの主要獣医誌を定期巡回し、犬・猫の内科トピックに該当する新着論文を
GitHub Pagesのダイジェスト（`index.html`）に蓄積するツールです。

## 2つのモード（自動で切り替わり）
- **無料モード（既定）** — `ANTHROPIC_API_KEY` を設定しなければこちら。
  該当論文をキーワードでトピック分類し、タイトル・抄録・リンクを一覧表示します。
  AIの要約・採点はしません。**費用ゼロ**。タイトルを見て自分で読む・要約する運用向け。
- **AIモード（任意）** — `ANTHROPIC_API_KEY` を設定すると有効化。
  各論文をClaudeが採点・和文要約し、有用度で絞り込んで掲載します（少額の従量課金）。

どちらも GitHub Actions / GitHub Pages / PubMed は無料です。

## 仕組み
1. GitHub Actions が毎日 06:00 JST に起動
2. `fetch_and_digest.py` が PubMed E-utilities で対象誌の新着を取得（直近 `RELDATE` 日分）
3. キーがあればClaudeで要約、無ければキーワードでトピック分類
4. `data/papers.json` に蓄積し `index.html` を再生成
5. 変更をコミット → GitHub Pages が自動公開

## セットアップ（無料モード）
1. リポジトリを作成し、ファイル一式をプッシュ（`導入マニュアル.md` 参照）
2. **Settings → Secrets → Actions** で `NCBI_API_KEY`・`NCBI_EMAIL` を登録（推奨。無くても可）
3. **Settings → Pages** を `main` / `/(root)` に設定
4. **Actions** から手動実行 → `index.html` が生成される
5. 公開URLをブックマーク

`ANTHROPIC_API_KEY` を後から Secret に足せば、次回実行からAIモードに自動で切り替わります。

## 調整（すべて `config.py`）
- 対象誌 `JOURNALS` ／ トピック `TOPIC_GROUPS` ／ 巡回日数 `RELDATE`
- AIモードのときの掲載基準 `MIN_USEFULNESS`、モデル `MODEL`
- 週1回にするなら `radar.yml` の cron を `0 21 * * 1`（毎週月曜）に

## 注意
- 60日間リポジトリに活動がないと、GitHubの仕様で定期実行が自動停止します（手動Runで再開）
- 公開リポジトリにすると一覧ページの内容も公開されます。非公開なら private に
- 抄録はスクリーニング用。内容は必ず原著（PubMedリンク）で確認してください
