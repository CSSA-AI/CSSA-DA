# knowledge_base 的 modality / refresh 字段

`knowledge_base` 表新增了两个正交字段:`modality`(`qa` | `doc`)和 `refresh`
(`replace` | `append`)。见 migration
[20260817_0005_add_modality_column.py](../../../migrations/versions/20260817_0005_add_modality_column.py)。

## 为什么用 TEXT,不用 enum / CHECK 约束

`modality` 和 `refresh` 的取值目前都只有两个,而且短期内稳定。但如果在数据库层加
CHECK 约束,以后任何一次取值调整(比如未来新增第三种 modality)都得走一次 migration
才能改。而校验放在 loader 层(应用代码)同样能拦住脏数据,改起来只是改 Python,不用
碰数据库、不用发布。所以这里的选择是:**约束放应用层,不放 schema**。TEXT 类型本身
不代表"不校验"——loader 侧仍然要求显式传值、且只接受合法取值,缺失或非法值直接报错。

## 不加 authority 字段

可信度(官方 / 社团 / 民间)以后大概率会成为第三根独立的轴,但现在还没有需要用到它
的场景,所以本次不设计、不加这个字段。之所以在这里写一笔,是为了明确:`modality` 和
`source` 都不应该被拿来隐含可信度含义——比如不要用"这是 doc 所以更权威"这种推断。
把这个位置留空,是有意的,不是遗漏。