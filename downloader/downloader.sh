#!/bin/bash

BASE_URL="https://nuvem.anitsu.moe/api"
COOKIE_FILE="$(pwd)/cookies.txt"

LOG_DIR="$(pwd)/logs"
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

read -p "Pesquisar: " QUERY

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
read -p "Nome padrão: " PADRAO

echo
echo "[1] Animes"
echo "[2] Filmes"
echo "[3] Digitar caminho manual"
read -p "Destino: " DEST

BASE_DIR=""
IS_ANIME=false

case "$DEST" in
  1)
    BASE_DIR="/mnt/e/Animes"
    IS_ANIME=true
    ;;
  2)
    BASE_DIR="/mnt/e/Filmes"
    ;;
  3)
    read -e -p "Diretório base: " BASE_DIR
    BASE_DIR="${BASE_DIR/#\~/$HOME}"
    ;;
  *)
    echo "Opção inválida."
    exit 1
    ;;
esac

SEASON=""
if $IS_ANIME; then
  read -p "Temporada: " SEASON
  FINAL_DIR="$BASE_DIR/$PADRAO/Season $SEASON"
else
  FINAL_DIR="$BASE_DIR/$PADRAO"
fi

mkdir -p "$FINAL_DIR"

if [ ! -w "$FINAL_DIR" ]; then
  echo "Erro: diretório não gravável."
  exit 1
fi

RENAMED=()

if $IS_ANIME; then
  EP=1
  for f in "${SELECTED[@]}"; do
    EXT="${f##*.}"
    RENAMED+=(
      "$(printf "%s - S%02dE%02d.%s" "$PADRAO" "$SEASON" "$EP" "$EXT")"
    )
    ((EP++))
  done
else
  EXT="${SELECTED[0]##*.}"
  RENAMED+=("$PADRAO.$EXT")
fi

JOB_SCRIPT="$LOG_DIR/job_$(date +%s).sh"
LOG_FILE="$LOG_DIR/download_$(date +%Y%m%d_%H%M%S).log"

{
  echo '#!/usr/bin/env bash'
  echo "BASE_URL=\"$BASE_URL\""
  echo "COOKIE_FILE=\"$COOKIE_FILE\""
  declare -f encode

  for i in "${!SELECTED[@]}"; do
    SRC="${SELECTED[$i]}"
    DST="${RENAMED[$i]}"
    FULL="$TARGET_PATH/$SRC"
    echo "echo \"Baixando: $DST\""
    echo "curl -L -b \"$COOKIE_FILE\" -o \"$FINAL_DIR/$DST\" \"$BASE_URL/download?path=$(encode "$FULL")\""
  done

  echo 'echo "Downloads finalizados."'
} > "$JOB_SCRIPT"

chmod +x "$JOB_SCRIPT"

"$JOB_SCRIPT" > "$LOG_FILE" 2>&1 &

echo
echo "Downloads iniciados."
echo "Destino: $FINAL_DIR"

