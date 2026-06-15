#!/bin/bash
# =============================================================================
# paragraph.sh — Structural Variant Genotyping with Paragraph
# =============================================================================
# Description:
#   Genotypes structural variants from aligned BAM files using Paragraph.
#   Computes sequencing depth, builds a sample manifest, and runs
#   multigrmpy.py for graph-based SV genotyping.
#
# Usage:
#   bash paragraph.sh <input.bam> <reference.fa> <output_prefix> \
#                      <threads> <input.vcf> <sample_id>
#
# Dependencies:
#   Paragraph v2.4a (idxdepth, multigrmpy.py), samtools, bc, awk
# =============================================================================

set -euo pipefail

# ======================== Configuration =======================================
# >>> MODIFY THESE PATHS BEFORE RUNNING <<<
PARAGRAPH_BIN="<YOUR_SOFTWARE_DIR>/paragraph-v2.4a-binary/bin"
PYTHON="<YOUR_CONDA_ENV>/bin/python"    # Python with paragraph installed
# =============================================================================

# --- Parse arguments ----------------------------------------------------------
inputBam="$1"
refFasta="$2"
outputPrefix="$3"
threads="$4"
inputVcf="$5"
sample_id="$6"

# --- Step 1: Calculate sequencing depth ---------------------------------------
mkdir -p "${outputPrefix}/tmp" "${outputPrefix}/depth" "${outputPrefix}/manifest"
export TMPDIR="${outputPrefix}/tmp"

echo "Calculating depth for ${sample_id}..."
"${PARAGRAPH_BIN}/idxdepth" \
    -b "${inputBam}" \
    -r "${refFasta}" \
    -o "${outputPrefix}/depth/${sample_id}.json" \
    --threads "${threads}"

# --- Step 2: Build manifest ---------------------------------------------------
manifest="${outputPrefix}/manifest/${sample_id}.manifest.txt"
echo -e "id\tpath\tdepth\tread length" > "${manifest}"

Depth_ReadsLength=$(awk '{
    match($0, /],"depth":([0-9]+\.[0-9]+)/, a)
    match($0, /"read_length":([0-9]+)/, b)
    print a[1] "\t" b[1]
}' "${outputPrefix}/depth/${sample_id}.json")

echo -e "${sample_id}\t${inputBam}\t${Depth_ReadsLength}" >> "${manifest}"

# --- Step 3: Run Paragraph genotyping -----------------------------------------
Depth=$(cut -f3 "${manifest}" | tail -1)
maxDepth=$(echo "20 * ${Depth} / 1" | bc)

echo "Running Paragraph genotyping (depth=${Depth}, maxDepth=${maxDepth})..."
"${PYTHON}" "${PARAGRAPH_BIN}/multigrmpy.py" \
    -i "${inputVcf}" \
    -M "${maxDepth}" \
    -m "${manifest}" \
    -r "${refFasta}" \
    -t "${threads}" \
    -o "${outputPrefix}" \
    --scratch-dir "${outputPrefix}/tmp" \
    &> "${outputPrefix}/${sample_id}.paragraph.log"

# --- Cleanup ------------------------------------------------------------------
unset TMPDIR
rm -rf "${outputPrefix}/tmp"

echo "Paragraph genotyping complete: ${outputPrefix}"
