import json
import torch
from torch.utils.data import Dataset

class QADataset(Dataset):
    def __init__(self, path, tokenizer, max_len=512, negative_ratio=1):
        """
        path: 数据文件路径 (json)
        tokenizer: 来自 CrossEncoder 的 tokenizer
        max_len: 最大序列长度
        negative_ratio: 每个正样本配多少个负样本 (默认 1:1)
        """
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        self.tokenizer = tokenizer
        self.max_len = max_len
        self.negative_ratio = negative_ratio

        # 构造正样本
        self.samples = []
        for item in self.data:
            q = item["question"]
            a = item["answer"]
            self.samples.append((q, a, 1))  # 正样本 label=1

        # 构造负样本（简单随机负例）
        if negative_ratio > 0:
            import random
            all_answers = [d["answer"] for d in self.data]
            for item in self.data:
                q = item["question"]
                for _ in range(negative_ratio):
                    neg_a = random.choice(all_answers)
                    # 确保不是正确答案
                    if neg_a != item["answer"]:
                        self.samples.append((q, neg_a, 0))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        q, a, label = self.samples[idx]
        enc = self.tokenizer(
            q, a,
            truncation=True,
            padding="max_length",
            max_length=self.max_len,
            return_tensors="pt"
        )
        return {
            "input_ids": enc["input_ids"].squeeze(0),
            "attention_mask": enc["attention_mask"].squeeze(0),
            "labels": torch.tensor(label, dtype=torch.long)
        }
