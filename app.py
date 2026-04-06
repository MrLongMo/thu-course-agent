"""
THU 選課輔助工具 - Flask 主程式
"""
import json
import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify, request

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

    # 關鍵字搜尋（課程名稱）
    if q:
        results = [
            c for c in results
            if q in c.get('課程名稱', '').lower()
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


if __name__ == '__main__':
    app.run(debug=True, port=5001)
