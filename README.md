# spendwarden-auditor

Find the money in an LLM bill from your own usage export. One file, standard
library only, no network calls, nothing leaves the machine.

```sh
python3 audit.py usage.csv                    # markdown report to stdout
python3 audit.py usage.csv --out report.md
python3 audit.py usage.csv --json             # findings as JSON
python3 audit.py --self-test                  # asserts the levers fire and stay quiet
```

## Input

Anything with a cost column per model. CSV or JSON, header names are matched
loosely, so these all work:

| Needs | Accepted header spellings |
|---|---|
| model | `model`, `model_id`, `engine`, `deployment` |
| cost | `cost`, `total_cost`, `spend`, `amount`, `billed_cost` |
| calls | `calls`, `requests`, `api_calls`, `count` |
| input tokens | `input_tokens`, `prompt_tokens`, `prompt` |
| output tokens | `output_tokens`, `completion_tokens`, `completion` |
| failures | `errors`, `failed`, `retries`, `failures` |

```csv
provider,model,requests,prompt_tokens,completion_tokens,total_cost,failed
acme,big-model,1000,1800000,200000,900.00,150
```

Only `model` and `cost` are required. More columns, sharper report.

## What it reports

Four levers, each computed from your columns with its assumption printed:

1. **Concentration** -- one model above half the bill is the cheapest place to start.
2. **Retry waste** -- failures above 1% of calls, priced at your average call cost.
3. **Prompt caching** -- input running 4x or more above output; the report bounds the
   saving at a stated cacheable share and discount band instead of asserting one.
4. **Price per token** -- models priced 2.5x above your own median $/Mtok.

A clean export yields no findings, and the report says so. Manufacturing advice
from a healthy bill is worse than saying nothing.

## What it deliberately does not do

No list-price table. Published prices move weekly and a stale table invents
savings that vanish on contact with the invoice. Every figure here is arithmetic
on what you were actually billed.

It also cannot tell you whether a cheaper model is good enough for a given task.
That is a measurement against real traffic, not a lookup.

## License

MIT.
