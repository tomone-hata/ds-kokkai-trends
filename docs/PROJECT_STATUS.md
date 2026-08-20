# プロジェクトステータス

> **いま何をしているか**を書く。フェーズ進行時・重要な判断が出たときに更新する。
> 何が存在するかは [INDEX.md](INDEX.md)、何をどう変えてきたかは [CHANGELOG.md](CHANGELOG.md)、決定の根拠は `decisions/` を見ること。
> **判断根拠をこのファイルに書かない。** ADRを起こし、下表からリンクする。

| 項目 | 内容 |
|---|---|
| 現在のフェーズ | **EXP-001 実施中。S-1（データ収集）完了・CP-1 通過。次は S-2（データ品質確認）** |
| 最終更新 | 2026-08-20 |

## フェーズ進捗

| フェーズ | 成果物 | 状態 | レビュー判定 |
|---|---|---|---|
| 要件定義 | [requirements/requirements-topic-extraction-poc.md](requirements/requirements-topic-extraction-poc.md) | **完了**（v2.1・実現可能性B・未確定10件はPoC設計書で解消。`main` へのマージはPoCフェーズ完了時） | **条件付き承認**（レビュー3回。差し戻し2回を経て） |
| PoC設計 | [design/poc-design-topic-extraction.md](design/poc-design-topic-extraction.md) | **完了**（v1.2・想定工数17.0〜18.0人日） | **条件付き承認**（レビュー3回。差し戻し2回を経て） |
| 実験 | [EXP-001 plan.md](experiments/EXP-001-topic-extraction-baseline/plan.md) | **実施中**（S-1 完了 / 全11ステージ中1） | 未実施（`report.md` 作成後） |
| アルゴリズム本設計 | | | |
| システム設計 | | | |
| 実装 | | | |
| システム検証 | | | |

## 現在のブロッカー

| # | 内容 | ブロックしている作業 | 対応者 | 期限 |
|---|---|---|---|---|
| 1 | 着手前の確定が必要な未確定事項5件（Q-013 LLMコスト／Q-015 参照リストの粒度／Q-016 一致率の算出定義／Q-017 撤退基準の閾値／**Q-018 分析単位**） | EXP-001 の着手 | PoC設計書 | EXP-001 着手まで |
| 2 | PoC設計書の未処理指摘7件（20.2節）。**S-5・S-6 期限の3件は ISSUE-003 で解消済み。** 残る到達期限は I-006 → S-9 着手まで | 各ステージの着手 | 担当 | 該当ステージ着手まで |
| 3 | **未コミットの変更が溜まっている**（S-1 実装・ISSUE-004/005/006・設計書 v1.2）。`poc/topic-extraction-2025` ブランチ上 | PR の作成 | ユーザー承認待ち | S-2 着手前 |

## 直近の重要な決定

| 日付 | 決定内容 | 根拠となる文書 |
|---|---|---|
| 2026-08-18 | PoCの対象を2025年の1年分（発言118,566件）、本番の対象期間を2019〜2025年（同819,428件）とする | API実測値。[ADR-001](decisions/ADR-001-poc-data-layer.md) 9章 |
| 2026-08-18 | PoC段階ではRDB・Dockerを導入せず、Parquet + DuckDBで完結させる。Postgres + Dockerは本実装フェーズから | [ADR-001](decisions/ADR-001-poc-data-layer.md) |
| 2026-08-18 | ドキュメント運用をID駆動（EXP / ISSUE / ADR）に定める。確定文書の改訂は作業ブランチ上で行う | `.claude/rules/documentation.md` |
| 2026-08-19 | PoC設計書（v0.5）をドラフト作成。**LLMコストの律速はTPMであり費用制限ではないことを確定**し、ベクトル化方式の決定要因を「品質」と「機密境界」に移した。API埋め込みは ADR-007 未起票のため EXP-001 では不実施 | [PoC設計書](design/poc-design-topic-extraction.md) |
| 2026-08-19 | 分析要件定義書を**v2.0として確定**し `requirements/` へ移動。レビュー3回（差し戻し2回→条件付き承認）を経てv1.0とし、その後 [ISSUE-001](issues/ISSUE-001-requirements-analysis-unit-and-review-conditions/issue.md) で**分析単位をPoCの比較項目へ変更**しv2.0。実現可能性B、未確定10件はPoC設計書で解消 | [要件定義書](requirements/requirements-topic-extraction-poc.md)、[3回目レビュー](reviews/レビュー_分析要件定義書-論点抽出PoC_v0.8_20260819.md) |
| 2026-08-20 | **S-1（データ収集）を完了し CP-1 を通過。** 2025年118,566件を稼働0.30時間で取得（期待値と完全一致・重複0）。本番規模への外挿2.06時間であり、**D-1（収集の成立性）は成立**。1月のみの標本は年全体の文字数分布を代表していなかった（中央値 196 対 318） | [config.md](../experiments/EXP-001-topic-extraction-baseline/config.md) |
| 2026-08-20 | **年内の時系列推移を「論点のトレンド」ではなく「会期・委員会構成という既知の構造の再現」として扱うと決定。** H-009 を改定し TM-4・TM-5 を追加。7月0件・9月は単一委員会247件であり、**月次系列は交絡どころか決定関係を含む**。トレンドの解釈は Phase 2（2019〜2025年）へ送る | [ISSUE-005](issues/ISSUE-005-timeseries-scope-and-committee-confound/issue.md)、[PoC設計書](design/poc-design-topic-extraction.md) v1.2 |
