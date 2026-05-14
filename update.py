"""
update.py — PickU 學期資料更新腳本

每學期換季時跑一次，自動完成：
  1. 從東海課程網下載新學期 XLS
  2. Parse 成 JSON
  3. 爬全部課程詳細資料（授課教師、上課時間、評分方式等）
  4. 更新 app.py 的 DATA_PATH 指向新學期檔案

用法：
  python update.py --year 115 --semester 1
"""

import argparse
import json
import os
import re
import sys
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup

BASE_DIR    = Path(__file__).parent
PROCESSED   = BASE_DIR / 'data' / 'processed'
APP_PY      = BASE_DIR / 'app.py'
DELAY       = 1  # 爬蟲每次 request 間隔秒數
THU_XLS_URL = "https://course.thu.edu.tw/course/{year}/{sem}/xcls.xls"
THU_COURSE  = "https://course.thu.edu.tw/view/{year}/{sem}/{cid}"

REQUIRED_FIELDS = ['課程概述', '評分方式', '授課教師', '上課時間']


# ── 1. 下載 XLS ──────────────────────────────────────────

def download_xls(year, semester):
    url  = THU_XLS_URL.format(year=year, sem=semester)
    dest = BASE_DIR / 'data' / f'courses_{year}_{semester}.xls'
    print(f'[1/4] 下載 {url}')
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        print(f'      儲存 → {dest}')
        return dest
    except Exception as e:
        print(f'      [警告] 下載失敗：{e}')
        print(f'      請手動下載 XLS 放到 {dest} 後重跑')
        sys.exit(1)


# ── 2. Parse XLS → JSON ──────────────────────────────────

def parse_xls(xls_path, year, semester):
    import pandas as pd
    dest = PROCESSED / f'courses_{year}_{semester}.json'
    print(f'[2/4] Parse XLS → {dest.name}')

    df = pd.read_csv(str(xls_path), encoding='big5', on_bad_lines='skip')

    # 統一欄位命名
    rename = {
        '選課代碼': '選課代碼', '課程名稱': '課程名稱',
        '開課系所名稱': '開課系所名稱', '必選修': '必選修',
        '學分2': '學分', '學分1': '學分',
    }
    for old, new in rename.items():
        if old in df.columns and new not in df.columns:
            df.rename(columns={old: new}, inplace=True)

    # 保留必要欄位
    keep = ['選課代碼', '課程名稱', '開課系所名稱', '必選修', '學分']
    keep = [c for c in keep if c in df.columns]
    df   = df[keep].dropna(subset=['選課代碼', '課程名稱'])
    df['選課代碼'] = df['選課代碼'].astype(int)

    courses = df.to_dict(orient='records')
    dest.write_text(json.dumps(courses, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'      共 {len(courses)} 門課程')
    return dest, courses


# ── 3. 爬課程詳細資料 ────────────────────────────────────

def scrape_all(courses, json_path, year, semester):
    total   = len(courses)
    pending = [c for c in courses if any(c.get(f) is None for f in REQUIRED_FIELDS)]
    print(f'[3/4] 爬課程詳細資料：{len(pending)} / {total} 門需要抓')
    print(f'      預計時間：約 {len(pending) // 60 + 1} 分鐘')

    id_map = {str(c['選課代碼']): c for c in courses}
    done   = 0

    for i, course in enumerate(pending):
        cid  = str(course['選課代碼'])
        name = course.get('課程名稱', '')
        url  = THU_COURSE.format(year=year, sem=semester, cid=cid)

        try:
            r = requests.get(url, timeout=10)
            r.encoding = 'utf-8'
            soup = BeautifulSoup(r.text, 'lxml')

            data = {
                '授課教師': _get_teacher(soup),
                '上課時間': _get_class_time(soup),
                '教室':     _get_classroom(soup),
                '課程概述': _get_section_text(soup, '課程概述'),
                '評分方式': _get_grading_table(soup),
            }

            updated = []
            for key, val in data.items():
                if id_map[cid].get(key) is None and val is not None:
                    id_map[cid][key] = val
                    updated.append(key)

            done += 1
            if updated:
                print(f'  [{i+1}/{len(pending)}] {cid} {name[:12]} → {updated}')

        except Exception as e:
            print(f'  [{i+1}/{len(pending)}] {cid} 失敗：{e}')

        # 每 50 門存一次（斷點保護）
        if (i + 1) % 50 == 0:
            json_path.write_text(json.dumps(courses, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'  [進度存檔] {i+1}/{len(pending)}')

        if i + 1 < len(pending):
            time.sleep(DELAY)

    json_path.write_text(json.dumps(courses, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'      完成！共抓 {done} 門')


# ── 4. 更新 app.py DATA_PATH ─────────────────────────────

def update_app_py(year, semester):
    new_filename = f'courses_{year}_{semester}.json'
    print(f'[4/4] 更新 app.py → {new_filename}')

    content = APP_PY.read_text(encoding='utf-8')
    updated = re.sub(
        r"(DATA_PATH\s*=\s*os\.path\.join\([^)]+\))[^\n]*",
        f"DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'processed', '{new_filename}')",
        content,
    )
    APP_PY.write_text(updated, encoding='utf-8')
    print(f'      完成！重啟 app.py 後生效')


# ── HTML 解析輔助函數 ────────────────────────────────────

def _get_section_text(soup, title):
    h2 = soup.find('h2', string=title)
    if not h2:
        return None
    parts = []
    for sib in h2.find_next_siblings():
        if sib.name == 'h2':
            break
        text = sib.get_text(separator='\n', strip=True)
        if text:
            parts.append(text)
    return '\n'.join(parts) if parts else None


def _get_grading_table(soup):
    h2 = soup.find('h2', string='評分方式')
    if not h2:
        return None
    tbl = h2.find_next('table')
    if not tbl:
        return None
    rows    = tbl.find_all('tr')
    headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])] if rows else []
    result  = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all(['th', 'td'])]
        if any(cells):
            result.append(dict(zip(headers, cells)))
    return result or None


def _get_teacher(soup):
    for p in soup.find_all('p'):
        text = p.get_text()
        if '授課教師：' in text:
            a = p.find('a')
            if a:
                return a.get_text(strip=True) or None
            m = re.search(r'授課教師：([^\s<\n]+)', text)
            if m:
                return m.group(1).strip()
    return None


def _get_class_time(soup):
    for p in soup.find_all('p'):
        text = p.get_text(separator='\n')
        if '上課時間：' not in text:
            continue
        m = re.search(r'上課時間：(.+?)(?:\n|$)', text)
        if not m:
            continue
        raw     = m.group(1).strip()
        bracket = re.search(r'\[(.+?)\]', raw)
        if bracket:
            return raw[:bracket.start()].strip()
        m2 = re.match(r'([\d一二三四五六日/,B]+)\s+(.+)', raw)
        return m2.group(1).strip() if m2 else raw
    return None


def _get_classroom(soup):
    for p in soup.find_all('p'):
        text = p.get_text(separator='\n')
        if '上課時間：' not in text:
            continue
        m = re.search(r'上課時間：(.+?)(?:\n|$)', text)
        if not m:
            continue
        raw     = m.group(1).strip()
        bracket = re.search(r'\[(.+?)\]', raw)
        if bracket:
            return bracket.group(1).strip()
        m2 = re.match(r'([\d一二三四五六日/,B]+)\s+(.+)', raw)
        return m2.group(2).strip() if m2 else None
    return None


# ── Main ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='PickU 學期資料更新')
    parser.add_argument('--year',     type=int, required=True, help='學年（如 115）')
    parser.add_argument('--semester', type=int, required=True, choices=[1, 2], help='學期（1 或 2）')
    parser.add_argument('--skip-download', action='store_true', help='跳過下載（XLS 已存在）')
    args = parser.parse_args()

    PROCESSED.mkdir(parents=True, exist_ok=True)
    print(f'\n=== PickU 資料更新：{args.year} 學年第 {args.semester} 學期 ===\n')

    xls_path = BASE_DIR / 'data' / f'courses_{args.year}_{args.semester}.xls'
    if not args.skip_download:
        download_xls(args.year, args.semester)

    json_path, courses = parse_xls(xls_path, args.year, args.semester)
    scrape_all(courses, json_path, args.year, args.semester)
    update_app_py(args.year, args.semester)

    print(f'\n✅ 全部完成！執行 python app.py 啟動新學期版本\n')


if __name__ == '__main__':
    main()
