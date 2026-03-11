@echo off
REM Oracle 환경에서 봇 실행 (Windows)
cd /d "%~dp0"

if not exist .env (
  echo WARN: .env 없음. .env.example 참고 후 .env 생성
)

python main.py
