import json
import random
from generator_module import GeneratorModule

def print_usage(u):
    if u:
        print(f"\n[usage] prompt={u.get('prompt_tokens')}  "
              f"completion={u.get('completion_tokens')}  "
              f"total={u.get('total_tokens')}  "
              f"elapsed={u.get('elapsed_sec')}s")

if __name__ == "__main__":
    # 本地测试：加载清洗后的数据（真实部署时请用 模块二/三 的结果替代）
    with open("qa_clean_data.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)
    mock_context = random.sample(dataset, min(5, len(dataset)))

    gen = GeneratorModule(model_name="gpt-5-nano", temperature=0.2)

    # —— 非流式 —— 
    ans = gen.generate_answer(
        "在墨尔本如何办理公交卡？",
        mock_context,
        session_id="demo-user-1",
        on_usage=print_usage
    )
    print("\n=== 非流式最终回答 ===\n", ans)

    # —— 流式 —— 
    print("\n=== 流式输出（逐字） ===")
    for piece in gen.stream_answer(
        "那需要多少钱？",   # 追问，验证 memory 是否理解“公交卡”的上下文
        mock_context,
        session_id="demo-user-1",
        on_usage=print_usage
    ):
        print(piece, end="", flush=True)
    print()
