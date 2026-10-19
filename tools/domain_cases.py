"""Evaluator-owned pure-compute contracts and independent deterministic cases.

These inputs/expected outputs are never sent to the code generator. Public cases
are reproducible examples, not a claim of secret production benchmark coverage.
"""

import csv
import io
import random
from collections import Counter
from fractions import Fraction


def domains():
    rng = random.Random(72819)
    invoices = [[], [{"quantity": 3, "unit_cents": 199}, {"quantity": 2, "unit_cents": 50}]]
    invoices += [
        [
            {"quantity": rng.randrange(6), "unit_cents": rng.randrange(100000)}
            for _ in range(rng.randrange(8))
        ]
        for _ in range(14)
    ]
    intervals = [[], [[5, 8], [1, 3], [3, 6]], [[-5, -2], [0, 1], [2, 2]]]
    intervals += [
        [sorted([rng.randrange(-20, 21), rng.randrange(-20, 21)]) for _ in range(rng.randrange(9))]
        for _ in range(13)
    ]

    def interval_oracle(values):
        # Independently mark coverage of integer edges/points, then rebuild union.
        points = set()
        for start, end in values:
            points.update(range(2 * start, 2 * end + 1))
        result = []
        for point in sorted(points):
            if not result or point > result[-1][1] + 1:
                result.append([point, point])
            else:
                result[-1][1] = point
        return [[start // 2, end // 2] for start, end in result]

    words = ["", "A a B", "Straße STRASSE 世界 世界", "word, word word,", "\t\n"]
    words += [
        " ".join(
            rng.choice(["A", "a", "世界", "Straße", "STRASSE", "x,"])
            for _ in range(rng.randrange(12))
        )
        for _ in range(11)
    ]

    def obj(properties):
        return {
            "type": "object",
            "required": list(properties),
            "additionalProperties": False,
            "properties": properties,
        }

    result = [
        {
            "name": "invoice-total",
            "goal": "Given invoice lines, compute total_cents = sum(quantity * unit_cents). Empty lines => 0.",
            "inputs": {
                "type": "array",
                "maxItems": 30,
                "items": obj(
                    {
                        "quantity": {"type": "integer", "minimum": 0, "maximum": 100},
                        "unit_cents": {"type": "integer", "minimum": 0, "maximum": 1000000},
                    }
                ),
            },
            "outputs": obj({"total_cents": {"type": "integer", "minimum": 0}}),
            "cases": [
                (v, {"total_cents": sum(line["quantity"] * line["unit_cents"] for line in v)})
                for v in invoices
            ],
            "source": 'import json,sys\nv=json.load(sys.stdin)\njson.dump({"total_cents":sum(x["quantity"]*x["unit_cents"] for x in v)},sys.stdout)\n',
        },
        {
            "name": "merge-intervals",
            "goal": "Merge overlapping OR TOUCHING integer intervals. Input array of [start,end] pairs with start<=end. Sort ascending and return merged array. Empty => [].",
            "inputs": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "integer", "minimum": -10000, "maximum": 10000},
                },
            },
            "outputs": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "integer"},
                },
            },
            "cases": [(v, interval_oracle(v)) for v in intervals],
            "source": "import json,sys\nvalues=sorted(json.load(sys.stdin))\nout=[]\nfor a,b in values:\n if out and a<=out[-1][1]: out[-1][1]=max(out[-1][1],b)\n else: out.append([a,b])\njson.dump(out,sys.stdout)\n",
        },
        {
            "name": "word-histogram",
            "goal": "Count whitespace-separated words using str.casefold(). Return word to integer count mapping. Preserve punctuation as part of words. Empty text => {}.",
            "inputs": {"type": "string", "maxLength": 4096},
            "outputs": {
                "type": "object",
                "additionalProperties": {"type": "integer", "minimum": 1},
            },
            "cases": [(v, dict(Counter(v.casefold().split()))) for v in words],
            "source": "import json,sys\nfrom collections import Counter\njson.dump(dict(Counter(json.load(sys.stdin).casefold().split())),sys.stdout,ensure_ascii=False)\n",
        },
    ]
    result.extend(extra_domains(rng))
    return result


def extra_domains(rng):
    def obj(properties):
        return {
            "type": "object",
            "required": list(properties),
            "additionalProperties": False,
            "properties": properties,
        }

    strings = {"type": "array", "maxItems": 30, "items": {"type": "string", "maxLength": 40}}
    unique_inputs = [[], ["a", "b", "a"], ["A", "a", "A"], ["", "", "世界"]]
    unique_inputs += [
        [rng.choice(["a", "b", "世界", "", "x,"]) for _ in range(rng.randrange(20))]
        for _ in range(12)
    ]
    unique_cases = []
    for values in unique_inputs:
        expected = []
        for item in values:
            if item not in expected:
                expected.append(item)
        unique_cases.append((values, expected))
    matrices = [[], [[]], [[1, 2], [3, 4]], [[1], [2], [3]]]
    for _ in range(12):
        rows, columns = rng.randrange(1, 7), rng.randrange(7)
        matrices.append([[rng.randrange(-100, 101) for _ in range(columns)] for _ in range(rows)])
    matrix_schema = {
        "type": "array",
        "maxItems": 12,
        "items": {"type": "array", "maxItems": 12, "items": {"type": "integer"}},
    }
    fraction_inputs = [{"numerator": 0, "denominator": 7}, {"numerator": -12, "denominator": 18}]
    fraction_inputs += [
        {"numerator": rng.randrange(-10000, 10001), "denominator": rng.randrange(1, 1001)}
        for _ in range(14)
    ]
    csv_cases = [
        ({"csv": "a,b\n"}, {"totals": []}),
        ({"csv": 'a,b\n"2","3"\n-1,5\n'}, {"totals": [5, 4]}),
    ]
    for _ in range(14):
        columns = rng.randrange(1, 6)
        rows = [[rng.randrange(-100, 101) for _ in range(columns)] for _ in range(rng.randrange(8))]
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow([f"column{i}" for i in range(columns)])
        writer.writerows(rows)
        csv_cases.append(({"csv": stream.getvalue()}, {"totals": [sum(row) for row in rows]}))
    brackets = ["", "([]{})", "([)]", "((", ")", "世界(a)[b]{c}"]
    brackets += [
        "".join(rng.choice("()[]{}ab") for _ in range(rng.randrange(30))) for _ in range(10)
    ]

    def balanced(value):
        text = "".join(c for c in value if c in "()[]{}")
        while True:
            reduced = text.replace("()", "").replace("[]", "").replace("{}", "")
            if text == reduced:
                return text == ""
            text = reduced

    return [
        {
            "name": "stable-unique",
            "goal": "Remove duplicate strings preserving first occurrence order. Comparison is case-sensitive. Empty => [].",
            "inputs": strings,
            "outputs": strings,
            "cases": unique_cases,
            "source": "import json,sys\njson.dump(list(dict.fromkeys(json.load(sys.stdin))),sys.stdout)\n",
        },
        {
            "name": "matrix-transpose",
            "goal": "Transpose a rectangular integer matrix. Input rows have equal length. An empty matrix or zero columns returns [].",
            "inputs": matrix_schema,
            "outputs": matrix_schema,
            "cases": [
                (
                    v,
                    [[v[row][col] for row in range(len(v))] for col in range(len(v[0]))]
                    if v
                    else [],
                )
                for v in matrices
            ],
            "source": "import json,sys\nv=json.load(sys.stdin)\njson.dump([list(row) for row in zip(*v)],sys.stdout)\n",
        },
        {
            "name": "fraction-reduce",
            "goal": "Reduce numerator/denominator to lowest terms. Denominator is positive; keep it positive. Zero numerator returns 0/1. Return numerator and denominator integer fields.",
            "inputs": obj(
                {
                    "numerator": {"type": "integer", "minimum": -1000000, "maximum": 1000000},
                    "denominator": {"type": "integer", "minimum": 1, "maximum": 1000},
                }
            ),
            "outputs": obj(
                {"numerator": {"type": "integer"}, "denominator": {"type": "integer", "minimum": 1}}
            ),
            "cases": [
                (
                    v,
                    {
                        "numerator": Fraction(v["numerator"], v["denominator"]).numerator,
                        "denominator": Fraction(v["numerator"], v["denominator"]).denominator,
                    },
                )
                for v in fraction_inputs
            ],
            "source": "import json,sys,math\nv=json.load(sys.stdin)\ng=math.gcd(v['numerator'],v['denominator'])\njson.dump({'numerator':v['numerator']//g,'denominator':v['denominator']//g},sys.stdout)\n",
        },
        {
            "name": "csv-row-sums",
            "goal": "Parse the csv string using standard CSV quoting. The first row is a header. Every later cell is a signed integer, with no blank rows. Return totals: one integer sum per data row. Header-only => empty totals array.",
            "inputs": obj({"csv": {"type": "string", "maxLength": 4096}}),
            "outputs": obj(
                {"totals": {"type": "array", "maxItems": 20, "items": {"type": "integer"}}}
            ),
            "cases": csv_cases,
            "source": "import json,sys,csv,io\nv=json.load(sys.stdin)\nrows=list(csv.reader(io.StringIO(v['csv'])))\njson.dump({'totals':[sum(map(int,row)) for row in rows[1:]]},sys.stdout)\n",
        },
        {
            "name": "balanced-brackets",
            "goal": "Return balanced: true iff parentheses (), square brackets [] and braces {} are properly nested and closed. Ignore all other characters. Empty text is balanced.",
            "inputs": {"type": "string", "maxLength": 512},
            "outputs": obj({"balanced": {"type": "boolean"}}),
            "cases": [(v, {"balanced": balanced(v)}) for v in brackets],
            "source": "import json,sys\nv=json.load(sys.stdin)\ns=[]\nok=True\nfor c in v:\n if c in '([{': s.append(c)\n elif c in ')]}':\n  if not s or s.pop()!={')':'(',']':'[','}':'{'}[c]: ok=False;break\njson.dump({'balanced':ok and not s},sys.stdout)\n",
        },
    ]
