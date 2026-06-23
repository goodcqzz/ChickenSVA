#!/bin/bash
# =============================================================================
# minigraph.sh — Graph-Based SV Calling with Minigraph + vg
# =============================================================================
# Description:
#   Constructs pangenome graphs from genome assemblies using Minigraph,
#   then extracts structural variants via vg deconstruct.
#
# Usage:
#   bash minigraph.sh <genome_list.txt>
#   genome_list.txt format: <sample_id> <assembly.fasta> per line
#
# Pipeline:
#   minigraph → vg convert → vg autoindex → vg snarls → vg deconstruct → VCF
#
# Dependencies:
#   minigraph (>=0.20), vg (>=1.48)
# =============================================================================

set -euo pipefail

# ======================== Configuration =======================================
# >>> MODIFY THESE PATHS BEFORE RUNNING <<<
REF="<YOUR_REF_DIR>/reference.fa"       # reference genome
THREADS_PER_JOB=10                       # threads per job
MAX_CONCURRENT=5                         # max parallel jobs
# =============================================================================

GENOME_LIST="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Create output directories -----------------------------------------------
MINIGRAPH_DIR="${SCRIPT_DIR}/minigraph"
VCF_DIR="${MINIGRAPH_DIR}/03.VCF"
mkdir -p "${MINIGRAPH_DIR}" "${VCF_DIR}"

# ======================== FIFO Concurrency Control ============================
mkdir -p "${HOME}/tmp"
fifo="${HOME}/tmp/$$.fifo"
mkfifo "$fifo"
exec 6<>"$fifo"
rm -f "$fifo"
for ((i = 0; i < MAX_CONCURRENT; i++)); do echo >&6; done

# ======================== Main Loop ===========================================
while IFS= read -r line || [[ -n "$line" ]]; do
    read -u6
    {
        id=$(echo "$line" | awk '{print $1}')
        fa=$(echo "$line" | awk '{print $2}')

        sample_dir="${MINIGRAPH_DIR}/${id}"
        mkdir -p "${sample_dir}"

        echo "[Minigraph] Processing: ${id}"
        cd "${sample_dir}"

        # Step 1: Build GFA graph
        minigraph -cxggs -t "${THREADS_PER_JOB}" "${REF}" "${fa}" \
            > "${id}.rgfa"

        # Step 2: Convert GFA format
        vg convert -g "${id}.rgfa" -f -t "${THREADS_PER_JOB}" \
            > "${id}.vg.gfa"

        # Step 3: Build vg autoindex (giraffe workflow)
        vg autoindex --workflow giraffe \
            --gfa "${id}.vg.gfa" \
            -t "${THREADS_PER_JOB}" \
            -R XG \
            --prefix "${id}"

        # Step 4: Get snarls
        vg snarls "${id}.xg" "${id}.snarls"

        # Step 5: Deconstruct variants to VCF
        vg deconstruct "${id}.giraffe.gbz" \
            -r "${id}.snarls" -a \
            > "${id}.vg.vcf"

        # Step 6: Collect VCF
        ln -sf "${sample_dir}/${id}.vg48.vcf" "${VCF_DIR}/"
        cd "${SCRIPT_DIR}"

        echo >&6
        echo "[Done] Minigraph finished for ${id}"
    } &
done < "${GENOME_LIST}"

wait
exec 6>&-

echo "Minigraph pipeline complete. VCFs in: ${VCF_DIR}"
