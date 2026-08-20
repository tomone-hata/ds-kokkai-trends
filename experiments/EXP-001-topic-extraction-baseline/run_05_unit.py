"""EXP-001 S-5: 分析単位の決定（PoC設計書 6.3A節 Q-018。U-1 / U-2 の比較）。

比較条件（6.3A.3節）:
  分かち書き = W-2（SudachiPy モードA。S-3 の決定）
  前処理水準 = E-2（文字数 <= 20 を除外。S-4 の決定）
  適用構成 = X-1 相当の1構成のみ（V-1 TF-IDF 生 + C-1 k-means、k=100 の暫定固定）
  乱数シード = 42、L2正規化

**1構成に限る理由**: 単位の比較が目的であり、複数構成を回すと単位と構成が交絡する。

U-2 の構築（6.3A.1節）:
  issueID でグループ化し、speechOrder の昇順で改行連結する。
  分かち書きの前に改行を半角空白へ置換し、区切り文字が語彙へ混入しないようにする。

**シルエット係数は算出しない**（5.2.4節）。**参照リストとの一致率は用いない**（5.3.6節・6.3A.4節）。

実験コードのため、ハードコードは許容する。ただし config.md へ記録すること
（.claude/rules/experiment-code.md 禁止事項2）。
"""
import json
import logging
import random
import re
import resource
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import duckdb
import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize as l2_normalize

# --- ハードコード値（config.md に記録すること） ---
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_GLOB = "data/raw/year=*/month=*/speech.parquet"
OUT_DIR = REPO_ROOT / "outputs" / "EXP-001-topic-extraction-baseline" / "s5_unit"
SEED = 42
EXPECTED_SPEECHES = 117_440      # 工程2A 後の件数（S-2 実測）
EXPECTED_AFTER_E2 = 111_426      # E-2 適用後の件数（S-4 実測）

T2 = 20                          # S-4 で採用した前処理水準 E-2 の閾値
K_CLUSTERS = 100                 # 9.1節（暫定固定）
KMEANS_N_INIT = 3                # S-3・S-4 と同一（設計書に指定なし）
KMEANS_MAX_ITER = 300
MIN_DF = 5                       # S-3・S-4 と同一（設計書に指定なし）
MAX_DF = 0.5                     # 同上
SUBLINEAR_TF = True              # 同上
TOP_TERMS = 20
SE_A_SAMPLE = 20                 # 5.2.1節（単位ごとランダム20件）
KEEP_POS = ("名詞", "動詞", "形容詞")
SUDACHI_MODE = "A"               # W-2（S-3 の決定）

# 撤退基準 D-3（2.3節）
D3A_MAX_SHARE = 80.0             # 最大クラスタの占有率がこれ以上なら単一化
D3B_CLUSTER_RATIO = 5.0          # クラスタ数が対象件数のこれ%を超えたら過分散

# 議事進行マーカー（H-010 の観測用。担当が構成したものであり [推測]）
PROC_MARKERS = ["異議", "起立", "採決", "賛成", "挙手", "速記", "散会", "休憩",
                "動議", "可決", "否決", "討論", "本案", "諸君", "質疑", "理事", "散", "開議"]
PROC_MIN_HITS = 3

RE_SPEAKER_PREFIX = r"^○[^ ]{0,39} "
RE_STAGE_KAKU = r"〔[^〕]{0,60}〕"
RE_STAGE_PAREN = r"\((?:拍手|発言する者あり)\)"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("s5")


def peak_memory_gb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 3)


def assert_output_is_gitignored():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "check-ignore", "-q", str(OUT_DIR)],
                       cwd=REPO_ROOT, capture_output=True)
    assert r.returncode == 0, f"出力先が Git 追跡対象になっている: {OUT_DIR}"
    log.info("アサーション: 出力先は .gitignore 対象である")


def assert_partition_schemas_identical():
    """全パーティションで列構成が一致することを確認する（設計書 13.2節 #2a・ISSUE-006）。"""
    import pyarrow.parquet as pq

    sigs = {}
    for f in sorted(REPO_ROOT.glob("data/raw/year=*/month=*/speech.parquet")):
        sigs.setdefault(tuple(pq.read_schema(f).names), []).append(f.parent.name)
    assert len(sigs) == 1, f"列構成が一致しないパーティションがある: {sigs}"
    log.info("アサーション: 全 %d パーティションで列構成が一致（%d列）",
             len(next(iter(sigs.values()))), len(next(iter(sigs))))


def normalize(text):
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(RE_SPEAKER_PREFIX, "", t)
    t = re.sub(RE_STAGE_KAKU, "", t)
    t = re.sub(RE_STAGE_PAREN, "", t)
    return re.sub(r"\s+", " ", t).strip()


def load_units():
    """工程1・2・2A・3・4（E-2）を適用し、U-1 と U-2 を構築する。"""
    con = duckdb.connect()
    con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{RAW_GLOB}', hive_partitioning=1)")
    rows = con.execute(
        "SELECT speechID, issueID, speechOrder, speech FROM raw "
        "WHERE speechOrder <> 0 ORDER BY issueID, speechOrder").fetchall()
    total, uniq = con.execute("SELECT COUNT(*), COUNT(DISTINCT speechID) FROM raw").fetchone()
    assert total == uniq, f"speechID に重複がある: {total - uniq} 件"
    assert len(rows) == EXPECTED_SPEECHES, f"件数が S-2 の実測と異なる: {len(rows)}"

    # 工程3 正規化 → 工程4 短文除外（E-2）
    kept = [(r[1], r[2], t) for r in rows if len(t := normalize(r[3])) > T2]
    assert len(kept) == EXPECTED_AFTER_E2, f"E-2 適用後の件数が S-4 の実測と異なる: {len(kept)}"
    log.info("U-1: %s 件（E-2 適用後）", f"{len(kept):,}")

    # U-2: issueID でグループ化し speechOrder の昇順で連結（6.3A.1節 手順3・4）
    groups, order = {}, []
    for iid, so, t in kept:
        if iid not in groups:
            groups[iid] = []
            order.append(iid)
        groups[iid].append((so, t))
    u2_texts, u2_counts = [], []
    for iid in order:
        parts = [t for _so, t in sorted(groups[iid], key=lambda x: x[0])]
        u2_texts.append("\n".join(parts))      # 区切りは改行1文字
        u2_counts.append(len(parts))
    # 手順6 アサーション: 連結前後で発言数の合計が一致すること
    assert sum(u2_counts) == len(kept), \
        f"連結前後で発言数が一致しない: {sum(u2_counts)} vs {len(kept)}"
    log.info("U-2: %s 会議（連結前後の発言数一致を確認: %s 件）",
             f"{len(u2_texts):,}", f"{sum(u2_counts):,}")
    return [t for _i, _s, t in kept], u2_texts, u2_counts


def tokenize_w2(texts):
    """W-2: SudachiPy モードA、名詞・動詞・形容詞に限定。改行は半角空白へ置換済み。"""
    from sudachipy import Dictionary, SplitMode

    tok = Dictionary().create()
    out = []
    for i, t in enumerate(texts):
        toks = []
        for chunk in (t[j:j + 10000] for j in range(0, len(t), 10000)):
            for m in tok.tokenize(chunk, SplitMode.A):
                if m.part_of_speech()[0] in KEEP_POS:
                    toks.append(m.normalized_form())
        out.append(toks)
        if (i + 1) % 40000 == 0:
            log.info("  分かち書き: %s 件", f"{i + 1:,}")
    return out


def assert_matrix_sane(X, label):
    """設計書 13.2節 #4・#5。特徴量行列の健全性と L2 正規化を確認する。"""
    import numpy as _np
    data = X.data if hasattr(X, "data") else _np.asarray(X).ravel()
    assert _np.isfinite(data).all(), f"[{label}] 特徴量行列に欠損または無限大がある"
    norms = _np.sqrt(X.multiply(X).sum(axis=1)).A.ravel() if hasattr(X, "multiply") \
        else _np.linalg.norm(X, axis=1)
    nz = norms[norms > 0]
    assert _np.allclose(nz, 1.0, atol=1e-6), \
        f"[{label}] L2正規化されていない行がある（最小 {nz.min():.6f} / 最大 {nz.max():.6f}）"
    log.info("  アサーション[%s]: 欠損・無限大なし / L2ノルム=1（有効 %d 行）", label, len(nz))


def gini(x):
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    return 0.0 if x.sum() == 0 else float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def run_unit(unit, texts):
    t0 = time.monotonic()
    # 6.3A.1節 手順4: 分かち書きの前に区切り文字を半角空白へ置換する
    tokens = tokenize_w2([t.replace("\n", " ") for t in texts])
    tok_sec = round(time.monotonic() - t0, 1)
    assert len(tokens) == len(texts), "分かち書き結果の件数が入力と一致しない"

    t1 = time.monotonic()
    vec = TfidfVectorizer(analyzer=lambda x: x, min_df=MIN_DF, max_df=MAX_DF,
                          lowercase=False, sublinear_tf=SUBLINEAR_TF)
    X = l2_normalize(vec.fit_transform(tokens))
    assert_matrix_sane(X, unit)
    km = KMeans(n_clusters=K_CLUSTERS, random_state=SEED,
                n_init=KMEANS_N_INIT, max_iter=KMEANS_MAX_ITER)
    labels = km.fit_predict(X)
    assert len(labels) == len(texts), "予測結果の件数が入力と一致しない"

    sizes = np.bincount(labels, minlength=K_CLUSTERS)
    n_nonempty = int((sizes > 0).sum())
    max_share = 100.0 * float(sizes.max()) / len(labels)
    cluster_ratio = 100.0 * n_nonempty / len(labels)

    terms = np.array(vec.get_feature_names_out())
    top = {}
    for c in range(K_CLUSTERS):
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            continue
        mean = np.asarray(X[idx].mean(axis=0)).ravel()
        top[int(c)] = [str(t) for t in terms[np.argsort(-mean)[:TOP_TERMS]]]

    # H-010 の観測（単位別）
    proc = [c for c, t in top.items()
            if sum(1 for w in t if any(k in w for k in PROC_MARKERS)) >= PROC_MIN_HITS]
    proc_n = int(sizes[proc].sum()) if proc else 0

    m = {
        "unit": unit, "n_docs": len(texts),
        "mean_tokens": round(float(np.mean([len(x) for x in tokens])), 2),
        "vocab": len(vec.vocabulary_),
        "M-1_n_clusters_nonempty": n_nonempty,
        "M-3_max_cluster_share_pct": round(max_share, 2),
        "M-4_size_gini": round(gini(sizes), 4),
        "cluster_size_min": int(sizes.min()), "cluster_size_median": int(np.median(sizes)),
        "cluster_size_mean": round(float(sizes.mean()), 1),
        "D-3a_breached": max_share >= D3A_MAX_SHARE,
        "D-3b_cluster_ratio_pct": round(cluster_ratio, 4),
        "D-3b_breached": cluster_ratio > D3B_CLUSTER_RATIO,
        "H-010_proc_clusters": len(proc),
        "H-010_proc_docs": proc_n,
        "H-010_proc_pct": round(100.0 * proc_n / len(labels), 2),
        "tokenize_seconds": tok_sec,
        "cluster_seconds": round(time.monotonic() - t1, 1),
        "peak_memory_gb": round(peak_memory_gb(), 2),
    }
    log.info("  [%s] 件数 %s / 語彙 %s / 非空C %d / 最大占有 %.2f%% / 平均サイズ %.1f",
             unit, f"{m['n_docs']:,}", f"{m['vocab']:,}", n_nonempty, max_share, m["cluster_size_mean"])
    log.info("  [%s] D-3a=%s / D-3b=%s（クラスタ数は対象件数の %.4f%%） / H-010 %d個 %.2f%%",
             unit, m["D-3a_breached"], m["D-3b_breached"], cluster_ratio,
             len(proc), m["H-010_proc_pct"])
    return m, labels, sizes, top


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    assert_output_is_gitignored()
    assert_partition_schemas_identical()

    u1_texts, u2_texts, u2_counts = load_units()
    cnt = np.array(u2_counts)
    ch = np.array([len(t) for t in u2_texts])
    scale = {
        "n_meetings": len(u2_texts),
        "speeches_per_meeting": {"mean": round(float(cnt.mean()), 1), "median": int(np.median(cnt)),
                                 "min": int(cnt.min()), "max": int(cnt.max()),
                                 "p90": int(np.percentile(cnt, 90))},
        "chars_per_meeting": {"mean": round(float(ch.mean()), 1), "median": int(np.median(ch)),
                              "min": int(ch.min()), "max": int(ch.max()),
                              "p90": int(np.percentile(ch, 90))},
    }
    (OUT_DIR / "u2_scale.json").write_text(json.dumps(scale, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    log.info("U-2 の規模: 1会議あたり発言 中央値 %d・最大 %d / 文字 中央値 %s・最大 %s",
             scale["speeches_per_meeting"]["median"], scale["speeches_per_meeting"]["max"],
             f"{scale['chars_per_meeting']['median']:,}", f"{scale['chars_per_meeting']['max']:,}")

    results, cache = [], {}
    for unit, texts in [("U-1", u1_texts), ("U-2", u2_texts)]:
        log.info("=== %s ===", unit)
        m, labels, sizes, top = run_unit(unit, texts)
        results.append(m)
        cache[unit] = {"labels": labels, "sizes": sizes, "top_terms": top}
        np.save(OUT_DIR / f"labels_{unit}.npy", labels)
        (OUT_DIR / f"top_terms_{unit}.json").write_text(
            json.dumps(top, ensure_ascii=False, indent=2), encoding="utf-8")

    (OUT_DIR / "metrics.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # --- SE-A: 両単位から各20クラスタ（5.2.1節） ---
    rng = random.Random(SEED)
    items, key = [], []
    for unit in ["U-1", "U-2"]:
        cs = sorted(cache[unit]["top_terms"].keys())
        for c in rng.sample(cs, min(SE_A_SAMPLE, len(cs))):
            items.append({"terms": cache[unit]["top_terms"][c],
                          "size": int(cache[unit]["sizes"][c])})
            key.append({"unit": unit, "cluster_id": c})
    order = list(range(len(items)))
    rng.shuffle(order)
    (OUT_DIR / "se_a_presented.json").write_text(
        json.dumps([{"item_no": i + 1, **items[o]} for i, o in enumerate(order)],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "se_a_key_DO_NOT_OPEN_BEFORE_RATING.json").write_text(
        json.dumps([{"item_no": i + 1, **key[o]} for i, o in enumerate(order)],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("SE-A: %d 件を提示用に出力（単位名を伏せ、シャッフル済み）", len(items))
    log.info("S-5 の計算完了。ピークメモリ %.2f GB", peak_memory_gb())


if __name__ == "__main__":
    main()
