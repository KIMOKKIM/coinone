# TASK_INSTRUCTION.md

Project rebuild instruction — recreate BTC spot auto-trader from scratch.

Summary:
- Existing codebase is deprecated. Keep `.env` only. Rebuild new project structure and files.
- This repository now contains a fresh implementation scaffold for a safe, paper-first BTC spot trader.
- The new structure, configs, and basic implementations are included. See README for usage.

Important rules applied:
- `.env` preserved in place (do not delete or modify its values).
- Existing strategy code was not reused; new modules are implemented under `app/`.
- Paper trading is the default mode (PAPER_TRADING=True).
- The system emphasizes safety, logging, state persistence, and testability (backtest).

Next steps for operator:
- Review `config.py` and fill `.env` with API keys if you intend to use live mode.
- Run `pip install -r requirements.txt`
- Run backtest: `python main.py --backtest --days 90`
- Run dashboard: `python main.py --dashboard`

