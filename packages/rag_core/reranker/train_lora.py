import torch
from torch.utils.data import DataLoader
from transformers import AdamW, get_scheduler
from tqdm import tqdm
from sentence_transformers import CrossEncoder
from peft import get_peft_model, LoraConfig, TaskType

# 导入你写好的 QADataset
from qa_dataset import QADataset

# 1. 加载基础 cross-encoder
base_model_name = "cross-encoder/ms-marco-MiniLM-L12-v2"
cross_encoder = CrossEncoder(base_model_name, num_labels=2, max_length=512, device="cuda")

# 取出底层 HuggingFace 模型
hf_model = cross_encoder.model

# 2. 配置 LoRA
lora_config = LoraConfig(
    task_type=TaskType.SEQ_CLS,  # 序列分类任务
    r=8,
    lora_alpha=16,
    lora_dropout=0.1
)
hf_model = get_peft_model(hf_model, lora_config)

# 3. 准备数据
train_dataset = QADataset("data/qa_train.json", cross_encoder.tokenizer)
train_loader = DataLoader(train_dataset, batch_size=16, shuffle=True)

# 4. 优化器 & 学习率调度
optimizer = AdamW(hf_model.parameters(), lr=2e-5)
num_training_steps = len(train_loader) * 3  # 假设 3 个 epoch
lr_scheduler = get_scheduler("linear", optimizer=optimizer,
                             num_warmup_steps=0,
                             num_training_steps=num_training_steps)

criterion = torch.nn.CrossEntropyLoss()

# 5. 训练循环
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
hf_model.to(device)

for epoch in range(3):
    hf_model.train()
    loop = tqdm(train_loader, desc=f"Epoch {epoch+1}")
    for batch in loop:
        optimizer.zero_grad()
        outputs = hf_model(
            input_ids=batch["input_ids"].to(device),
            attention_mask=batch["attention_mask"].to(device)
        )
        loss = criterion(outputs.logits, batch["labels"].to(device))
        loss.backward()
        optimizer.step()
        lr_scheduler.step()
        loop.set_postfix(loss=loss.item())

# 6. 保存 LoRA adapter
hf_model.save_pretrained("lora_adapter/")
print("✅ LoRA adapter 已保存到 lora_adapter/")
