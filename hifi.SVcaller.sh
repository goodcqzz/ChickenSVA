#!/bin/bash
# =============================================================================
# hifi.SVcaller.sh — HiFi Read-Based Structural Variant Calling Pipeline
# =============================================================================
# Description:
#   Parallelized SV detection from PacBio HiFi reads using three callers:
#   Sniffles2, cuteSV, and SVIM. Producer-consumer architecture with
#   FIFO-based concurrency control overlaps mapping and SV calling.
#
# Usage:
#   bash hifi.SVcaller.sh <sample_list.txt>
#
# Dependencies:
#   minimap2, samtools, sniffles (v2.6.1), cuteSV (v2.1.2),
#   svim (v2.0.0), bcftools
# =============================================================================

set -euo pipefail

# ======================== Configuration =======================================
# >>> MODIFY THESE PATHS BEFORE RUNNING <<<
DATA_DIR="<YOUR_DATA_DIR>"
FQ_DIR="${DATA_DIR}/05.hifi/01.fq"                # input FASTQ directory
REF="${DATA_DIR}/01.ref/reference.fa"              # reference genome FASTA
THREADS=5                                           # threads per tool call
THREAD_MAP=4                                        # concurrent mapping jobs
THREAD_CALL=4                                       # concurrent SV calling jobs
TMPDIR="$HOME/tmp/"
# =============================================================================

SAMPLE_LIST="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Create output directories -----------------------------------------------
for dir in 02.bam 03.sniffles 03.cuteSV 03.svim 04.merge.sv; do
    mkdir -p "${SCRIPT_DIR}/${dir}"
done

BAM_DIR="$(cd "${SCRIPT_DIR}/02.bam" && pwd)"
SNIFFLES_DIR="$(cd "${SCRIPT_DIR}/03.sniffles" && pwd)"
CUTESV_DIR="$(cd "${SCRIPT_DIR}/03.cuteSV" && pwd)"
SVIM_DIR="$(cd "${SCRIPT_DIR}/03.svim" && pwd)"
OUTPUT_DIR="$(cd "${SCRIPT_DIR}/04.merge.sv" && pwd)"

# --- Index reference if needed ------------------------------------------------
if [ ! -s "${REF}.fai" ]; then
    echo "Indexing reference genome..."
    samtools faidx "${REF}"
fi

# --- Timing -------------------------------------------------------------------
start_time=$(date +%s)

# ======================== Producer-Consumer Setup =============================

# FIFO for mapping concurrency control
fifo_map="${TMPDIR}/$$.map.fifo"
mkdir -p "${TMPDIR}"
mkfifo "$fifo_map"
exec 6<>"$fifo_map"
rm "$fifo_map"
for ((i = 0; i < THREAD_MAP; i++)); do echo; done >&6

# FIFO for SV calling concurrency control
fifo_call="${TMPDIR}/$$.call.fifo"
mkfifo "$fifo_call"
exec 7<>"$fifo_call"
rm "$fifo_call"
for ((i = 0; i < THREAD_CALL; i++)); do echo; done >&7

# SV calling task queue
callsv_queue="${TMPDIR}/callsv_queue.txt"
: > "$callsv_queue"

# --- SV Caller Consumer (background process) ----------------------------------
(
    while read -r bam; do
        [[ "$bam" == "END" ]] && break
        read -u7  # acquire token
        {
            id=$(basename "$bam" .sort.bam)
            sniffles_vcf="${id}.sniffles.vcf"
            cutesv_vcf="${id}.cuteSV.vcf"
            svim_vcf="${id}.svim.vcf"

            echo "[SV Calling] Sample: ${id}"

            # Sniffles2
            echo "  -> sniffles v2.6.1"
            sniffles -i "${bam}" -v "${SNIFFLES_DIR}/${sniffles_vcf}" \
                     -t "${THREADS}" --reference "${REF}" --sample-id "${id}"
            mv "${SNIFFLES_DIR}/${sniffles_vcf}" "${OUTPUT_DIR}/"

            # cuteSV
            echo "  -> cuteSV v2.1.2"
            mkdir -p "${CUTESV_DIR}/${id}"
            cuteSV -t 10 -S "${id}" "${bam}" "${REF}" \
                   "${CUTESV_DIR}/${cutesv_vcf}" \
                   "${CUTESV_DIR}/${id}/" --genotype --min_size 50
            mv "${CUTESV_DIR}/${cutesv_vcf}" "${OUTPUT_DIR}/"

            # SVIM
            echo "  -> svim v2.0.0"
            svim alignment --min_sv_size 50 "${SVIM_DIR}/${id}" "${bam}" "${REF}"
            mv "${SVIM_DIR}/${id}/variants.vcf" "${SVIM_DIR}/${svim_vcf}"
            sed -i 's/Sample/'"${id}"'/g' "${SVIM_DIR}/${svim_vcf}"
            bcftools view -i 'QUAL >= 5' "${SVIM_DIR}/${svim_vcf}" \
                > "${OUTPUT_DIR}/${id}.q5.svim.vcf"

            echo >&7  # release token
            echo "[Done] SV calling finished for ${id}"
        } &
    done < <(tail -f "$callsv_queue")
) &
callsv_consumer_pid=$!

# ======================== Main Loop: Mapping (Producer) =======================

while read -r sample_fq; do
    read -u6  # acquire token
    {
        fq="${FQ_DIR}/${sample_fq}"
        sample_name="${sample_fq%%.*}"
        bam_out="${BAM_DIR}/${sample_name}.sort.bam"

        echo "[$(date)] Mapping: ${sample_fq}"

        # minimap2 -> sort -> index
        minimap2 -ax map-hifi -Y --MD -t "${THREADS}" "${REF}" "${fq}" \
            | samtools view -@ 10 -bS \
            | samtools sort -@ 10 -o "${bam_out}" -
        samtools index -@ 10 "${bam_out}"

        # Enqueue BAM for SV calling
        echo "${bam_out}" >> "$callsv_queue"
        echo >&6  # release token
    } &
done < "${SAMPLE_LIST}"

# ======================== Cleanup & Wait ======================================

wait
sleep 5
echo "END" >> "$callsv_queue"
pkill -f "tail -f $callsv_queue" 2>/dev/null || true
exec 6>&-
exec 7>&-
wait "$callsv_consumer_pid"

stop_time=$(date +%s)
echo "Total runtime: $((stop_time - start_time)) seconds"
