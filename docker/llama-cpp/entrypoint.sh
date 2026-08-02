#!/usr/bin/env bash
set -euo pipefail

profile_file="${LLM_LAB_PROFILE_FILE:-/opt/llm-lab/profile.json}"
[[ -r "${profile_file}" ]] || { echo "ERROR: perfil no legible: ${profile_file}" >&2; exit 2; }

profile_id="$(jq -r '.id' "${profile_file}")"
model_dir="/models/${profile_id}"
mkdir -p "${model_dir}"

download_artifact() {
  local selector="$1"
  local repository file revision checksum destination temporary url
  repository="$(jq -r "${selector}.repository" "${profile_file}")"
  file="$(jq -r "${selector}.file" "${profile_file}")"
  revision="$(jq -r "${selector}.revision // \"main\"" "${profile_file}")"
  checksum="$(jq -r "${selector}.sha256 // \"\"" "${profile_file}")"
  destination="${model_dir}/$(basename "${file}")"
  temporary="${destination}.part"
  url="https://huggingface.co/${repository}/resolve/${revision}/${file}"
  if [[ ! -f "${destination}" ]]; then
    echo "Descargando ${repository}/${file} (${revision})..."
    curl_args=(--fail --location --retry 5 --retry-delay 2 --continue-at - --output "${temporary}")
    if [[ -n "${HF_TOKEN:-}" ]]; then curl_args+=(--header "Authorization: Bearer ${HF_TOKEN}"); fi
    curl "${curl_args[@]}" "${url}"
    mv "${temporary}" "${destination}"
  fi
  if [[ -n "${checksum}" ]]; then
    echo "${checksum}  ${destination}" | sha256sum --check --status \
      || { echo "ERROR: checksum inválido para ${destination}" >&2; exit 5; }
  fi
  printf '%s\n' "${destination}"
}

model_path="$(download_artifact '.model' | tail -n 1)"

args=(
  --host 0.0.0.0
  --port 8080
  --alias "${profile_id}"
  --ctx-size "$(jq -r '.server.contextSize' "${profile_file}")"
  --parallel "$(jq -r '.server.parallel' "${profile_file}")"
  --model "${model_path}"
)

if jq -e '.draftModel != null' "${profile_file}" >/dev/null; then
  draft_path="$(download_artifact '.draftModel' | tail -n 1)"
  args+=(--model-draft "${draft_path}")
fi

if [[ "${LLM_LAB_MODE:-serve}" == "pull" ]]; then
  echo "Artefactos preparados para ${profile_id}"
  exit 0
fi

if [[ -n "${LLM_LAB_API_KEY:-}" ]]; then
  args+=(--api-key "${LLM_LAB_API_KEY}")
fi

while IFS= read -r arg; do args+=("${arg}"); done < <(jq -r '.server.arguments[]' "${profile_file}")

exec llama-server "${args[@]}"
