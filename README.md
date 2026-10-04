# premium

Paper-only research system for **steady premium with controlled, capped losses**: defined-risk option selling, covered calls, trend-following on futures/commodities, factor investing. It runs separately from **the Nifty system** (folder `../suzlon`, GitHub repo `nifty`) and never modifies it.

- Design and risk rules: [docs/DESIGN.md](docs/DESIGN.md)
- Studies (each pre-declared, results appended): [docs/studies/](docs/studies/)

```powershell
# after the Nifty system's End of Day has finished:
powershell -ExecutionPolicy Bypass -File scripts\snapshot.ps1   # copy market data (read-only for the Nifty system)
uv run pytest -q                                              # tests
```
