#!/bin/bash
# =============================================================================
# svim_asm.sh — Assembly-Based SV Calling with SVIM-asm
# =============================================================================
# Description:
#   Detects structural variants from genome assemblies using SVIM-asm.
#   Aligns each assembly to the reference with minimap2 (asm5 mode),
#   then calls SVs with svim-asm in haploid mode.
#
# Usage:
#   bash svim_asm.sh <genome_list.txt>
#   genome_list.txt format: <sample_id> <assembly.fasta> per line
#
# Dependencies:
#   minimap2, samtools, svim-asm, bgzip, tabix
# =============================================================================

set -euo pipefail

# ======================== Configuration =======================================
# >>> MODIFY THESE PATHS BEFORE RUNNING <<<
REF="<YOUR_REF_DIR>/reference.fa"       # reference genome
THREADS_PER_JOB=7                        # threads per alignment
MAX_CONCURRENT=8                         # max parallel jobs
# =============================================================================

GENOME_LIST="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Create output directories -----------------------------------------------
BAM_DIR="${SCRIPT_DIR}/svim-asm/01.bam"
RESULT_DIR="${SCRIPT_DIR}/svim-asm/02.results"
mkdir -p "${BAM_DIR}" "${RESULT_DIR}"

# --- Timing -------------------------------------------------------------------
start_time=$(date +%s)

# ======================== FIFO Concurrency Control ============================
mkdir -p "${HOME}/tmp"
fifo="${HOME}/tmp/$$.fifo"
mkfifo "$fifo"
exec 6<>"$fifo"
rm "$fifo"
for ((i = 0; i < MAX_CONCURRENT; i++)); do echo >&6; done

# ======================== Main Loop ===========================================
while IFS= read -r line || [[ -n "$line" ]]; do
    read -u6
    {
        id=$(echo "$line" | awk '{print $1}')
        fa=$(echo "$line" | awk '{print $2}')

        vcf_dir="${RESULT_DIR}/${id}_vcf"
        mkdir -p "${vcf_dir}"

        echo "[SVIM-asm] Processing: ${id}"

        # Alignment: minimap2 asm5
        minimap2 -a -x asm5 --cs -r2k -t "${THREADS_PER_JOB}" \
            "${REF}" "${fa}" \
            | samtools sort -@ 5 -o "${BAM_DIR}/${id}.sort.bam"
        samtools index "${BAM_DIR}/${id}.sort.bam"

        # SV calling: svim-asm haploid
        svim-asm haploid "${vcf_dir}" "${BAM_DIR}/${id}.sort.bam" "${REF}"

        # Post-processing
        cd "${vcf_dir}"
        sed "s/Sample/${id}/g" variants.vcf > "${id}_svimasm.vcf"
        bgzip -k "${id}_svimasm.vcf"
        tabix "${id}_svimasm.vcf.gz"
        mv "${id}_svimasm"* "${RESULT_DIR}/"
        touch "${id}.done"
        cd "${SCRIPT_DIR}"

        echo >&6
        echo "[Done] SVIM-asm finished for ${id}"
    } &
done < "${GENOME_LIST}"

wait
exec 6>&-

stop_time=$(date +%s)
echo "SVIM-asm complete. Runtime: $((stop_time - start_time)) seconds"
echo "Results in: ${RESULT_DIR}"
