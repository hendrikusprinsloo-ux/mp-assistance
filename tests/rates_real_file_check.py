"""Run: .venv/bin/python tests/rates_real_file_check.py "<results csv>"   Prints what the Upload tab's rate warning would say for that file."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

r = server.rates_check(Path(sys.argv[1]))
print(r["rows"], "scraped rows;", r["same"], "same label;", r["changed"], "changed")
print("would become issues:", [(c["hotel"], c["channel"], c["new_diff"]) for c in r["would_confirm"]])
print("would stop being issues:", r["no_longer"])
