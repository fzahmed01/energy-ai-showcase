"""
EU funding radar: Horizon Europe 2026-2027, Cluster 5 (Climate, Energy, Mobility).

Reads the official Work Programme PDF, extracts every topic with its budget,
type of action, TRL and deadlines, then scores how well each topic fits a
profile (by default: energy communities, flexibility, consumers and AI for
energy). Writes radar.csv, radar.json and the charts used in the README.

Run:  python radar.py "Cluster 5_Horizon Europe Work Programme 2026-2027.pdf" [YYYY-MM-DD]
Needs: pdftotext (poppler-utils), pandas, matplotlib
"""
import json, re, subprocess, sys
from datetime import date, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
TODAY = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
PORTAL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{}"

DESTINATIONS = [
    "Climate sciences and responses", "Cross-sectoral solutions for the climate transition",
    "Sustainable, secure and competitive energy supply", "Efficient, sustainable and inclusive energy use",
    "Clean and competitive solutions for all transport modes", "Safe, Resilient Transport and Smart Mobility",
]

# Profile: theme -> (weight, keywords). Edit this to point the radar at another specialism.
PROFILE = {
    "Energy communities & sharing": (5, ["energy communit", "energy sharing", "citizen energy", "collective self-consumption", "prosumer"]),
    "Flexibility & demand response": (4, ["flexibility", "demand response", "demand-side", "load shifting", "peak shaving", "aggregator"]),
    "Consumers & social": (3, ["consumer", "citizen", "energy poverty", "vulnerable", "societal readiness", "social innovation"]),
    "AI, data & digital": (3, ["artificial intelligence", " ai ", " ai-", "machine learning", "digital twin", "data space", "forecasting"]),
    "Grids & storage": (2, ["distribution grid", "distribution system", " dso", "electricity grid", "energy storage", "battery storage"]),
    "Buildings & heat": (1, ["building", "renovation", "heat pump", "district heating"]),
    "EU policy & markets": (1, ["electricity market", "market design", "regulatory", "business model"]),
}


def pdf_text(pdf):
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout


def clean(s):
    s = re.sub(r"Part 8 - Page \d+ of \d+", " ", s)
    s = re.sub(r"Horizon Europe - Work Programme 2026-2027\s+Climate, Energy and Mobility", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s):
    return datetime.strptime(s.strip(), "%d %b %Y").date()


def extract(text):
    lines = text.split("\n")
    body = next(i for i, l in enumerate(lines) if l.strip() == "Climate sciences and responses for the transformation towards climate neutrality" and i > 2000)

    calls, cur = {}, None
    for l in lines[:body]:
        if m := re.match(r"^\s{20,}(HORIZON-CL5-\d{4}-\d{2}(?:-Two-Stage)?)\s*$", l):
            cur = m.group(1); calls.setdefault(cur, {})
        elif cur and (m := re.match(r"^\s*(Opening|Deadline\(s\)):\s*(.+?)\s*$", l)):
            calls[cur].setdefault(m.group(1), m.group(2))

    stop = next(i for i, l in enumerate(lines) if i > body and l.lower().startswith("other actions"))
    starts = [i for i, l in enumerate(lines) if body <= i < stop and re.match(r"^HORIZON-CL5-\d{4}-[^:]+:", l)]
    topics, dest = [], None
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else stop
        # a destination heading inside the block starts the next destination's introduction
        end = next((j for j in range(i + 1, end) if not lines[j].startswith(" ") and any(lines[j].startswith(d) for d in DESTINATIONS)), end)
        for j in range(starts[k - 1] if k else body, i):
            if not lines[j].startswith(" ") and (d := next((d for d in DESTINATIONS if lines[j].startswith(d)), None)):
                dest = lines[j].strip()
        tid, title = lines[i].split(":", 1)
        j = i + 1
        while lines[j].strip() and not lines[j].startswith("Call:"):
            title += " " + lines[j].strip(); j += 1
        flat = clean("\n".join(lines[i:end]))
        call = re.match(r"HORIZON-CL5-\d{4}-\d{2}(?:-Two-Stage)?", tid).group(0)
        budget = re.search(r"total indicative budget for the topic is EUR ([\d.]+) million", flat)
        m = re.search(r"EU contribution of (around|between) EUR(.{0,160}?)million", flat)
        nums = re.findall(r"(?<![\d/])(\d{1,3}\.\d{2})(?!\d)", m.group(2)) if m else []
        per = f"{nums[0]}-{nums[1]}" if m and m.group(1) == "between" and len(nums) > 1 else (nums[0] if nums else "")
        toa = re.search(r"Type of Action ([A-Z][A-Za-z \-]+?Actions?|Pre-commercial Procurement)", flat)
        trl = re.search(r"achieve TRL ([\d\-–]+)", flat)
        deadlines = re.findall(r"\d{2} \w{3} \d{4}", calls[call]["Deadline(s)"])
        topics.append(dict(
            id=tid.strip(), title=re.sub(r"\s+", " ", title.strip()), destination=dest, call=call,
            type=toa.group(1) if toa else "", budget_meur=float(budget.group(1)) if budget else None,
            per_project_meur=per, trl=trl.group(1) if trl else "",
            opening=calls[call]["Opening"], deadline=deadlines[0],
            second_stage=deadlines[1] if len(deadlines) > 1 else "",
            url=PORTAL.format(tid.strip().lower()),
            text=flat.split("Expected Outcome:", 1)[-1]))
    return topics


def score(t):
    title, text = " " + t["title"].lower() + " ", " " + t["text"].lower() + " "
    total, themes = 0, []
    for theme, (w, kws) in PROFILE.items():
        hits = sum(text.count(k) for k in kws) + 5 * sum(title.count(k) for k in kws)
        if hits:
            total += w * min(hits, 10)
            if hits >= 3:
                themes.append(theme)
    return total, themes


def status(t):
    o, d = parse_date(t["opening"]), parse_date(t["deadline"])
    return "Open" if o <= TODAY <= d else "Forthcoming" if TODAY < o else "Closed"


def main():
    topics = extract(pdf_text(sys.argv[1]))
    for t in topics:
        t["fit_raw"], t["themes"] = score(t)
        t["status"] = status(t)
    df = pd.DataFrame(topics).drop(columns="text")
    df["fit"] = (100 * df.fit_raw / df.fit_raw.max()).round().astype(int)
    df["themes"] = df.themes.str.join("; ")
    df = df.drop(columns="fit_raw").sort_values(["fit", "budget_meur"], ascending=False)
    df.to_csv(HERE / "radar.csv", index=False)
    df.to_json(HERE / "radar.json", orient="records", indent=1)

    print(f"{len(df)} topics, EUR {df.budget_meur.sum():,.0f}m, as of {TODAY}")
    print(df.groupby("status").budget_meur.agg(["count", "sum"]))
    live = df[df.status != "Closed"]
    print(live.head(15)[["id", "title", "type", "budget_meur", "deadline", "fit", "themes"]].to_markdown(index=False))

    # Chart: live budget by destination, coloured by fit
    colors = {"high": "#1f9d6b", "mid": "#3b82c4", "low": "#c3cad3"}
    live = live.assign(band=pd.cut(live.fit, [-1, 14, 34, 100], labels=["low", "mid", "high"]))
    piv = live.pivot_table(index="destination", columns="band", values="budget_meur", aggfunc="sum", observed=False).fillna(0)
    piv = piv.loc[piv.sum(axis=1).sort_values().index]
    piv.index = [re.sub(r" (for the transformation towards climate neutrality|services for passengers and goods)", "", d) for d in piv.index]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    left = 0
    for band, label in [("high", "Strong fit (35+)"), ("mid", "Some fit (15-34)"), ("low", "Weak fit")]:
        ax.barh(piv.index, piv[band], left=left, color=colors[band], label=label)
        left = left + piv[band]
    ax.set_xlabel("Budget still open or forthcoming (EUR million)")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(f"Cluster 5 budget still to play for, as of {TODAY:%d %b %Y}", fontweight="bold", fontsize=11, loc="left")
    fig.tight_layout(); fig.savefig(HERE / "budget_by_fit.png", dpi=150)

    # Chart: deadline timeline of live topics
    tl = live.assign(d=pd.to_datetime(live.deadline, format="%d %b %Y")).groupby(["d", "band"], observed=False).budget_meur.sum().unstack().fillna(0)
    fig, ax = plt.subplots(figsize=(10, 3.4))
    bottom = 0
    labels = [d.strftime("%d %b\n%Y") for d in tl.index]
    for band, label in [("high", "Strong fit"), ("mid", "Some fit"), ("low", "Weak fit")]:
        ax.bar(labels, tl[band], bottom=bottom, color=colors[band], label=label)
        bottom = bottom + tl[band]
    ax.set_ylabel("EUR million")
    ax.set_title("Upcoming deadlines (first stage)", fontweight="bold", fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(HERE / "deadlines.png", dpi=150)


if __name__ == "__main__":
    main()
