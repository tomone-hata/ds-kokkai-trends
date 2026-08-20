# ドキュメント目録

> **何が存在するか**の一覧。いま何をしているかは [PROJECT_STATUS.md](PROJECT_STATUS.md)、何をどう変えてきたかは [CHANGELOG.md](CHANGELOG.md) を見ること。
> 文書を追加・改訂・廃止したら、必ずこの表を更新する。
> **廃止した文書を削除せず「廃止」と明記する**のは、過去の判断の経緯を残すため。
>
> **`docs/` 配下は全て公開可能なものに限る。** 取得データは機密扱いとし、個票は `private/` へ置く（[ADR-002](decisions/ADR-002-public-private-boundary.md)）。

## 要件定義書 — `requirements/`

| 文書 | パス | 版 | 状態 | 概要 |
|---|---|---|---|---|
| 分析要件定義書: 国会会議録トレンド分析（論点抽出PoC） | [requirements/requirements-topic-extraction-poc.md](requirements/requirements-topic-extraction-poc.md) | **v2.1** | **現役**（`poc/topic-extraction-2025` 上。`main` へのマージをもって確定） | 発言を教師なしクラスタリングで論点抽出し時系列トレンドを可視化するPoCの要件。実現可能性B（条件付き）。未確定10件はPoC設計書で解消 |

## 設計書・仕様書（確定） — `design/`

**実装が参照してよいのはこの表の「現役」の文書のみ。**

| 文書 | パス | 版 | 状態 | 概要 |
|---|---|---|---|---|
| PoC設計書: 国会会議録トレンド分析（論点抽出 EXP-001） | [design/poc-design-topic-extraction.md](design/poc-design-topic-extraction.md) | **v1.5** | **現役**（`poc/topic-extraction-2025` 上。`main` へのマージをもって確定） | EXP-001 の実験計画。11ステージ・撤退基準・比較設計・評価設計。想定工数17.0〜18.0人日。未処理の指摘7件は20.2節 |

## 検討中の文書 — `drafts/`

確定版がまだ存在しない新規文書の作業場所。確定したら `design/` へ移動し、上の表へ登録する。
**既存の確定文書を改訂する場合はここを使わず、作業ブランチ上で `design/` を直接編集する。**

| 文書 | パス | 着手日 | 状態 |
|---|---|---|---|
| （なし。PoC設計書は v1.0 として `design/` へ移動済み） | | | |

## 決定記録（ADR） — `decisions/`

| ID | 決定内容 | 日付 | 状態 |
|---|---|---|---|
| [ADR-001](decisions/ADR-001-poc-data-layer.md) | PoCではRDB・Dockerを導入せず Parquet + DuckDB で完結させる | 2026-08-18 | 採用 |
| [ADR-002](decisions/ADR-002-public-private-boundary.md) | `docs/` は全て公開可能とし、取得データは機密扱いで `private/` へ分離する | 2026-08-18 | 採用 |
| [ADR-003](decisions/ADR-003-branch-strategy.md) | 実験・課題・実装をブランチで分け、実験も成果物として同一リポジトリに残す | 2026-08-18 | 採用（例外規定はADR-004により廃止） |
| [ADR-004](decisions/ADR-004-rule-change-via-branch.md) | 規約変更もブランチ経由とし、載せるブランチは影響範囲で判断する | 2026-08-18 | 採用 |
| [ADR-005](decisions/ADR-005-merge-via-pull-request.md) | ローカルでのマージを禁止し、Pull Request 経由でマージする | 2026-08-18 | 採用 |
| [ADR-006](decisions/ADR-006-reference-topic-list-storage.md) | 参照論点リストは独立した公開ソースから作成し `docs/` に置く | 2026-08-19 | 採用 |
| [ADR-008](decisions/ADR-008-review-checkpoints-in-large-experiments.md) | 多段の実験では、不可逆な決定の直後に `experiment-analyst` の検証を挟む | 2026-08-20 | 採用 |
| [ADR-009](decisions/ADR-009-dependency-declaration.md) | 依存は `pyproject.toml` に `==` で完全固定し、実験専用の依存を本番依存から分離する | 2026-08-20 | 採用 |
| [ADR-010](decisions/ADR-010-no-retroactive-revision.md) | 規約変更を過去へ遡って適用しない。実害が出る場合のみ個別に見直す | 2026-08-20 | 採用 |
| （ADR-007 起票予定） | 個票（発言本文）の外部LLMへの送信可否。**起票されるまで外部API埋め込み・代表発言による命名を実施しない**（PoC設計書 8.7節） | 未起票 | — |

## 実験 — `experiments/`

ドキュメントは `docs/experiments/EXP-NNN-{slug}/`、実コードは `experiments/EXP-NNN-{slug}/` に置き、**ディレクトリ名を一致させる**。

| ID | 実験名 | フェーズ | 計画 | レポート | 判定 |
|---|---|---|---|---|---|
| EXP-001 | 論点抽出ベースライン（`EXP-001-topic-extraction-baseline`） | PoC | [plan.md](experiments/EXP-001-topic-extraction-baseline/plan.md) | 未作成 | **実施中**（S-2 完了 / CP-1・**RP-A 通過**。次は S-3） |

## 課題・不具合 — `issues/`

未解決のみ掲載。全件は [issues/README.md](issues/README.md) を参照。

| ID | 種別 | 内容 | 状態 |
|---|---|---|---|
| （なし。ISSUE-001〜008 はすべて対応済。全件は [issues/README.md](issues/README.md) を参照） | | | |

## レビュー・検証レポート

| 文書 | パス | 日付 | 判定 |
|---|---|---|---|
| 分析要件定義書レビュー（v0.6対象） | [reviews/レビュー_分析要件定義書-論点抽出PoC_20260818.md](reviews/レビュー_分析要件定義書-論点抽出PoC_20260818.md) | 2026-08-18 | **差し戻し**（致命的4・重要15・軽微8） |
| 分析要件定義書 再レビュー（v0.7対象） | [reviews/レビュー_分析要件定義書-論点抽出PoC_v0.7_20260819.md](reviews/レビュー_分析要件定義書-論点抽出PoC_v0.7_20260819.md) | 2026-08-19 | **差し戻し**（新規: 高3・中10・低7） |
| 分析要件定義書 3回目レビュー（v0.8対象） | [reviews/レビュー_分析要件定義書-論点抽出PoC_v0.8_20260819.md](reviews/レビュー_分析要件定義書-論点抽出PoC_v0.8_20260819.md) | 2026-08-19 | **条件付き承認**（高0・中/低4）。移動条件A-1〜A-6は対応済、B-1〜B-6はPoC設計書までに処理（処理状況はPoC設計書20章） |
| [RP-A: EXP-001 S-2 データ品質確認](reviews/RP-A_EXP-001-S2-data-quality_20260820.md) | [reviews/RP-A_EXP-001-S2-data-quality_20260820.md](reviews/RP-A_EXP-001-S2-data-quality_20260820.md) | 2026-08-20 | **通過**（3回目。差し戻し2回を経て）。[ADR-008](decisions/ADR-008-review-checkpoints-in-large-experiments.md) の RP-A |
| PoC設計書 3回目レビュー（v0.11対象） | [reviews/レビュー_PoC設計書-論点抽出_v0.11_20260819.md](reviews/レビュー_PoC設計書-論点抽出_v0.11_20260819.md) | 2026-08-19 | **条件付き承認**（高0・中6）。移動条件C-1〜C-4は対応済 |
| PoC設計書 再レビュー（v0.9対象） | [reviews/レビュー_PoC設計書-論点抽出_v0.9_20260819.md](reviews/レビュー_PoC設計書-論点抽出_v0.9_20260819.md) | 2026-08-19 | **差し戻し**（高2＝反映の取りこぼし・検算42項目全一致）。v0.10 で解消 |
| PoC設計書レビュー（v0.6対象） | [reviews/レビュー_PoC設計書-論点抽出_v0.6_20260819.md](reviews/レビュー_PoC設計書-論点抽出_v0.6_20260819.md) | 2026-08-19 | **差し戻し**（高2・検算35項目中30一致）。**v0.8 で I-001・I-002 を解消済み・再レビュー待ち** |

## 上流の入力 — `inputs/`

外部から得た一次情報。**追記のみとし、後の決定に合わせて書き換えない**（`.claude/rules/documentation.md` 3.6節）。

| 文書 | パス | 日付 | 内容 |
|---|---|---|---|
| ヒアリング記録 | [inputs/hearing-2026-08-18.md](inputs/hearing-2026-08-18.md) | 2026-08-18 | 要件定義の根拠。依頼者の【発言】と提案への【承認】を区別して記録 |
| 国会会議録検索API 仕様の要約 | [inputs/kokkai-api-spec-summary.md](inputs/kokkai-api-spec-summary.md) | 2026-08-19 | エンドポイント・パラメータ・負荷制約・エラーコード・著作権。**公式ページ以外に情報源がない**ため控えを置く |
| 参照論点リストの情報源 | [inputs/reference-topic-sources.md](inputs/reference-topic-sources.md) | 2026-08-19 | 候補A〜Dの選定理由と、参照A・Bの**実在確認結果**（出典URL・見出し構造・掲載範囲の制約） |
| 参照論点リスト本体（参照A・B） | （未作成。AR-008。粒度基準はPoC設計書4章） | | クラスタ評価とベースラインに用いる |

## テンプレート — `_templates/`

| ファイル | 用途 |
|---|---|
| `experiment-plan.md` | 実験計画書（実験の**実施前**に書く） |
| `experiment-report.md` | 実験レポート（実施後） |
| `issue.md` | 課題・不具合 |
| `adr.md` | 決定記録 |
| `design-doc.md` | 設計書・仕様書（改訂履歴ヘッダ付き） |
