import sys
import importlib.util

spec = importlib.util.spec_from_file_location("new_manwa", "NEW-MANWA.PY")
new_manwa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new_manwa)

results = new_manwa.search_all_sources(["solo"])
print("Found", len(results), "results")
for r in results:
    if r["source"] in ["kunmanga", "weebrook"]:
        print(r["title"], "-", r["source"])
