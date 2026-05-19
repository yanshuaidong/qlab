"""DeepSeek API 联网搜索示例"""
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

api_key = os.getenv("DEEPSEEK_API_KEY")
print(f"API Key 前8位: {api_key[:8] if api_key else '未找到'}...")

resp = requests.post(
    "https://api.deepseek.com/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "今天有什么重要的科技新闻？"}],
        "enable_search": True,
        "stream": False,
    },
)

print(f"\nHTTP 状态码: {resp.status_code}")
print(f"完整响应:\n{json.dumps(resp.json(), ensure_ascii=False, indent=2)}")