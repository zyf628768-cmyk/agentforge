"""Generated-target example: execute only in the configured gVisor container."""

import csv
import io
import json
import statistics
import sys

value = json.load(sys.stdin)
rows = list(csv.DictReader(io.StringIO(value["csv"])))
numbers = [float(row[value["column"]]) for row in rows]
json.dump({"count": len(numbers), "sum": sum(numbers),
           "mean": statistics.mean(numbers) if numbers else None}, sys.stdout, allow_nan=False)
