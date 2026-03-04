import json
import os
import sys

# ================= 配置区域 =================
# 1. 待合并文件列表 (Hardcode)
FILES_TO_MERGE = [
    "data/YI_XIANG_HAO_JU.json",
    "data/YUN_XIAO_EDU_AU.json"
    # 在这里添加更多...
]

# 2. 输出文件
OUTPUT_FILE = "data/demo_data.json"
# ===========================================

def load_json_content(file_path):
    """读取 JSON 并统一转换为 List"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 兼容处理：如果是 {"articles": [...]} 格式，取出列表
    if isinstance(data, dict):
        # 尝试常见的 key，如果没有则报错
        if "articles" in data:
            return data["articles"]
        elif "data" in data:
            return data["data"]
        else:
            # 如果是字典但没找到列表 wrapper，可能单条数据，包成 list
            return [data]
    elif isinstance(data, list):
        return data
    else:
        raise ValueError("JSON 格式无法解析 (既不是 List 也不是包含 articles 的 Dict)")

def get_keys_from_item(item):
    """获取一个字典的所有 Key，用于比较"""
    return set(item.keys())

def main():
    print(f"🔍 正在进行格式检查 (共 {len(FILES_TO_MERGE)} 个文件)...")
    
    standard_keys = None
    standard_file = ""
    valid_data_buffer = []

    # --- 第一步：格式检查 (Validation Phase) ---
    for idx, file_path in enumerate(FILES_TO_MERGE):
        if not os.path.exists(file_path):
            print(f"❌ 错误: 文件不存在 -> {file_path}")
            sys.exit(1)

        try:
            items = load_json_content(file_path)
            
            if not items:
                print(f"⚠️ 警告: 文件为空，跳过 -> {file_path}")
                continue

            # 检查该文件内的每一条数据
            # (为了性能，这里默认检查第一条。如果你想极度严格，可以遍历 items)
            current_keys = get_keys_from_item(items[0])

            # 如果是第一个有效文件，将其设为“标准模板”
            if standard_keys is None:
                standard_keys = current_keys
                standard_file = file_path
                print(f"✅ 设定标准格式 (基于 {os.path.basename(file_path)}): {standard_keys}")
            else:
                # 后续文件必须与标准一致
                if current_keys != standard_keys:
                    print("\n🛑 格式不匹配！停止合并！")
                    print(f"标准文件 ({os.path.basename(standard_file)}): {standard_keys}")
                    print(f"错误文件 ({os.path.basename(file_path)}): {current_keys}")
                    
                    # 找出具体的差异
                    missing = standard_keys - current_keys
                    extra = current_keys - standard_keys
                    if missing: print(f"  -> 缺少 Key: {missing}")
                    if extra:   print(f"  -> 多余 Key: {extra}")
                    
                    sys.exit(1) # 直接退出程序

            # 如果检查通过，暂存数据
            valid_data_buffer.extend(items)
            print(f"  OK -> {os.path.basename(file_path)} (格式一致)")

        except Exception as e:
            print(f"❌ 解析错误 {file_path}: {str(e)}")
            sys.exit(1)

    # --- 第二步：写入文件 (Merge Phase) ---
    print(f"\n✨ 所有文件检查通过！开始合并 {len(valid_data_buffer)} 条数据...")
    
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(valid_data_buffer, f, ensure_ascii=False, indent=2)
        print(f"💾 成功保存到: {OUTPUT_FILE}")
    except Exception as e:
        print(f"❌ 写入失败: {e}")

if __name__ == "__main__":
    main()