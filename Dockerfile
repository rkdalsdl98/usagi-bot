# 로컬에서 항상 켜 두는 서버들(버튼 처리 serve_local.py, 우사기 채팅 봇 usagi_bot.py)과
# 수동 추천 실행(run_local.py)이 함께 쓰는 이미지. 어떤 스크립트를 돌릴지는 compose.yaml 이 정합니다.
# 비밀 값(.env)은 이미지에 넣지 않고, 실행할 때 compose 의 env_file 로 넘깁니다.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src ./src
COPY scripts ./scripts
