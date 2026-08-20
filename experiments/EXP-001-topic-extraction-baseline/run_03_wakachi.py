"""EXP-001 S-3: 分かち書きの決定（PoC設計書 7章 W-1〜W-4 の比較）。

処理順序は設計書 6.1節に従う。
  1 speechID の重複除去 / 2 期間の絞り込み / 2A 会議録冒頭情報の除外（ISSUE-008）
  3 テキスト正規化（6.2節。順序 3-1 NFKC → 3-2 空白 → 3-3 記号）
  4 短文除外 → **E-0（除外なし）の暫定固定のため実施しない**（7.1節）
  4A 分析単位 → **U-1（発言単位）の暫定固定のため何もしない**
  5 分かち書き（W-1〜W-4）/ 6 TF-IDF / 7 L2正規化 / 8 k-means（k=100 暫定固定）

**シルエット係数は算出しない**（5.2.4節。盲検化手順1 の実効性を保つため）。

出力は outputs/EXP-001-topic-extraction-baseline/s3_wakachi/（.gitignore 対象）。
SE-A 用の提示ファイルは方式名を伏せてシャッフルする（5.2.1節）。

実験コードのため、ハードコードは許容する。ただし config.md へ記録すること
（.claude/rules/experiment-code.md 禁止事項2）。
"""
import argparse
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
OUT_DIR = REPO_ROOT / "outputs" / "EXP-001-topic-extraction-baseline" / "s3_wakachi"
SEED = 42
EXPECTED_SPEECHES = 117_440      # 工程2A 後の件数（S-2 実測）

K_CLUSTERS = 100                 # 9.1節。S-3〜S-5 は k=100 の暫定固定
KMEANS_N_INIT = 3                # 設計書に指定なし。config.md に根拠を記録する
KMEANS_MAX_ITER = 300            # scikit-learn の既定値

# TF-IDF の文書頻度による足切り。**設計書 7.1節は適用を求めるが値を定めていない。**
# 値の選定根拠は config.md に記録する。
MIN_DF = 5                       # 絶対件数。117,440件に対し 0.004%
MAX_DF = 0.5                     # 割合。半数超の文書に現れる語を除く

TOP_TERMS = 20                   # 特徴語の件数（5章・5.2.1節）
SE_A_SAMPLE = 20                 # SE-A の提示件数（方式ごと。5.2.1節）

# 品詞の絞り込み（7.1節。ストップワードリストを使わず品詞で代替する）
KEEP_POS = ("名詞", "動詞", "形容詞")

# 6.2節 3-3 の除去パターン（S-2 で確定。NFKC・空白統一の適用後の表記）
RE_SPEAKER_PREFIX = r"^○[^ ]{0,39} "
RE_STAGE_KAKU = r"〔[^〕]{0,60}〕"
RE_STAGE_PAREN = r"\((?:拍手|発言する者あり)\)"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S", stream=sys.stdout,
)
log = logging.getLogger("s3")


def peak_memory_gb():
    """ピークメモリ（GB）。D-2d の判定に用いる。macOS の ru_maxrss はバイト。"""
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
    """6.2節の正規化。順序 3-1 → 3-2 → 3-3 は仕様である。"""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(RE_SPEAKER_PREFIX, "", t)
    t = re.sub(RE_STAGE_KAKU, "", t)
    t = re.sub(RE_STAGE_PAREN, "", t)
    return re.sub(r"\s+", " ", t).strip()


def load_speeches(limit=None):
    """工程1・2・2A・3 を適用して正規化済み本文を返す（工程4 は E-0 のため行わない）。"""
    con = duckdb.connect()
    con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{RAW_GLOB}', hive_partitioning=1)")
    total, uniq = con.execute("SELECT COUNT(*), COUNT(DISTINCT speechID) FROM raw").fetchone()
    assert total == uniq, f"speechID に重複がある: {total - uniq} 件"
    sql = "SELECT speechID, speech FROM raw WHERE speechOrder <> 0 ORDER BY speechID"
    if limit:
        sql += f" LIMIT {limit}"
    rows = con.execute(sql).fetchall()
    if not limit:
        assert len(rows) == EXPECTED_SPEECHES, f"件数が S-2 の実測と異なる: {len(rows)}"
    ids = [r[0] for r in rows]
    texts = [normalize(r[1]) for r in rows]
    assert all(texts), "正規化後に空文字となった発言がある"
    log.info("読み込み: %s 件（工程2A 後・正規化済み。E-0 のため短文除外なし）", f"{len(texts):,}")
    return ids, texts


def tokenize_sudachi(texts, mode_name):
    """W-1（モードC）/ W-2（モードA）。名詞・動詞・形容詞に限定する（7.1節）。"""
    from sudachipy import Dictionary, SplitMode

    mode = {"C": SplitMode.C, "A": SplitMode.A}[mode_name]
    tok = Dictionary().create()
    out = []
    for i, t in enumerate(texts):
        # SudachiPy は入力長に上限があるため分割して渡す
        toks = []
        for chunk in (t[j:j + 10000] for j in range(0, len(t), 10000)):
            for m in tok.tokenize(chunk, mode):
                if m.part_of_speech()[0] in KEEP_POS:
                    toks.append(m.normalized_form())
        out.append(toks)
        if (i + 1) % 20000 == 0:
            log.info("  分かち書き %s: %s 件", mode_name, f"{i + 1:,}")
    return out


def tokenize_ngram(texts, n):
    """W-3（2-gram）/ W-4（3-gram）。空白を除いた文字 n-gram。"""
    out = []
    for t in texts:
        s = t.replace(" ", "")
        out.append([s[i:i + n] for i in range(len(s) - n + 1)])
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


def run_method(mid, label, tokens, cache):
    """1方式について TF-IDF → L2正規化 → k-means を実行し、指標を返す。"""
    m = {"method_id": mid, "label": label}
    t0 = time.monotonic()

    m["WM-2_mean_tokens"] = round(float(np.mean([len(x) for x in tokens])), 2)
    m["WM-1_vocab_before_min_df"] = len({w for x in tokens for w in x})

    vec = TfidfVectorizer(
        analyzer=lambda x: x,          # 分かち書き済みのトークン列をそのまま使う
        min_df=MIN_DF, max_df=MAX_DF, lowercase=False, sublinear_tf=True,
    )
    X = vec.fit_transform(tokens)
    m["WM-1_vocab_after_min_df"] = len(vec.vocabulary_)
    m["matrix_shape"] = list(X.shape)
    m["matrix_nnz"] = int(X.nnz)
    m["matrix_density_pct"] = round(100.0 * X.nnz / (X.shape[0] * X.shape[1]), 4)
    m["vectorize_seconds"] = round(time.monotonic() - t0, 1)
    log.info("  [%s] 語彙 %s → %s / 平均トークン %s / %s 秒", mid,
             f"{m['WM-1_vocab_before_min_df']:,}", f"{m['WM-1_vocab_after_min_df']:,}",
             m["WM-2_mean_tokens"], m["vectorize_seconds"])

    X = l2_normalize(X)                # 工程7（5.1節の距離統一）
    assert_matrix_sane(X, mid)
    t1 = time.monotonic()
    km = KMeans(n_clusters=K_CLUSTERS, random_state=SEED,
                n_init=KMEANS_N_INIT, max_iter=KMEANS_MAX_ITER)
    labels = km.fit_predict(X)
    m["cluster_seconds"] = round(time.monotonic() - t1, 1)
    assert len(labels) == X.shape[0], "予測結果の件数が入力と一致しない"

    sizes = np.bincount(labels, minlength=K_CLUSTERS)
    m["M-1_n_clusters_nonempty"] = int((sizes > 0).sum())
    m["M-3_max_cluster_share_pct"] = round(100.0 * float(sizes.max()) / len(labels), 2)
    m["M-4_size_gini"] = round(float(gini(sizes)), 4)
    m["cluster_size_min"] = int(sizes.min())
    m["cluster_size_median"] = int(np.median(sizes))
    m["peak_memory_gb"] = round(peak_memory_gb(), 2)
    log.info("  [%s] 非空クラスタ %d / 最大占有率 %.2f%% / %s 秒 / ピーク %.2fGB",
             mid, m["M-1_n_clusters_nonempty"], m["M-3_max_cluster_share_pct"],
             m["cluster_seconds"], m["peak_memory_gb"])

    # 特徴語トップ20（クラスタ内の平均TF-IDF値の上位。設計書 5章）
    terms = np.array(vec.get_feature_names_out())
    top = {}
    for c in range(K_CLUSTERS):
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            continue
        mean = np.asarray(X[idx].mean(axis=0)).ravel()
        top[int(c)] = [str(t) for t in terms[np.argsort(-mean)[:TOP_TERMS]]]
    cache[mid] = {"labels": labels, "sizes": sizes, "top_terms": top}
    m["total_seconds"] = round(time.monotonic() - t0, 1)
    return m


def gini(x):
    """M-4 不均衡度。クラスタサイズのジニ係数。"""
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    if x.sum() == 0:
        return 0.0
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def build_se_a(cache, methods):
    """SE-A 提示ファイル。方式名を伏せ、全方式をまとめてシャッフルする（5.2.1節）。"""
    rng = random.Random(SEED)
    items, key = [], []
    for mid, _label in methods:
        cs = [c for c, _ in cache[mid]["top_terms"].items()]
        picked = rng.sample(cs, min(SE_A_SAMPLE, len(cs)))
        for c in picked:
            items.append({"terms": cache[mid]["top_terms"][c],
                          "size": int(cache[mid]["sizes"][c])})
            key.append({"method_id": mid, "cluster_id": c})
    order = list(range(len(items)))
    rng.shuffle(order)
    presented = [{"item_no": i + 1, **items[o]} for i, o in enumerate(order)]
    keymap = [{"item_no": i + 1, **key[o]} for i, o in enumerate(order)]
    (OUT_DIR / "se_a_presented.json").write_text(
        json.dumps(presented, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "se_a_key_DO_NOT_OPEN_BEFORE_RATING.json").write_text(
        json.dumps(keymap, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("SE-A: %d 件を提示用に出力（方式名は伏せ、対応表は別ファイル）", len(presented))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="動作確認用の件数制限")
    args = ap.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)
    assert_output_is_gitignored()
    assert_partition_schemas_identical()

    ids, texts = load_speeches(args.limit)
    methods = [("W-1", "SudachiPy モードC（最長単位）"), ("W-2", "SudachiPy モードA（最短単位）"),
               ("W-3", "文字2-gram"), ("W-4", "文字3-gram")]
    tokenizers = {"W-1": lambda: tokenize_sudachi(texts, "C"),
                  "W-2": lambda: tokenize_sudachi(texts, "A"),
                  "W-3": lambda: tokenize_ngram(texts, 2),
                  "W-4": lambda: tokenize_ngram(texts, 3)}

    results, cache = [], {}
    for mid, label in methods:
        log.info("=== %s: %s ===", mid, label)
        t0 = time.monotonic()
        tokens = tokenizers[mid]()
        tok_sec = round(time.monotonic() - t0, 1)
        assert len(tokens) == len(texts), "分かち書き結果の件数が入力と一致しない"
        empty = sum(1 for x in tokens if not x)
        log.info("  [%s] 分かち書き %s 秒 / 空の結果 %d 件", mid, tok_sec, empty)
        r = run_method(mid, label, tokens, cache)
        r["tokenize_seconds"] = tok_sec
        r["empty_token_docs"] = empty
        results.append(r)
        del tokens

    (OUT_DIR / "wm_metrics.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for mid, _ in methods:
        (OUT_DIR / f"top_terms_{mid}.json").write_text(
            json.dumps(cache[mid]["top_terms"], ensure_ascii=False, indent=2), encoding="utf-8")
        np.save(OUT_DIR / f"labels_{mid}.npy", cache[mid]["labels"])
    build_se_a(cache, methods)

    log.info("S-3 完了。ピークメモリ %.2f GB / 出力先 %s",
             peak_memory_gb(), OUT_DIR.relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()
