#!/usr/bin/env python3
"""spendwarden audit -- find the money in an LLM usage export.

Reads a CSV or JSON export of your own LLM usage (cost and token columns are
enough) and writes a review sheet: where the money goes, which of four levers
could plausibly move it, and what evidence is missing before you act.

No network calls, no dependencies, no data leaves the machine.

    python3 audit.py usage.csv                 # markdown to stdout
    python3 audit.py usage.csv --out report.md
    python3 audit.py usage.csv --json          # machine-readable findings
    python3 audit.py --self-test

ponytail: prices are not bundled. A price table guesses at list prices that
change weekly; the levers below are computed from the buyer's own billed cost,
so the arithmetic stays true whatever the invoice says.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Header aliases, lowercased and stripped of spaces/underscores.
ALIASES = {
    "provider": ("provider", "vendor", "api", "service", "source"),
    "model": ("model", "modelid", "modelname", "engine", "deployment"),
    "calls": ("calls", "requests", "nrequests", "count", "apiCalls".lower()),
    "input_tokens": ("inputtokens", "prompttokens", "prompt", "intokens", "input"),
    "output_tokens": ("outputtokens", "completiontokens", "completion", "outtokens", "output"),
    "cost": ("cost", "totalcost", "spend", "amount", "billedcost", "usd"),
    "errors": ("errors", "failed", "failedcalls", "failures", "retries", "status5xx"),
}

# A lever is only reported when its own arithmetic clears a threshold, so a
# clean export produces an empty findings list instead of manufactured advice.
CACHE_INPUT_RATIO = 4.0        # input tokens per output token
CACHE_DISCOUNT_LOW = 0.5       # typical prompt-cache discount on cached input
CACHE_DISCOUNT_HIGH = 0.9
CACHE_CACHEABLE_SHARE = 0.6    # share of input that is usually repeated prefix
WASTE_ERROR_SHARE = 0.01       # report retries above 1% of calls
OUTLIER_FACTOR = 2.5           # cost per Mtok vs the export median
CONCENTRATION_SHARE = 0.5      # one model holding half the bill


def _norm(h: str) -> str:
    return "".join(ch for ch in h.lower() if ch.isalnum())


def _pick(header: list[str]) -> dict[str, str]:
    """Map our field names onto the export's actual column names."""
    norm = {_norm(h): h for h in header}
    out = {}
    for field_name, candidates in ALIASES.items():
        for c in candidates:
            if _norm(c) in norm:
                out[field_name] = norm[_norm(c)]
                break
    return out


@dataclass
class Usage:
    provider: str
    model: str
    calls: float = 0.0
    input_tokens: float = 0.0
    output_tokens: float = 0.0
    cost: float = 0.0
    errors: float = 0.0

    @property
    def tokens(self) -> float:
        return self.input_tokens + self.output_tokens


@dataclass
class Finding:
    lever: str
    confidence: str          # high / medium / low
    headline: str
    detail: str
    saving_low: float = 0.0
    saving_high: float = 0.0


@dataclass
class Report:
    rows: list[Usage] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(r.cost for r in self.rows)

    @property
    def total_calls(self) -> float:
        return sum(r.calls for r in self.rows)


def _num(value) -> float:
    if value is None:
        return 0.0
    s = str(value).strip().replace(",", "").replace("$", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def load(path: str | Path) -> list[Usage]:
    p = Path(path)
    if p.suffix.lower() == ".json":
        raw = json.loads(p.read_text())
        if isinstance(raw, dict):
            raw = raw.get("rows") or raw.get("data") or raw.get("usage") or []
        header = list({k for row in raw for k in row})
        cols = _pick(header)
        rows = raw
    else:
        with p.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            cols = _pick(reader.fieldnames or [])
            rows = list(reader)
    missing = [f for f in ("model", "cost") if f not in cols]
    if missing:
        raise SystemExit(
            f"could not find column(s) {', '.join(missing)} in {p.name}; "
            f"saw {sorted(cols.values())}. Use --self-test to see the expected shape."
        )
    out = []
    for row in rows:
        get = lambda k: row.get(cols[k]) if k in cols else None  # noqa: E731
        out.append(
            Usage(
                provider=str(get("provider") or "").strip(),
                model=str(get("model") or "").strip(),
                calls=_num(get("calls")),
                input_tokens=_num(get("input_tokens")),
                output_tokens=_num(get("output_tokens")),
                cost=_num(get("cost")),
                errors=_num(get("errors")),
            )
        )
    return [r for r in out if r.cost > 0 or r.tokens > 0]


def _pct(part: float, whole: float) -> str:
    return f"{(100.0 * part / whole):.0f}%" if whole else "0%"


def analyse(rows: list[Usage]) -> Report:
    rep = Report(rows=rows)
    total = rep.total_cost
    if not rows or total <= 0:
        return rep

    per_token = [(r, r.cost / r.tokens * 1_000_000) for r in rows if r.tokens > 0]
    median = sorted(v for _, v in per_token)[len(per_token) // 2] if per_token else 0.0

    # Lever 1: one model carries most of the bill.
    by_model: dict[str, float] = {}
    for r in rows:
        by_model[r.model] = by_model.get(r.model, 0.0) + r.cost
    top_model, top_cost = max(by_model.items(), key=lambda kv: kv[1])
    if top_cost / total > CONCENTRATION_SHARE:
        rep.findings.append(
            Finding(
                lever="concentration",
                confidence="high",
                headline=f"{_pct(top_cost, total)} of spend is one model ({top_model})",
                detail=(
                    f"Consolidation is not a saving on its own, but a single model above half the bill "
                    f"is the cheapest place to start: one substitution, renegotiation or cache change "
                    f"moves the whole number. Ask what {_pct(top_cost, total)} of traffic must stay on it."
                ),
            )
        )

    # Lever 2: retries and failures.
    err = sum(r.errors for r in rows)
    calls = rep.total_calls
    if calls > 0 and err / calls >= WASTE_ERROR_SHARE:
        wasted = total * (err / calls)
        rep.findings.append(
            Finding(
                lever="retry waste",
                confidence="high",
                headline=f"{err:.0f} failed calls, about ${wasted:,.2f} of billed work",
                detail=(
                    f"{_pct(err, calls)} of calls failed or retried. If the failures were billed, that spend "
                    f"bought nothing. Fix the largest failing provider first, then re-measure."
                ),
                saving_low=wasted * 0.5,
                saving_high=wasted,
            )
        )

    # Lever 3: input-heavy traffic, the prompt-cache case.
    inp = sum(r.input_tokens for r in rows)
    outp = sum(r.output_tokens for r in rows)
    if outp > 0 and inp / outp >= CACHE_INPUT_RATIO:
        input_cost = total * (inp / (inp + outp)) if (inp + outp) else 0.0
        low = input_cost * CACHE_CACHEABLE_SHARE * CACHE_DISCOUNT_LOW
        high = input_cost * CACHE_CACHEABLE_SHARE * CACHE_DISCOUNT_HIGH
        rep.findings.append(
            Finding(
                lever="prompt caching",
                confidence="medium",
                headline=f"input is {inp / outp:.0f}x output -- {_pct(inp, inp + outp)} of tokens",
                detail=(
                    f"Long repeated prefixes are the usual cause. Assuming {CACHE_CACHEABLE_SHARE:.0%} of input "
                    f"is a re-sent prefix and caching discounts it {CACHE_DISCOUNT_LOW:.0%}-{CACHE_DISCOUNT_HIGH:.0%}, "
                    f"the ceiling is ${low:,.2f}-${high:,.2f} against ${input_cost:,.2f} of input spend. "
                    f"Verify the share before quoting the number."
                ),
                saving_low=low,
                saving_high=high,
            )
        )

    # Lever 4: the same traffic, priced very differently per token.
    if median > 0:
        outliers = [(r, v) for r, v in per_token if v >= median * OUTLIER_FACTOR and r.cost > 0]
        outliers.sort(key=lambda rv: -rv[0].cost)
        if outliers:
            r, v = outliers[0]
            saving = r.cost - (r.tokens / 1_000_000 * median)
            rep.findings.append(
                Finding(
                    lever="price per token",
                    confidence="low",
                    headline=f"{r.model} costs ${v:,.0f}/Mtok, {v / median:.1f}x your median",
                    detail=(
                        f"Your own export prices {len(outliers)} model(s) at least {OUTLIER_FACTOR:.1f}x the "
                        f"median of ${median:,.0f}/Mtok. Repricing just {r.model} at that median would free "
                        f"${saving:,.2f}. Cheap is not the same as fit: check the task, context and failure rate "
                        f"before moving traffic."
                    ),
                    saving_low=saving * 0.25,
                    saving_high=saving,
                )
            )

    rep.findings.sort(key=lambda f: -(f.saving_high or 0))
    return rep


def render(rep: Report, source: str) -> str:
    total = rep.total_cost
    lines = [
        f"# spendwarden audit -- {Path(source).name}",
        "",
        f"**Billed spend in this export:** ${total:,.2f} over {rep.total_calls:,.0f} calls.",
        "",
        "This sheet prices only what your invoice already says. It does not fetch list prices, "
        "because they change weekly and a stale table invents savings. Every number below is "
        "arithmetic on your own columns, with the assumption stated.",
        "",
        "## Where the money goes",
        "",
        "| Model | Provider | Cost | Share | $/Mtok | Calls |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in sorted(rep.rows, key=lambda r: -r.cost)[:12]:
        per_mtok = f"{r.cost / r.tokens * 1_000_000:,.0f}" if r.tokens else "-"
        lines.append(
            f"| {r.model or '-'} | {r.provider or '-'} | ${r.cost:,.2f} | "
            f"{_pct(r.cost, total)} | {per_mtok} | {r.calls:,.0f} |"
        )

    lines += ["", "## Levers, strongest first", ""]
    if not rep.findings:
        lines += [
            "No lever cleared its threshold. That is a clean result, not a failure: the usual "
            "causes (one model dominating the bill, retry waste, input-heavy traffic, per-token "
            "outliers) are all absent from this export.",
            "",
        ]
    for i, f in enumerate(rep.findings, 1):
        band = (
            f" Estimated ceiling: ${f.saving_low:,.2f}-${f.saving_high:,.2f}."
            if f.saving_high
            else ""
        )
        lines += [
            f"### {i}. {f.headline}",
            "",
            f"*{f.lever} -- confidence {f.confidence}*",
            "",
            f"{f.detail}{band}",
            "",
        ]

    lines += [
        "## What this sheet cannot see",
        "",
        "- Contracted rates, committed-use discounts and credits: the invoice already nets them.",
        "- Whether a cheaper model is good enough for the task. That is a measurement, not a table.",
        "- Free-tier and vendor-programme eligibility, which depends on accounts and terms you hold.",
        "",
        "Reply to this report if you want the levers verified against real traffic before you change anything.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- self-test

def _self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "usage.csv"
        p.write_text(
            "provider,model,requests,prompt_tokens,completion_tokens,total_cost,failed\n"
            "acme,big-model,1000,1800000,200000,900.00,150\n"
            "acme,small-model,4000,100000,200000,40.00,0\n"
            "other,cheap-model,500,50000,50000,5.00,0\n"
        )
        rows = load(p)
        assert len(rows) == 3, rows
        assert rows[0].input_tokens == 1_800_000, rows[0]
        rep = analyse(rows)
        assert rep.total_cost == 945.0, rep.total_cost
        levers = {f.lever for f in rep.findings}
        assert "concentration" in levers, levers          # big-model is 95% of spend
        assert "retry waste" in levers, levers            # 150/5500 calls > 1%
        assert "prompt caching" in levers, levers         # 9.15M input vs 1.25M output
        assert "price per token" in levers, levers        # 90/Mtok vs median
        md = render(rep, "usage.csv")
        assert "spendwarden audit" in md and "| big-model |" in md
        assert "confidence high" in md

        # A clean export must produce zero findings and say so.
        clean = Path(td) / "clean.csv"
        clean.write_text(
            "provider,model,calls,input_tokens,output_tokens,cost\n"
            "a,m1,100,10000,10000,1.00\n"
            "a,m2,100,10000,10000,1.00\n"
        )
        rep2 = analyse(load(clean))
        assert rep2.findings == [], rep2.findings
        assert "No lever cleared its threshold" in render(rep2, "clean.csv")

        # A JSON export with different header names must map the same way.
        j = Path(td) / "usage.json"
        j.write_text(json.dumps({"rows": [
            {"vendor": "a", "engine": "m1", "apiCalls": 5, "prompt": 100, "completion": 100, "spend": "2.50"}
        ]}))
        rows3 = load(j)
        assert rows3[0].cost == 2.5 and rows3[0].calls == 5, rows3[0]

    print("audit self-test: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit an LLM usage export for savings.")
    ap.add_argument("export", nargs="?", help="CSV or JSON usage export")
    ap.add_argument("--out", help="write the markdown report here")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.export:
        ap.error("an export file is required (or pass --self-test)")

    rep = analyse(load(args.export))
    if args.json:
        print(json.dumps(
            {
                "source": args.export,
                "total_cost": round(rep.total_cost, 2),
                "total_calls": rep.total_calls,
                "findings": [f.__dict__ for f in rep.findings],
            },
            indent=2,
        ))
        return 0

    text = render(rep, args.export)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out} ({len(rep.findings)} findings, ${rep.total_cost:,.2f} audited)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
