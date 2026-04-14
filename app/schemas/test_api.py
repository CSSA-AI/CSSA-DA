import requests

url = "http://127.0.0.1:8000/chat"
payload = {"query": "如何租房？"}

response = requests.post(url, json=payload)

print("status_code:", response.status_code)
print("response_json:", response.json())