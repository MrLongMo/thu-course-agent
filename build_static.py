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


# ── Demo 課程補強資料：為 5 個不同系所的代表性課程補上完整欄位 ──
# key = 選課代碼（字串），value = 要合併進課程的額外欄位
DEMO_ENHANCEMENTS = {
    '987': {  # C++程式設計 — 資訊工程學系
        '授課教師': '陳建宏',
        '上課時間': '二/2,3,4',
        '教室': '資工201',
        '選課人數': 45,
        '上限人數': 50,
        '課程概述': (
            '本課程以 C++ 為主要程式語言，介紹物件導向程式設計的核心概念，包括類別、'
            '繼承、多型、泛型程式設計（STL）及例外處理。課程強調程式邏輯訓練與實作能力，'
            '每週均有上機練習與小作業，期末需完成一個完整的專題程式開發。'
        ),
        '評分方式': [
            {'評分項目': '期中考',    '配分比例': '30', '說明': '筆試+上機'},
            {'評分項目': '期末考',    '配分比例': '30', '說明': '筆試+上機'},
            {'評分項目': '平時作業',  '配分比例': '25', '說明': '每週程式作業'},
            {'評分項目': '期末專題',  '配分比例': '15', '說明': '小組實作'},
        ],
    },
    '98': {  # 英文作文（一）— 外國語文學系
        '授課教師': '林雅婷',
        '上課時間': '三/3,4',
        '教室': '語201',
        '選課人數': 22,
        '上限人數': 25,
        '課程概述': (
            '本課程訓練學生英文寫作的基礎技巧，涵蓋段落結構、論點發展、文法修辭與'
            '學術寫作規範。每週以不同主題進行寫作練習，教師提供個別回饋。'
            '課程結束時學生需繳交完整的議論文一篇（1200字以上）。'
        ),
        '評分方式': [
            {'評分項目': '週作業',    '配分比例': '40', '說明': '每週500字寫作'},
            {'評分項目': '期中作業',  '配分比例': '25', '說明': '800字命題作文'},
            {'評分項目': '期末論文',  '配分比例': '25', '說明': '1200字議論文'},
            {'評分項目': '課堂參與',  '配分比例': '10', '說明': '同儕互評、討論'},
        ],
    },
    '1572': {  # 統計學 — 統計學系
        '授課教師': '張明德',
        '上課時間': '一/3,4,5',
        '教室': '理203',
        '選課人數': 38,
        '上限人數': 45,
        '課程概述': (
            '本課程為統計學基礎課程，涵蓋敘述統計、機率理論、抽樣分佈、假設檢定、'
            '迴歸分析等主題。強調統計概念的理解與應用，並透過 R 語言進行實際資料分析。'
            '學生需具備微積分基礎，課程計算量較大，需勤加練習。'
        ),
        '評分方式': [
            {'評分項目': '期中考',    '配分比例': '35', '說明': '閉書考試'},
            {'評分項目': '期末考',    '配分比例': '35', '說明': '閉書考試'},
            {'評分項目': '作業',      '配分比例': '20', '說明': '每兩週一份'},
            {'評分項目': '出席',      '配分比例': '10', '說明': '點名'},
        ],
    },
    '28': {  # 中國文學史 — 中國文學系
        '授課教師': '吳明章',
        '上課時間': '五/2,3,4',
        '教室': '文101',
        '選課人數': 33,
        '上限人數': 40,
        '課程概述': (
            '本課程系統性介紹中國文學的歷史演變，從先秦諸子百家到明清小說，探討各時代'
            '文學思潮、重要作家與代表作品。課程兼顧文本細讀與宏觀脈絡，培養學生對'
            '中國文化傳統的認識與批判思考能力。'
        ),
        '評分方式': [
            {'評分項目': '期中報告',  '配分比例': '30', '說明': '指定作品分析'},
            {'評分項目': '期末考試',  '配分比例': '35', '說明': '論述題'},
            {'評分項目': '讀書報告',  '配分比例': '25', '說明': '每月一篇'},
            {'評分項目': '課堂討論',  '配分比例': '10', '說明': ''},
        ],
    },
    '2034': {  # 社會工作理論 — 社會工作學系
        '授課教師': '李桂英',
        '上課時間': '四/6,7,8',
        '教室': '社工301',
        '選課人數': 27,
        '上限人數': 35,
        '課程概述': (
            '本課程介紹社會工作的主要實務理論基礎，包括系統理論、生態觀點、優勢觀點、'
            '認知行為理論等。透過案例討論與角色扮演，培養學生運用理論分析實務情境的能力，'
            '並反思理論與實踐之間的張力。'
        ),
        '評分方式': [
            {'評分項目': '期中考',    '配分比例': '25', '說明': ''},
            {'評分項目': '理論分析報告', '配分比例': '35', '說明': '小組案例應用'},
            {'評分項目': '課堂討論',  '配分比例': '25', '說明': '每週案例討論'},
            {'評分項目': '出席',      '配分比例': '15', '說明': ''},
        ],
    },
}

# ── Demo AI 分析：預先寫好各 demo 課程的分析內容 ──
DEMO_ANALYSES = {
    '987': {  # C++程式設計
        'analysis': (
            '摘要：陳建宏老師的C++課程以實作為主，作業量偏多，每週都有程式作業需要繳交。'
            '上課風格清楚有條理，但對初學者來說難度不低，建議提前預習。'
            '期中、期末均為上機考試，平時勤練習的同學普遍反映成績還不錯。\n'
            '整體傾向：正面\n'
            '難易度：4/5（物件導向概念抽象，加上大量coding作業，時間壓力較大）'
        ),
        'source_count': 5,
        'source_note': '參考 5 筆 Dcard 貼文（Demo 預填資料）',
        'sources': [
            {'title': 'Dcard 東海大學版 — C++程式設計心得', 'url': 'https://www.dcard.tw/f/thu/p/example1'},
            {'title': 'Dcard — 資工必修雷課討論', 'url': 'https://www.dcard.tw/f/thu/p/example2'},
        ],
        'demo': True,
    },
    '98': {  # 英文作文（一）
        'analysis': (
            '摘要：林雅婷老師批改仔細，每篇作文都有詳細的個別回饋，對英文寫作進步幫助很大。'
            '每週作業量固定，需要認真投入時間，不能拖稿。'
            '老師上課氣氛輕鬆，但對文法錯誤要求嚴格，建議課前複習英文語法規則。\n'
            '整體傾向：正面\n'
            '難易度：3/5（作業量大但難度合理，只要認真寫就能維持不錯的成績）'
        ),
        'source_count': 4,
        'source_note': '參考 4 筆 Dcard 貼文（Demo 預填資料）',
        'sources': [
            {'title': 'Dcard 東海大學版 — 英文作文一評價', 'url': 'https://www.dcard.tw/f/thu/p/example3'},
        ],
        'demo': True,
    },
    '1572': {  # 統計學
        'analysis': (
            '摘要：張明德老師講課節奏快，板書清晰，但數學推導較多，對文科背景的同學挑戰較大。'
            'R 語言實作部分需要自學，老師提供的講義說明有限。'
            '考試偏重計算與應用題，建議多刷練習題，純背公式不夠。\n'
            '整體傾向：中性\n'
            '難易度：4/5（機率推導加上R語言雙重壓力，數學底子不好的同學要早做準備）'
        ),
        'source_count': 6,
        'source_note': '參考 6 筆 Dcard 貼文（Demo 預填資料）',
        'sources': [
            {'title': 'Dcard — 統計學心得分享', 'url': 'https://www.dcard.tw/f/thu/p/example4'},
            {'title': 'Dcard — 東海統計系課程討論', 'url': 'https://www.dcard.tw/f/thu/p/example5'},
        ],
        'demo': True,
    },
    '28': {  # 中國文學史
        'analysis': (
            '摘要：吳明章老師博學多聞，上課旁徵博引，課程內容豐富但記憶量龐大。'
            '報告佔分高，需要對指定文本有深入分析，不能流於表面。'
            '老師對遲交作業不友善，建議按時繳交。整體氛圍嚴肅但收穫豐富。\n'
            '整體傾向：正面\n'
            '難易度：3/5（內容廣博，背誦量大，但老師教學清晰，認真讀不會太難）'
        ),
        'source_count': 3,
        'source_note': '參考 3 筆 Dcard 貼文（Demo 預填資料）',
        'sources': [
            {'title': 'Dcard 東海大學版 — 中文系必修課討論', 'url': 'https://www.dcard.tw/f/thu/p/example6'},
        ],
        'demo': True,
    },
    '2034': {  # 社會工作理論
        'analysis': (
            '摘要：李桂英老師擅長以實際案例帶入理論，課堂討論互動活躍，氣氛溫暖。'
            '分組報告需要將理論應用在真實社工案例上，對實務能力培養很有幫助。'
            '考試以申論題為主，需要掌握各理論派別的核心概念與差異。\n'
            '整體傾向：正面\n'
            '難易度：2/5（只要認真參與討論、閱讀指定文本，成績普遍不錯）'
        ),
        'source_count': 4,
        'source_note': '參考 4 筆 Dcard 貼文（Demo 預填資料）',
        'sources': [
            {'title': 'Dcard — 社工系課程評價', 'url': 'https://www.dcard.tw/f/thu/p/example7'},
            {'title': 'Dcard 東海大學版 — 社會工作理論心得', 'url': 'https://www.dcard.tw/f/thu/p/example8'},
        ],
        'demo': True,
    },
}

# 將 DEMO_ENHANCEMENTS 合併進 ALL_COURSES（原地修改，不影響原始 JSON 檔案）
_course_map = {str(c.get('選課代碼', '')): c for c in ALL_COURSES}
for code, extra in DEMO_ENHANCEMENTS.items():
    if code in _course_map:
        _course_map[code].update(extra)


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


# ── 靜態資料注入器：注入全域變數供 index.html 靜態模式使用 ──
# 使用獨特占位符，避免 str.format() 解析 JSON 中的 {} 字元
STATIC_DATA_INJECTOR = """
<script>
/* ── 靜態 Demo 模式：注入課程資料至全域變數，供 fetchCourses() 等函式直接使用 ── */
window.__STATIC_COURSES  = __COURSES_JSON__;
window.__STATIC_ANALYSES = __ANALYSES_JSON__;
</script>
"""


def build():
    # 設定 Jinja2 環境（加入 tojson filter 供 planner.html 使用）
    env = Environment(loader=FileSystemLoader('web/templates'))
    env.filters['tojson'] = lambda v, **kw: json.dumps(v, ensure_ascii=False)

    os.makedirs('docs', exist_ok=True)

    # ── 生成 index.html ──
    courses_json       = json.dumps(ALL_COURSES, ensure_ascii=False, separators=(',', ':'))
    demo_analyses_json = json.dumps(DEMO_ANALYSES, ensure_ascii=False, separators=(',', ':'))

    # 用 replace() 取代占位符，完全避免 str.format() 解析 JSON 中的 {} 問題
    injector = STATIC_DATA_INJECTOR \
        .replace('__COURSES_JSON__', courses_json) \
        .replace('__ANALYSES_JSON__', demo_analyses_json)

    html = env.get_template('index.html').render(departments=DEPARTMENTS)
    # 修正 /planner 連結為相對路徑
    html = html.replace('href="/planner"', 'href="planner.html"')
    # 將資料注入器注入到主 <script> 之前
    html = html.replace('\n<script>\n  // ════════════════════════════════\n  //  State',
                        injector + '\n<script>\n  // ════════════════════════════════\n  //  State')

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
    # 修正 planner.html 中的連結（Flask 路由 → GitHub Pages 相對路徑）
    planner_html = planner_html.replace('href="/"',          'href="index.html"')
    planner_html = planner_html.replace('href="/#schedule"', 'href="index.html#schedule"')
    planner_html = planner_html.replace('href="/planner"',   'href="planner.html"')

    with open('docs/planner.html', 'w', encoding='utf-8') as f:
        f.write(planner_html)
    print(f'✅ docs/planner.html 生成完畢（共 {len(planner_html)//1024} KB）')

    print('\n🎉 靜態檔案已生成至 docs/ 資料夾')


if __name__ == '__main__':
    build()
