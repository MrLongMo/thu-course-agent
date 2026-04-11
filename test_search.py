from dotenv import load_dotenv
import os
from tavily import TavilyClient
from groq import Groq

load_dotenv()

api_key = os.getenv("TAVILY_API_KEY")
if not api_key:
    raise ValueError("TAVILY_API_KEY not found in .env")

groq_key = os.getenv("GROQ_API_KEY")
if not groq_key:
    raise ValueError("GROQ_API_KEY not found in .env")

client = TavilyClient(api_key=api_key)
groq = Groq(api_key=groq_key)


def analyze_course_with_claude(course_name: str, teacher_name: str = ""):
    # 1. Tavily search（包含老師名提高精準度）
    query = f"東海大學 {course_name} {teacher_name} Dcard 評價".strip() if teacher_name else f"東海大學 {course_name} 評價 心得 site:dcard.tw"
    response = client.search(
        query=query,
        search_depth="advanced",
        include_domains=["dcard.tw"],
        max_results=8,
        include_answer=True,
        include_raw_content=False,
    )

    # 2. 過濾 score >= 0.3
    filtered = [r for r in response.get("results", []) if r.get("score", 0) >= 0.3]

    if not filtered:
        print(f"找不到足夠相關的 Dcard 評價（score < 0.3）")
        return

    # 3. 取 top 3-5 筆
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

    # 5. 呼叫 Groq
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
    analysis = chat.choices[0].message.content

    # 5. Print 結果
    print(f"\n{'='*50}")
    print(f"  {course_name} AI 分析")
    print(f"{'='*50}")
    print(f"（參考 {len(top_results)} 筆 Dcard 貼文，已過濾低相關度）\n")
    print(analysis)
    print(f"{'='*50}\n")

# 測試：包含老師名的搜尋 query
TEST_COURSE = "品牌管理"
TEST_TEACHER = "陳老師"  # 替換成實際老師名

response = client.search(
    query=f"東海大學 {TEST_COURSE} {TEST_TEACHER} Dcard 評價",
    search_depth="advanced",
    include_domains=["dcard.tw"],
    max_results=10,
    include_raw_content=False,
)

print(f"\n{'='*60}")
print(f"Query: {response.get('query')}")
print(f"Results: {len(response.get('results', []))}")
print(f"{'='*60}\n")

for i, result in enumerate(response.get("results", []), 1):
    print(f"[{i}] {result.get('title', 'No Title')}")
    print(f"    URL   : {result.get('url')}")
    print(f"    Score : {result.get('score', 'N/A')}")
    print(f"    Content: {result.get('content', '')[:200]}...")
    print()

# 新 function 測試（帶老師名）
analyze_course_with_claude(TEST_COURSE, TEST_TEACHER)
