# プロジェクトステータス

> **いま何をしているか**を書く。フェーズ進行時・重要な判断が出たときに更新する。
> 何が存在するかは [INDEX.md](INDEX.md)、何をどう変えてきたかは [CHANGELOG.md](CHANGELOG.md)、決定の根拠は `decisions/` を見ること。
> **判断根拠をこのファイルに書かない。** ADRを起こし、下表からリンクする。

| 項目 | 内容 |
|---|---|
| 現在のフェーズ | **EXP-001 実施中。S-3 完了（W-2 採用）。次は S-4（前処理水準の決定）** |
| 最終更新 | 2026-08-20 |

## フェーズ進捗

| フェーズ | 成果物 | 状態 | レビュー判定 |
|---|---|---|---|
| 要件定義 | [requirements/requirements-topic-extraction-poc.md](requirements/requirements-topic-extraction-poc.md) | **完了**（v2.1・実現可能性B・未確定10件はPoC設計書で解消。`main` へのマージはPoCフェーズ完了時） | **条件付き承認**（レビュー3回。差し戻し2回を経て） |
| PoC設計 | [design/poc-design-topic-extraction.md](design/poc-design-topic-extraction.md) | **完了**（v1.5・想定工数17.0〜18.0人日） | **条件付き承認**（レビュー3回。差し戻し2回を経て） |
| 実験 | [EXP-001 plan.md](experiments/EXP-001-topic-extraction-baseline/plan.md) | **実施中**（S-3 完了 / 全11ステージ中3） | RP-A 通過。**次のゲートは RP-B（S-5 完了時）** |
| アルゴリズム本設計 | | | |
| システム設計 | | | |
| 実装 | | | |
| システム検証 | | | |

## 現在のブロッカー

| # | 内容 | ブロックしている作業 | 対応者 | 期限 |
|---|---|---|---|---|
| 1 | 着手前の確定が必要な未確定事項5件（Q-013 LLMコスト／Q-015 参照リストの粒度／Q-016 一致率の算出定義／Q-017 撤退基準の閾値／**Q-018 分析単位**） | EXP-001 の着手 | PoC設計書 | EXP-001 着手まで |
| 3 | **`poc/topic-extraction-2025` が未 push。** S-1・S-2 完了分、ADR-008 の取り込み、設計書 v1.4、ISSUE-004〜008 を含む | PR の作成 | ユーザー承認待ち | PoCフェーズ完了時 |
| 2 | PoC設計書の未処理指摘7件（20.2節）。**S-5・S-6 期限の3件は ISSUE-003 で解消済み。** 残る到達期限は I-006 → S-9 着手まで | 各ステージの着手 | 担当 | 該当ステージ着手まで |

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
| 2026-08-20 | **多段の実験では、不可逆な決定の直後に `experiment-analyst` の検証を挟むと決定**（RP-A〜RP-D）。撤退基準は「無駄に走り続けること」しか止めず、貪欲決定では誤った前提が下流へ静かに伝播するため。**実験の単位を小さく切る案は、収集だけ・前処理だけでは成立性を判定できないため退けた**（初回に限る） | [ADR-008](decisions/ADR-008-review-checkpoints-in-large-experiments.md) |
| 2026-08-20 | **RP-A が S-2 を差し戻し、ADR-008 が最初の適用で機能した。** 初回 S-2 は設計書 6.1節を確認せず生の `speech` 列を測っており、「短文は大量に存在しない」という結論が反転した（≤10字が 12件 → 3,458件）。**アサーション5件はすべて通過しており、実行の成否では検出できない誤りであった** | [RP-Aレポート](reviews/RP-A_EXP-001-S2-data-quality_20260820.md)、[ISSUE-007](issues/ISSUE-007-s2-aggregation-deviates-from-design/issue.md) |
| 2026-08-20 | **RP-A を通過（3回目）。S-2 を完了し T1 = 10 / T2 = 20 が機械的に確定。** 差し戻し2回はいずれも実質的な誤りを検出した。2回目は「設計に違反したからこそ正しい値が出ていた」状態の指摘であり、**値の妥当性だけを見ていては検出できなかった**。ADR-008 7節の見直し条件2（差し戻し0回なら不要）には該当しない | [RP-Aレポート](reviews/RP-A_EXP-001-S2-data-quality_20260820.md) |
| 2026-08-20 | **S-3 で W-2（SudachiPy モードA）を採用し、S-4 以降で固定。** 決定規則1（SE-A 解釈可能率 35%）で単独首位。**撤退基準 D-2 は全項目通過**し縮退不要。**H-010（議事進行クラスタの分離）は初回観測として成立**。あわせて**LLMを主観評価の評価者にすると別の方式を採用していた**ことが実測で判明（人とLLMの一致率40%、LLM同士は91%） | [config.md](../experiments/EXP-001-topic-extraction-baseline/config.md) |
