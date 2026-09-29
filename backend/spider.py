import requests
import json
import urllib3

# 忽略由于 verify=False 产生的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ⚠️ 注意：你现在的 URL 只有 user 和 limit，如果必须传其他参数，请加在 URL 或 params 中
url = "https://luxwork.online/ajax/ai/conversations?user=1642&limit=30"

headers = {
    "Accept": "*/*",
    "Accept-Language": "zh,en-GB;q=0.9,en;q=0.8,zh-CN;q=0.7",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "https://luxwork.online/lux-ai",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

cookies = {
    "mgr-sid": "c1960168-a65a-468b-8d42-4aef711f13fc",
    "somoveLanguage": "zh",
}

# 代理配置（如果不需要代理，可以删掉 proxies=proxies）
proxies = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
}

try:
    print("正在发送请求...")
    # 如果你需要传第一次代码里的那些参数（isSelf, selfShop等），请用 requests.post 并且传 data=payload
    # 目前沿用你第二次的 GET 请求
    response = requests.get(
        url,
        headers=headers,
        cookies=cookies,
        proxies=proxies,
        timeout=30,
        verify=False
    )

    print(f"状态码: {response.status_code}")
    json_data = response.json()
    print(json.dumps(json_data, ensure_ascii=False, indent=2))

    if not json_data.get('content', {}).get('data'):
        print("\n💡 提示: 返回的数据为空，建议检查 Cookie 是否过期，或补全 URL 参数。")

except Exception as e:
    print(f"❌ 请求发生异常: {e}")