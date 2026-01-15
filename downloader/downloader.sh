#!/bin/bash

BASE_URL="https://nuvem.anitsu.moe/api"
COOKIE_FILE="$HOME/cookies.txt"

LOG_DIR="$HOME/logs"
mkdir -p "$LOG_DIR"

encode() {
  printf '%s' "$1" | sed \
    -e 's/%/%25/g' \
    -e 's/ /%20/g' \
    -e 's/\[/%5B/g' \
    -e 's/\]/%5D/g'
}

human_size() {
  local bytes=$1
  if [ "$bytes" -ge 1073741824 ]; then
    awk "BEGIN { printf \"%.2f GB\", $bytes/1073741824 }"
  else
    awk "BEGIN { printf \"%.2f MB\", $bytes/1048576 }"
  fi
}

read -p "Pesquisar anime: " QUERY

SEARCH_JSON=$(curl -s -b "$COOKIE_FILE" \
  "$BASE_URL/search?q=$(encode "$QUERY")")

NAMES=()
PATHS=()

while IFS= read -r v; do NAMES+=("$v"); done \
  < <(echo "$SEARCH_JSON" | jq -r '.results[].name')

while IFS= read -r v; do PATHS+=("$v"); done \
  < <(echo "$SEARCH_JSON" | jq -r '.results[].path')

if [ ${#NAMES[@]} -eq 0 ]; then
  echo "Nenhum resultado encontrado."
  exit 1
fi

echo
echo "Resultados encontrados:"
for i in "${!NAMES[@]}"; do
  TYPE="DESCONHECIDO"
  case "${PATHS[$i]}" in
    Animes/*) TYPE="ANIME" ;;
    Mangás/*) TYPE="MANGÁ" ;;
  esac
  printf "[%d] [%s] %s\n" $((i+1)) "$TYPE" "${NAMES[$i]}"
done

echo
read -p "Escolha uma opção: " CHOICE
TARGET_PATH="${PATHS[$((CHOICE-1))]}"
ENC_TARGET=$(encode "$TARGET_PATH")

FILES=()
SIZES=()

while IFS= read -r name && IFS= read -r size; do
  FILES+=("$name")
  SIZES+=("$size")
done < <(
  curl -s -b "$COOKIE_FILE" \
    "$BASE_URL/files?path=$ENC_TARGET" |
  jq -r '.files[]
    | select(.is_directory == false and .extension == ".mkv")
    | .name, .size'
)

if [ ${#FILES[@]} -eq 0 ]; then
  echo "Nenhum arquivo MKV encontrado."
  exit 1
fi

echo
echo "Arquivos disponíveis:"
for i in "${!FILES[@]}"; do
  printf "[%d] %s (%s)\n" \
    $((i+1)) "${FILES[$i]}" "$(human_size "${SIZES[$i]}")"
done

echo
read -p "Baixar (a) todos ou (s) selecionar? " MODE

SELECTED=()

if [ "$MODE" = "a" ]; then
  SELECTED=("${FILES[@]}")
else
  read -p "Digite os números: " NUMS
  for n in $NUMS; do
    SELECTED+=("${FILES[$((n-1))]}")
  done
fi

echo
read -p "Nome padrão do anime: " PADRAO
read -p "Temporada (número): " SEASON

RENAMED=()

if [ "$MODE" = "a" ] || [ "${#SELECTED[@]}" -gt 1 ]; then
  EP=1
  for f in "${SELECTED[@]}"; do
    EXT="${f##*.}"
    RENAMED+=(
      "$(printf "%s - S%02dE%02d.%s" "$PADRAO" "$SEASON" "$EP" "$EXT")"
    )
    ((EP++))
  done
else
  read -p "Número do episódio: " EP
  f="${SELECTED[0]}"
  EXT="${f##*.}"
  RENAMED+=(
    "$(printf "%s - S%02dE%02d.%s" "$PADRAO" "$SEASON" "$EP" "$EXT")"
  )
fi

echo
read -p "Diretório de download: " DOWNLOAD_DIR
DOWNLOAD_DIR="${DOWNLOAD_DIR/#\~/$HOME}"
mkdir -p "$DOWNLOAD_DIR"

JOB_SCRIPT="$LOG_DIR/job_$(date +%s).sh"
LOG_FILE="$LOG_DIR/download_$(date +%Y%m%d_%H%M%S).log"

echo
echo "Iniciando downloads em background"
echo "Log: $LOG_FILE"
echo

{
  echo '#!/usr/bin/env bash'
  echo "BASE_URL=\"$BASE_URL\""
  echo "COOKIE_FILE=\"$COOKIE_FILE\""
  echo
  declare -f encode
  echo

  for i in "${!SELECTED[@]}"; do
    SRC="${SELECTED[$i]}"
    DST="${RENAMED[$i]}"
    FULL="$TARGET_PATH/$SRC"
    echo "echo \"Baixando: $DST\""
    echo "curl -L -b \"$COOKIE_FILE\" -o \"$DOWNLOAD_DIR/$DST\" \"$BASE_URL/download?path=$(encode "$FULL")\""
    echo
  done

  echo 'echo "Downloads finalizados."'
} > "$JOB_SCRIPT"

chmod +x "$JOB_SCRIPT"

"$JOB_SCRIPT" > "$LOG_FILE" 2>&1 &

BG_PID=$!

echo "Downloads iniciados com sucesso."
echo "PID: $BG_PID"