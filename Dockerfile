# 使用兼容性更好的 Python 3.11 轻量镜像
FROM python:3.11-slim

# 安装系统依赖（解决编译问题）
RUN apt-get update && apt-get install -y \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /APP

# 先复制 requirements 文件（利用 Docker 缓存层）
COPY requirements.txt .

# 正确升级 pip 并安装依赖
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 设置环境变量
ENV TELEGRAM_ACCESS_TOKEN=8100118901:AAEbutYd2l_QTEpyP-qkxGYYPY8m3lKGDm8
ENV CHATGPT_BASICURL=https://genai.hkbu.edu.hk/general/rest
ENV CHATGPT_MODELNAME=gpt-4-o-mini
ENV CHATGPT_APIVERSION=2024-05-01-preview
ENV CHATGPT_ACCESS_TOKEN=0f2019ec-e7e0-43cb-847a-929e1d81d901
ENV MYSQL_HOST=139.196.153.131
ENV MYSQL_USER=root
ENV MYSQL_PASSWORD=Wyy20020431!
ENV MYSQL_DATABASE=comp7940

# 启动命令
CMD ["python", "chatbot.py"]