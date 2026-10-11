"""Report figures (static PNGs for the markdown report)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
    "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def source_overlap(summary: dict, out: Path) -> None:
    order = ["codes + troponin", "codes only", "troponin only"]
    vals = [summary["overlap"][k] for k in order]
    fig, ax = plt.subplots(figsize=(6.4, 2.2))
    ax.barh(order[::-1], vals[::-1], color=[ORANGE, BLUE, AQUA][::-1], height=0.55)
    for i, v in enumerate(vals[::-1]):
        ax.text(v + 0.2, i, str(v), va="center", color=INK)
    ax.set_xlabel("patients")
    ax.set_title(f"Patients with MI evidence, by source (n = {sum(vals)} of {summary['patients']})",
                 loc="left", color=INK, fontsize=11)
    ax.xaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def troponin_quality(summary: dict, linkage: pd.DataFrame, out: Path) -> None:
    n = summary["troponin_rows"]
    text_only = summary["troponin_text_only_rows"]
    strict = int(linkage.iloc[0].troponin_rows_linked)
    windowed = int(linkage.iloc[1].troponin_rows_linked)
    rows = [
        ("Result stored as", [("numeric value", n - text_only, BLUE), ("text only ('<0.01' in comments)", text_only, ORANGE)]),
        ("Linked to an admission", [("by hadm_id", strict, BLUE), ("by 24h time window", windowed - strict, AQUA),
                                    ("not linkable", n - windowed, GRID)]),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 2.1))
    for y, (label, segs) in enumerate(rows[::-1]):
        left = 0
        for name, v, col in segs:
            ax.barh(y, v, left=left, color=col, height=0.5, edgecolor="white", linewidth=2)
            if v:
                ax.text(left + v / 2, y, f"{v}", ha="center", va="center",
                        color="white" if col != GRID else INK2, fontsize=9)
            left += v
    ax.set_yticks([0, 1], [r[0] for r in rows[::-1]])
    ax.set_xlim(0, n)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, segs in rows for _, _, c in segs]
    labels = [nm for _, segs in rows for nm, _, _ in segs]
    ax.legend(handles, labels, ncol=3, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.22))
    ax.set_title(f"Troponin T result storage and linkage (n = {n} rows)", loc="left", color=INK, fontsize=11)
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def peak_troponin(adm: pd.DataFrame, threshold: float, out: Path) -> None:
    groups = [("MI code", adm[adm.code_any], BLUE),
              ("no MI code,\ntroponin positive", adm[~adm.code_any & adm.troponin_positive], AQUA)]
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for y, (label, df, col) in enumerate(groups):
        vals = df.peak_tnt.fillna(-1)
        tested = vals[vals >= 0].clip(lower=0.005)  # '<0.01' plotted just under the detection limit
        ax.scatter(tested, [y] * len(tested), s=46, color=col, edgecolor="white", linewidth=1.5, zorder=3)
        n_untested = int((vals < 0).sum())
        if n_untested:
            ax.text(0.0042, y + 0.25, f"+{n_untested} not tested", fontsize=8, color=INK2)
    ax.axvline(threshold, color=INK2, linestyle="--", linewidth=1)
    ax.text(threshold * 1.08, 1.45, f"{threshold} ng/mL\n(lab's MI threshold)", fontsize=8, color=INK2, va="top")
    ax.set_xscale("log"); ax.set_xlim(0.004, 12)
    ax.set_yticks([0, 1], [g[0] for g in groups]); ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel("peak troponin T, ng/mL (log scale; '<0.01' plotted at 0.005)")
    ax.set_title("Peak troponin per admission", loc="left", color=INK, fontsize=11)
    ax.xaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def build_all(out_dir: Path, fig_dir: Path, threshold: float) -> None:
    import json
    fig_dir.mkdir(parents=True, exist_ok=True)
    summary = json.loads((out_dir / "summary.json").read_text())
    linkage = pd.read_csv(out_dir / "linkage_sensitivity.csv")
    adm = pd.read_csv(out_dir / "admission_mi_evidence.csv")
    source_overlap(summary, fig_dir / "fig1_source_overlap.png")
    troponin_quality(summary, linkage, fig_dir / "fig2_troponin_quality.png")
    peak_troponin(adm, threshold, fig_dir / "fig3_peak_troponin.png")
