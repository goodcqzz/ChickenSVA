# HiFi and Assembly Structural Variant Calling Pipeline

A multi-caller structural variant (SV) detection pipeline integrating both **read-based** and **assembly-based** approaches from PacBio HiFi sequencing data and genome assemblies. The pipeline employs six complementary SV callers and merges results through two independent strategies (reference-based and graph-based) to produce a high-confidence final SV set.

## Pipeline Overview

```
                        ┌─────────────────────────────────┐
                        │          SV Callers              │
                        │                                  │
  ┌──────────┐          │  Read-based:                     │
  │ 16 HiFi  │─────────►│    Sniffles2, cuteSV, SVIM       │
  │  reads   │          │                                  │
  └──────────┘          │  Assembly-based:                 │
                        │    Minigraph, SVIM-asm, Pav      │
  ┌──────────┐          │                                  │
  │24 Genome │─────────►│                                  │
  │Assemblies│          └──────┬──────────────┬────────────┘
  └──────────┘                 │              │
                               ▼              ▼
                    ┌──────────────┐  ┌──────────────┐
                    │  Reference-  │  │  Graph-based │
                    │  based Merge │  │  (vg tools)  │
                    │  (Jasmine)   │  │              │
                    └──────┬───────┘  └──────┬───────┘
                           │                 │
                           ▼                 ▼
                        ┌─────────────────────┐
                        │   Final SV set       │──────► SV
                        └─────────────────────┘
```

## Scripts

| Script | Input | Callers | Description |
|--------|-------|---------|-------------|
| `hifi.SVcaller.sh` | HiFi reads (FASTQ) | Sniffles2, cuteSV, SVIM | Read-based SV calling with producer-consumer parallelism |
| `svim_asm.sh` | Genome assemblies (FASTA) | SVIM-asm | Assembly-to-reference alignment + SV calling |
| `minigraph.sh` | Genome assemblies (FASTA) | Minigraph + vg | Pangenome graph construction + variant deconstruction |
| `pav.sh` | Genome assemblies | Pav | Assembly-based SV genotyping (containerized) |
| `paragraph.sh` | BAM + VCF | Paragraph | Graph-based SV genotyping on final SV set |

## Software Requirements

### Read-Based Callers

| Tool | Version | Purpose |
|------|---------|---------|
| minimap2 | >=2.24 | Long-read alignment (map-hifi mode) |
| samtools | >=1.15 | BAM sorting, indexing |
| Sniffles2 | 2.6.1 | SV calling from HiFi reads |
| cuteSV | 2.1.2 | SV calling with genotyping |
| SVIM | 2.0.0 | SV calling from alignments |
| bcftools | >=1.15 | VCF filtering (QUAL >= 5) |

### Assembly-Based Callers

| Tool | Version | Purpose |
|------|---------|---------|
| minimap2 | >=2.24 | Assembly-to-reference alignment (asm5 mode) |
| SVIM-asm | latest | Assembly-based SV calling |
| Minigraph | >=0.20 | Pangenome graph construction |
| vg | >=1.48 | Graph manipulation and variant deconstruction |
| Pav | latest | Assembly-based SV genotyping (Apptainer) |
| Apptainer | >=1.0 | Container runtime for Pav |

### Genotyping & Merging

| Tool | Version | Purpose |
|------|---------|---------|
| Paragraph | 2.4a | Graph-based SV genotyping |
| Jasmine | latest | VCF merging (reference-based) |

## Quick Start

### 1. Configure paths

Each script has a `Configuration` section at the top. Edit the placeholder paths before running:

```bash
# Example: edit hifi.SVcaller.sh
DATA_DIR="/path/to/your/data"
REF="${DATA_DIR}/reference.fa"
```

### 2. Read-Based SV Calling

```bash
# Prepare sample list (one FASTQ filename per line)
ls /path/to/fastq/*.fq > sample_list.txt

bash hifi.SVcaller.sh sample_list.txt
```

### 3. Assembly-Based SV Calling

#### SVIM-asm

```bash
# genome_list.txt: <sample_id> <assembly.fasta> per line
bash svim_asm.sh genome_list.txt
```

#### Minigraph (Graph-Based)

```bash
bash minigraph.sh genome_list.txt
```

#### Pav

```bash
bash pav.sh
```

### 4. SV Genotyping with Paragraph

```bash
bash paragraph.sh \
    input.sort.bam \
    reference.fa \
    output_prefix \
    8 \
    final_sv_set.vcf \
    sample_id
```

## Input Formats

### Sample List (HiFi reads)
```
sample01_R1.fq.gz
sample02_R1.fq.gz
```

### Genome List (assemblies)
```
sample01    /path/to/sample01.assembly.fa
sample02    /path/to/sample02.assembly.fa
```

## Output

| Caller | Output | Format |
|--------|--------|--------|
| Sniffles2 | `*.sniffles.vcf` | Standard VCF |
| cuteSV | `*.cuteSV.vcf` | VCF with genotype |
| SVIM | `*.q5.svim.vcf` | VCF filtered (QUAL >= 5) |
| SVIM-asm | `*_svimasm.vcf.gz` + `.tbi` | Compressed + indexed VCF |
| Minigraph | `*.vg48.vcf` | Deconstructed graph VCF |

## Citation

- **Sniffles2**: Smolka et al. (2024) *Nature Biotechnology*
- **cuteSV**: Jiang et al. (2020) *Genome Biology*
- **SVIM**: Heller & Vingron (2019) *Bioinformatics*
- **SVIM-asm**: Heller & Vingron (2023) *Genome Biology*
- **Minigraph**: Li et al. (2020) *Genome Biology*
- **vg**: Garrison et al. (2018) *Nature Biotechnology*
- **Paragraph**: Eggert et al. (2021) *Genome Biology*
- **Jasmine**: Smolka & Marschall (2022) *Genome Research*

## License

Scripts are provided as-is for research purposes.
