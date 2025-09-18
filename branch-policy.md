# 📜 Branch Policy / 分支管理规范

## 1. Branch Types / 分支类型

### Main Branch (主干分支)
- `main`：始终保持稳定、可测试、可部署状态。

### Shared Module Branches (模块共享分支)
- 例如：
  - `feature-retriever`
  - `feature-reranker`
  - `feature-generator`
- 用于多人协作开发时的中间整合，避免直接将个人代码合并到主干。

### Personal Feature Branches (个人功能分支)
- 命名规范：
  ```
  feature/<module>/<developer>
  ```
  示例：
  - `feature/retriever/devin`
  - `feature/reranker/simone`
- 每位开发者在个人分支中自由开发。

## 2. Workflow / 工作流程

### Step 1: 创建个人分支
```
git checkout main
git pull origin main
git checkout -b feature/retriever/devin
git push -u origin feature/retriever/devin
```

### Step 2: 保持与 main 同步（使用 rebase）
```
git fetch origin
git rebase origin/main
# 如果有冲突，解决后：
git add .
git rebase --continue
# 然后强推到远端
git push -f origin feature/retriever/devin
```

### Step 3: 合并个人分支到模块共享分支
在 GitHub 上发起 Pull Request：
- base: `feature-retriever`
- compare: `feature/retriever/devin`

推荐使用 **Squash and merge** 合并方式，以保持提交记录简洁。

### Step 4: 在共享分支进行模块级测试
- 在共享分支（如 `feature-retriever`）中执行测试。
- 确保多人协作的功能整合后仍然稳定。

### Step 5: 合并模块共享分支到主干（main）
当模块开发稳定后：
- 在 GitHub 上发起 Pull Request：
  - base: `main`
  - compare: `feature-retriever`

推荐使用：
- **Squash and merge**（适用于多个开发者提交）
- 或 **Rebase and merge**（保持线性历史）

合并后可以选择删除已完成的共享分支。

## 3. Rules / 规则
```
| 分支类型        | 是否允许 rebase | 是否允许 force-push | 合并目标 |
|-----------------|------------------|----------------------|-----------|
| main            | ❌ 禁止         | ❌ 禁止             | 无        |
| shared branch   | ❌ 禁止         | ❌ 禁止             | main      |
| personal branch | ✅ 允许         | ✅ 允许             | shared branch |
```
## 4. 分支命名示例
```
| 类型       | 命名示例                         |
|------------|----------------------------------|
| shared     | `feature-retriever`              |
| personal   | `feature/retriever/devin`        |
| bugfix     | `bugfix/reranker/score-overflow` |
| hotfix     | `hotfix/retriever/null-check`    |
```
## 5. 补充建议

- 开发早期（尚未搭建 CI/CD 时），可以将 `main` 替换为 `develop` 分支作为集成主干。
- 后续当 `main` 配置好测试与部署后，再将 `develop` 合并入 `main`，切换回正式流程。