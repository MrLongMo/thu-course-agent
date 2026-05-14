"""
THU 選課輔助工具 - Flask 主程式
"""
import json
import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

load_dotenv()

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

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')

# 啟動時讀取課程資料
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'processed', 'courses_114_2.json')

with open(DATA_PATH, encoding='utf-8') as f:
    ALL_COURSES = json.load(f)

# 整理所有系所列表（去空值、排序）
DEPARTMENTS = sorted(set(
    c.get('開課系所名稱', '').strip()
    for c in ALL_COURSES
    if c.get('開課系所名稱', '').strip()
))

PLANNER_REQUIREMENT = {
    'totalCredits': 128,
    'categories': {
        'required': 64,
        'departmentElective': 30,
        'generalEducation': 28,
        'freeElective': 6,
    }
}

PLANNER_PROFILE = {
    'school': '東海大學',
    'department': '企業管理學系',
    'year': 3,
    'workloadPreference': 'balanced',
}

PLANNER_COMPLETED_COURSES = [
    {'id': 'done-001', 'title': '管理學', 'category': 'required', 'credits': 3},
    {'id': 'done-002', 'title': '經濟學（一）', 'category': 'required', 'credits': 3},
    {'id': 'done-003', 'title': '經濟學（二）', 'category': 'required', 'credits': 3},
    {'id': 'done-004', 'title': '會計學（一）', 'category': 'required', 'credits': 3},
    {'id': 'done-005', 'title': '會計學（二）', 'category': 'required', 'credits': 3},
    {'id': 'done-006', 'title': '統計學（一）', 'category': 'required', 'credits': 3},
    {'id': 'done-007', 'title': '行銷管理', 'category': 'required', 'credits': 3},
    {'id': 'done-008', 'title': '組織行為', 'category': 'required', 'credits': 3},
    {'id': 'done-009', 'title': '商業英文簡報', 'category': 'departmentElective', 'credits': 3},
    {'id': 'done-010', 'title': '服務業管理', 'category': 'departmentElective', 'credits': 3},
    {'id': 'done-011', 'title': '創業管理', 'category': 'departmentElective', 'credits': 3},
    {'id': 'done-012', 'title': '數位行銷概論', 'category': 'departmentElective', 'credits': 3},
    {'id': 'done-013', 'title': '人文與科技', 'category': 'generalEducation', 'credits': 2},
    {'id': 'done-014', 'title': '公民社會', 'category': 'generalEducation', 'credits': 2},
    {'id': 'done-015', 'title': '自然科學導論', 'category': 'generalEducation', 'credits': 2},
    {'id': 'done-016', 'title': '藝術欣賞', 'category': 'generalEducation', 'credits': 2},
    {'id': 'done-017', 'title': '體育與健康', 'category': 'generalEducation', 'credits': 2},
    {'id': 'done-018', 'title': '跨域自主學習', 'category': 'freeElective', 'credits': 4},
]


def _planner_category(course):
    """將現有課程欄位映射到修業規劃範本使用的學分類別。"""
    dept = course.get('開課系所名稱', '')
    required_type = str(course.get('必選修', '')).replace('.0', '')

    if '通識' in dept or dept in {'大一英文', '大一大二體育', '第二外國語'}:
        return 'generalEducation'
    if dept == PLANNER_PROFILE['department']:
        return 'required' if required_type == '1' else 'departmentElective'
    return 'freeElective'


def _planner_priority(course):
    """讓示範候選課程優先顯示企劃書提到的管理、資料、AI、創新相關課。"""
    title = course.get('課程名稱', '')
    dept = course.get('開課系所名稱', '')
    keywords = ('資料', 'AI', '人工智慧', '統計', '管理', '策略', '創新', '行銷', '專題', '設計')
    score = 0
    if dept == PLANNER_PROFILE['department']:
        score += 100
    if any(keyword in title for keyword in keywords):
        score += 30
    if course.get('上課時間'):
        score += 10
    return score


def _planner_course_payload(course):
    """前端修業規劃頁需要的輕量課程資料。"""
    return {
        'id': str(course.get('選課代碼', '')),
        'code': str(course.get('選課代碼', '')),
        'title': course.get('課程名稱', ''),
        'department': course.get('開課系所名稱', ''),
        'teacher': course.get('授課教師', ''),
        'category': _planner_category(course),
        'credits': course.get('學分') or 0,
        'enrolled': course.get('選課人數') or 0,
        'limit': course.get('上限人數') or 0,
        'timeText': course.get('上課時間', ''),
        'room': course.get('教室', ''),
        'overview': course.get('課程概述', ''),
        'assessment': course.get('評分方式', []),
    }


def _planner_candidates():
    """限制候選清單大小，避免範本頁載入整份課程資料。"""
    relevant = [
        c for c in ALL_COURSES
        if c.get('開課系所名稱') == PLANNER_PROFILE['department']
        or '通識' in c.get('開課系所名稱', '')
        or c.get('開課系所名稱') in {'資訊工程學系', '工業工程與經營資訊學系', '大一英文'}
    ]
    relevant.sort(key=_planner_priority, reverse=True)
    return [_planner_course_payload(c) for c in relevant[:160]]


def _is_management_demo_course(course):
    """判斷是否使用管理學截圖用示範分析。"""
    return (
        course.get('開課系所名稱') == '企業管理學系'
        and course.get('課程名稱') == '管理學'
    )


def _demo_management_analysis(course):
    """在沒有 API key 時，提供管理學截圖用的中性 AI 分析範本。"""
    teacher_name = course.get('授課教師', '').strip() or '授課教師'
    course_id = str(course.get('選課代碼', ''))
    assessments = course.get('評分方式') or []
    assessment_text = '、'.join(
        f"{item.get('評分項目')} {item.get('配分比例')}%"
        for item in assessments
        if item.get('評分項目') and item.get('配分比例')
    ) or '期中、期末與課堂參與'

    teacher_notes = {
        '黃櫻美': '評量結構以期中考、期末考、期末報告、小考與出席組成，適合希望用穩定考試節奏掌握管理基礎的學生。',
        '張譽騰': '評量同時包含考試、小組作業、期末報告與課堂參與，課程可能較重視團隊討論與應用表達。',
        '吳祉芸': '評量包含期中期末、小組任務與課程參與，課堂互動與任務完成度在成績中占比較高。',
    }
    note = teacher_notes.get(
        teacher_name,
        '課程以管理理論與實務應用並重，適合作為企業管理學系低年級核心基礎課程。'
    )

    return {
        'analysis': (
            f"摘要：{teacher_name} 的管理學示範分析依官方課程綱要與評分方式整理。"
            "課程定位為管理基礎課，內容涵蓋企業組織運作、管理理論與實務案例，"
            "並透過資料蒐集、報告製作或課堂參與訓練團隊合作與邏輯表達。"
            f"{note} 評分方式包含 {assessment_text}。\n"
            "整體傾向：中性\n"
            "難易度：3/5（屬於基礎必修課，概念門檻不高，但需要固定準備考試、完成報告或小組任務）"
        ),
        'source_count': 0,
        'source_note': '示範結果：依官方課程綱要與評分方式生成，未使用 Tavily / Groq API',
        'sources': [
            {
                'title': f"東海課程綱要：管理學（{teacher_name}）",
                'url': f"https://course.thu.edu.tw/view/114/2/{course_id}",
            }
        ],
        'demo': True,
    }


@app.route('/')
def index():
    return render_template('index.html', departments=DEPARTMENTS)


@app.route('/planner')
def planner():
    return render_template(
        'planner.html',
        profile=PLANNER_PROFILE,
        requirement=PLANNER_REQUIREMENT,
        completed_courses=PLANNER_COMPLETED_COURSES,
        candidate_courses=_planner_candidates(),
    )


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
    On-demand 抓東海課程網上課時間
    回傳格式：[{"day": 3, "periods": [6,7], "room": "L205"}]
    day: 1=一(週一) … 5=五(週五)
    """
    url = f"https://course.thu.edu.tw/view/114/2/{course_id}"
    try:
        r = requests.get(url, timeout=8)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'lxml')

        # 找「上課時間：三/6,7[L205]」格式的文字
        time_tag = soup.find(string=re.compile(r'上課時間'))
        if not time_tag:
            return jsonify({'slots': []})

        raw = time_tag.strip()
        # 去掉「上課時間：」前綴
        raw = re.sub(r'^上課時間：\s*', '', raw)

        day_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}
        slots = []
        # 可能多時段，以空白或逗號分隔：「三/6,7[L205] 五/1,2[...]」
        for part in re.split(r'\s+', raw):
            # 格式：天/節次[教室] 或 天/節次
            m = re.match(r'([一二三四五])/([0-9,]+)(?:\[([^\]]*)\])?', part)
            if m:
                day = day_map.get(m.group(1))
                periods = [int(p) for p in m.group(2).split(',') if p]
                room = m.group(3) or ''
                if day:
                    slots.append({'day': day, 'periods': periods, 'room': room})

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
    # 按選課代碼找課程
    course = next(
        (c for c in ALL_COURSES if str(c.get('選課代碼', '')) == course_id),
        None
    )
    if not course:
        return jsonify({'error': '找不到課程'}), 404

    course_name = course.get('課程名稱', '')
    teacher_name = course.get('授課教師', '').strip()

    # 截圖展示用：管理學先回傳固定示範分析，避免本機缺 API key 時無法展示。
    if _is_management_demo_course(course):
        return jsonify(_demo_management_analysis(course))

    try:
        result = analyze_course(course_name, teacher_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'分析失敗：{str(e)}'}), 500


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
    if _is_management_demo_course(course):
        dept = course.get('開課系所名稱', '')
        siblings = [
            c for c in ALL_COURSES
            if c.get('課程名稱', '') == name and c.get('開課系所名稱', '') == dept
        ]
    else:
        siblings = [c for c in ALL_COURSES if c.get('課程名稱', '') == name]
    return jsonify({'courses': siblings})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
