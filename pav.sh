#!/bin/bash
# =============================================================================
# pav.sh — Assembly-Based SV Genotyping with Pav
# =============================================================================
# Description:
#   Runs Pav (Profile-aware Variant caller) for assembly-based SV genotyping
#   using an Apptainer/Singularity container.
#
# Usage:
#   bash pav.sh
#
# Dependencies:
#   Apptainer (or Singularity), Pav container image (pav.sif)
# =============================================================================

set -euo pipefail

# ======================== Configuration =======================================
# >>> MODIFY THESE PATHS BEFORE RUNNING <<<
PAV_SIF="<YOUR_SOFTWARE_DIR>/pav.sif"   # Pav container image
BIND_DIR="<YOUR_DATA_DIR>/"              # data directory to bind mount
THREADS=12                                # threads for Pav
# =============================================================================

# --- Check container exists ---------------------------------------------------
if [ ! -f "${PAV_SIF}" ]; then
    echo "ERROR: Pav container not found at ${PAV_SIF}"
    echo "Please build or download the Pav SIF image first."
    exit 1
fi

# --- Run Pav ------------------------------------------------------------------
echo "Launching Pav container..."
echo "  Image:   ${PAV_SIF}"
echo "  Bind:    ${BIND_DIR}"
echo "  Threads: ${THREADS}"

apptainer run \
    -B "${BIND_DIR}" \
    --writable-tmpfs \
    "${PAV_SIF}" \
    -c "${THREADS}"
