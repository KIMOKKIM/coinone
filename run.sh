#!/bin/bash
# Oracle 환경에서 봇 실행
# 사용법: ./run.sh 또는 bash run.sh

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "WARN: .env 없음. .env.example을 참고해 .env 생성 후 실행하세요."
fi

# Python 가상환경(권장)
if [ -d "venv" ]; then
  source venv/bin/activate
fi

python main.py
