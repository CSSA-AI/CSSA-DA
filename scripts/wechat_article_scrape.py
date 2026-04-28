import json
import requests
import urllib.parse
import os
import time
import re
import shutil
import sys
from datetime import datetime

# ==========================================
# 系统配置 (Configuration)
# ==========================================
API_KEY = 'afd78ef5a5984e2d85f672c244c98138'
FAKE_ID = "MjM5OTAxNTM0MA=="  # 墨大 CSSA
BASE_URL = "https://down.mptext.top/api/public/v1"

# 目录与文件路径配置
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
TEMP_DIR = os.path.join(DATA_DIR, "temp_chunks")
STATE_FILE = os.path.join(DATA_DIR, "scraper_state.json")
FINAL_FILE = os.path.join(DATA_DIR, "wechat_articles_all.json")
# ==========================================

def init_environment():
    """初始化目录结构"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

def load_state():
    """读取上次的抓取进度"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                # 将列表转回集合，方便 O(1) 查找
                state["seen_links"] = set(state.get("seen_links", []))
                print(f"🔄 [RESUME] 发现历史进度！将从第 {state['begin']} 篇继续抓取...")
                return state
        except Exception as e:
            print(f"⚠️ [WARN] 状态文件损坏，将重新开始: {e}")
    
    return {
        "begin": 0,
        "total_saved": 0,
        "valid_count": 0,
        "seen_links": set()
    }

def save_state(state):
    """持久化保存当前进度"""
    state_copy = state.copy()
    # JSON 不支持 set，转回 list
    state_copy["seen_links"] = list(state_copy["seen_links"])
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state_copy, f, ensure_ascii=False, indent=2)

def merge_and_cleanup(state):
    """最终合并所有 Chunk 并清理战场"""
    print("\n" + "="*50)
    print("📦 [MERGE] 抓取主循环结束，开始合并数据块...")
    
    all_articles = []
    chunk_files = sorted([f for f in os.listdir(TEMP_DIR) if f.endswith(".json")])
    
    for chunk_name in chunk_files:
        chunk_path = os.path.join(TEMP_DIR, chunk_name)
        with open(chunk_path, "r", encoding="utf-8") as f:
            all_articles.extend(json.load(f))
            
    if all_articles:
        with open(FINAL_FILE, "w", encoding="utf-8") as f:
            json.dump(all_articles, f, ensure_ascii=False, indent=2)
        print(f"✅ [SUCCESS] 成功合并 {len(all_articles)} 篇文章至: {FINAL_FILE}")
        
        # 痕迹清理：确认写入成功后，删除 temp 文件夹和状态文件
        shutil.rmtree(TEMP_DIR)
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        print("🧹 [CLEANUP] 临时分块和状态文件已清理完毕。")
    else:
        print("📭 [INFO] 未发现任何有效数据可合并。")
    
    print("="*50)
    print(f"🎉 任务总计: 入库 {state['total_saved']} 篇 | 合格长文 {state['valid_count']} 篇")

def fetch_pipeline():
    init_environment()
    state = load_state()
    headers = {"X-Auth-Key": API_KEY}
    size = 20  # 每批次 20 篇

    try:
        while True:
            print(f"\n📡 [FETCH] 正在请求批次: 第 {state['begin']} - {state['begin'] + size} 篇...")
            list_url = f"{BASE_URL}/article"
            params = {"fakeid": FAKE_ID, "begin": state['begin'], "size": size}
            
            res = requests.get(list_url, headers=headers, params=params)
            res_data = res.json()
            
            # API 级别错误处理
            if res_data.get("base_resp", {}).get("ret") != 0:
                err = res_data.get('base_resp', {}).get('err_msg')
                print(f"❌ [API ERROR] 接口报错: {err}")
                print("💡 提示: 可能是密钥已过期。请更新代码里的 API_KEY 后重新运行，脚本会自动断点续传！")
                break

            articles = res_data.get("articles", [])
            
            if not articles:
                print("🏁 [INFO] API 返回为空，已触及历史最深处！所有文章抓取完毕。")
                merge_and_cleanup(state)
                return

            batch_results = []
            new_articles_count = 0
            
            for item in articles:
                title = item.get("title", "未命名文章")
                link = item.get("link")
                
                # 防重检查
                if not link or link in state["seen_links"]:
                    continue
                
                state["seen_links"].add(link)
                new_articles_count += 1
                
                encoded_url = urllib.parse.quote(link, safe='')
                download_url = f"{BASE_URL}/download?url={encoded_url}&format=markdown"
                
                # 下载与兼容解析
                try:
                    dl_res = requests.get(download_url, timeout=10)
                    try:
                        content = dl_res.json().get("data", "")
                    except:
                        content = dl_res.text
                except Exception as e:
                    print(f"  ⚠️ [WARN] 下载失败: {title} | {e}")
                    content = ""

                # 数据清洗与评估
                pure_text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', content)
                pure_length = len(pure_text)
                
                # 丢弃极长乱码
                if len(content) > 3000 and pure_length < 50:
                    print(f"  🗑️ [DROP] 丢弃乱码/纯图: {title}")
                    continue
                
                is_valid = pure_length >= 50
                if is_valid:
                    state["valid_count"] += 1
                    status_tag = f"✅ [VALID]"
                else:
                    status_tag = f"🔖 [SHORT]"

                print(f"  📥 {status_tag} {title[:25]}... | 有效字数: {pure_length}")

                create_time = item.get("create_time", 0)
                formatted_date = datetime.fromtimestamp(create_time).strftime('%Y-%m-%d') if create_time else "1970-01-01"

                batch_results.append({
                    "title": title,
                    "link": link,
                    "content": content,
                    "date": formatted_date,
                    "source": "WeChat",
                    "is_valid_for_rag": is_valid
                })
                time.sleep(0.5)

            # 死循环保护
            if new_articles_count == 0:
                print("🏁 [INFO] 本批次无新数据，检测到循环，终止抓取。")
                merge_and_cleanup(state)
                return

            # ======= 批次落盘机制 =======
            if batch_results:
                batch_filename = os.path.join(TEMP_DIR, f"batch_{state['begin']}.json")
                with open(batch_filename, "w", encoding="utf-8") as f:
                    json.dump(batch_results, f, ensure_ascii=False, indent=2)
                
                state["total_saved"] += len(batch_results)
            
            # 更新下一页指针并保存全局状态
            state['begin'] += len(articles)
            save_state(state)
            
            print(f"💾 [STATE SAVED] 进度已备份 | 累计总数: {state['total_saved']} | 累计合格: {state['valid_count']}")

    except KeyboardInterrupt:
        # ======= 优雅中断机制 =======
        print("\n🛑 [INTERRUPT] 接收到手动中止信号 (Ctrl+C)！")
        print("💾 正在紧急保护现场并保存状态...")
        save_state(state)
        print("✅ 状态保存成功！下次运行将自动从本次断点继续。")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 [FATAL ERROR] 发生未捕获的异常: {e}")
        save_state(state)
        sys.exit(1)

if __name__ == "__main__":
    fetch_pipeline()