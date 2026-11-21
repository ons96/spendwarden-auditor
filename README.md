# spendwarden-auditor

[![self-test](https://github.com/ons96/spendwarden-auditor/actions/workflows/selftest.yml/badge.svg)](https://github.com/ons96/spendwarden-auditor/actions/workflows/selftest.yml)

Find the money in an LLM bill from your own usage export. One file, standard
library only, Python 3.10 or newer, no network calls, nothing leaves the
machine.

```sh
python3 audit.py usage.csv                    # markdown report to stdout
python3 audit.py usage.csv --out report.md
python3 audit.py usage.csv --json             # findings as JSON
python3 audit.py --self-test                  # asserts the levers fire and stay quiet
```

See what it prints without running anything:
[`examples/demo-report.md`](examples/demo-report.md), built from
[`examples/demo-usage.csv`](examples/demo-usage.csv).

## Input

Anything with a cost column per model. CSV or JSON, header names are matched
loosely, so these all work:

| Needs | Accepted header spellings |
|---|---|
| model | `model`, `model_id`, `engine`, `deployment` |
| cost | `cost`, `total_cost`, `spend`, `amount`, `billed_cost`, `cost_usd` |
| calls | `calls`, `requests`, `api_calls`, `count`, `num_requests` |
| input tokens | `input_tokens`, `prompt_tokens`, `prompt`, `tokens_prompt`, `n_context_tokens_total` |
| output tokens | `output_tokens`, `completion_tokens`, `completion`, `tokens_completion`, `n_generated_tokens_total` |
| failures | `errors`, `failed`, `retries`, `failures` |

Bucketed exports are fine. A per-day, per-model file (OpenRouter activity,
OpenAI org usage, Anthropic usage) collapses to one row per provider and model
with the daily figures summed, so the report talks about models, not days.

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

## Getting your data out

Every provider hides it somewhere different. These are the paths that produce a
file this tool reads:

| Provider | Where | What you get |
|---|---|---|
| OpenRouter | Activity page, download CSV | per-model, per-day spend |
| OpenAI | Org settings, usage, export | per-model daily token counts; add billed cost |
| Anthropic | Console, usage, export | per-model daily tokens |
| LiteLLM or a gateway | spend logs table | cost and tokens per request |
| Your own proxy | whatever you log | keep `provider`, `model`, `cost`, tokens |

If the export has tokens but no dollar figure, add a cost column using the rate
you were actually charged. A guessed rate produces a guessed ceiling, and the
report will say which lever rests on it.

## If you would rather someone else read it

The tool is the free half. Send an anonymised export (model names, calls,
tokens, cost; drop account ids, keys, prompt text) and the same four levers come
back as a written read of where the bill goes, priced against your own numbers
rather than a list price. The contact address lives in the repository profile.

The free read stays free, including when it concludes nothing is worth fixing.
Two paid things exist beyond it, and neither replaces the reader above:

- **Config pack, $99, paid up front.** A reviewed gateway configuration built
  around the keys and vendors you already pay, plus this tool wired to your
  logs. Fixed scope, delivered as files.
- **Spend review, 25% of the first year's verified savings, minimum $500,
  capped at $1,500.** Quoted only after the free read, and invoiced once the
  saving shows in a second month's export. The floor and the delay are the same
  fact: verification costs a month.

Neither offer routes a paid workload through free-tier or keyless endpoints.
That gets the buyer's keys and IPs banned, which is not a saving.

## License

MIT.
