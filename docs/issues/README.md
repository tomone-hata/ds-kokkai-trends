# 課題・不具合 台帳

> 1件につき1ディレクトリ（`ISSUE-NNN-{slug}/`）を作り、本体を `issue.md` に置く。
> **非公開の証跡は `private/issues/ISSUE-NNN-{slug}/` へ置き、`issue.md` からはパスのみ参照する。**
> 雛形は `docs/_templates/issue.md`。
> **解決済みの項目も削除しない。** 同じ調査を繰り返さないための記録である。

## 種別

| 種別 | 対象 |
|---|---|
| 不具合 | 自分たちのコードの誤り |
| 外部要因 | 国会会議録APIの仕様変更・障害など、制御外の変化 |
| 改善 | 動いてはいるが直したいもの |
| 調査 | 原因不明の事象、または判断のための事前調査 |

## 一覧

| ID | 種別 | 内容 | 状態 | 起票日 | 解決日 | 影響した文書 |
|---|---|---|---|---|---|---|
| [ISSUE-001](ISSUE-001-requirements-analysis-unit-and-review-conditions/issue.md) | 改善 | 分析要件定義書 v1.0 の改訂（分析単位の根拠の飛躍、およびレビュー条件B-2〜B-6） | **対応済** | 2026-08-19 | 2026-08-19 | [要件定義書](../requirements/requirements-topic-extraction-poc.md) v1.0 → **v2.0** |
| [ISSUE-002](ISSUE-002-requirements-ar006-and-unit-reference-scope/issue.md) | 改善 | AR-006 受入条件の充足方法、および分析単位と参照リストの観測範囲 | **対応済** | 2026-08-19 | 2026-08-19 | [要件定義書](../requirements/requirements-topic-extraction-poc.md) v2.0 → **v2.1** |
| [ISSUE-003](ISSUE-003-poc-design-stage-and-decision-rules/issue.md) | 改善 | PoC設計書の構成確定ステージ、決定規則の主観評価の特定、D-3 の扱いの用語整理 | **対応済** | 2026-08-20 | 2026-08-20 | [PoC設計書](../design/poc-design-topic-extraction.md) v1.0 → **v1.1** |

状態: 調査中 / 対応中 / 対応済 / 保留 / 仕様として受容

## 運用ルール

1. **調査ログは追記のみ。** 否定された仮説も消さない
2. **設計変更を伴う対策の場合、`design/` の該当文書を改訂し、版数を上げて起票IDを改訂履歴に残す**
3. **証跡は公開可否で置き分ける。** 公開可能なもの（エラーメッセージ、本文を除いたレスポンス構造、件数・統計値、再現スクリプト）は `ISSUE-NNN-{slug}/` 直下、非公開のもの（生レスポンス、詳細ログ、個票の抜き出し）は `private/issues/ISSUE-NNN-{slug}/` へ置く
4. **取得データは機密扱い。生の発言と話者を `docs/` に書かない**（発言本文・発言者名。`speechID` は伏せる）。`CLAUDE.md` 3章、[ADR-002](../decisions/ADR-002-public-private-boundary.md)
