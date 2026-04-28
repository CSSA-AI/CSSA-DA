# 🚀 CSSA-AI 极简开发速查表 (Docker 保姆级教程)

欢迎加入开发！请严格按照以下步骤操作你的 Docker 环境。

💡 **核心铁律：** 我们在本地写代码（修改 Python 文件）保存后，容器内会**瞬间同步生效**，绝对不需要重新打包！
只有当你修改了 `environment_cpu.yml` 或 `environment_gpu.yml`（新增了第三方库），或者修改了 `Dockerfile` 时，才需要加 `--build` 重新构建。

---

## 🌟 第一阶段：新人入职 / 首次拉取代码 (仅执行一次)

当你第一次把项目从 GitHub Clone 下来时，我们需要让 Docker 帮你“盖房子”（下载系统环境和第三方库）。过程大约 3-5 分钟，请耐心等待。

**根据你的电脑配置，选择一行命令执行：**

* **🍏 Mac 或 无显卡 Windows (CPU 组)：**
```bash
docker compose --profile cpu up -d --build
```

* **🎮 带 Nvidia 显卡的 Windows (GPU 组)：**
```bash
docker compose --profile gpu up -d --build
```

*(看到全部显示 `Started` 或 `Running` 后，说明你的专属开发环境已经搭好了！)*

---

## 📅 第二阶段：日常开发节奏 (每天循环)

房子盖好了，以后每天写代码只需要三步走，**不需要**再加 `--build` 了。

### 🌞 第一步：上班开机 (只需几秒)

```bash
# CPU 组执行：
docker compose --profile cpu up -d

# GPU 组执行：
docker compose --profile gpu up -d
```

### 💻 第二步：运行你的代码 
*保持 Docker 在后台运行，打开一个新的终端窗口来敲这些运行命令。*

**1. 跑单次脚本 (例如 Data Squad 测试爬虫):**
```bash
# CPU 组执行：
docker exec -it rag_worker_cpu python 你的脚本名字.py

# GPU 组执行：
docker exec -it rag_worker_gpu python 你的脚本名字.py
```

**2. 跑 FastAPI 后端 (Platform Squad 专属，带代码热更新):**
```bash
# CPU 组执行 (GPU 组请将 cpu 换成 gpu)：
docker exec -it rag_worker_cpu uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*(运行后，在浏览器访问 http://localhost:8000/docs 查看接口文档)*

**3. 跑 Streamlit 前端界面 (Demo Squad 专属):**
```bash
# CPU 组执行 (GPU 组请将 cpu 换成 gpu)：
docker exec -it rag_worker_cpu streamlit run scripts/demo.py
```
*(运行后，直接在浏览器访问 http://localhost:8501)*

### 🌙 第三步：下班关机 (省电且释放内存)

```bash
docker compose down
```
*(放心执行！我们在本地映射了数据卷，你的代码和数据库里的数据绝对不会丢，明天 up -d 瞬间恢复原样。)*

---

## 🛠️ 第三阶段：高级排错 (遇到 Bug 怎么办)

如果你发现程序没按预期运行，或者想钻进环境内部看看：

* **像用 Linux 一样进入容器内部敲命令:**
```bash
docker exec -it rag_worker_cpu bash
```

* **查看数据库有没有报错日志:**
```bash
docker logs -f rag_postgres_db
```

* **如果环境彻底搞乱了，想推倒重来 (核弹级清理):**
```bash
docker compose down
docker rm -f rag_worker_cpu
docker compose --profile cpu up -d --build --force-recreate
 
```

## 建立本地数据库
```bash
docker exec -i rag_postgres_db psql -U rag_user -d rag_vectordb < database_setup.sql # Linux/Mac User
type database_setup.sql | docker exec -i rag_postgres_db psql -U rag_user -d rag_vectordb # Windows User
docker exec -it rag_worker_cpu python scripts/import_demo.py
```

## 进入数据库运行SQL Query

```bash
docker exec -it rag_postgres_db psql -U rag_user -d rag_vectordb
# 这个SQL语句可以是任何想要的
SELECT COUNT(*) FROM knowledge_base;
```

## 本地测试流程

*本地测试应该用来进行unittest，以轻量化为目的。Integration test请使用docker*

### 1. 创建虚拟环境

```bash
python3 -m venv cssa-ci source 
source cssa-ci/bin/activate   # Mac/Linux
.\cssa-ci\Scripts\Activate.ps1
```

### 2. 安装依赖

```bash
pip install -r requirements-ci.txt
```

### 3. 测试


```bash
# 跑单个测试文件 
pytest tests/filename.py -v

# 跑全部测试文件
pytest -v
```

