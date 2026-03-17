# 📜 Branch Policy / 分支管理规范

## 1. Branch Types / 分支类型

### Main Branch (主干分支)
- `main`：始终保持稳定、可测试、可部署状态。

### Personal Branches (个人分支)
- 命名规范：
  ```
  <category>/<desctription>/<developer>
  ```
  示例：
  - `feature/retriever/devin`
  - `chore/branch-policy/devin`
  - `bugfix/typo-fix/devin`

- 每位开发者在个人分支中自由开发。
#### Category
  - feature: 功能实现
  - chore：非功能性的实现，如config，

## 2. Workflow / 工作流程

### Step 1: 创建个人分支
```
git checkout main
git pull origin main
git checkout -b feature/retriever/devin
git push -u origin feature/retriever/devin
```

### Step 2: 频繁保持与 main 同步（使用 rebase）
```
git fetch origin
git rebase origin/main
# 如果有冲突，解决后：
git add .
git rebase --continue
# 然后强推到远端
git push -f origin feature/retriever/devin
```

### Step 3: 合并个人分支到主干（main）
在 GitHub 上发起 Pull Request：
- base: `feature-retriever`
- compare: `feature/retriever/devin`

推荐使用：
- **Squash and merge**（适用于多个开发者提交）
- 或 **Rebase and merge**（保持线性历史）

合并后建议删除已完成的个人分支。

## 3. 分支命名示例
```
| 类型       | 命名示例                         |
|------------|----------------------------------|
| personal   | `feature/retriever/devin`        |
| bugfix     | `bugfix/reranker/score-overflow` |
| hotfix     | `hotfix/retriever/null-check`    |
```
## 4. 补充建议

- 开发早期（尚未搭建 CI/CD 时），可以将 `main` 替换为 `develop` 分支作为集成主干。
- 后续当 `main` 配置好测试与部署后，再将 `develop` 合并入 `main`，切换回正式流程。