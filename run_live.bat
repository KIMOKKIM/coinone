@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [실거래 모드] 실제 주문이 전송됩니다. 5초 후 시작...
timeout /t 5 /nobreak > nul
set PAPER_TRADING=false
python main.py --live
