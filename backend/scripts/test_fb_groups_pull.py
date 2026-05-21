#!/usr/bin/env python3
"""本地测试 Apify facebook-groups-scraper（需配置 APIFY_TOKEN）。

用法（在 backend 目录，使用项目 conda/venv）:
  python scripts/test_fb_groups_pull.py "https://www.facebook.com/groups/491282852595550" --limit 3

说明：群组抓取通常需 1～10 分钟，脚本会每 15 秒打印一次 Apify 运行状态。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402


def _get_client():
    if not settings.apify_token:
        print("ERROR: 未配置 APIFY_TOKEN，请在 backend/.env 中设置")
        sys.exit(1)
    from apify_client import ApifyClient

    return ApifyClient(settings.apify_token)


def run_with_progress(
    group_url: str,
    *,
    results_limit: int,
    view_option: str,
    timeout_secs: int = 600,
    poll_interval: int = 15,
) -> dict:
    client = _get_client()
    actor_id = settings.apify_fb_groups_actor
    run_input = {
        "startUrls": [{"url": group_url}],
        "viewOption": view_option,
        "resultsLimit": int(results_limit),
    }
    print(f"[test] actor={actor_id}")
    print(f"[test] input={json.dumps(run_input, ensure_ascii=False)}")
    print(f"[test] 正在启动 Apify（公开群组才有效，请耐心等待）…")

    actor = client.actor(actor_id)
    run = actor.start(run_input=run_input)
    run_id = run["id"]
    print(f"[test] started run_id={run_id} initial_status={run.get('status')}")

    deadline = time.time() + timeout_secs
    last_status = None
    while time.time() < deadline:
        run = client.run(run_id).get()
        st = run.get("status")
        if st != last_status:
            print(f"[test] status={st}")
            last_status = st
        if st in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT", "ABORTING"):
            break
        time.sleep(poll_interval)
    else:
        print(f"[test] ERROR: 超过 {timeout_secs}s 仍未结束，可在 Apify 控制台查看 run: {run_id}")
        sys.exit(2)

    st = run.get("status")
    if st != "SUCCEEDED":
        msg = run.get("statusMessage") or (run.get("meta") or {}).get("errorMessage") or st
        print(f"[test] ERROR: run 失败 status={st} message={msg}")
        print(f"[test] 控制台: https://console.apify.com/actors/runs/{run_id}")
        sys.exit(1)

    dataset_id = run.get("defaultDatasetId")
    items = list(client.dataset(dataset_id).iterate_items()) if dataset_id else []
    print(f"[test] SUCCEEDED dataset={dataset_id} count={len(items)}")
    return {"run_id": run_id, "dataset_id": dataset_id, "items": items}


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Apify facebook-groups-scraper")
    parser.add_argument("group_url", help="Facebook 公开群组 URL")
    parser.add_argument("--limit", type=int, default=5, help="resultsLimit")
    parser.add_argument(
        "--view",
        default="CHRONOLOGICAL",
        choices=["CHRONOLOGICAL", "RECENT_ACTIVITY", "TOP_POSTS", "CHRONOLOGICAL_LISTINGS"],
    )
    parser.add_argument("--timeout", type=int, default=600, help="最长等待秒数")
    args = parser.parse_args()

    result = run_with_progress(
        args.group_url.strip(),
        results_limit=args.limit,
        view_option=args.view,
        timeout_secs=args.timeout,
    )
    items = result.get("items") or []
    if not items:
        print("[test] 成功但 0 条：可能是私密群、需登录、或该群近期无帖。换公开大群再试。")
        sys.exit(0)
    first = items[0]
    print("[test] first item keys:", sorted(first.keys()))
    print(json.dumps(first, ensure_ascii=False, indent=2)[:5000])


if __name__ == "__main__":
    main()
