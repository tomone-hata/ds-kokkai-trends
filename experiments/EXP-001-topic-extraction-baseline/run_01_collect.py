"""S-1: データ収集（EXP-001）

国会会議録検索API から発言単位のデータを月単位で収集し、Parquet へ保存する。

実験コードであり保守しない（.claude/rules/experiment-code.md）。ハードコード可。
ただし以下は守る:
  - print() を使わず logging を使う
  - 出力先が .gitignore 対象であることをアサートする
  - APIエラーのリトライは 19001（混雑）のみ。19004〜19020 は即座に失敗させる
  - トランスポート層の失敗（接続断）は19001と別系統でリトライする（ISSUE-004）
  - 逐次アクセスのみ。並列化しない
  - raw_json 列で API レスポンスを可逆に保持する（ADR-001 6.1節）

実行:
    uv run python experiments/EXP-001-topic-extraction-baseline/run_01_collect.py \
        --from 2025-01-01 --until 2025-12-31
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# ---- 設定（ハードコード可。ただし config.md に記録すること） ----
API_URL = "https://kokkai.ndl.go.jp/api/speech"
MAXIMUM_RECORDS = 100          # 仕様上の上限。1〜100（確認日 2026-08-19）
WAIT_SECONDS = 3.0             # リクエスト「前」に待つ
TIMEOUT_SECONDS = 60.0
RETRY_ATTEMPTS = 5             # 19001 のみ
# ISSUE-004: トランスポート層の失敗（接続断）は19001と別系統でリトライする。
# 切断の原因が未特定（keep-alive競合 / アクセス遮断 / 経路障害）のため、
# 双方に耐えるよう待機を長めに取る。
TRANSPORT_RETRY_ATTEMPTS = 5
TRANSPORT_WAIT_MIN = 30.0
TRANSPORT_WAIT_MAX = 600.0
PROGRESS_EVERY = 20            # 何リクエストごとに進捗ログを出すか
D1A_THRESHOLD_RECORDS = 10_000       # D-1a の判定時点
D1A_PROJECTED_HOURS = 24.0           # D-1a の閾値
POC_TOTAL_EXPECTED = 118_566         # 2025年の想定件数
PROD_TOTAL_EXPECTED = 819_428        # 2019〜2025年の想定件数
D1C_PROJECTED_HOURS = 168.0          # D-1c の閾値（7日）

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "collect_manifest.json"
EXP_NAME = "EXP-001-topic-extraction-baseline"
OUT_DIR = REPO_ROOT / "outputs" / EXP_NAME

log = logging.getLogger("collect")


class BusyError(Exception):
    """19001（混雑）。これだけリトライしてよい。"""


class ApiError(Exception):
    """19001 以外の API エラー。リトライしない。"""


def assert_output_is_gitignored():
    """出力先が .gitignore 対象であることを確認する（experiment-code.md 禁止事項6）。"""
    for target in (RAW_DIR, OUT_DIR):
        target.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["git", "check-ignore", "-q", str(target)],
            cwd=REPO_ROOT, capture_output=True,
        )
        assert r.returncode == 0, f"出力先が Git 追跡対象になっている: {target}"
    log.info("アサーション: 出力先は .gitignore 対象である")


def month_ranges(start: date, end: date):
    """期間を月単位に分割する。収集単位（設計書 3.2.1節）。"""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first = date(y, m, 1)
        last = date(y + (m == 12), (m % 12) + 1, 1) - __import__("datetime").timedelta(days=1)
        out.append((max(first, start), min(last, end)))
        y, m = y + (m == 12), (m % 12) + 1
    return out


@retry(
    # ISSUE-004: 接続断は要求の内容に起因しないため19001と別系統で扱う。
    # 待機を長めに取るのは、アクセス遮断であった場合に短間隔の再試行が
    # 状況を悪化させるため。keep-alive競合であれば1回目で回復する。
    retry=retry_if_exception_type(httpx.TransportError),
    stop=stop_after_attempt(TRANSPORT_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=TRANSPORT_WAIT_MIN, max=TRANSPORT_WAIT_MAX),
    reraise=True,
    before_sleep=lambda st: log.warning(
        "接続エラーのため待機して再試行する（%d回目 / %d）: %s",
        st.attempt_number, TRANSPORT_RETRY_ATTEMPTS, st.outcome.exception(),
    ),
)
@retry(
    retry=retry_if_exception_type(BusyError),
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=4, max=120),
    reraise=True,
)
def fetch(client, params):
    """1リクエスト。待機はリクエスト『前』に置く（再開直後の連続発射を防ぐため）。"""
    time.sleep(WAIT_SECONDS)
    r = client.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
    r.raise_for_status()
    body = r.json()
    if "message" in body:
        detail = body.get("details", [])
        msg = str(body["message"])
        # 19001 は「混み合っております」。コード自体はレスポンスに含まれないため文言で判定する
        if "混み合" in msg or "しばらく" in msg:
            raise BusyError(msg)
        raise ApiError(f"{msg} / details={detail}")
    return body


def load_manifest():
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"units": {}}


def save_manifest(man):
    MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_unit(client, unit_from: date, unit_until: date, man, counters):
    """1つの収集単位（1か月）を取得する。"""
    key = f"{unit_from:%Y-%m}"
    rec = man["units"].get(key, {})
    if rec.get("status") == "完了":
        log.info("[%s] 完了済みのためスキップ", key)
        return

    log.info("[%s] 収集を開始する（%s 〜 %s）", key, unit_from, unit_until)
    rec = {"status": "進行中", "started_at": datetime.now().isoformat(timespec="seconds"),
           "errors": rec.get("errors", {})}
    man["units"][key] = rec
    save_manifest(man)

    rows, seen_ids = [], set()
    start_record, expected = 1, None
    unit_started = time.monotonic()

    while True:
        params = {
            "from": unit_from.isoformat(), "until": unit_until.isoformat(),
            "startRecord": start_record, "maximumRecords": MAXIMUM_RECORDS,
            "recordPacking": "json",
        }
        try:
            body = fetch(client, params)
        except BusyError as e:
            rec["errors"]["19001"] = rec["errors"].get("19001", 0) + 1
            counters["errors"]["19001"] = counters["errors"].get("19001", 0) + 1
            rec["status"] = "失敗"
            save_manifest(man)
            raise RuntimeError(f"[{key}] 19001 のリトライが上限に達した: {e}") from e
        except ApiError as e:
            rec["errors"]["other"] = rec["errors"].get("other", 0) + 1
            rec["status"] = "失敗"
            save_manifest(man)
            raise
        except httpx.TransportError as e:
            # ISSUE-004: リトライ上限に達した接続エラー。無制限に再試行せず停止する
            rec["errors"]["transport"] = rec["errors"].get("transport", 0) + 1
            counters["errors"]["transport"] = counters["errors"].get("transport", 0) + 1
            rec["status"] = "失敗"
            save_manifest(man)
            raise RuntimeError(
                f"[{key}] 接続エラーのリトライが上限に達した（ISSUE-004）: {e}"
            ) from e

        counters["requests"] += 1

        if expected is None:
            expected = int(body.get("numberOfRecords", 0))
            rec["expected"] = expected
            log.info("[%s] 期待件数 = %s 件", key, f"{expected:,}")
            save_manifest(man)
            if expected == 0:
                break

        for r in body.get("speechRecord", []):
            sid = r.get("speechID")
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            rows.append({**r, "raw_json": json.dumps(r, ensure_ascii=False)})

        counters["records"] = counters["base_records"] + len(rows)
        if counters["requests"] % PROGRESS_EVERY == 0:
            elapsed_h = (time.monotonic() - counters["t0"]) / 3600
            log.info(
                "進捗: 累計 %s 件 / %s リクエスト / 稼働 %.2f 時間 / エラー %s",
                f"{counters['records']:,}", counters["requests"], elapsed_h, counters["errors"],
            )
            judge_d1a(counters)

        nxt = body.get("nextRecordPosition")
        if not nxt:
            break
        start_record = int(nxt)

    unit_hours = (time.monotonic() - unit_started) / 3600

    # --- 完了判定: 件数一致 かつ speechID の重複・欠損なし（両方を満たす場合のみ完了） ---
    got = len(rows)
    dup = len(rows) - len(seen_ids)
    ok = (got == expected) and (dup == 0)

    rec.update({
        "got": got, "expected": expected, "duplicates": dup,
        "elapsed_hours": round(unit_hours, 4),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": "完了" if ok else "失敗",
    })

    if not ok:
        save_manifest(man)
        raise RuntimeError(
            f"[{key}] 完了判定に失敗: 取得 {got} 件 / 期待 {expected} 件 / 重複 {dup} 件"
        )

    # --- Parquet へ保存（raw_json 列で可逆に保持する。ADR-001 6.1節） ---
    # 0件の月はファイルを作らない。pa.Table.from_pylist([]) は 0行0列となり、
    # 列構成が他の月と揃わずグロブ読み込みが壊れるため（ISSUE-006）。
    if rows:
        part = RAW_DIR / f"year={unit_from.year}" / f"month={unit_from.month:02d}"
        part.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), part / "speech.parquet", compression="zstd")
    else:
        log.info("[%s] 該当0件のためファイルを作成しない", key)

    counters["base_records"] += got
    counters["records"] = counters["base_records"]
    save_manifest(man)
    log.info("[%s] 完了: %s 件 / 稼働 %.2f 時間", key, f"{got:,}", unit_hours)


def judge_d1a(counters):
    """D-1a: 累計10,000件時点で、2025年118,566件への外挿が24時間を超えるか。"""
    if counters["d1a_done"] or counters["records"] < D1A_THRESHOLD_RECORDS:
        return
    counters["d1a_done"] = True
    hours = (time.monotonic() - counters["t0"]) / 3600
    rate = counters["records"] / hours if hours > 0 else float("inf")
    projected = POC_TOTAL_EXPECTED / rate
    log.warning(
        "D-1a 判定: 実測 %.0f 件/時 → 2025年 %s 件の外挿 %.2f 時間（閾値 %.0f 時間）",
        rate, f"{POC_TOTAL_EXPECTED:,}", projected, D1A_PROJECTED_HOURS,
    )
    counters["d1a"] = {"rate_per_hour": rate, "projected_hours": projected,
                       "threshold_hours": D1A_PROJECTED_HOURS,
                       "breached": projected > D1A_PROJECTED_HOURS}
    if projected > D1A_PROJECTED_HOURS:
        raise SystemExit(
            f"D-1a に抵触した（外挿 {projected:.2f} 時間 > {D1A_PROJECTED_HOURS} 時間）。"
            "中断する。maximumRecords と待機秒の設計を見直すこと（plan.md 3.1節）"
        )


def judge_cp1(counters):
    """CP-1: D-1b・D-1c を判定する。"""
    hours = (time.monotonic() - counters["t0"]) / 3600
    rate = counters["records"] / hours if hours > 0 else float("inf")
    prod = PROD_TOTAL_EXPECTED / rate
    d1b = hours > D1A_PROJECTED_HOURS
    d1c = prod > D1C_PROJECTED_HOURS
    log.warning(
        "CP-1: 稼働 %.2f 時間 / %.0f 件・時 / 本番外挿 %.2f 時間（%.1f 日）",
        hours, rate, prod, prod / 24,
    )
    log.warning("D-1b（稼働24時間超）= %s / D-1c（本番外挿7日超）= %s", d1b, d1c)
    result = {"elapsed_hours": hours, "rate_per_hour": rate,
              "prod_projected_hours": prod, "d1b_breached": d1b, "d1c_breached": d1c}
    (OUT_DIR / "cp1_judgement.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if d1c:
        raise SystemExit("D-1c に抵触した。撤退基準に該当する（plan.md 3.1節）")
    return result


def main():
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--until", dest="date_until", required=True)
    a = ap.parse_args()

    assert_output_is_gitignored()

    start = date.fromisoformat(a.date_from)
    end = date.fromisoformat(a.date_until)
    assert start <= end, "from は until 以下でなければならない"

    man = load_manifest()
    done = sum(u.get("got", 0) for u in man["units"].values() if u.get("status") == "完了")
    counters = {"t0": time.monotonic(), "requests": 0, "records": done,
                "base_records": done, "errors": {}, "d1a_done": done >= D1A_THRESHOLD_RECORDS,
                "d1a": None}

    units = month_ranges(start, end)
    log.info("収集単位: %d か月（%s 〜 %s）／既取得 %s 件", len(units), start, end, f"{done:,}")

    with httpx.Client(headers={"User-Agent": "ds-kokkai-trends/EXP-001"}) as client:
        for uf, uu in units:
            collect_unit(client, uf, uu, man, counters)

    log.info("全単位の収集が完了した: 累計 %s 件", f"{counters['records']:,}")
    judge_cp1(counters)


if __name__ == "__main__":
    main()
