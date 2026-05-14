"""
scrape_graduation.py — 畢業規定資料爬蟲

功能：
  給定系所網站 URL，自動找出必修科目表圖片/PDF 並下載
  下載後用 Claude Vision（透過 Groq llama 或 Claude API）解析成結構化 JSON

用法（需人工確認解析結果）：
  python scrape_graduation.py --url https://ba.thu.edu.tw --dept BA --year 112

目前支援系所：
  企管系 (BA)：data/graduation/ba_112.json ✅ 已完成
"""

import argparse
import json
import os
import re
import sys
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BASE_DIR  = Path(__file__).parent
GRAD_DIR  = BASE_DIR / 'data' / 'graduation'
IMG_DIR   = BASE_DIR / 'data' / 'graduation' / 'raw_images'

KEYWORDS = ['必修科目', '修業規定', '畢業學分', '課程地圖', '修課地圖']


def find_graduation_pages(dept_url):
    """在系所網站找出所有跟修業規定有關的頁面連結"""
    print(f'搜尋：{dept_url}')
    try:
        r = requests.get(dept_url, timeout=10)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'lxml')

        links = []
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            href = a['href']
            if any(kw in text for kw in KEYWORDS):
                full_url = urljoin(dept_url, href)
                links.append({'text': text, 'url': full_url})

        print(f'找到 {len(links)} 個相關連結：')
        for i, l in enumerate(links):
            print(f'  [{i}] {l["text"]} → {l["url"]}')

        return links
    except Exception as e:
        print(f'[錯誤] {e}')
        return []


def download_images_from_page(page_url, dept_code, year):
    """從指定頁面下載所有圖片（必修科目表通常係圖片格式）"""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    print(f'\n下載圖片：{page_url}')

    try:
        r = requests.get(page_url, timeout=10)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'lxml')

        saved = []
        for i, img in enumerate(soup.find_all('img')):
            src = img.get('src', '')
            if not src or 'logo' in src.lower() or 'icon' in src.lower():
                continue

            img_url  = urljoin(page_url, src)
            ext      = Path(urlparse(img_url).path).suffix or '.jpg'
            filename = f'{dept_code}_{year}_{i}{ext}'
            dest     = IMG_DIR / filename

            try:
                img_r = requests.get(img_url, timeout=10)
                dest.write_bytes(img_r.content)
                size  = dest.stat().st_size
                if size > 10_000:  # 只保留大於 10KB 的（排除小 icon）
                    saved.append(str(dest))
                    print(f'  ✅ 下載 {filename} ({size//1024}KB)')
                else:
                    dest.unlink()
            except Exception as e:
                print(f'  ⚠️ {img_url} 失敗：{e}')

        return saved
    except Exception as e:
        print(f'[錯誤] {e}')
        return []


def save_template(dept_code, year, dept_name=''):
    """生成空白 JSON 模板，供人工填入或 AI 解析後存入"""
    GRAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = GRAD_DIR / f'{dept_code.lower()}_{year}.json'

    template = {
        "dept": dept_name or dept_code,
        "dept_code": dept_code,
        "apply_from": year,
        "total_credits": None,
        "required_credits": None,
        "elective_credits": None,
        "elective_note": "",
        "categories": {
            "基礎課程": {"courses": []},
            "通識必修課程": {"required_credits": None, "note": "", "domains": []},
            "學系必修科目": {"courses": []}
        },
        "source_url": "",
        "last_updated": "2026-05-14"
    }

    dest.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n✅ 模板已存：{dest}')
    print('   請用 Claude Vision 解析圖片後填入')
    return dest


def list_completed():
    """列出已完成的系所"""
    GRAD_DIR.mkdir(exist_ok=True)
    files = list(GRAD_DIR.glob('*.json'))
    if not files:
        print('尚無已完成的系所資料')
        return

    print(f'已完成 {len(files)} 個系所：')
    for f in sorted(files):
        data = json.loads(f.read_text(encoding='utf-8'))
        dept = data.get('dept', f.stem)
        year = data.get('apply_from', '?')
        total = data.get('total_credits', '?')
        print(f'  ✅ {dept}（{year}學年起）— 畢業學分 {total}')


def main():
    parser = argparse.ArgumentParser(description='PickU 畢業規定爬蟲')
    parser.add_argument('--url',    help='系所網站首頁 URL')
    parser.add_argument('--dept',   help='系所代碼（如 BA、CS）')
    parser.add_argument('--year',   type=int, help='適用學年度（如 112）')
    parser.add_argument('--list',   action='store_true', help='列出已完成系所')
    args = parser.parse_args()

    if args.list:
        list_completed()
        return

    if not all([args.url, args.dept, args.year]):
        print('用法：python scrape_graduation.py --url <URL> --dept <代碼> --year <學年>')
        print('      python scrape_graduation.py --list')
        sys.exit(1)

    # 1. 找修業規定相關頁面
    links = find_graduation_pages(args.url)

    # 2. 下載第一個符合的頁面圖片
    if links:
        images = download_images_from_page(links[0]['url'], args.dept, args.year)
        if images:
            print(f'\n共下載 {len(images)} 張圖片，存於 {IMG_DIR}')
            print('下一步：用 Claude 讀取圖片，解析必修科目表')

    # 3. 生成 JSON 模板
    save_template(args.dept, args.year)


if __name__ == '__main__':
    main()
