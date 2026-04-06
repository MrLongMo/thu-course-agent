import pandas as pd
import json

# 讀取 CSV（副檔名 .xls，Big5/CP950 編碼），跳過欄位數不一致的行
df = pd.read_csv("data/courses_114_2.xls", encoding="cp950", on_bad_lines="skip")

# 只保留需要的欄位，學分用「學分2」
records = []
for _, row in df.iterrows():
    records.append({
        "選課代碼": str(row["選課代碼"]).strip(),
        "課程名稱": str(row["課程名稱"]).strip(),
        "開課系所名稱": str(row["開課系所名稱"]).strip(),
        "必選修": row["必選修"],
        "學分": int(row["學分2"]) if pd.notna(row["學分2"]) else 0,
    })

# 輸出 JSON
output_path = "data/processed/courses_114_2.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

print(f"成功 parse {len(records)} 筆課程 → {output_path}")
