import requests
import json

headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://luxwork.online",
    "Pragma": "no-cache",
    "Referer": "https://luxwork.online/products",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": "\"Microsoft Edge\";v=\"149\", \"Chromium\";v=\"149\", \"Not)A;Brand\";v=\"24\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\""
}
cookies = {
    "mgr-sid": "1d1715e6-82ca-4745-879c-f6d215b47aac",
    "somoveLanguage": "zh"
}
url = "https://luxwork.online/ajax/products/list"
data = {
    "draw": "1",
    "start": "0",
    "limit": "50",
    "isSelf": "1",
    "selfShop": "1",
    "mergedFlag": "0",
    "splitFlag": "0",
    "name": "",
    "categoryId": "",
    "kindId": "",
    "shopId": "-1",
    "isSynInfo": "",
    "isSyn": "",
    "discount": "",
    "recommend": "",
    "hasFreeze": "",
    "qinsiNum": "",
    "comeRecourse": "",
    "hasRfId": "",
    "timeRange": ""
}

response = requests.post(url, headers=headers, cookies=cookies, data=data)

# 打印响应状态码
print(f"状态码: {response.status_code}")
print(f"状态信息: {response.reason}\n")
print("=" * 50)
print("响应内容:")
print("=" * 50)

# 尝试解析 JSON 并格式化输出
try:
    json_data = response.json()
    print(json.dumps(json_data, ensure_ascii=False, indent=2))

    # 如果是分页数据，可以进一步解析
    if isinstance(json_data, dict):
        print("\n" + "=" * 50)
        print("数据摘要:")
        print("=" * 50)

        # 如果有 data 字段且包含总记录数
        if 'data' in json_data and isinstance(json_data['data'], dict):
            if 'recordsTotal' in json_data['data']:
                print(f"总记录数: {json_data['data']['recordsTotal']}")
            if 'data' in json_data['data'] and isinstance(json_data['data']['data'], list):
                print(f"当前返回记录数: {len(json_data['data']['data'])}")

        # 如果有直接的 recordsTotal
        elif 'recordsTotal' in json_data:
            print(f"总记录数: {json_data['recordsTotal']}")
            if 'data' in json_data and isinstance(json_data['data'], list):
                print(f"当前返回记录数: {len(json_data['data'])}")

except json.JSONDecodeError:
    # 如果不是 JSON 格式，直接打印原始文本（但限制长度）
    print(response.text[:500] + "..." if len(response.text) > 500 else response.text)