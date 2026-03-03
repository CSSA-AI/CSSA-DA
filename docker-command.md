# 🚀 极简开发速查表 (Docker)

💡 **注意：** 修改 Python 代码后**不需要**重新构建，保存后容器内直接生效！只有修改了 `environment.yml` 才需要加 `--build` 重新启动。

## 1. 🟢 启动与关闭 (每天第一步)

# 启动环境 (Mac / 无显卡)
docker-compose --profile cpu up -d

# 启动环境 (带 Nvidia 显卡)
docker-compose --profile gpu up -d

# 下班关闭环境
docker-compose down

---

## 2. 💻 运行代码

# 跑单次脚本 (例如: python test.py)
docker exec -it rag_worker_cpu python test.py    # CPU组
docker exec -it rag_worker_gpu python test.py    # GPU组

# 跑 FastAPI 后端 (带热更新)
docker exec -it rag_worker_cpu uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 跑 Streamlit 前端界面
docker exec -it rag_worker_cpu streamlit run app.py

---

## 3. 🛠 调试与排错

# 钻进容器内部 (像用 Linux 一样敲命令)
docker exec -it rag_worker_cpu bash

# 查看数据库的报错日志
docker logs -f rag_postgres_db