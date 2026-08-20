"""EXP-001 S-4: 前処理水準の決定（PoC設計書 6.3節 E-0 / E-1 / E-2 の比較）。

比較条件（6.3.2節）:
  分かち書き = W-2（SudachiPy モードA。S-3 で決定）
  ベクトル化 = TF-IDF（V-1） / クラスタリング = k-means k=100（暫定固定）
  分析単位 = U-1（発言単位。暫定固定） / 乱数シード = 42

**E-0 は S-3 の W-2 の結果を再利用する。** 条件（分かち書き・単位・k・シード）が
完全に一致するため再計算しても同一の結果になる。再利用することで、S-3 で
評価済みの20クラスタがそのまま E-0 の SE-A 結果として使える。

**シルエット係数は算出しない**（5.2.4節）。**参照リストとの一致率は用いない**（5.3.6節）。

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
S3_DIR = REPO_ROOT / "outputs" / "EXP-001-topic-extraction-baseline" / "s3_wakachi"
OUT_DIR = REPO_ROOT / "outputs" / "EXP-001-topic-extraction-baseline" / "s4_preprocess"
SEED = 42
EXPECTED_SPEECHES = 117_440      # 工程2A 後の件数（S-2 実測）

T1 = 10                          # S-2 で 6.3.1節 手順3 により確定
T2 = 20                          # S-2 で 6.3.1節 手順4 により確定
LEVELS = [("E-0", None), ("E-1", T1), ("E-2", T2)]

K_CLUSTERS = 100                 # 9.1節（暫定固定）
KMEANS_N_INIT = 3                # S-3 と同一（設計書に指定なし）
KMEANS_MAX_ITER = 300
MIN_DF = 5                       # S-3 と同一（設計書に指定なし）
MAX_DF = 0.5                     # 同上
SUBLINEAR_TF = True              # 同上
TOP_TERMS = 20
SE_A_SAMPLE = 20                 # 5.2.1節（水準ごとランダム20件）
KEEP_POS = ("名詞", "動詞", "形容詞")
SUDACHI_MODE = "A"               # W-2（S-3 の決定）

RE_SPEAKER_PREFIX = r"^○[^ ]{0,39} "
RE_STAGE_KAKU = r"〔[^〕]{0,60}〕"
RE_STAGE_PAREN = r"\((?:拍手|発言する者あり)\)"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("s4")


def peak_memory_gb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 3)


def assert_output_is_gitignored():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "check-ignore", "-q", str(OUT_DIR)],
                       cwd=REPO_ROOT, capture_output=True)
    assert r.returncode == 0, f"出力先が Git 追跡対象になっている: {OUT_DIR}"
    log.info("アサーション: 出力先は .gitignore 対象である")


def normalize(text):
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(RE_SPEAKER_PREFIX, "", t)
    t = re.sub(RE_STAGE_KAKU, "", t)
    t = re.sub(RE_STAGE_PAREN, "", t)
    return re.sub(r"\s+", " ", t).strip()


def load_speeches():
    con = duckdb.connect()
    con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{RAW_GLOB}', hive_partitioning=1)")
    rows = con.execute(
        "SELECT speechID, speech FROM raw WHERE speechOrder <> 0 ORDER BY speechID").fetchall()
    assert len(rows) == EXPECTED_SPEECHES, f"件数が S-2 の実測と異なる: {len(rows)}"
    texts = [normalize(r[1]) for r in rows]
    assert all(texts), "正規化後に空文字となった発言がある"
    log.info("読み込み: %s 件（工程2A 後・正規化済み）", f"{len(texts):,}")
    return texts


def tokenize_w2(texts):
    """W-2: SudachiPy モードA、名詞・動詞・形容詞に限定（S-3 の決定）。"""
    from sudachipy import Dictionary, SplitMode

    tok = Dictionary().create()
    mode = SplitMode.A
    out = []
    for i, t in enumerate(texts):
        toks = []
        for chunk in (t[j:j + 10000] for j in range(0, len(t), 10000)):
            for m in tok.tokenize(chunk, mode):
                if m.part_of_speech()[0] in KEEP_POS:
                    toks.append(m.normalized_form())
        out.append(toks)
        if (i + 1) % 40000 == 0:
            log.info("  分かち書き: %s 件", f"{i + 1:,}")
    return out


def gini(x):
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    return 0.0 if x.sum() == 0 else float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def cluster_level(level, tokens, keep_idx):
    """1水準について TF-IDF → L2正規化 → k-means を実行する。"""
    t0 = time.monotonic()
    sub = [tokens[i] for i in keep_idx]
    vec = TfidfVectorizer(analyzer=lambda x: x, min_df=MIN_DF, max_df=MAX_DF,
                          lowercase=False, sublinear_tf=SUBLINEAR_TF)
    X = vec.fit_transform(sub)
    X = l2_normalize(X)
    km = KMeans(n_clusters=K_CLUSTERS, random_state=SEED,
                n_init=KMEANS_N_INIT, max_iter=KMEANS_MAX_ITER)
    labels = km.fit_predict(X)
    assert len(labels) == len(sub), "予測結果の件数が入力と一致しない"

    sizes = np.bincount(labels, minlength=K_CLUSTERS)
    terms = np.array(vec.get_feature_names_out())
    top = {}
    for c in range(K_CLUSTERS):
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            continue
        mean = np.asarray(X[idx].mean(axis=0)).ravel()
        top[int(c)] = [str(t) for t in terms[np.argsort(-mean)[:TOP_TERMS]]]

    m = {
        "level": level, "n_docs": len(sub),
        "vocab": len(vec.vocabulary_),
        "M-1_n_clusters_nonempty": int((sizes > 0).sum()),
        "M-3_max_cluster_share_pct": round(100.0 * float(sizes.max()) / len(labels), 2),
        "M-4_size_gini": round(gini(sizes), 4),
        "cluster_size_min": int(sizes.min()), "cluster_size_median": int(np.median(sizes)),
        "seconds": round(time.monotonic() - t0, 1), "peak_memory_gb": round(peak_memory_gb(), 2),
    }
    log.info("  [%s] 件数 %s / 語彙 %s / 非空C %d / 最大占有 %.2f%% / %s 秒",
             level, f"{m['n_docs']:,}", f"{m['vocab']:,}", m["M-1_n_clusters_nonempty"],
             m["M-3_max_cluster_share_pct"], m["seconds"])
    return m, labels, sizes, top


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    assert_output_is_gitignored()

    texts = load_speeches()
    lengths = np.array([len(t) for t in texts])

    t0 = time.monotonic()
    tokens = tokenize_w2(texts)
    log.info("分かち書き（W-2）完了: %s 秒", round(time.monotonic() - t0, 1))

    # --- E-0 は S-3 の W-2 の結果を再利用する ---
    e0_labels = np.load(S3_DIR / "labels_W-2.npy")
    e0_top = {int(k): v for k, v in json.loads((S3_DIR / "top_terms_W-2.json").read_text()).items()}
    assert len(e0_labels) == len(texts), "S-3 の E-0 結果と件数が一致しない"
    e0_sizes = np.bincount(e0_labels, minlength=K_CLUSTERS)
    results = [{
        "level": "E-0", "n_docs": len(texts), "vocab": 20674,
        "M-1_n_clusters_nonempty": int((e0_sizes > 0).sum()),
        "M-3_max_cluster_share_pct": round(100.0 * float(e0_sizes.max()) / len(e0_labels), 2),
        "M-4_size_gini": round(gini(e0_sizes), 4),
        "cluster_size_min": int(e0_sizes.min()), "cluster_size_median": int(np.median(e0_sizes)),
        "reused_from": "S-3 の W-2（条件が完全に一致するため再計算しない）",
    }]
    log.info("[E-0] S-3 の W-2 の結果を再利用（%s 件）", f"{len(e0_labels):,}")
    cache = {"E-0": {"labels": e0_labels, "sizes": e0_sizes, "top_terms": e0_top}}

    # --- E-1・E-2 を実行 ---
    for level, thr in LEVELS[1:]:
        keep = np.where(lengths > thr)[0]
        excluded = len(texts) - len(keep)
        log.info("=== %s: 文字数 <= %d を除外（%s 件・%.3f%%） ===",
                 level, thr, f"{excluded:,}", 100.0 * excluded / len(texts))
        m, labels, sizes, top = cluster_level(level, tokens, keep)
        m["threshold"] = thr
        m["excluded"] = int(excluded)
        m["excluded_pct"] = round(100.0 * excluded / len(texts), 3)
        results.append(m)
        cache[level] = {"labels": labels, "sizes": sizes, "top_terms": top}
        np.save(OUT_DIR / f"labels_{level}.npy", labels)

    for level in cache:
        (OUT_DIR / f"top_terms_{level}.json").write_text(
            json.dumps(cache[level]["top_terms"], ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- SE-A: E-1・E-2 のみ提示する（E-0 は S-3 で評価済み） ---
    rng = random.Random(SEED)
    items, key = [], []
    for level in ["E-1", "E-2"]:
        cs = sorted(cache[level]["top_terms"].keys())
        for c in rng.sample(cs, min(SE_A_SAMPLE, len(cs))):
            items.append({"terms": cache[level]["top_terms"][c],
                          "size": int(cache[level]["sizes"][c])})
            key.append({"level": level, "cluster_id": c})
    order = list(range(len(items)))
    rng.shuffle(order)
    (OUT_DIR / "se_a_presented.json").write_text(
        json.dumps([{"item_no": i + 1, **items[o]} for i, o in enumerate(order)],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "se_a_key_DO_NOT_OPEN_BEFORE_RATING.json").write_text(
        json.dumps([{"item_no": i + 1, **key[o]} for i, o in enumerate(order)],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("SE-A: %d 件を提示用に出力（E-1・E-2 のみ。E-0 は S-3 で評価済み）", len(items))
    log.info("S-4 の計算完了。ピークメモリ %.2f GB", peak_memory_gb())


if __name__ == "__main__":
    main()
