# premium

Paper-only research system for **steady premium with controlled, capped losses**: defined-risk option selling, covered calls, trend-following on futures/commodities, factor investing. It runs separately from `../suzlon` (the Nifty options paper-trading system) and never modifies it.

- Design and risk rules: [docs/DESIGN.md](docs/DESIGN.md)
- Studies (each pre-declared, results appended): [docs/studies/](docs/studies/)

```powershell
# after suzlon's End of Day has finished:
powershell -ExecutionPolicy Bypass -File scripts\snapshot.ps1   # copy market data (read-only for suzlon)
uv run pytest -q                                              # tests
```
