"""
Community battery flexibility: individual vs. shared operation.

Seventeen homes with rooftop PV and a 6.4 kWh home battery each
(CityLearn Challenge 2022 dataset, one year at hourly resolution).
We compare three ways of running the same hardware:

  A. PV only           - no batteries used
  B. Individual        - each home runs its own battery for self-consumption
  C. Community         - the 17 batteries act as one shared pool, coordinated
                          to shave the community's grid peak each day

Run:  python analysis.py   (needs pandas, numpy, matplotlib)
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data"
EFF = 0.9  # round-trip efficiency from the dataset schema, applied on charge


def load_community():
    schema = json.loads((DATA / "schema.json").read_text())
    loads, pv, batteries = [], [], []
    for name, b in schema["buildings"].items():
        df = pd.read_csv(DATA / b["energy_simulation"])
        loads.append(df["Equipment Electric Power [kWh]"].to_numpy())
        pv.append(df["Solar Generation [W/kW]"].to_numpy() * b["pv"]["attributes"]["nominal_power"] / 1000)
        a = b["electrical_storage"]["attributes"]
        batteries.append((a["capacity"], a["nominal_power"]))
    price = pd.read_csv(DATA / "pricing.csv").iloc[:, 0].to_numpy()
    carbon = pd.read_csv(DATA / "carbon_intensity.csv").iloc[:, 0].to_numpy()
    return np.array(loads), np.array(pv), batteries, price, carbon


def step(soc, net, cap, power, limit=0.0, grid_charge=False):
    """One hour of battery operation. net > 0 means demand, < 0 surplus.
    Discharges only the part of demand above `limit`. With grid_charge, also
    tops up from the grid while import stays under `limit`. Returns (grid, soc)."""
    if net < 0 or (grid_charge and net < limit):
        room = -net if net < 0 else limit - net
        charge = min(room, power, (cap - soc) / EFF)
        return net + charge, soc + charge * EFF
    discharge = min(max(net - limit, 0), power, soc)
    return net - discharge, soc - discharge


def individual(loads, pv, batteries):
    grid = np.zeros(loads.shape[1])
    for h, (cap, power) in enumerate(batteries):
        soc = 0.0
        for t in range(loads.shape[1]):
            g, soc = step(soc, loads[h, t] - pv[h, t], cap, power)
            grid[t] += g
    return grid


def community(loads, pv, batteries):
    """Pooled batteries. Each day, find the lowest import cap the pool can hold
    (perfect day-ahead forecast): discharge above the cap, and top up from the
    grid in quiet hours below it."""
    cap = sum(c for c, _ in batteries)
    power = sum(p for _, p in batteries)
    net = (loads - pv).sum(axis=0)
    grid, soc = np.zeros_like(net), 0.0

    def run_day(day, soc0, limit):
        out, s = [], soc0
        for n in day:
            g, s = step(s, n, cap, power, limit, grid_charge=True)
            out.append(g)
        return np.array(out), s

    for d in range(0, len(net), 24):
        day = net[d:d + 24]
        lo, hi = 0.0, max(day.max(), 0.0)
        for _ in range(30):  # bisection on the daily import cap
            mid = (lo + hi) / 2
            g, _ = run_day(day, soc, mid)
            lo, hi = (lo, mid) if g.max() <= mid + 1e-6 else (mid, hi)
        grid[d:d + 24], soc = run_day(day, soc, hi)
    return grid


def metrics(grid, price, carbon):
    imp = np.clip(grid, 0, None)
    return {
        "Grid peak (kW)": imp.max(),
        "Grid import (MWh/yr)": imp.sum() / 1000,
        "Export to grid (MWh/yr)": -np.clip(grid, None, 0).sum() / 1000,
        "Electricity cost ($/yr)": (imp * price).sum(),
        "Emissions (t CO2/yr)": (imp * carbon).sum() / 1000,
    }


def main():
    loads, pv, batteries, price, carbon = load_community()
    scenarios = {
        "A. PV only": (loads - pv).sum(axis=0),
        "B. Individual batteries": individual(loads, pv, batteries),
        "C. Community-shared batteries": community(loads, pv, batteries),
    }
    table = pd.DataFrame({k: metrics(g, price, carbon) for k, g in scenarios.items()}).T
    print(table.round(1).to_markdown())
    table.round(2).to_csv(HERE / "results.csv")

    # Chart 1: headline comparison
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    colors = ["#9aa5b1", "#3b82c4", "#1f9d6b"]
    for ax, col in zip(axes, ["Grid peak (kW)", "Grid import (MWh/yr)", "Electricity cost ($/yr)"]):
        ax.bar(["PV only", "Individual", "Community"], table[col], color=colors)
        ax.set_title(col, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Same 17 batteries, three ways to run them", fontweight="bold")
    fig.tight_layout()
    fig.savefig(HERE / "comparison.png", dpi=150)

    # Chart 2: the peak week, hour by hour
    a = np.clip(scenarios["A. PV only"], 0, None)
    start = int(np.argmax(a)) // 24 * 24 - 72
    start = max(start, 0)
    hours = np.arange(168)
    fig, ax = plt.subplots(figsize=(11, 3.6))
    for (k, g), c in zip(scenarios.items(), colors):
        ax.plot(hours, np.clip(g[start:start + 168], 0, None), label=k, color=c, lw=1.6)
    ax.set_xlabel("Hour of the peak week")
    ax.set_ylabel("Community grid import (kW)")
    ax.legend(frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(HERE / "peak_week.png", dpi=150)


if __name__ == "__main__":
    main()
