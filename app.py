"""
THU 選課輔助工具 - Flask 主程式
"""
import json
import os
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


if __name__ == '__main__':
    app.run(debug=True, port=5001)
