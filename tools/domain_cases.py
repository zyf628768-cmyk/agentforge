"""Evaluator-owned pure-compute contracts and independent deterministic cases.

These inputs/expected outputs are never sent to the code generator. Public cases
are reproducible examples, not a claim of secret production benchmark coverage.
"""

import random
from collections import Counter


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

    return [
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
