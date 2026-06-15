"""
THU 選課輔助工具 - Flask 主程式
"""
import json
import os
import re
import time
import requests
from collections import defaultdict
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

load_dotenv()

# ── Rate limiting：每個 IP 每分鐘最多 3 次 AI 分析 ──
_rate_store: dict = defaultdict(list)
RATE_LIMIT  = 3   # 最多次數
RATE_WINDOW = 60  # 秒

def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        return False
    _rate_store[ip].append(now)
    return True

# ── AI 分析客戶端（lazy init，避免缺 key 時整個 app 掛掉）──
_tavily_client = None
_groq_client = None

def _get_clients():
    """取得 Tavily 和 Groq 客戶端，首次呼叫時才初始化"""
    global _tavily_client, _groq_client
    if _tavily_client is None:
        from tavily import TavilyClient
        from groq import Groq
        _tavily_client = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))
        _groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))
    return _tavily_client, _groq_client


def analyze_course(course_name: str, teacher_name: str = "") -> dict:
    """
    搜尋 Dcard 評價並用 Groq 分析課程
    回傳：
      {'no_data': True}                       — 搜唔到評價
      {'analysis': str, 'source_count': int}  — 成功分析
    """
    tavily, groq = _get_clients()

    # 1. Tavily 搜尋 Dcard 評價（包含老師名提高精準度）
    query = f"東海大學 {course_name} {teacher_name} Dcard 評價".strip() if teacher_name else f"東海大學 {course_name} 評價 心得 site:dcard.tw"
    response = tavily.search(
        query=query,
        search_depth="advanced",
        include_domains=["dcard.tw"],
        max_results=8,
        include_answer=True,
        include_raw_content=False,
    )

    # 2. 取出所有結果，整理來源列表（title 優先，fallback 到 url）
    all_results = response.get("results", [])
    source_list = [
        {"title": r.get("title") or r["url"], "url": r["url"]}
        for r in all_results
        if r.get("url")
    ]

    # 過濾低相關度結果（score < 0.3）用於分析
    filtered = [r for r in all_results if r.get("score", 0) >= 0.3]
    if not filtered:
        return {'no_data': True, 'sources': source_list}

    # 3. 取 top 5 筆，組成 prompt 內容
    top_results = filtered[:5]
    sources = "\n\n".join(
        f"[來源 {i+1}] {r['url']}\n{r.get('content', '')}"
        for i, r in enumerate(top_results)
    )

    # 4. 組建 system prompt（有老師名時加入只分析該老師評價的規則）
    teacher_rule = (
        f"- 只分析關於「{teacher_name}」的評價內容，如果搜尋結果提及其他老師，直接忽略該部分內容\n"
        f"- 老師名「{teacher_name}」會在 user prompt 中標注，請嚴格以此為準\n"
    ) if teacher_name else ""

    # 5. 呼叫 Groq llama-3.3-70b-versatile 分析
    chat = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一個分析大學課程評價的助理，請使用繁體中文回答。\n"
                    "根據提供的 Dcard 討論內容，完成以下三項分析，並嚴格按照指定格式輸出，不要加入其他文字。\n\n"
                    "重要規則：\n"
                    "- 只能根據提供的資料作出分析，嚴禁自行推斷或補充任何資料中沒有的內容\n"
                    "- 如果提供的資料不足以完成某項分析，該項必須填寫「資料不足」\n"
                    "- 如果完全沒有有用資料，三項全部填寫「資料不足」，不要強行生成內容\n"
                    "- 有 quote 原文依據先可以給出評分，否則填「資料不足」\n"
                    f"{teacher_rule}"
                    "\n格式：\n"
                    "摘要：（3-5句，涵蓋老師風格、上課難度、考試/報告情況，如資料不足則填「資料不足」）\n"
                    "整體傾向：（正面 / 中性 / 負面，擇一，如資料不足則填「資料不足」）\n"
                    "難易度：X/5（1=極易，5=極難，並簡單解釋原因，如資料不足則填「資料不足」）"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"以下係東海大學「{course_name}」「{teacher_name}」嘅 Dcard 評價，"
                    f"只分析關於「{teacher_name}」嘅內容，忽略其他老師嘅評價：\n\n{sources}\n\n"
                    "請先判斷以上內容是否包含真實的課程評價。如果內容為空、與該課程無關、或資訊量不足以分析，直接三項全部輸出「資料不足」，不要強行生成內容。"
                ) if teacher_name else (
                    f"以下是東海大學「{course_name}」的 Dcard 評價內容：\n\n{sources}\n\n"
                    "請先判斷以上內容是否包含真實的課程評價。如果內容為空、與該課程無關、或資訊量不足以分析，直接三項全部輸出「資料不足」，不要強行生成內容。"
                ),
            },
        ],
        max_tokens=600,
    )

    return {
        'analysis': chat.choices[0].message.content,
        'source_count': len(top_results),
        'sources': source_list,
    }

def _parse_slots_from_json(course):
    """從課程 JSON 的上課時間字串解析 slots，唔需要爬網站"""
    raw  = (course.get('上課時間') or '').strip()
    room = (course.get('教室') or '').strip()
    if not raw:
        return []
    day_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}
    slots = []
    for part in re.split(r'\s+', raw):
        m = re.match(r'([一二三四五])/([0-9,B]+)(?:\[([^\]]*)\])?', part)
        if m:
            day = day_map.get(m.group(1))
            periods = []
            for p in m.group(2).split(','):
                p = p.strip()
                if p == 'B':
                    periods.append('B')
                elif p.isdigit():
                    periods.append(int(p))
            if day and periods:
                slots.append({'day': day, 'periods': periods, 'room': m.group(3) or room})
    return slots


app = Flask(__name__, template_folder='web/templates', static_folder='web/static')

# 啟動時讀取課程資料
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'processed', 'courses_115_1.json')
GRAD_DIR  = os.path.join(os.path.dirname(__file__), 'data', 'graduation')

# 從檔名抽出學年學期，供 fallback 爬蟲使用
_m = re.search(r'courses_(\d+)_(\d+)\.json', DATA_PATH)
CURRENT_YEAR, CURRENT_SEM = (_m.group(1), _m.group(2)) if _m else ('114', '2')

with open(DATA_PATH, encoding='utf-8') as f:
    ALL_COURSES = json.load(f)

# 整理所有系所列表（去空值、排序）
DEPARTMENTS = sorted(set(
    str(c.get('開課系所名稱', '') or '').strip()
    for c in ALL_COURSES
    if str(c.get('開課系所名稱', '') or '').strip()
))

# 課程時間 cache：避免重複爬東海網站
# key: course_id (str) → value: slots list
_time_cache = {
    str(c['選課代碼']): _parse_slots_from_json(c)
    for c in ALL_COURSES
    if c.get('上課時間')
}


@app.route('/')
def index():
    return render_template('index.html', departments=DEPARTMENTS,
                           current_year=CURRENT_YEAR, current_sem=CURRENT_SEM)


@app.route('/api/courses')
def api_courses():
    """
    查詢課程 API
    params:
      q    — 搜尋關鍵字（課程名 or 老師名）
      dept — 系所篩選
      page — 頁碼（預設 1）
      per_page — 每頁筆數（預設 30）
    """
    q = request.args.get('q', '').strip().lower()
    dept = request.args.get('dept', '').strip()
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(1, int(request.args.get('per_page', 30))))

    results = ALL_COURSES

    # 系所篩選
    if dept:
        results = [c for c in results if c.get('開課系所名稱', '') == dept]

    # 關鍵字搜尋（課程名稱、授課教師、選課代碼）
    if q:
        results = [
            c for c in results
            if q in c.get('課程名稱', '').lower()
            or q in c.get('授課教師', '').lower()
            or q in str(c.get('選課代碼', '')).lower()
        ]

    total = len(results)
    start = (page - 1) * per_page
    end = start + per_page
    page_data = results[start:end]

    return jsonify({
        'total': total,
        'page': page,
        'per_page': per_page,
        'courses': page_data
    })


@app.route('/api/course_time/<course_id>')
def api_course_time(course_id):
    """
    查詢課程上課時間
    優先順序：記憶體 cache → JSON 資料 → 即時爬網站（並存入 cache）
    回傳格式：[{"day": 3, "periods": [6,7], "room": "L205"}]
    """
    # 1. cache hit：直接回傳
    if course_id in _time_cache:
        return jsonify({'slots': _time_cache[course_id]})

    # 2. JSON 有資料：parse 後存 cache 回傳
    course = next((c for c in ALL_COURSES if str(c.get('選課代碼', '')) == course_id), None)
    if course and course.get('上課時間'):
        slots = _parse_slots_from_json(course)
        _time_cache[course_id] = slots
        return jsonify({'slots': slots})

    # 3. fallback：爬東海網站（只在 JSON 未有資料時才用）
    url = f"https://course.thu.edu.tw/view/{CURRENT_YEAR}/{CURRENT_SEM}/{course_id}"
    try:
        r = requests.get(url, timeout=8)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'lxml')

        time_tag = soup.find(string=re.compile(r'上課時間'))
        if not time_tag:
            _time_cache[course_id] = []
            return jsonify({'slots': []})

        raw = re.sub(r'^上課時間：\s*', '', time_tag.strip())
        day_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}
        slots = []
        for part in re.split(r'\s+', raw):
            m = re.match(r'([一二三四五])/([0-9,B]+)(?:\[([^\]]*)\])?', part)
            if m:
                day = day_map.get(m.group(1))
                periods = []
                for p in m.group(2).split(','):
                    p = p.strip()
                    if p == 'B':
                        periods.append('B')
                    elif p.isdigit():
                        periods.append(int(p))
                if day and periods:
                    slots.append({'day': day, 'periods': periods, 'room': m.group(3) or ''})

        _time_cache[course_id] = slots
        return jsonify({'slots': slots})
    except Exception as e:
        return jsonify({'slots': [], 'error': str(e)}), 500


@app.route('/api/analyze/<course_id>')
def api_analyze(course_id):
    """
    AI 分析指定課程的 Dcard 評價
    params: course_id — 選課代碼
    回傳: { analysis, source_count } 或 { no_data: true } 或 { error }
    """
    # Rate limit 檢查
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    if not _check_rate_limit(ip):
        return jsonify({'error': '請求過於頻繁，請稍後再試（每分鐘最多 3 次）'}), 429

    # 按選課代碼找課程
    course = next(
        (c for c in ALL_COURSES if str(c.get('選課代碼', '')) == course_id),
        None
    )
    if not course:
        return jsonify({'error': '找不到課程'}), 404

    course_name = course.get('課程名稱', '')
    teacher_name = course.get('授課教師', '').strip()
    try:
        result = analyze_course(course_name, teacher_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'分析失敗：{str(e)}'}), 500


@app.route('/api/enrollment/<course_id>')
def api_enrollment(course_id):
    """
    即時查詢課程名額（上限 / 現選 / 餘額）
    資料來源：東海課程網官方 API（real-time）
    """
    import re as _re
    url = (
        f"https://course.thu.edu.tw/api/course-list"
        f"?year={CURRENT_YEAR}&term={CURRENT_SEM}&keyword={course_id}"
    )
    try:
        r = requests.get(url, timeout=8)
        data = r.json()
        # 找 course code 完全符合的那行（strip html 後比對）
        for row in data.get('data', []):
            code = _re.sub(r'<[^>]+>', '', row[0]).strip().lstrip('0') or '0'
            if code == str(int(course_id)):
                status_html = row[5]
                cap  = _re.search(r'上限\s*(\d+)', status_html)
                enr  = _re.search(r'現選\s*(\d+)', status_html)
                left = _re.search(r'餘額\s*(\d+)', status_html)
                return jsonify({
                    'capacity':  int(cap.group(1))  if cap  else None,
                    'enrolled':  int(enr.group(1))  if enr  else None,
                    'remaining': int(left.group(1)) if left else None,
                })
        return jsonify({'error': '找不到課程名額資料'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/siblings/<course_id>')
def api_siblings(course_id):
    """
    返回與指定課程同名的所有課程（不同老師）
    用途：判斷是否顯示「比較所有老師」按鈕
    """
    course = next(
        (c for c in ALL_COURSES if str(c.get('選課代碼', '')) == course_id),
        None
    )
    if not course:
        return jsonify({'error': '找不到課程'}), 404

    name = course.get('課程名稱', '')
    siblings = [c for c in ALL_COURSES if c.get('課程名稱', '') == name]
    return jsonify({'courses': siblings})


@app.route('/api/graduation/analyze', methods=['POST'])
def api_graduation_analyze():
    """
    輸入：自由格式修課紀錄文字（含通識/選修）
    用 Groq 解析 → 比對畢業要求 → 回傳缺口分析 + 建議
    """
    body       = request.get_json(silent=True) or {}
    dept_code  = body.get('dept', 'BA')
    year       = int(body.get('year', 114))
    transcript = body.get('transcript', '').strip()

    if not transcript:
        return jsonify({'error': '請輸入修課紀錄'}), 400

    path = os.path.join(GRAD_DIR, f'{dept_code.lower()}_{year}.json')
    if not os.path.exists(path):
        return jsonify({'error': '尚無此系所資料'}), 404
    with open(path, encoding='utf-8') as f:
        grad = json.load(f)

    cats          = grad.get('categories', {})
    basic_courses = cats.get('基礎課程', {}).get('courses', [])
    dept_courses  = cats.get('學系必修科目', {}).get('courses', [])
    all_req_map   = {c['name']: c for c in basic_courses + dept_courses}

    # ── Groq 解析修課紀錄 ──
    try:
        _, groq_client = _get_clients()
        chat = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": (
                    "從以下台灣大學修課紀錄中提取所有課程資訊，只返回純 JSON，不要有其他文字：\n"
                    '{"courses":[{"name":"課程名稱","credits":學分數,"grade":"成績"}]}\n'
                    "學分若不清楚填 0，成績若沒有填空字串。\n\n"
                    f"修課紀錄：\n{transcript[:3000]}"
                )
            }],
            max_tokens=2000,
            temperature=0,
        )
        raw = chat.choices[0].message.content.strip()
        # 去除 markdown 代碼塊
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE)
        parsed_courses = json.loads(raw).get('courses', [])
    except Exception as e:
        return jsonify({'error': f'AI 解析失敗：{str(e)}'}), 500

    # ── 分類課程 ──
    required_done  = []   # 已修且符合畢業必修
    other_done     = []   # 通識 / 選修（不在必修名單內）

    for c in parsed_courses:
        name    = (c.get('name') or '').strip()
        credits = c.get('credits', 0) or 0
        if not name:
            continue

        if name in all_req_map:
            # 若 AI 回傳學分為 0，改用畢業規定的學分
            if credits == 0:
                credits = all_req_map[name].get('credits', 0)
            c['credits'] = credits
            required_done.append(c)
        elif credits > 0:
            other_done.append(c)

    req_credits_done   = sum(c.get('credits', 0) for c in required_done)
    other_credits_done = sum(c.get('credits', 0) for c in other_done)

    # ── 未修必修（只查學系必修，基礎課程通常全修）──
    done_names = {c['name'] for c in required_done}
    missing = []
    for c in dept_courses:
        if c['name'] in done_names:
            continue
        prereq     = c.get('prereq', [])
        prereq_met = all(p in done_names for p in prereq)
        available  = [
            {
                '選課代碼': co['選課代碼'],
                '授課教師': co.get('授課教師') or '—',
                '上課時間': co.get('上課時間') or '—',
            }
            for co in ALL_COURSES
            if co.get('課程名稱') == c['name']
        ]
        missing.append({
            'name':       c['name'],
            'credits':    c.get('credits', 0),
            'prereq':     prereq,
            'prereq_met': prereq_met,
            'group':      c.get('group', ''),
            'available':  available,
        })

    missing.sort(key=lambda x: (not x['prereq_met'], not bool(x['available'])))

    return jsonify({
        'required_done':      required_done,
        'other_done':         other_done,
        'req_credits_done':   req_credits_done,
        'other_credits_done': other_credits_done,
        'total_credits_done': req_credits_done + other_credits_done,
        'missing_required':   missing,
    })


@app.route('/api/graduation/suggestions', methods=['POST'])
def api_graduation_suggestions():
    """
    輸入：已修課程清單
    輸出：未修必修課 × 本學期開課情況，依可修優先排序
    """
    body      = request.get_json(silent=True) or {}
    dept_code = body.get('dept', 'BA')
    year      = int(body.get('year', 114))
    completed = set(body.get('completed', []))

    path = os.path.join(GRAD_DIR, f'{dept_code.lower()}_{year}.json')
    if not os.path.exists(path):
        return jsonify({'error': '尚無此系所資料'}), 404

    with open(path, encoding='utf-8') as f:
        grad = json.load(f)

    dept_courses = grad.get('categories', {}).get('學系必修科目', {}).get('courses', [])
    suggestions  = []

    for c in dept_courses:
        if c['name'] in completed:
            continue

        prereq     = c.get('prereq', [])
        prereq_met = all(p in completed for p in prereq)

        # 比對本學期開課（課程名稱完全相符）
        available = [
            {
                '選課代碼': co['選課代碼'],
                '授課教師': co.get('授課教師') or '—',
                '上課時間': co.get('上課時間') or '—',
                '學分':     co.get('學分', 0),
            }
            for co in ALL_COURSES
            if co.get('課程名稱') == c['name']
        ]

        suggestions.append({
            'name':       c['name'],
            'credits':    c.get('credits', 0),
            'semesters':  c.get('semesters', []),
            'prereq':     prereq,
            'prereq_met': prereq_met,
            'group':      c.get('group', ''),
            'available':  available,
        })

    # 排序：先修已完成 + 本學期有開課 → 最優先
    suggestions.sort(key=lambda x: (
        not x['prereq_met'],
        not bool(x['available']),
        -x['credits']
    ))

    return jsonify({'suggestions': suggestions})


@app.route('/api/graduation/<dept_code>/<int:year>')
def api_graduation(dept_code, year):
    """返回指定系所、入學學年的畢業規定 JSON"""
    path = os.path.join(GRAD_DIR, f'{dept_code.lower()}_{year}.json')
    if not os.path.exists(path):
        return jsonify({'error': '尚無此系所資料'}), 404
    with open(path, encoding='utf-8') as f:
        return jsonify(json.load(f))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
