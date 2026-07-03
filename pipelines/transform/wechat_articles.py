import re
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class WechatTransformStats:
    input_count: int
    skipped_count: int
    dropped_count: int
    output_count: int
    original_char_count: int
    cleaned_char_count: int

    @property
    def removed_char_count(self) -> int:
        return self.original_char_count - self.cleaned_char_count


@dataclass(frozen=True)
class WechatTransformResult:
    records: list[dict[str, Any]]
    stats: WechatTransformStats


def clean_text(text: str | None) -> str:
    """
    数据深度净化核心逻辑：使用正则表达式剔除无用字符、图片、前端代码和模板
    """
    if not text:
        return ""
        
    # ================= 阶段 1: 尾部模板截断 =================
    # 砍掉底部千篇一律的废话，防止污染 RAG 向量池
    footer_markers = [
        r'\*?\*?联系我们\*?\*?\s*\n\s*大家有任何关于CSSA的疑问', # 匹配 "联系我们..."
        r'此外！CSSA 目前设有以下\*?\*?社群',                  # 匹配 "社群列表..."
        r'\*?\*?墨尔本大学中国学生学者联谊会\*?\*?\s*\n\s*\*?\*?主席邮箱', # 匹配 "底部邮箱..."
        r'大家有需要的可以\*?\*?私信 CSSA小助手',
        r'\\?-END\\?-',                                     # 增加：匹配结尾的 -END-
        r'文案\s*[/丨]\s*[a-zA-Z\u4e00-\u9fa5]+'            # 增加：匹配 "文案 / William"
    ]
    
    # 找到最早出现模板的位置，将其后面的内容全部切除
    truncate_index = len(text)
    for marker in footer_markers:
        match = re.search(marker, text)
        if match:
            truncate_index = min(truncate_index, match.start())
    text = text[:truncate_index]

    # ================= 阶段 2: 微信专有噪音剔除 =================
    # 增加/修改：强化 CSS 剔除，兼容所有带有 \_ 的样式表和群组样式
    text = re.sub(r'(?:#js|#page-content|\.\_|img|\.sns)[^\{]*\{[^}]+\}', '', text)
    
    # 剔除 "小说阅读器" 等 UI 占位符
    text = re.sub(r'在小说阅读器读本章.*?在小说阅读器中沉浸阅读', '', text, flags=re.DOTALL)
    
    # 增加/修改：剔除文章开头的作者冗余信息及所有 javascript:void 占位链接
    text = re.sub(r'(墨大中国学生会\s*){2,}', '', text)
    text = re.sub(r'\[.*?\]\(javascript:void\\?\(0\\?\);?\)', '', text)
    
    # 增加：剔除无意义的长条等号/减号分割线 (如 ========================)
    text = re.sub(r'={5,}|-{5,}', '', text)

    # ================= 阶段 3: 通用 Markdown/HTML 净化 =================
    # 1. 剔除 Markdown 图片: ![alt text](https://...)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 2. 剔除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 3. 剔除游离的腾讯图片链接
    text = re.sub(r'https?://mmbiz\.qpic\.cn/[^\s\n]+', '', text)
    
    # ================= 阶段 4: 排版整理 =================
    # 剔除不可见字符 (零宽字符等)
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff]', '', text)
    # 替换不寻常的换行符 (修复 VS Code 警告的 LS/PS)
    text = re.sub(r'[\u2028\u2029]', '\n', text)
    # 清除整行全是空格的“幽灵行”
    text = re.sub(r'^[ \t]+$', '', text, flags=re.MULTILINE)
    
    # 暴力剔除所有星号 (Markdown 残留)
    text = text.replace('*', '')
    
    # 压缩多余空格与换行
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[\r\n]+', '', text)
    
    return text.strip()


def transform_articles(
    raw_articles: list[dict[str, Any]],
    *,
    created_at: date,
) -> WechatTransformResult:
    processed_articles = []
    original_char_count = 0
    cleaned_char_count = 0
    dropped_count = 0
    skipped_count = 0

    for item in raw_articles:
        if not item.get("is_valid_for_rag", False):
            skipped_count += 1
            continue

        title = item.get("title", "未命名文章")
        raw_content = item.get("content", "")
        original_char_count += len(raw_content)
        
        # 核心清洗步骤
        cleaned_content = clean_text(raw_content)
        cleaned_char_count += len(cleaned_content)
        
        # 二次质量检验: 如果砍掉模板和乱码后，正文所剩无几，直接抛弃
        if len(re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', cleaned_content)) < 30:
            dropped_count += 1
            continue

        if not cleaned_content.startswith(title) and not cleaned_content.startswith(f"# {title}"):
            full_text = f"# {title}\n\n{cleaned_content}"
        else:
            full_text = cleaned_content

        rag_item = {
            "question_text": title,
            "content": full_text,
            "source": "WeChat: 墨大中国学生会",
            "author": None,
            "post_date": item.get("date", "1970-01-01"),
            "language": "zh",
            "created_at": created_at.isoformat(),
            "tags": ["微信公众号", "CSSA"],
            "link": item.get("link", "")
        }
        
        processed_articles.append(rag_item)

    return WechatTransformResult(
        records=processed_articles,
        stats=WechatTransformStats(
            input_count=len(raw_articles),
            skipped_count=skipped_count,
            dropped_count=dropped_count,
            output_count=len(processed_articles),
            original_char_count=original_char_count,
            cleaned_char_count=cleaned_char_count,
        ),
    )

