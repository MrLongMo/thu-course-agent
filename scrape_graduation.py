"""
scrape_graduation.py — 畢業規定資料爬蟲（v2）

資料源：東海大學「各學系必修科目表查詢系統」
  https://fsis.thu.edu.tw/wwwstud/info/MustList.php
呢個系統提供結構化 HTML table（唔係圖片），可以直接 parse，
唔再需要靠 Claude Vision 解析截圖。

用法：
  python scrape_graduation.py --majr 340 --code ev --year 114
  python scrape_graduation.py --list-majr      # 列出所有學系代碼
  python scrape_graduation.py --list           # 列出已完成嘅系所 JSON

⚠️ 生成嘅 JSON 係自動解析嘅草稿，學分數字、先修關係請人手核對一次先正式採用。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

# fsis.thu.edu.tw 嘅證書鏈有缺陷（Missing Subject Key Identifier），
# 但網站內容本身可信（東海官方教務系統），跳過驗證先可以連到。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).parent
GRAD_DIR = BASE_DIR / 'data' / 'graduation'
SEM_LABELS = ['大一上', '大一下', '大二上', '大二下', '大三上', '大三下',
              '大四上', '大四下', '大五上', '大五下']

FORM_URL = "https://fsis.thu.edu.tw/wwwstud/info/MustList.php"
LIST_URL = "https://fsis.thu.edu.tw/wwwstud/info/MustList-submajr-server.php?job=list"
HEADERS  = {'User-Agent': 'Mozilla/5.0'}


def get_leaf_depts():
    """爬表單頁面，列出所有「葉節點」學系代碼+名稱（排除學院標頭）"""
    r = requests.get(FORM_URL, timeout=15, verify=False, headers=HEADERS)
    r.raise_for_status()
    m = re.search(r'<select name="majr".*?</select>', r.text, re.S)
    if not m:
        raise RuntimeError('搵唔到學系選單，網站結構可能變咗')
    opts = re.findall(r"<option value='(\w+)'>([^<]+)</option>", m.group(0))
    leaf = []
    for code, name in opts:
        if '--' not in name:
            continue  # 學院標頭，無 '--' 前綴
        clean = re.sub(r'^[\s]*--[\s]*', '', name.replace('&nbsp;', '')).strip()
        leaf.append((code, clean))
    return leaf


def list_majr_codes():
    for code, name in get_leaf_depts():
        print(f'{code}  {name}')


def get_subgroups(majr, stype='A'):
    """有啲學系（如資工系）再分『組別』，要揀組別先有得查。冇分組就回傳 []"""
    r = requests.get(
        f'https://fsis.thu.edu.tw/wwwstud/info/MustList-submajr-server.php?job=group&type={stype}&majr={majr}',
        timeout=15, verify=False, headers=HEADERS,
    )
    if 'nothing in subgroup' in r.text:
        return []
    opts = re.findall(r"<option\s+(?:selected\s+)?value='(\w+)'>([^<]*)</option>", r.text)
    return [(v, n.replace('&nbsp;', '').strip()) for v, n in opts if v not in ('0', '99', '')]


def _post_list(year, majr, stype, p_grop=None):
    data = {'setyear': year, 'stype': stype, 'majr': majr, 'submajr': ''}
    if p_grop is not None:
        data['p_grop'] = p_grop
    r = requests.post(LIST_URL, data=data, timeout=20, verify=False, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    title_tag = soup.find('h4')
    title_text = title_tag.get_text(strip=True) if title_tag else ''
    tables = [t for t in soup.find_all('table') if len(t.find_all('tr')) > 2]
    return (tables[0], title_text) if tables else (None, title_text)


def fetch_table(year: str, majr: str, stype: str = 'A'):
    """先試唔帶組別查詢；攞唔到真實資料先試各個組別（回傳第一個有資料嘅組）
    回傳：(table, title, group_name_or_None)"""
    table, title = _post_list(year, majr, stype)
    if table is not None:
        return table, title, None

    for grop_val, grop_name in get_subgroups(majr, stype):
        table, title = _post_list(year, majr, stype, p_grop=grop_val)
        if table is not None:
            return table, title, grop_name

    raise RuntimeError('搵唔到課程表，可能呢個系所/學年度/學制冇資料')


def parse_course_cell(text: str):
    """'11001-中文 (Chinese)' → ('11001', '中文')"""
    m = re.match(r'^(\d+)-(.+)$', text)
    if not m:
        return None, text.strip()
    code, rest = m.groups()
    name = re.sub(r'\s*\(.*\)\s*$', '', rest).strip()
    return code, name


def parse_table(table):
    rows = table.find_all('tr')
    categories = {}
    current_cat = None
    summary = {}

    for tr in rows[2:]:  # 跳過兩行 header
        tds = [td.get_text(strip=True) for td in tr.find_all('td')]
        if not tds:
            continue

        label = tds[0]
        if '必修學分數' in label:
            nums_raw = tds[1:9]
            nums = [int(x) for x in nums_raw if x.isdigit()]
            summary['required_total'] = nums[0] if nums else None
            summary['semester_required'] = nums[1:] if len(nums) > 1 else []
            continue
        if '選修學分數' in label:
            digits = re.findall(r'\d+', ' '.join(tds[1:]))
            summary['elective_credits'] = int(digits[0]) if digits else None
            continue
        if '畢業學分數' in label:
            digits = re.findall(r'\d+', ' '.join(tds[1:]))
            summary['total_credits'] = int(digits[0]) if digits else None
            continue

        if label:
            current_cat = re.sub(r'[A-Za-z ]+$', '', label).strip()
            categories.setdefault(current_cat, [])

        if len(tds) < 3 or current_cat is None:
            continue
        course_cell = tds[1]
        if not course_cell:
            continue
        code, name = parse_course_cell(course_cell)
        credits_text = tds[2]
        credits = int(credits_text) if credits_text.isdigit() else 0

        sem_cells = tds[3:13]
        semesters = [SEM_LABELS[i] for i, v in enumerate(sem_cells) if v.strip().isdigit()]
        memo = tds[13] if len(tds) > 13 else ''

        categories[current_cat].append({
            'code': code, 'name': name, 'credits': credits,
            'semesters': semesters, 'memo': memo,
        })

    return categories, summary


def build_json(dept_name, dept_code, year, categories, summary, source_url):
    out_categories = {}
    for cat_name, courses in categories.items():
        if '通識' in cat_name:
            domains = [c['name'] for c in courses]
            note_texts = [c['memo'] for c in courses if c['memo']]
            credit_match = re.search(r'(\d+)\s*學分', note_texts[0]) if note_texts else None
            out_categories[cat_name] = {
                'required_credits': int(credit_match.group(1)) if credit_match else None,
                'note': note_texts[0] if note_texts else '',
                'domains': domains,
            }
        elif '基礎' in cat_name:
            out_categories[cat_name] = {
                'courses': [
                    {'name': c['name'], 'credits': c['credits'], 'semesters': c['semesters'], 'required': True}
                    for c in courses
                ]
            }
        else:
            out_categories[cat_name] = {
                'courses': [
                    {'name': c['name'], 'credits': c['credits'], 'semesters': c['semesters'], 'prereq': []}
                    for c in courses
                ]
            }

    sem_required = summary.get('semester_required', [])[:8]
    while len(sem_required) < 8:
        sem_required.append(0)

    return {
        'dept': dept_name,
        'dept_code': dept_code.upper(),
        'apply_from': year,
        'total_credits': summary.get('total_credits'),
        'required_credits': summary.get('required_total'),
        'elective_credits': summary.get('elective_credits'),
        'elective_note': '',
        'semester_required': sem_required,
        'categories': out_categories,
        'source_url': source_url,
        'last_updated': None,
    }


def scrape_one(majr, code, year, stype='A'):
    """爬單一系所，成功就存檔，回傳 (dept_name, result, out_path) 或 raise"""
    table, title, grop_name = fetch_table(year, majr, stype)
    categories, summary = parse_table(table)
    dept_match = re.search(r'(學士班|博士班)(.+?)必修科目表', title)
    dept_name = dept_match.group(2).strip() if dept_match else title
    result = build_json(
        dept_name, code, year, categories, summary,
        source_url=f'{FORM_URL}（majr={majr}, year={year}, stype={stype}' +
                   (f', p_grop={grop_name}' if grop_name else '') + '）',
    )
    GRAD_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GRAD_DIR / f'{code.lower()}_{year}.json'
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return dept_name, result, out_path


def scrape_all_depts(year, stype='A'):
    """跑遍所有葉節點學系，逐一嘗試爬畢業規定（用 majr 數字代碼做 dept_code）"""
    depts = get_leaf_depts()
    print(f'共 {len(depts)} 個學系候選，開始逐一查詢（學年 {year}，學制 {stype}）...\n')

    ok, skipped = [], []
    for majr, name in depts:
        try:
            dept_name, result, out_path = scrape_one(majr, majr, year, stype)
            ok.append((majr, dept_name, result['total_credits']))
            print(f'✅ {majr} {name} → {out_path.name}（畢業學分 {result["total_credits"]}）')
        except Exception as e:
            skipped.append((majr, name, str(e)))
            print(f'⏭️  {majr} {name} → 跳過（{e}）')

    print(f'\n=== 完成：成功 {len(ok)} / 共 {len(depts)}，跳過 {len(skipped)} ===')
    if skipped:
        print('跳過原因通常係：呢個代碼係研究所/在職專班，冇日間學士班資料')
    print('\n⚠️  全部係自動爬出嚟嘅草稿，記得抽樣核對學分數字、先修科目關係先正式使用。')


def list_completed():
    GRAD_DIR.mkdir(exist_ok=True)
    files = [f for f in GRAD_DIR.glob('*.json')]
    if not files:
        print('尚無已完成的系所資料')
        return
    print(f'已完成 {len(files)} 個系所：')
    for f in sorted(files):
        data = json.loads(f.read_text(encoding='utf-8'))
        print(f'  ✅ {data.get("dept", f.stem)}（{data.get("apply_from","?")}學年起）— 畢業學分 {data.get("total_credits","?")}')


def main():
    parser = argparse.ArgumentParser(description='東海畢業必修科目表爬蟲（資料源：fsis.thu.edu.tw）')
    parser.add_argument('--majr', help='學系代碼，例如環工系=340（用 --list-majr 查全部）')
    parser.add_argument('--code', help='輸出檔案用嘅系所縮寫，例如 ev')
    parser.add_argument('--year', help='學年度，例如 114')
    parser.add_argument('--stype', default='A', help='學制代碼，預設 A=日間學士班')
    parser.add_argument('--list-majr', action='store_true', help='列出所有學系代碼')
    parser.add_argument('--list', action='store_true', help='列出已完成嘅系所 JSON')
    parser.add_argument('--all', action='store_true', help='一次過爬晒所有學系（需配合 --year）')
    args = parser.parse_args()

    if args.list_majr:
        list_majr_codes()
        return
    if args.list:
        list_completed()
        return
    if args.all:
        if not args.year:
            print('用 --all 要指定 --year')
            sys.exit(1)
        scrape_all_depts(args.year, args.stype)
        return
    if not all([args.majr, args.code, args.year]):
        parser.print_help()
        sys.exit(1)

    dept_name, result, out_path = scrape_one(args.majr, args.code, args.year, args.stype)
    print(f'已生成：{out_path}')
    print(f'系所：{dept_name}，畢業學分：{result["total_credits"]}，必修：{result["required_credits"]}，選修：{result["elective_credits"]}')
    print('\n⚠️  呢份係自動爬出嚟嘅草稿，請人手核對學分數字、先修科目關係先正式使用。')


if __name__ == '__main__':
    main()
