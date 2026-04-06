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


def analyze_course_with_claude(course_name: str):
    # 1. Tavily search
    response = client.search(
        query=f"東海大學 {course_name} 評價 心得 site:dcard.tw",
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

    # 4. 呼叫 Groq
    chat = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一個分析大學課程評價的助理，請使用繁體中文回答。"
                    "根據提供的 Dcard 討論內容，完成以下三項分析，"
                    "並嚴格按照指定格式輸出，不要加入其他文字。\n\n"
                    "格式：\n"
                    "摘要：（3-5句，涵蓋老師風格、上課難度、考試/報告情況）\n"
                    "整體傾向：（正面 / 中性 / 負面，擇一）\n"
                    "難易度：X/5（1=極易，5=極難，並簡單解釋原因）"
                ),
            },
            {
                "role": "user",
                "content": f"以下是東海大學「{course_name}」的 Dcard 評價內容：\n\n{sources}",
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

response = client.search(
    query="東海大學 品牌管理 評價 心得 site:dcard.tw",
    search_depth="advanced",
    include_domains=["dcard.tw"],
    max_results=10,
    include_raw_content=False,
)

# 原有 search test
response = client.search(
    query="東海大學 品牌管理 評價 心得 site:dcard.tw",
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

# 新 function 測試
analyze_course_with_claude("品牌管理")
