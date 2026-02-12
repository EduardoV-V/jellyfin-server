#!/bin/bash

BASE_URL="https://nuvem.anitsu.moe/api"
COOKIE_FILE="$(pwd)/cookies.txt"

LOG_DIR="$(pwd)/logs"
mkdir -p "$LOG_DIR"

RED="\e[91m"
CYAN="\e[96m"
GRAY="\e[90m"
RESET="\e[0m"

encode() {
  jq -rn --arg v "$1" '$v|@uri'
}

human_size() {
  local bytes=$1
  if [ "$bytes" -ge 1073741824 ]; then
    awk "BEGIN { printf \"%.2f GB\", $bytes/1073741824 }"
  else
    awk "BEGIN { printf \"%.2f MB\", $bytes/1048576 }"
  fi
}

# Função para extrair todos os cookies no formato correto
get_cookie_header() {
    if [ -f "$COOKIE_FILE" ]; then
        # Extrair todos os cookies válidos do arquivo Netscape
        grep -v '^#' "$COOKIE_FILE" | grep -v '^$' | awk '{print $6 "=" $7}' | tr '\n' '; ' | sed 's/; $//'
    else
        echo ""
    fi
}

check_aria2() {
  if ! command -v aria2c &> /dev/null; then
    echo "Instalando aria2 para downloads mais rápidos..."
    sudo apt update && sudo apt install aria2 -y
  fi
}

read -p "Pesquisar: " QUERY

SEARCH_JSON=$(curl -s -b "$COOKIE_FILE" \
  "$BASE_URL/search?q=$(encode "$QUERY")")

NAMES=()
PATHS=()

mapfile -t NAMES < <(echo "$SEARCH_JSON" | jq -r '.results[].name')
mapfile -t PATHS < <(echo "$SEARCH_JSON" | jq -r '.results[].path')

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
INITIAL_PATH="${PATHS[$((CHOICE-1))]}"

FILES=()
SIZES=()

browse_files() {
  ROOT_PATH="$1"
  CURRENT_PATH="$1"
  local return_to_download=false

  while true; do
    clear

    RESPONSE=$(curl -s -b "$COOKIE_FILE" \
      "$BASE_URL/files?path=$(encode "$CURRENT_PATH")")

    PARENT_PATH=$(echo "$RESPONSE" | jq -r '.parent // empty')

    echo -e "${RED}Diretório remoto:${RESET} ${CYAN}$CURRENT_PATH${RESET}"
    
    MKV_COUNT=$(echo "$RESPONSE" | jq '[.files[] | select(.is_directory == false and (.extension == "mkv" or .extension == ".mkv"))] | length')
    
    if [ "$MKV_COUNT" -gt 0 ]; then
      echo -e "${RED}Comandos:${RESET} [b] voltar | [r] início | [d] baixar MKVs | [q] sair"
    else
      echo -e "${RED}Comandos:${RESET} [b] voltar | [r] início | [q] sair"
    fi
    
    echo "----------------------------------------"

    mapfile -t NAMES < <(echo "$RESPONSE" | jq -r '.files[].name')
    mapfile -t IS_DIR < <(echo "$RESPONSE" | jq -r '.files[].is_directory')
    mapfile -t EXT < <(echo "$RESPONSE" | jq -r '.files[].extension // empty')
    mapfile -t SIZE < <(echo "$RESPONSE" | jq -r '.files[].size')

    for i in "${!NAMES[@]}"; do
      if [ "${IS_DIR[$i]}" = "true" ]; then
        printf "[%d] ${CYAN}%s/${RESET}\n" $((i+1)) "${NAMES[$i]}"
      else
        if [ "${EXT[$i]}" = "mkv" ] || [ "${EXT[$i]}" = ".mkv" ]; then
          printf "[%d] ${RED}%s${RESET} ${GRAY}(%s)${RESET}\n" \
            $((i+1)) "${NAMES[$i]}" "$(human_size "${SIZE[$i]}")"
        else
          printf "[%d] %s ${GRAY}(%s)${RESET}\n" \
            $((i+1)) "${NAMES[$i]}" "$(human_size "${SIZE[$i]}")"
        fi
      fi
    done

    echo
    read -rp "Escolha: " CHOICE

    case "$CHOICE" in
      q) return ;;

      r)
        CURRENT_PATH="$ROOT_PATH"
        ;;

      d)
        if [ "$MKV_COUNT" -gt 0 ]; then
          TARGET_PATH="$CURRENT_PATH"
          return_to_download=true
          return
        fi
        ;;

      b)
        if [ -n "$PARENT_PATH" ]; then
          CURRENT_PATH="$PARENT_PATH"
        fi
        ;;

      ''|*[!0-9]*) continue ;;

      *)
        IDX=$((CHOICE-1))
        [ -z "${NAMES[$IDX]}" ] && continue

        if [ "${IS_DIR[$IDX]}" = "true" ]; then
          CURRENT_PATH="$CURRENT_PATH/${NAMES[$IDX]}"
        else
          FULL_PATH="$CURRENT_PATH/${NAMES[$IDX]}"
          FILES+=("$FULL_PATH")
          SIZES+=("${SIZE[$IDX]}")

          echo
          echo -e "${RED}Adicionado:${RESET} ${NAMES[$IDX]}"
          sleep 1
        fi
        ;;
    esac
  done
}

browse_files "$INITIAL_PATH"

if [ ${#FILES[@]} -eq 0 ]; then
  while IFS= read -r name && IFS= read -r size; do
    FILES+=("$TARGET_PATH/$name")
    SIZES+=("$size")
  done < <( curl -s -b "$COOKIE_FILE" \
    "$BASE_URL/files?path=$(encode "$TARGET_PATH")" \
    | jq -r '.files[] | select(.is_directory == false and (.extension == "mkv" or .extension == ".mkv")) | .name, .size' )
fi

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
  1) BASE_DIR="/mnt/e/Animes"; IS_ANIME=true ;;
  2) BASE_DIR="/mnt/e/Filmes" ;;
  3)
    read -e -p "Diretório base: " BASE_DIR
    BASE_DIR="${BASE_DIR/#\~/$HOME}"
    ;;
  *) echo "Opção inválida."; exit 1 ;;
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
    RENAMED+=( "$(printf "%s - S%02dE%02d.%s" "$PADRAO" "$SEASON" "$EP" "$EXT")" )
    ((EP++))
  done
else
  EXT="${SELECTED[0]##*.}"
  RENAMED+=("$PADRAO.$EXT")
fi

check_aria2
COOKIE_HEADER=$(get_cookie_header)

if [ -z "$COOKIE_HEADER" ]; then
    echo "ERRO: Não foi possível extrair cookie"
    exit 1
fi

JOB_SCRIPT="$LOG_DIR/job_$(date +%s).sh"
LOG_FILE="$LOG_DIR/download_$(date +%Y%m%d_%H%M%S).log"
ARIA2_SESSION="$LOG_DIR/aria2_session_$(date +%s).txt"

{
  echo '#!/usr/bin/env bash'
  echo "BASE_URL=\"$BASE_URL\""
  echo "COOKIE_FILE=\"$COOKIE_FILE\""
  echo "FINAL_DIR=\"$FINAL_DIR\""
  echo "COOKIE_HEADER=\"$COOKIE_HEADER\""
  echo "ARIA2_SESSION=\"$ARIA2_SESSION\""
  declare -f encode human_size
  
  echo 'echo "Iniciando downloads com aria2..."'
  echo 'echo "Data: $(date)"'
  echo 'echo "=========================================="'
  
  echo 'if command -v aria2c &> /dev/null; then'
  echo '  echo "Configurando aria2 para downloads paralelos..."'
  
  # Criar arquivo de input para aria2 (todos os downloads de uma vez)
  echo '  INPUT_FILE="'"$LOG_DIR"'/aria2_input_$(date +%s).txt"'
  
  # Preparar URLs para download paralelo
  echo '  echo "# Arquivos para download" > "$INPUT_FILE"'
  for i in "${!SELECTED[@]}"; do
    SRC="${SELECTED[$i]}"
    DST="${RENAMED[$i]}"
    URL="$BASE_URL/download?path=$(encode "$SRC")"
    echo "  echo \"$URL\" >> \"\$INPUT_FILE\""
    echo "  echo \"  dir=\$FINAL_DIR\" >> \"\$INPUT_FILE\""
    echo "  echo \"  out=$DST\" >> \"\$INPUT_FILE\""
  done
  
  echo '  echo "Iniciando download de ${#SELECTED[@]} arquivos em paralelo..."'
  
  # Comando aria2 otimizado
  echo '  aria2c --input-file="$INPUT_FILE" \'
  echo '    --header="Cookie: $COOKIE_HEADER" \'
  echo '    --header="User-Agent: Mozilla/5.0" \'
  echo '    --header="Referer: https://nuvem.anitsu.moe" \'
  echo '    --check-certificate=false \'
  echo '    --max-tries=5 \'
  echo '    --retry-wait=3 \'
  echo '    --timeout=60 \'
  echo '    --connect-timeout=30 \'
  echo '    --max-connection-per-server=16 \'
  echo '    --min-split-size=2M \'
  echo '    --split=16 \'
  echo '    --max-concurrent-downloads=5 \'
  echo '    --file-allocation=prealloc \'
  echo '    --continue=true \'
  echo '    --save-session="$ARIA2_SESSION" \'
  echo '    --auto-save-interval=10 \'
  echo '    --console-log-level=notice \'
  echo '    --summary-interval=30'
  
  echo '  rm -f "$INPUT_FILE"'
  echo 'else'
  echo '  echo "Aria2 não encontrado, usando curl..."'
  echo '  for i in "${!SELECTED[@]}"; do'
  echo '    SRC="${SELECTED[$i]}"'
  echo '    DST="${RENAMED[$i]}"'
  echo '    echo "Baixando: $DST"'
  echo '    curl -L -b "$COOKIE_FILE" \'
  echo '      --connect-timeout 60 \'
  echo '      --max-time 3600 \'
  echo '      --retry 5 \'
  echo '      --retry-delay 2 \'
  echo '      --retry-max-time 7200 \'
  echo '      --progress-bar \'
  echo '      -o "$FINAL_DIR/$DST" \'
  echo '      "$BASE_URL/download?path=$(encode "$SRC")"'
  echo '    echo "------------------------------------------"'
  echo '  done'
  echo 'fi'
  
  echo 'echo "=========================================="'
  echo 'echo "Downloads finalizados em: $(date)"'
  echo 'echo "Total de arquivos baixados: '${#SELECTED[@]}'"'
  echo 'echo "Destino: $FINAL_DIR"'
} > "$JOB_SCRIPT"

chmod +x "$JOB_SCRIPT"

echo
echo "Iniciando downloads com aria2..."
echo "Para monitorar: tail -f $LOG_FILE"

"$JOB_SCRIPT" > "$LOG_FILE" 2>&1 &
DOWNLOAD_PID=$!
echo "PID: $DOWNLOAD_PID"