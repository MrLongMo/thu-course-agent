"""
scrape_details.py
抓取東海大學課程資訊網的課程詳細資料
並 merge 入 data/processed/courses_114_2.json

已有資料的欄位不會覆蓋，只補缺少的 fields。

用法：
  測試模式（只跑企管系）： python scrape_details.py --test
  全部課程：              python scrape_details.py
"""

import json
import time
import re
import argparse
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
BASE_URL = "https://course.thu.edu.tw/view/114/2/{}"
JSON_PATH = Path("data/processed/courses_114_2.json")
DELAY = 1  # 每次 request 間隔秒數
TEST_DEPT = "企業管理學系"  # 測試模式只跑呢個系

# 需要補爬的所有 fields（任何一個缺就要去抓）
REQUIRED_FIELDS = ["課程概述", "評分方式", "授課教師", "上課時間"]


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
        if any(cells):
            result.append(dict(zip(headers, cells)))
    return result if result else None


def get_teacher(soup):
    """從「教師與教學助理」段落抽出授課教師名稱"""
    # 找含有「授課教師：」文字的 <p>
    for p in soup.find_all("p"):
        text = p.get_text()
        if "授課教師：" in text:
            # 找 p 裡面第一個 <a>（老師名字）
            a = p.find("a")
            if a:
                name = a.get_text(strip=True)
                if name:
                    return name
            # 沒有 <a> 就用 regex 抽文字
            m = re.search(r"授課教師：([^\s<\n]+)", text)
            if m:
                return m.group(1).strip()
    return None


def get_class_info(soup):
    """從「基本資料」段落抽出上課時間同教室"""
    class_time = None
    classroom = None

    for p in soup.find_all("p"):
        text = p.get_text(separator="\n")
        if "上課時間：" not in text:
            continue

        # 抓「上課時間：」後面到換行為止的整段
        m = re.search(r"上課時間：(.+?)(?:\n|$)", text)
        if not m:
            continue

        raw = m.group(1).strip()

        # 教室通常在時間槽後面，格式例如：
        #   一/2,3,4 社科101        → 時間 + 教室
        #   一/2,3,4,B[遠距課程]   → 遠距，教室欄用括號內文字
        #   一/2,3,4               → 只有時間，無教室

        # 先嘗試抓 [xxx] 括號內容當教室
        bracket = re.search(r"\[(.+?)\]", raw)
        if bracket:
            classroom = bracket.group(1).strip()
            # 時間是括號前的部分
            class_time = raw[:bracket.start()].strip()
        else:
            # 時間槽格式：數字/數字,數字... 後接空格再接教室名
            m2 = re.match(r"([\d一二三四五六日/,]+)\s+(.+)", raw)
            if m2:
                class_time = m2.group(1).strip()
                classroom = m2.group(2).strip()
            else:
                # 只有時間，沒有教室
                class_time = raw

        break  # 只取第一個匹配

    return class_time, classroom


def scrape_course(course_id):
    """抓單堂課，回傳所有可抓到的 fields dict，失敗回傳 None"""
    url = BASE_URL.format(course_id)
    try:
        r = requests.get(url, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            print(f"  [警告] {course_id} HTTP {r.status_code}")
            return None

        soup = BeautifulSoup(r.text, "lxml")
        class_time, classroom = get_class_info(soup)

        return {
            "課程概述": get_section_text(soup, "課程概述"),
            "評分方式": get_grading_table(soup),
            "授課教師": get_teacher(soup),
            "上課時間": class_time,
            "教室": classroom,
        }
    except Exception as e:
        print(f"  [錯誤] {course_id} → {e}")
        return None


def needs_update(course):
    """判斷課程是否有任何 field 仍未填入"""
    return any(course.get(f) is None for f in REQUIRED_FIELDS)


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

        # 所有 fields 都已有資料則跳過（支援斷點續跑）
        if not needs_update(course):
            skipped += 1
            continue

        print(f"[{i+1}/{len(targets)}] {cid} {name}")
        data = scrape_course(cid)

        if data:
            # 只補缺少的 fields，唔覆蓋已有資料
            updated_fields = []
            for key, value in data.items():
                if id_map[cid].get(key) is None and value is not None:
                    id_map[cid][key] = value
                    updated_fields.append(key)

            done += 1
            print(f"  補入欄位：{updated_fields if updated_fields else '（無新資料）'}")
            print(f"  教師：{data.get('授課教師') or '—'}  "
                  f"時間：{data.get('上課時間') or '—'}  "
                  f"教室：{data.get('教室') or '—'}")
        else:
            print(f"  [失敗] 略過")

        # 每 100 門存一次（斷點保護，避免意外中斷失去進度）
        if (done + skipped) % 100 == 0 and done > 0:
            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(courses, f, ensure_ascii=False, indent=2)
            print(f"  [進度存檔] 已處理 {done + skipped} / {len(targets)}")

        # 每次 request 後 delay
        if i + 1 < len(targets):
            time.sleep(DELAY)

    # 寫回 JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(courses, f, ensure_ascii=False, indent=2)

    print(f"\n完成！抓取 {done} 堂，跳過（已完整）{skipped} 堂")
    print(f"已存回 {JSON_PATH}")

    # 印出一個企管系 sample 確認結果
    sample = next(
        (c for c in courses if c.get("開課系所名稱") == TEST_DEPT and c.get("授課教師")),
        None
    )
    if sample:
        print("\n── Sample（企管系）──")
        print(json.dumps(sample, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
