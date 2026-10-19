# Example dataset and demo

A miniature, self-contained dataset extracted from the full CCRP
(chromosome 5, 5–7 Mb, 100 of the 2,063 samples) plus a runnable demo of the
two core capabilities: **SV query** and **genotype imputation**.

```
examples/
├── data/
│   ├── mini_panel.chr5.vcf.gz(.tbi)   # 40,095 variants × 100 samples (genotypes)
│   ├── sv_freq_mini.csv                # SV records + per-breed frequencies (GBK, as production)
│   └── phenotype_breeds_2024.csv       # breed-level phenotype table (GBK)
├── make_example_data.py                # how the mini dataset was extracted (reproducible)
└── run_demo.sh / run_demo.py           # the demo
```

## Run

```bash
bash examples/run_demo.sh
# or, if your pysam lives in a conda env:
CHICKENSV_PYTHON=/path/to/env/bin/python bash examples/run_demo.sh
```

Requirements: `python3` + `pysam`, and `java` for the Beagle step.
`beagle.jar` is **not** bundled (third-party license); the script downloads it
once from the official site, or put it at `examples/beagle.jar` /
`refpanel/beagle.jar` yourself.

## What the demo does

1. **SV query** — lists chr5 deletions from the frequency table with gene
   annotations (what the chat agent's `query_sv` tool does).
2. **Imputation benchmark (miniature)** — 60 samples serve as the Beagle
   reference panel; for the other 40, 80% of genotypes are blanked
   (simulating low-pass data). Beagle imputes the missing genotypes and the
   script reports allele concordance against the blanked truth
   (≈ 0.84 in this toy setting; the manuscript reports the full benchmark
   across SNP/INDEL/SV, MAF strata, and sequencing depths).

## Regenerating the mini dataset

If you have the full panel and frequency table (Zenodo, see main README):

```bash
python examples/make_example_data.py \
    --full-panel refpanel/2063.10.14.imiss0.2.panel.plink_ph.AN_AC.reiid.vcf.gz \
    --sv-freq data/2063_SV_frq.csv --out examples/data
```
