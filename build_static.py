"""
build_static.py — 將 Flask 模板編譯成 GitHub Pages 用的靜態 HTML
執行方式：python build_static.py
輸出：docs/index.html, docs/planner.html
"""
import json
import os
from jinja2 import Environment, FileSystemLoader

# ── 讀取課程資料 ──
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'processed', 'courses_114_2.json')
with open(DATA_PATH, encoding='utf-8') as f:
    ALL_COURSES = json.load(f)

# 整理系所列表（與 app.py 一致）
DEPARTMENTS = sorted(set(
    c.get('開課系所名稱', '').strip()
    for c in ALL_COURSES
    if c.get('開課系所名稱', '').strip()
))

# ── Planner 資料（與 app.py 一致）──
PLANNER_PROFILE = {
    'school': '東海大學',
    'department': '企業管理學系',
    'year': 3,
    'workloadPreference': 'balanced',
}

PLANNER_REQUIREMENT = {
    'totalCredits': 128,
    'categories': {
        'required': 64,
        'departmentElective': 30,
        'generalEducation': 28,
        'freeElective': 6,
    }
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
    """映射課程到修業類別。"""
    dept = course.get('開課系所名稱', '')
    required_type = str(course.get('必選修', '')).replace('.0', '')
    if '通識' in dept or dept in {'大一英文', '大一大二體育', '第二外國語'}:
        return 'generalEducation'
    if dept == PLANNER_PROFILE['department']:
        return 'required' if required_type == '1' else 'departmentElective'
    return 'freeElective'


def _planner_priority(course):
    """排序候選課程。"""
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
    """候選課程列表（最多 160 筆）。"""
    relevant = [
        c for c in ALL_COURSES
        if c.get('開課系所名稱') == PLANNER_PROFILE['department']
        or '通識' in c.get('開課系所名稱', '')
        or c.get('開課系所名稱') in {'資訊工程學系', '工業工程與經營資訊學系', '大一英文'}
    ]
    relevant.sort(key=_planner_priority, reverse=True)
    return [_planner_course_payload(c) for c in relevant[:160]]


# ── fetch 攔截器：靜態模式下攔截所有 /api/* 請求 ──
FETCH_INTERCEPTOR_TEMPLATE = """
<script>
/* ── 靜態 Demo 模式：攔截 /api/* 請求，改用本地資料 ── */
(function () {{
  const ALL_COURSES = {courses_json};

  const _orig = window.fetch.bind(window);
  window.fetch = function (resource, opts) {{
    const url = typeof resource === 'string' ? resource : (resource.url || '');

    /* /api/courses?q=...&dept=...&page=...&per_page=... */
    if (url.startsWith('/api/courses')) {{
      const p        = new URLSearchParams(url.split('?')[1] || '');
      const q        = (p.get('q') || '').toLowerCase().trim();
      const dept     = p.get('dept') || '';
      const page     = Math.max(1, parseInt(p.get('page')     || '1'));
      const per_page = Math.min(100, Math.max(1, parseInt(p.get('per_page') || '30')));

      let res = ALL_COURSES;
      if (dept) res = res.filter(c => c['開課系所名稱'] === dept);
      if (q)    res = res.filter(c =>
        (c['課程名稱']  || '').toLowerCase().includes(q) ||
        (c['授課教師']  || '').toLowerCase().includes(q) ||
        String(c['選課代碼'] || '').includes(q)
      );

      const total    = res.length;
      const start    = (page - 1) * per_page;
      const courses  = res.slice(start, start + per_page);
      const payload  = {{ total, page, per_page, courses }};
      return Promise.resolve({{ ok: true, json: () => Promise.resolve(payload) }});
    }}

    /* /api/analyze/<id> — 顯示靜態 demo 提示 */
    if (/^[/]api[/]analyze[/]/.test(url)) {{
      return Promise.resolve({{
        ok: true,
        json: () => Promise.resolve({{
          no_data: false,
          analysis: '摘要：此為 GitHub Pages 靜態展示版本，AI 搜尋 Dcard 評價功能需要後端伺服器支援。\\n整體傾向：中性\\n難易度：資料不足',
          source_count: 0,
          source_note: '📌 靜態 Demo 版本 — AI 分析需要後端伺服器（Tavily + Groq）',
          sources: []
        }})
      }});
    }}

    /* /api/course_time/<id> — 回傳空時間（時間表功能需後端） */
    if (/^[/]api[/]course_time[/]/.test(url)) {{
      return Promise.resolve({{ ok: true, json: () => Promise.resolve({{ slots: [] }}) }});
    }}

    /* /api/siblings/<id> — 從本地資料找同名課程 */
    if (/^[/]api[/]siblings[/]/.test(url)) {{
      const cid     = url.split('/').pop();
      const course  = ALL_COURSES.find(c => String(c['選課代碼']) === cid);
      const siblings = course
        ? ALL_COURSES
            .filter(c => c['課程名稱'] === course['課程名稱'])
            .map(c => ({{ id: String(c['選課代碼']), teacher: c['授課教師'] || '', name: c['課程名稱'] || '' }}))
        : [];
      return Promise.resolve({{ ok: true, json: () => Promise.resolve(siblings) }});
    }}

    return _orig(resource, opts);
  }};
}})();
</script>
"""


def build():
    # 設定 Jinja2 環境（加入 tojson filter 供 planner.html 使用）
    env = Environment(loader=FileSystemLoader('web/templates'))
    env.filters['tojson'] = lambda v, **kw: json.dumps(v, ensure_ascii=False)

    os.makedirs('docs', exist_ok=True)

    # ── 生成 index.html ──
    courses_json = json.dumps(ALL_COURSES, ensure_ascii=False, separators=(',', ':'))
    interceptor  = FETCH_INTERCEPTOR_TEMPLATE.format(courses_json=courses_json)

    html = env.get_template('index.html').render(departments=DEPARTMENTS)
    # 修正 /planner 連結為相對路徑
    html = html.replace('href="/planner"', 'href="planner.html"')
    # 在 </body> 前注入攔截器
    html = html.replace('</body>', interceptor + '\n</body>')

    with open('docs/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✅ docs/index.html 生成完畢（{len(ALL_COURSES)} 筆課程，共 {len(html)//1024} KB）')

    # ── 生成 planner.html ──
    planner_html = env.get_template('planner.html').render(
        profile=PLANNER_PROFILE,
        requirement=PLANNER_REQUIREMENT,
        completed_courses=PLANNER_COMPLETED_COURSES,
        candidate_courses=_planner_candidates(),
    )
    # 修正返回首頁連結
    planner_html = planner_html.replace('href="/"', 'href="index.html"')

    with open('docs/planner.html', 'w', encoding='utf-8') as f:
        f.write(planner_html)
    print(f'✅ docs/planner.html 生成完畢（共 {len(planner_html)//1024} KB）')

    print('\n🎉 靜態檔案已生成至 docs/ 資料夾')


if __name__ == '__main__':
    build()
