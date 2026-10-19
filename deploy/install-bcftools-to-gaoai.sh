#!/usr/bin/env bash
# 将 bcftools 离线装入 gaoai（独立 lib 目录，避免 OpenSSL 冲突）
set -euo pipefail

CONDA_BASE="${CONDA_BASE:-${HOME}/miniconda3}"
TARGET_ENV="${CHICKENSV_CONDA_ENV:-gaoai}"
SOURCE_ENV="${BCFTOOLS_SOURCE_ENV:-sv-analysis}"

TARGET="${CONDA_BASE}/envs/${TARGET_ENV}"
SOURCE="${CONDA_BASE}/envs/${SOURCE_ENV}"
BIO="${TARGET}/bioinfo"
BIN="${BIO}/bin"
LIB="${BIO}/lib"

[[ -x "${SOURCE}/bin/bcftools" ]] || { echo "源环境无 bcftools: ${SOURCE}" >&2; exit 1; }

echo "安装 bcftools 到 ${TARGET} (bioinfo/) ..."

rm -rf "${BIO}"
mkdir -p "${BIN}" "${LIB}"

for b in bcftools tabix bgzip htsfile; do
  [[ -f "${SOURCE}/bin/${b}" ]] && cp -f "${SOURCE}/bin/${b}" "${BIN}/${b}.real" && chmod +x "${BIN}/${b}.real"
done

while IFS= read -r line; do
  lib=$(echo "$line" | awk '{print $3}')
  [[ -z "$lib" || "$lib" == "not" ]] && continue
  [[ "$lib" == /lib/* || "$lib" == /usr/* ]] && continue
  cp -fn "$lib" "${LIB}/" 2>/dev/null || true
done < <(ldd "${SOURCE}/bin/bcftools")

for lib in "${SOURCE}/lib/libhts.so"*; do
  [[ -e "$lib" ]] && cp -fn "$lib" "${LIB}/"
done

wrap() {
  local name="$1"
  cat > "${TARGET}/bin/${name}" <<EOF
#!/usr/bin/env bash
export LD_LIBRARY_PATH="${LIB}:\${LD_LIBRARY_PATH:-}"
exec "${BIN}/${name}.real" "\$@"
EOF
  chmod +x "${TARGET}/bin/${name}"
  echo "  ${TARGET}/bin/${name}"
}

for b in bcftools tabix bgzip htsfile; do
  [[ -x "${BIN}/${b}.real" ]] && wrap "$b"
done

"${TARGET}/bin/bcftools" --version | head -1
echo "完成"
