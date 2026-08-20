"""EXP-001 S-2: データ品質確認（PoC設計書 3.3節 Q-1〜Q-7）。

集計は全て DuckDB の SQL で書く（ADR-001）。pandas での手続き的な集計を既定にしない。

出力先は outputs/EXP-001-topic-extraction-baseline/s2_quality/（.gitignore 対象）。
Q-4 の中間結果は発言本文に由来するため、docs/ へは集計値のみを載せる。

ISSUE-007（RP-A の差し戻し）により、以下を設計書に合わせている。
  - 測定対象を「正規化後の本文長」にする（設計書 6.1節 工程3 → 工程4）。生の値も併記する
  - ビン境界を 6.3.1節 手順1 のとおり上端を含む形にする
  - ビンを 10字刻み10本 + 101〜200 + 201〜 にする
  - 重複率を 6.3.1節 手順2 の定義（1 − ユニーク ÷ 件数）にする
  - 院・会議種別・月のセグメント別除外率を算出する
ISSUE-008 により、工程2A（会議録冒頭情報の除外）を集計の前に適用する。
ISSUE-007 追記（D-5・D-6）により、以下も設計書に合わせている。
  - 正規化を 6.2節の順序（3-1 NFKC → 3-2 空白の統一 → 3-3 記号の除去）で実装する
  - 3-3 の正規表現は NFKC・空白統一を適用した後の表記で定義する
  - T2 を 6.3.1節 手順4（T1 の1つ上のビンの上端）で決める

実験コードのため、ハードコードは許容する。ただし config.md へ記録すること
（.claude/rules/experiment-code.md 禁止事項2）。
"""
import json
import logging
import random
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import duckdb

# --- ハードコード値（config.md に記録すること） ---
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_GLOB = "data/raw/year=*/month=*/speech.parquet"
OUT_DIR = REPO_ROOT / "outputs" / "EXP-001-topic-extraction-baseline" / "s2_quality"
EXPECTED_RECORDS = 118_566      # S-1 の実測値（API の numberOfRecords 合計）
EXPECTED_HEADER_RECORDS = 1_126  # 工程2A で除外される会議録冒頭情報（= 会議数）
EXPECTED_FILE_COLUMNS = 22      # Parquet の列数。hive の year・month を除く
SEED = 42                       # S-2 に乱数処理は無いが、規約により固定する
TOP_N = 50                      # Q-2・Q-6 で保存する上位件数

# 設計書 6.3.1節 手順1 のビン。値は各ビンの「上端」であり、区間は上端を含む。
# 1〜10, 11〜20, ..., 91〜100, 101〜200, 201〜
DUP_BIN_UPPER = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200]
# 短文除外の閾値候補（Q-3 の走査点）
THRESHOLD_CANDIDATES = [5, 10, 15, 20, 30, 50, 100, 150, 200]

# --- 6.2節 3-3 の除去パターン（S-2 の実データ確認により確定。ISSUE-007 対策1・9） ---
# 重要: 3-3 は 3-1（NFKC）と 3-2（空白の統一）の「後」に適用される（6.2節は順序も仕様）。
# NFKC により全角空白 U+3000 は半角空白へ、全角丸括弧 （） は半角 () へ変換される。
# したがって以下のパターンは、いずれも NFKC・空白統一を適用した後の表記で定義する。
# 話者表記: 3-2 適用後、全発言が `○` で始まり、先頭40字以内に半角空白を持つ
RE_SPEAKER_PREFIX = r"^○[^ ]{0,39} "
# ト書き: 〔〕 は NFKC で変換されない
RE_STAGE_KAKU = r"〔[^〕]{0,60}〕"
# ト書き（丸括弧）: NFKC 適用後は半角括弧になる
RE_STAGE_PAREN = r"\((?:拍手|発言する者あり)\)"


def normalize(text):
    """6.2節の正規化。順序は 3-1 → 3-2 → 3-3 で固定（節題が「順序も固定」）。"""
    t = unicodedata.normalize("NFKC", text)              # 3-1
    t = re.sub(r"\s+", " ", t).strip()                   # 3-2
    t = re.sub(RE_SPEAKER_PREFIX, "", t)                 # 3-3
    t = re.sub(RE_STAGE_KAKU, "", t)
    t = re.sub(RE_STAGE_PAREN, "", t)
    return re.sub(r"\s+", " ", t).strip()                # 3-2 の再適用（除去で生じた連続空白）


REQUIRED_COLUMNS = [
    "speechID", "issueID", "session", "nameOfHouse", "nameOfMeeting", "issue",
    "date", "closing", "speechOrder", "speaker", "speakerGroup",
    "speakerPosition", "speakerRole", "speech", "raw_json", "year", "month",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("s2")


def assert_output_is_gitignored():
    """出力先が .gitignore 対象であることを確認する（experiment-code.md 禁止事項6）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "check-ignore", "-q", str(OUT_DIR)], cwd=REPO_ROOT, capture_output=True
    )
    assert r.returncode == 0, f"出力先が Git 追跡対象になっている: {OUT_DIR}"
    log.info("アサーション: 出力先は .gitignore 対象である")


def assert_partition_schemas_identical():
    """全パーティションで列構成が一致することを確認する（設計書 13.2節 #2a・ISSUE-006）。"""
    import pyarrow.parquet as pq

    sigs = {}
    for f in sorted(REPO_ROOT.glob("data/raw/year=*/month=*/speech.parquet")):
        sigs.setdefault(tuple(pq.read_schema(f).names), []).append(f.parent.name)
    assert len(sigs) == 1, f"列構成が一致しないパーティションがある: {sigs}"
    cols = next(iter(sigs))
    assert len(cols) == EXPECTED_FILE_COLUMNS, f"列数が想定と異なる: {len(cols)}"
    log.info("アサーション: 全 %d パーティションで列構成が一致（%d列）",
             len(next(iter(sigs.values()))), len(cols))


def save(name, rows, columns):
    path = OUT_DIR / f"{name}.json"
    path.write_text(
        json.dumps([dict(zip(columns, r)) for r in rows], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    log.info("保存: %s（%d行）", path.relative_to(REPO_ROOT), len(rows))


def q(con, sql):
    cur = con.execute(sql)
    return cur.fetchall(), [d[0] for d in cur.description]


def bin_case_sql(len_expr):
    """設計書 6.3.1節 手順1 のビン。上端を含む区間として割り当てる。"""
    whens = " ".join(
        f"WHEN {len_expr} <= {u} THEN {u}" for u in DUP_BIN_UPPER
    )
    return f"CASE {whens} ELSE 99999 END"


def main():
    random.seed(SEED)
    assert_output_is_gitignored()
    assert_partition_schemas_identical()

    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW raw AS SELECT * FROM read_parquet('{RAW_GLOB}', hive_partitioning=1)"
    )
    summary = {"seed": SEED}

    actual = {d[0] for d in con.execute("DESCRIBE SELECT * FROM raw").fetchall()}
    missing = [c for c in REQUIRED_COLUMNS if c not in actual]
    assert not missing, f"想定列が存在しない: {missing}"
    log.info("アサーション: 想定列 %d 件すべて存在", len(REQUIRED_COLUMNS))

    # --- Q-1: 総件数と speechID の重複（工程2A の前に判定する） ---
    total, uniq = con.execute("SELECT COUNT(*), COUNT(DISTINCT speechID) FROM raw").fetchone()
    dup = total - uniq
    assert dup == 0, f"speechID に重複がある: {dup} 件"
    assert total == EXPECTED_RECORDS, f"総件数が S-1 の実測と異なる: {total}"
    log.info("Q-1: 総件数 %s / ユニーク %s / 重複 %s", f"{total:,}", f"{uniq:,}", dup)
    summary["Q-1"] = {"total": total, "unique_speech_id": uniq, "duplicates": dup}

    # --- 工程2A: 会議録冒頭情報の除外（ISSUE-008・設計書 6.1節） ---
    n_header, n_by_speaker, n_meetings = con.execute("""
        SELECT SUM(CASE WHEN speechOrder = 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN speaker = '会議録情報' THEN 1 ELSE 0 END),
               COUNT(DISTINCT issueID) FROM raw""").fetchone()
    # speechOrder=0 と speaker='会議録情報' が同一集合であること（API 側の変化の検出）
    mismatch = con.execute("""
        SELECT COUNT(*) FROM raw WHERE (speechOrder = 0) <> (speaker = '会議録情報')""").fetchone()[0]
    assert mismatch == 0, f"speechOrder=0 と speaker='会議録情報' が一致しない: {mismatch} 件"
    assert n_header == EXPECTED_HEADER_RECORDS, f"冒頭情報の件数が想定と異なる: {n_header}"
    assert n_header == n_meetings, f"冒頭情報が1会議1件でない: {n_header} vs {n_meetings}"
    log.info("工程2A: 会議録冒頭情報 %s 件を除外（会議数 %s と一致）", f"{n_header:,}", f"{n_meetings:,}")
    summary["工程2A"] = {"excluded": n_header, "by_speaker_label": n_by_speaker,
                         "meetings": n_meetings, "remaining": total - n_header}

    # --- 正規化（6.2節 3-1〜3-3。順序も仕様） ---
    # NFKC は DuckDB の組込関数に無いため Python 側で適用し、Arrow テーブルとして結合する。
    # 集計は SQL のまま（ADR-001）。正規化は集計ではなく前処理である。
    import pyarrow as pa

    pairs = con.execute(
        "SELECT speechID, speech FROM raw WHERE speechOrder <> 0"
    ).fetchall()
    norm_map = pa.table({
        "speechID": pa.array([p[0] for p in pairs], pa.string()),
        "norm": pa.array([normalize(p[1]) for p in pairs], pa.string()),
    })
    con.register("norm_map", norm_map)
    con.execute("""
        CREATE VIEW s AS
        SELECT r.*, n.norm FROM raw r JOIN norm_map n USING (speechID)
        WHERE r.speechOrder <> 0""")
    n_speech = con.execute("SELECT COUNT(*) FROM s").fetchone()[0]
    assert n_speech == total - n_header
    # 話者表記の除去が全件で効いたこと
    left = con.execute("SELECT COUNT(*) FROM s WHERE norm LIKE '○%'").fetchone()[0]
    assert left == 0, f"話者表記が除去されていない発言がある: {left} 件"
    log.info("正規化: %s 件に適用（話者表記の残存 0 件）", f"{n_speech:,}")

    r, cols = q(con, """SELECT ROUND(AVG(LENGTH(speech)-LENGTH(norm)),2) AS mean_removed,
        MEDIAN(LENGTH(speech)-LENGTH(norm)) AS median_removed,
        MAX(LENGTH(speech)-LENGTH(norm)) AS max_removed, MIN(LENGTH(norm)) AS min_norm_len
        FROM s""")
    save("norm_effect", r, cols)
    summary["正規化の効果"] = dict(zip(cols, r[0]))
    log.info("正規化で減る文字数: 平均 %s / 中央値 %s", r[0][0], r[0][1])

    # --- Q-2: 件数分布 ---
    for name, sql in [
        ("q2_by_month", """SELECT month, COUNT(*) AS n, COUNT(DISTINCT issueID) AS meetings,
             COUNT(DISTINCT nameOfMeeting) AS meeting_names, COUNT(DISTINCT date) AS days
             FROM s GROUP BY month ORDER BY month"""),
        ("q2_by_house", "SELECT nameOfHouse, COUNT(*) AS n FROM s GROUP BY 1 ORDER BY 2 DESC"),
        ("q2_by_meeting", f"""SELECT nameOfMeeting, COUNT(*) AS n, COUNT(DISTINCT issueID) AS meetings,
             MIN(month) AS first_month, MAX(month) AS last_month
             FROM s GROUP BY 1 ORDER BY 2 DESC LIMIT {TOP_N}"""),
        ("q2_by_session", """SELECT session, COUNT(*) AS n, MIN(date) AS from_date, MAX(date) AS to_date
             FROM s GROUP BY 1 ORDER BY 1"""),
    ]:
        save(name, *q(con, sql))
    summary["Q-2"] = {
        "distinct_meeting_names": con.execute("SELECT COUNT(DISTINCT nameOfMeeting) FROM s").fetchone()[0],
        "distinct_issue_id": con.execute("SELECT COUNT(DISTINCT issueID) FROM s").fetchone()[0],
    }

    # --- Q-3: 文字数分布。正規化後を主とし、生を併記する ---
    for label, col in [("norm", "norm"), ("raw", "speech")]:
        rows, cols = q(con, f"""
            SELECT '{label}' AS target, COUNT(*) AS n, ROUND(AVG(LENGTH({col})),1) AS mean,
              MIN(LENGTH({col})) AS min,
              QUANTILE_CONT(LENGTH({col}),0.01) AS p1, QUANTILE_CONT(LENGTH({col}),0.05) AS p5,
              QUANTILE_CONT(LENGTH({col}),0.10) AS p10, QUANTILE_CONT(LENGTH({col}),0.25) AS p25,
              MEDIAN(LENGTH({col})) AS p50, QUANTILE_CONT(LENGTH({col}),0.75) AS p75,
              QUANTILE_CONT(LENGTH({col}),0.90) AS p90, QUANTILE_CONT(LENGTH({col}),0.99) AS p99,
              MAX(LENGTH({col})) AS max, SUM(LENGTH({col})) AS total_chars
            FROM s""")
        save(f"q3_length_{label}", rows, cols)
        summary[f"Q-3-{label}"] = dict(zip(cols, rows[0]))
    log.info("Q-3: 正規化後 平均 %s / 中央値 %s / 最大 %s",
             summary["Q-3-norm"]["mean"], summary["Q-3-norm"]["p50"], summary["Q-3-norm"]["max"])

    cand = ", ".join(str(t) for t in THRESHOLD_CANDIDATES)
    rows, cols = q(con, f"""
        SELECT t AS threshold,
          SUM(CASE WHEN LENGTH(norm) <= t THEN 1 ELSE 0 END) AS excluded_norm,
          ROUND(100.0*SUM(CASE WHEN LENGTH(norm) <= t THEN 1 ELSE 0 END)/COUNT(*),3) AS excluded_norm_pct,
          SUM(CASE WHEN LENGTH(speech) <= t THEN 1 ELSE 0 END) AS excluded_raw,
          ROUND(100.0*SUM(CASE WHEN LENGTH(speech) <= t THEN 1 ELSE 0 END)/COUNT(*),3) AS excluded_raw_pct
        FROM s, (SELECT UNNEST([{cand}]) AS t) GROUP BY t ORDER BY t""")
    save("q3_threshold_candidates", rows, cols)
    summary["Q-3-thresholds"] = [dict(zip(cols, r)) for r in rows]

    # --- Q-4: 重複率。設計書 6.3.1節 手順1・2 のとおり ---
    for label, col in [("norm", "norm"), ("raw", "speech")]:
        rows, cols = q(con, f"""
            WITH d AS (SELECT {col} AS t, COUNT(*) AS c FROM s GROUP BY {col}),
                 b AS (SELECT t, c, {bin_case_sql(f'LENGTH(t)')} AS bin FROM d)
            SELECT bin AS bin_upper, COUNT(*) AS distinct_texts, SUM(c) AS n,
              ROUND(100.0*(1 - COUNT(*)::DOUBLE / SUM(c)),2) AS dup_rate_design,
              ROUND(100.0*SUM(CASE WHEN c>1 THEN c ELSE 0 END)/SUM(c),2) AS dup_rate_impl,
              MAX(c) AS max_repeat
            FROM b GROUP BY bin ORDER BY bin""")
        save(f"q4_duplicate_by_bin_{label}", rows, cols)
        summary[f"Q-4-{label}"] = [dict(zip(cols, r)) for r in rows]

    rows, cols = q(con, """
        WITH d AS (SELECT norm, COUNT(*) AS c FROM s GROUP BY norm)
        SELECT COUNT(*) AS distinct_texts, SUM(c) AS total,
          ROUND(100.0*(1 - COUNT(*)::DOUBLE/SUM(c)),2) AS dup_rate_design,
          ROUND(100.0*SUM(CASE WHEN c>1 THEN c ELSE 0 END)/SUM(c),2) AS dup_rate_impl,
          MAX(c) AS max_repeat FROM d""")
    save("q4_duplicate_overall_norm", rows, cols)
    summary["Q-4-overall"] = dict(zip(cols, rows[0]))

    # T1・T2 の機械的決定（6.3.1節 手順3・4）
    # 手順3: 重複率（手順2 の定義）が 50% を超える最大のビンの上端を T1 とする
    # 手順4: T1 の1つ上のビンの上端を T2 とする
    bins = [r for r in summary["Q-4-norm"] if r["bin_upper"] != 99999]
    over = [r["bin_upper"] for r in bins if r["dup_rate_design"] > 50]
    assert over, "重複率が50%を超えるビンが無く、6.3.1節 手順3 で T1 が決まらない"
    t1 = max(over)
    idx = DUP_BIN_UPPER.index(t1)
    assert idx + 1 < len(DUP_BIN_UPPER), "T1 が最上位ビンであり、手順4 で T2 が決まらない"
    t2 = DUP_BIN_UPPER[idx + 1]
    excl = {r["threshold"]: (r["excluded_norm"], r["excluded_norm_pct"])
            for r in summary["Q-3-thresholds"]}
    summary["T1_T2"] = {
        "T1": t1, "T2": t2,
        "rule": "6.3.1節 手順3（重複率50%超の最大ビンの上端）/ 手順4（その1つ上のビンの上端）",
        "bins_over_50pct": over,
        "E-1_excluded": excl.get(t1), "E-2_excluded": excl.get(t2),
    }
    log.info("6.3.1節の手順による T1 = %s（除外 %s件）/ T2 = %s（除外 %s件）",
             t1, excl.get(t1, ("-",))[0], t2, excl.get(t2, ("-",))[0])

    rows, cols = q(con, f"""
        SELECT norm, COUNT(*) AS repeats, LENGTH(norm) AS len, COUNT(DISTINCT nameOfMeeting) AS meetings
        FROM s GROUP BY norm HAVING COUNT(*)>1 ORDER BY 2 DESC LIMIT {TOP_N}""")
    save("q4_top_duplicates_WITH_TEXT", rows, cols)
    log.warning("q4_top_duplicates_WITH_TEXT.json は発言本文を含む。docs/ へ転記しない")

    # --- Q-5: 欠損率 ---
    parts = [
        f"SELECT '{c}' AS column_name, SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS nulls, "
        f"SUM(CASE WHEN CAST({c} AS VARCHAR)='' THEN 1 ELSE 0 END) AS empties, "
        f"ROUND(100.0*SUM(CASE WHEN {c} IS NULL OR CAST({c} AS VARCHAR)='' THEN 1 ELSE 0 END)/COUNT(*),3) AS missing_pct FROM s"
        for c in sorted(actual)
    ]
    rows, cols = q(con, " UNION ALL ".join(parts) + " ORDER BY 4 DESC, 1")
    save("q5_missing_rate", rows, cols)
    summary["Q-5"] = [dict(zip(cols, r)) for r in rows if r[3] > 0]

    # --- Q-6: 集計軸のユニーク値 ---
    for name, col in [("q6_speaker_group", "speakerGroup"), ("q6_speaker_position", "speakerPosition"),
                      ("q6_speaker_role", "speakerRole"), ("q6_meeting_name", "nameOfMeeting")]:
        save(name, *q(con, f"""
            SELECT {col} AS value, COUNT(*) AS n, COUNT(DISTINCT month) AS months_present,
              MIN(month) AS first_month, MAX(month) AS last_month
            FROM s WHERE {col} IS NOT NULL AND {col} <> '' GROUP BY 1 ORDER BY 2 DESC LIMIT {TOP_N}"""))
        summary.setdefault("Q-6", {})[col] = con.execute(
            f"SELECT COUNT(DISTINCT {col}) FROM s WHERE {col} IS NOT NULL AND {col} <> ''").fetchone()[0]

    save("q6_speaker_group_coverage", *q(con, """
        SELECT speakerGroup AS value, COUNT(*) AS n, COUNT(DISTINCT month) AS months_present,
          MIN(month) AS first_month, MAX(month) AS last_month
        FROM s WHERE speakerGroup IS NOT NULL AND speakerGroup <> ''
        GROUP BY 1 HAVING COUNT(*) >= 100 ORDER BY months_present ASC, n DESC"""))

    # --- Q-7: 会議種別による差（文字数とフォーマット） ---
    mt = """CASE WHEN nameOfMeeting LIKE '%本会議%' THEN '本会議'
                 WHEN nameOfMeeting LIKE '%委員会%' THEN '委員会'
                 WHEN nameOfMeeting LIKE '%調査会%' THEN '調査会'
                 WHEN nameOfMeeting LIKE '%審査会%' THEN '審査会'
                 ELSE 'その他' END"""
    rows, cols = q(con, f"""
        SELECT {mt} AS meeting_type, COUNT(*) AS n,
          ROUND(AVG(LENGTH(norm)),1) AS mean_norm, MEDIAN(LENGTH(norm)) AS p50_norm,
          QUANTILE_CONT(LENGTH(norm),0.9) AS p90_norm, MAX(LENGTH(norm)) AS max_norm,
          ROUND(AVG(LENGTH(speech)-LENGTH(norm)),2) AS mean_removed
        FROM s GROUP BY 1 ORDER BY 2 DESC""")
    save("q7_by_meeting_type", rows, cols)
    summary["Q-7"] = [dict(zip(cols, r)) for r in rows]

    save("q7_format_by_meeting_type", *q(con, f"""
        SELECT {mt} AS meeting_type, COUNT(*) AS n,
          ROUND(100.0*SUM(CASE WHEN speech LIKE '%' || chr(10) || '%' THEN 1 ELSE 0 END)/COUNT(*),2) AS has_newline_pct,
          ROUND(100.0*SUM(CASE WHEN speech LIKE '%〔%' THEN 1 ELSE 0 END)/COUNT(*),2) AS has_stage_kaku_pct,
          ROUND(100.0*SUM(CASE WHEN speech LIKE '%（拍手%' THEN 1 ELSE 0 END)/COUNT(*),2) AS has_applause_pct,
          ROUND(100.0*SUM(CASE WHEN speech LIKE '%（%' THEN 1 ELSE 0 END)/COUNT(*),2) AS has_paren_pct
        FROM s GROUP BY 1 ORDER BY 2 DESC"""))

    # --- セグメント別の除外率（ISSUE-007 対策6。6.3.2節の決定規則は総件数しか見ない） ---
    for name, seg in [("seg_by_house", "nameOfHouse"), ("seg_by_month", "month"),
                      ("seg_by_meeting_type", mt)]:
        save(name, *q(con, f"""
            SELECT {seg} AS segment, COUNT(*) AS n,
              {", ".join(f"ROUND(100.0*SUM(CASE WHEN LENGTH(norm)<={t} THEN 1 ELSE 0 END)/COUNT(*),2) AS excl_{t}" for t in [10,20,30,50])}
            FROM s GROUP BY 1 ORDER BY 2 DESC"""))

    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    log.info("S-2 完了。出力先: %s", OUT_DIR.relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()
