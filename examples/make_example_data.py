#!/usr/bin/env python3
"""Generate the miniature example dataset from the full CCRP.

Extracts one chromosome-5 window and a subset of samples from the full
reference panel VCF, and the matching rows from the SV-frequency table.
Run from the repository root:

    python examples/make_example_data.py --full-panel refpanel/<full-panel>.vcf.gz \
        --sv-freq data/2063_SV_frq.csv --out examples/data

The full panel and frequency table are available from Zenodo (see README).
"""
import argparse
import csv
import pathlib
import sys

import pysam

WINDOW = ("5", 5_000_000, 7_000_000)   # contig, start, end (a 2 Mb chr5 window)
N_SAMPLES = 100


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full-panel", required=True, help="full CCRP panel VCF (.vcf.gz)")
    ap.add_argument("--sv-freq", required=True, help="2063_SV_frq.csv")
    ap.add_argument("--out", default="examples/data", help="output directory")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    contig, start, end = WINDOW

    vf = pysam.VariantFile(args.full_panel)
    samples = list(vf.header.samples)[:N_SAMPLES]
    vf.subset_samples(samples)
    out_vcf = out / "mini_panel.chr5.vcf.gz"
    n_variants = 0
    with pysam.VariantFile(out_vcf, "wz", header=vf.header) as w:
        for rec in vf.fetch(contig, start, end):
            w.write(rec)
            n_variants += 1
    pysam.tabix_index(str(out_vcf), preset="vcf", force=True)
    print(f"[panel]   {out_vcf}: {n_variants} SVs x {len(samples)} samples (chr{contig}:{start}-{end})")

    # 频率表为 GBK 编码（与生产数据一致），按二进制逐行子集，保持编码不变
    n_rows = 0
    out_csv = out / "sv_freq_mini.csv"
    with open(args.sv_freq, "r", encoding="gbk", newline="") as fin, \
            open(out_csv, "w", encoding="gbk", newline="") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        header = next(reader)
        writer.writerow(header)
        chr_i = header.index("Chr")
        pos_i = header.index("POS")
        for row in reader:
            try:
                if row[chr_i] == contig and start <= int(row[pos_i]) <= end:
                    writer.writerow(row)
                    n_rows += 1
            except (ValueError, IndexError):
                continue
    print(f"[sv freq] {out_csv}: {n_rows} SV rows")
    if n_variants == 0 or n_rows == 0:
        print("WARNING: empty subset — check contig naming in the source files", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
