# 更新履歴

> **何をどう変えてきたか**の記録。現在地は `PROJECT_STATUS.md`、文書の一覧は `INDEX.md` を見ること。
> `docs/` 配下と同じく、**生の発言と話者を書かない**（`CLAUDE.md` 3章）。

## 記載ルール

### 1. 同じ日・同じ対象の変更は、最終状態のみを1行で書く

途中経過を残さない。AをBに変え、さらにBをCに変えた場合、**「AをCにした」と1行で書く**。
繰り返しの試行錯誤を全て残すと、後から読んだときに何が現在の状態か分からなくなるため。

```
NG:  | 収集処理 | 取得単位を会議単位に変更 |
     | 収集処理 | 取得単位を発言単位に変更 |
OK:  | 収集処理 | 取得単位を会議単位から発言単位に変更 |
```

### 2. 対象が異なれば、同じ日でも行を分ける

「新しい条件でクラスタリングを実験した」と「API取得の仕様を変えた」は別の対象であり、
まとめると意味が失われる。**正規化するのは対象が同じ場合に限る。**

「対象」は処理・機能・文書の単位で決める（例: 収集処理、クラスタリング、ドキュメント構成、データ層）。

### 3. 過去の日付の記述は書き換えない

正規化してよいのは**当日の作業中のみ**。前日以前の行は、誤記の修正を除いて変更しない。

### 4. gitの履歴と役割を分ける

コミット単位の機械的な記録はgitに任せる。ここには**判断と結果**を書く。
「なぜ」を詳しく書く必要がある場合はADRを起こし、`関連` 列からリンクする。

---

## 2026-08-18

| 対象 | 変更内容 | 関連 |
|---|---|---|
| リポジトリ | git初期化（`main`）し、GitHub（public / MIT License）へ公開。`.gitignore` に `outputs/` `private/` `.DS_Store` を追加 | - |
| プロジェクト規約 | `CLAUDE.md` に目的・フェーズ・データソース制約・外部LLM利用の規約を記載 | - |
| データ層 | PoCはParquet + DuckDBで完結させ、RDB・Dockerの導入は本実装フェーズからと決定 | [ADR-001](decisions/ADR-001-poc-data-layer.md) |
| ドキュメント構成 | `docs/` をID駆動（EXP / ISSUE / ADR）に再編。`INDEX.md`・`issues/`・`decisions/`・`drafts/`・`_templates/` を新設し、運用規約を `.claude/rules/documentation.md` に定義 | - |
| 機密データの境界 | 取得データを機密扱いとし、境界を「生の発言と話者を出さない」に設定。`outputs/`・`private/` を新設 | [ADR-002](decisions/ADR-002-public-private-boundary.md) |
| 対象データ | PoCの対象を2025年（発言118,566件）、本番想定を2019〜2025年（同819,428件）と確定。2019年でコロナ前の基準年を確保し、年央で不完全な2026年を除外 | [ADR-001](decisions/ADR-001-poc-data-layer.md) 9章 |
| 実行環境 | uvでプロジェクトを初期化し、Pythonを3.12に固定。依存は httpx / duckdb / pyarrow / pydantic / tenacity、開発依存は pytest | - |
| ブランチ運用 | 作業をブランチで分け、**Pull Request 経由でマージ**する方式を採用（ローカルマージ禁止・Merge commit固定）。規約変更もブランチ経由とし、載せるブランチは影響範囲で判断する。実験も成果物として同一リポジトリに残すと定義 | [ADR-003](decisions/ADR-003-branch-strategy.md) / [ADR-004](decisions/ADR-004-rule-change-via-branch.md) / [ADR-005](decisions/ADR-005-merge-via-pull-request.md) |
| 要件定義 | 分析要件定義書のドラフトをv0.7まで作成。依頼者への確認事項を全件クローズし、LLMコスト見積もり・参照論点リストを要件化。deliverable-reviewerのレビュー1回目は差し戻し（致命的4・重要15・軽微8） | [1回目レビュー](reviews/レビュー_分析要件定義書-論点抽出PoC_20260818.md) |
| ドキュメント構成 | `docs/inputs/` を新設し、ヒアリング記録を保存。**追記のみ**とする規約を定めた（記録を事後に編集できると `[事実]` タグの検証が循環するため） | `.claude/rules/documentation.md` 3.6節 |

## 2026-08-19

| 対象 | 変更内容 | 関連 |
|---|---|---|
| 要件定義 | レビュー3回（差し戻し2回→条件付き承認）を経て**v1.0として確定**。その後 [ISSUE-001](issues/ISSUE-001-requirements-analysis-unit-and-review-conditions/issue.md) で**分析単位をPoCの比較項目へ変更**しv2.0、[ISSUE-002](issues/ISSUE-002-requirements-ar006-and-unit-reference-scope/issue.md) で**AR-006受入条件の明確化と一致率の観測範囲の限定**を行い**v2.1**。未確定事項10件はPoC設計書で解消 | [3回目レビュー](reviews/レビュー_分析要件定義書-論点抽出PoC_v0.8_20260819.md)、[ISSUE-001](issues/ISSUE-001-requirements-analysis-unit-and-review-conditions/issue.md)、[ISSUE-002](issues/ISSUE-002-requirements-ar006-and-unit-reference-scope/issue.md) |
| PoC設計 | PoC設計書を **v1.0 として確定**し `design/` へ移動。着手前必須5件（Q-013・015・016・017・018）を確定し、実験内で決定する5件の比較設計を定義。**LLMコストの律速がTPMであり費用制限ではないことを確定**し、ベクトル化方式の決定要因を「品質」と「機密境界」へ移した。収集をマニフェスト方式で設計し期間を実行時の引数化。**レビュー3回（差し戻し2回→条件付き承認）**を経て、ステージの循環参照・Q-018の未統合・改訂の適用漏れを解消 | [PoC設計書](design/poc-design-topic-extraction.md)、[3回目レビュー](reviews/レビュー_PoC設計書-論点抽出_v0.11_20260819.md) |
| データ層 | **生データを可逆に保存する要件を追加**（`raw_json` 列）。取得と変換のコストが非対称であり、列マップ漏れによる再取得を避けるため | [ADR-001](decisions/ADR-001-poc-data-layer.md) 6.1節 |
| 上流の入力 | **国会会議録検索APIの仕様要約**と**参照論点リストの情報源**を `docs/inputs/` へ記録。参照A（施政方針演説）・参照B（提出議案）の**実在と見出し構造を確認**（レビューで3回未確認だった項目）。官邸サイトの掲載範囲の制約と、参照A・Bの粒度が1桁異なることが判明 | [API仕様の要約](inputs/kokkai-api-spec-summary.md)、[参照論点リストの情報源](inputs/reference-topic-sources.md) |
| 機密境界 | 参照論点リストの出典を、国会会議録APIとは独立した公開ソースへ変更。ADR-002の境界を解釈せずに済む形とした。**ただし解消するのは機密境界のみで、参照Aの内容がコーパス内に存在する点は残る**（ADR-006 訂正節） | [ADR-006](decisions/ADR-006-reference-topic-list-storage.md) |
| ドキュメント運用 | **マージ後のブランチ削除を規約化**（削除は承認を得てから実行）。**ADRについて決定を維持したまま根拠のみを訂正する手続き**を追加。`docs/inputs/` を公開・非公開の境界表へ明記 | `.claude/rules/documentation.md` 1・3.5・7節 |
