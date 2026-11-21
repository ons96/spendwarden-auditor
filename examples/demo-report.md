# spendwarden audit -- demo-usage.csv

**Billed spend in this export:** $945.00 over 5,500 calls.

This sheet prices only what your invoice already says. It does not fetch list prices, because they change weekly and a stale table invents savings. Every number below is arithmetic on your own columns, with the assumption stated.

## Where the money goes

| Model | Provider | Cost | Share | $/Mtok | Calls |
|---|---|---:|---:|---:|---:|
| big-model | acme | $900.00 | 95% | 450 | 1,000 |
| small-model | acme | $40.00 | 4% | 133 | 4,000 |
| cheap-model | other | $5.00 | 1% | 50 | 500 |

## Levers, strongest first

### 1. big-model costs $450/Mtok, 3.4x your median

*price per token -- confidence low*

Your own export prices 1 model(s) at least 2.5x the median of $133/Mtok. Repricing just big-model at that median would free $633.33. Cheap is not the same as fit: check the task, context and failure rate before moving traffic. Estimated ceiling: $158.33-$633.33.

### 2. input is 4x output -- 81% of tokens

*prompt caching -- confidence medium*

Long repeated prefixes are the usual cause. Assuming 60% of input is a re-sent prefix and caching discounts it 50%-90%, the ceiling is $230.34-$414.62 against $767.81 of input spend. Verify the share before quoting the number. Estimated ceiling: $230.34-$414.62.

### 3. 150 failed calls, about $25.77 of billed work

*retry waste -- confidence high*

3% of calls failed or retried. If the failures were billed, that spend bought nothing. Fix the largest failing provider first, then re-measure. Estimated ceiling: $12.89-$25.77.

### 4. 95% of spend is one model (big-model)

*concentration -- confidence high*

Consolidation is not a saving on its own, but a single model above half the bill is the cheapest place to start: one substitution, renegotiation or cache change moves the whole number. Ask what 95% of traffic must stay on it.

## What this sheet cannot see

- Contracted rates, committed-use discounts and credits: the invoice already nets them.
- Whether a cheaper model is good enough for the task. That is a measurement, not a table.
- Free-tier and vendor-programme eligibility, which depends on accounts and terms you hold.

Reply to this report if you want the levers verified against real traffic before you change anything.
