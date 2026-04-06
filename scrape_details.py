"""
scrape_details.py
抓取東海大學課程資訊網的「課程概述」和「評分方式」
並 merge 入 data/processed/courses_114_2.json

用法：
  測試模式（只跑企管系）： python scrape_details.py --test
  全部課程：              python scrape_details.py
"""

import json
import time
import argparse
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
BASE_URL = "https://course.thu.edu.tw/view/114/2/{}"
JSON_PATH = Path("data/processed/courses_114_2.json")
DELAY = 1  # 每次 request 間隔秒數
TEST_DEPT = "企業管理學系"  # 測試模式只跑呢個系


def get_section_text(soup, title):
    """抽取指定 h2 區塊內的純文字（到下一個 h2 為止）"""
    h2 = soup.find("h2", string=title)
    if not h2:
        return None
    parts = []
    for sib in h2.find_next_siblings():
        if sib.name == "h2":
            break
        text = sib.get_text(separator="\n", strip=True)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else None


def get_grading_table(soup):
    """把評分方式 table 轉成 list of dict"""
    h2 = soup.find("h2", string="評分方式")
    if not h2:
        return None
    tbl = h2.find_next("table")
    if not tbl:
        return None
    rows = tbl.find_all("tr")
    if not rows:
        return None

    # 第一行是 header
    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    result = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all(["th", "td"])]
        # 跳過空行
        if any(cells):
            result.append(dict(zip(headers, cells)))
    return result if result else None


def scrape_course(course_id):
    """抓單堂課，回傳 {'課程概述': ..., '評分方式': [...]} 或 None"""
    url = BASE_URL.format(course_id)
    try:
        r = requests.get(url, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            print(f"  [警告] {course_id} HTTP {r.status_code}")
            return None
        soup = BeautifulSoup(r.text, "lxml")
        return {
            "課程概述": get_section_text(soup, "課程概述"),
            "評分方式": get_grading_table(soup),
        }
    except Exception as e:
        print(f"  [錯誤] {course_id} → {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help=f"只跑 {TEST_DEPT}")
    args = parser.parse_args()

    # 讀取現有 JSON
    with open(JSON_PATH, encoding="utf-8") as f:
        courses = json.load(f)

    # 篩選目標課程
    targets = courses if not args.test else [
        c for c in courses if c.get("開課系所名稱") == TEST_DEPT
    ]

    mode = f"測試模式（{TEST_DEPT}）" if args.test else "全部課程"
    print(f"模式：{mode}，共 {len(targets)} 堂課\n")

    # 建立 course_id → course 的 index，方便 merge
    id_map = {str(c["選課代碼"]): c for c in courses}

    done = 0
    skipped = 0

    for i, course in enumerate(targets):
        cid = str(course["選課代碼"])
        name = course.get("課程名稱", "")

        # 若已有資料則跳過（支援斷點續跑）
        if course.get("課程概述") is not None or course.get("評分方式") is not None:
            skipped += 1
            continue

        print(f"[{i+1}/{len(targets)}] {cid} {name}")
        data = scrape_course(cid)

        if data:
            id_map[cid]["課程概述"] = data["課程概述"]
            id_map[cid]["評分方式"] = data["評分方式"]
            done += 1
            print(f"  概述: {'有' if data['課程概述'] else '無'}  "
                  f"評分: {'有' if data['評分方式'] else '無'}")
        else:
            # 抓失敗也記錄，避免重試浪費時間
            id_map[cid]["課程概述"] = None
            id_map[cid]["評分方式"] = None

        # 每次 request 後 delay
        if i + 1 < len(targets):
            time.sleep(DELAY)

    # 寫回 JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(courses, f, ensure_ascii=False, indent=2)

    print(f"\n完成！抓取 {done} 堂，跳過（已有資料）{skipped} 堂")
    print(f"已存回 {JSON_PATH}")


if __name__ == "__main__":
    main()
