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


@app.route('/')
def index():
    return render_template('index.html', departments=DEPARTMENTS)


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
    siblings = [c for c in ALL_COURSES if c.get('課程名稱', '') == name]
    return jsonify({'courses': siblings})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
