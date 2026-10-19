#!/usr/bin/env python3
"""ChickenSVA miniature end-to-end demo (no running services required).

Step 1 — SV query      : query the SV-frequency table — what the platform's
                         `query_sv` tool does behind the chat UI.
Step 2 — Imputation    : split the mini panel into reference (60 samples) and
                         target (40 samples), mask 80% of target genotypes
                         (simulating low-pass sequencing), impute with
                         Beagle, and score genotype concordance against the
                         masked truth — a miniature of the manuscript's
                         imputation benchmark.

Requirements: python3 with pysam; java (for Beagle).
"""
import csv
import pathlib
import random
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
BEAGLE_CANDIDATES = [
    pathlib.Path(__file__).resolve().parents[1] / "refpanel" / "beagle.jar",
    HERE / "beagle.jar",
]
BEAGLE_URL = "https://faculty.uw.edu/browning/beagle/beagle.28Jun21.1d.jar"
N_REF = 60
SITE_STEP = 3          # thin to every 3rd site (keeps the demo fast and light)
MAF_MIN, MAF_MAX = 0.05, 0.95
MASK_RATE = 0.80       # fraction of target genotypes blanked (simulated low-pass)
MASK_SEED = 42         # deterministic masking -> reproducible concordance


def step1_sv_query() -> None:
    print("=" * 72)
    print("STEP 1  SV query — chr5 deletions in the miniature frequency table")
    print("=" * 72)
    rows = []
    with open(DATA / "sv_freq_mini.csv", encoding="gbk", newline="") as f:
        for row in csv.DictReader(f):
            if row["SV_Type"] == "DEL":
                try:
                    rows.append((float(row["Mean_fre"]), row))
                except (KeyError, ValueError):
                    continue
    rows.sort(key=lambda t: t[0], reverse=True)
    print(f"{len(rows)} deletions found; top 5 by mean frequency:\n")
    print(f"{'SV_ID':<20}{'POS':>10}{'END':>10}  {'Mean_freq':>9}  Gene")
    for freq, r in rows[:5]:
        print(f"{r['ID']:<20}{r['POS']:>10}{r['End']:>10}  {freq:>9.3f}  {r.get('Gene', '')}")
    print("\n(In the full platform this runs through the chat agent, which chains")
    print(" query_sv -> query_annotation -> breed-association analyses.)")


def find_beagle() -> pathlib.Path:
    for p in BEAGLE_CANDIDATES:
        if p.exists() and p.stat().st_size > 100_000:
            return p
    dest = HERE / "beagle.jar"
    print(f"beagle.jar not found — downloading from {BEAGLE_URL} (one-time, ~25 MB)")
    try:
        subprocess.run(
            ["wget", "--timeout=90", "--tries=2", "-q", "-O", str(dest), BEAGLE_URL],
            check=True, timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        dest.unlink(missing_ok=True)
        raise SystemExit(
            f"下载 beagle.jar 失败（{BEAGLE_URL}）。\n"
            f"请手动下载后放到 {dest} 或仓库 refpanel/ 目录，再重跑本演示。"
        )
    if dest.stat().st_size < 100_000:
        dest.unlink(missing_ok=True)
        raise SystemExit(
            f"下载的 beagle.jar 异常（{dest.stat().st_size} 字节，疑似被墙或跳转页）。"
            "请手动下载后放入 examples/ 目录。"
        )
    return dest


def _kept_sites(panel: pathlib.Path):
    """Deterministically pick common, thinned sites from the FULL mini panel.

    The same rule is applied to reference and target files so that positions
    align, which Beagle requires. Rare sites dominate memory and add little
    to a toy demo, so they are dropped.
    """
    import pysam

    vf = pysam.VariantFile(str(panel))
    kept = set()
    for i, rec in enumerate(vf):
        if i % SITE_STEP:
            continue
        ac = an = 0
        for s in rec.samples.values():
            gt = s["GT"]
            if gt is None:
                continue
            for a in gt:
                an += 1
                if a == 1:
                    ac += 1
        if an and MAF_MIN <= ac / an <= MAF_MAX:
            kept.add((rec.contig, rec.pos))
    vf.close()
    return kept


def _write_subset(src_path: pathlib.Path, samples: list, out_path: pathlib.Path,
                  mask: bool, kept: set):
    """Write a sample subset of the panel; optionally blank every genotype."""
    import pysam

    vf = pysam.VariantFile(str(src_path))
    vf.subset_samples(samples)
    rng = random.Random(MASK_SEED)
    truth = {}          # {(sample, pos): alleles} — kept before masking
    with pysam.VariantFile(str(out_path), "wz", header=vf.header) as out:
        for rec in vf:
            if (rec.contig, rec.pos) not in kept:
                continue
            if mask and rng.random() < MASK_RATE:
                for s in samples:
                    gt = rec.samples[s]["GT"]
                    if gt is not None:
                        truth[(s, rec.pos)] = tuple(gt)
                    # 面板为二倍体；(None, None) 写出 './.'，而 None 会写成单倍 '.'，
                    # Beagle 会因样本内倍性不一致报错
                    rec.samples[s]["GT"] = (None, None)
            out.write(rec)
    pysam.tabix_index(str(out_path), preset="vcf", force=True)
    return truth


def step2_imputation() -> None:
    import pysam

    print("\n" + "=" * 72)
    print(f"STEP 2  Imputation benchmark — {N_REF} reference / rest as masked target")
    print("=" * 72)
    beagle = find_beagle()
    panel = DATA / "mini_panel.chr5.vcf.gz"
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="chickensva_demo_"))

    src = pysam.VariantFile(str(panel))
    samples = list(src.header.samples)
    src.close()
    ref_samples, tgt_samples = samples[:N_REF], samples[N_REF:]

    print(f"[1/5] selecting common variant sites (MAF {MAF_MIN}-{MAF_MAX}, 1-in-{SITE_STEP} thinning) ...")
    kept = _kept_sites(panel)
    print(f"      {len(kept)} sites retained")
    print(f"[2/5] writing reference panel ({len(ref_samples)} samples) ...")
    _write_subset(panel, ref_samples, workdir / "ref.vcf.gz", mask=False, kept=kept)
    print(f"[3/5] writing masked target ({len(tgt_samples)} samples, {int(MASK_RATE*100)}% of genotypes blanked) ...")
    truth = _write_subset(panel, tgt_samples, workdir / "target_masked.vcf.gz",
                          mask=True, kept=kept)

    print("[4/5] running Beagle ...")
    out_prefix = workdir / "imputed"
    proc = subprocess.run(
        ["java", "-Xmx3g", "-jar", str(beagle),
         f"gt={workdir / 'target_masked.vcf.gz'}",
         f"ref={workdir / 'ref.vcf.gz'}",
         f"out={out_prefix}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"Beagle 运行失败 (exit {proc.returncode}):\n{proc.stderr[-1500:]}"
        )
    imputed_path = workdir / "imputed.vcf.gz"

    print("[5/5] scoring genotype concordance vs masked truth ...")
    ivf = pysam.VariantFile(str(imputed_path))
    n_alleles = n_match = n_sites = 0
    for rec in ivf:
        called_any = False
        for s in tgt_samples:
            gt = rec.samples[s]["GT"]
            if gt is None:
                continue
            key = (s, rec.pos)
            if key not in truth or truth[key] is None:
                continue
            if len(gt) != len(truth[key]):
                continue
            called_any = True
            for a_called, a_true in zip(gt, truth[key]):
                n_alleles += 1
                if a_called == a_true:
                    n_match += 1
        if called_any:
            n_sites += 1
    print(f"\n      variants scored    : {n_sites}")
    print(f"      allele concordance : {n_match / n_alleles:.4f}  ({n_match}/{n_alleles} alleles)")
    print(f"\n      working files kept in: {workdir}")
    print(f"      (target genotypes were {int(MASK_RATE*100)}% blanked; imputation restores")
    print("       them from the reference panel + surviving genotypes — a miniature")
    print("       of the manuscript's low-pass WGS / SNP-chip benchmark)")


if __name__ == "__main__":
    step1_sv_query()
    step2_imputation()
