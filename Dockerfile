FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 默认 7860（HF Spaces 兼容）；Render/Railway 等平台会注入 PORT，容器启动时自动跟随
ENV PYTHONUNBUFFERED=1
EXPOSE 7860

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-7860} --workers 1 --threads 8 --timeout 600 app:app"]
