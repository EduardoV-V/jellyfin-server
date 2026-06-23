#!/data/data/com.termux/files/usr/bin/bash

# =========================== LOCKFILE ================================
LOCKFILE="/data/data/com.termux/files/home/.compressor.lock"

if [ -f "$LOCKFILE" ]; then
    OLD_PID=$(cat "$LOCKFILE")

    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Script ja esta executando (PID $OLD_PID)"
        exit 1
    else
        echo "Lockfile antigo encontrado. Limpando..."
        rm -f "$LOCKFILE"
    fi
fi

echo $$ > "$LOCKFILE"

trap 'rm -f "$LOCKFILE"' EXIT
# =====================================================================

# =========================== CONFIGURACOES ===========================
BASE="/storage/emulated/0/Download/Animes"
TEMP_DIR="/data/data/com.termux/files/home/tempcompress"
CRF=24
PRESET="medium"
# =====================================================================

# =========================== LOG SETUP ===============================
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

START_TIME=$(date '+%Y-%m-%d %H:%M:%S')
TOTAL_CONVERTED=0
TOTAL_FAILED=0
TOTAL_DIRS=0
# =====================================================================

mkdir -p "$TEMP_DIR"

log "Inicio da compressao segura (pasta-a-pasta)"
log "Base: $BASE"
log "Temporario: $TEMP_DIR"
log "CRF: $CRF | Preset: $PRESET"
log "----------------------------------------------"

# Funcao: verifica se deve ignorar
should_ignore() {
    local path="$1"

    while true; do
        if [ -f "$path/ignore" ]; then
            return 0
        fi

        if [ "$path" = "$BASE" ]; then
            break
        fi

        path="$(dirname "$path")"
    done

    return 1
}

# Encontrar diretorios com .mkv
find "$BASE" -type f -iname "*.mkv" -print0 | while IFS= read -r -d '' FILE; do
    dirname "$FILE"
done | sort -u | while read -r DIR; do

    [ ! -d "$DIR" ] && continue

    if should_ignore "$DIR"; then
        log "Ignorando (flag .ignore encontrada): $DIR"
        continue
    fi

    LOG_FILE="$DIR/.processed_videos"
    touch "$LOG_FILE"

    VIDEOS=()
    while IFS= read -r -d '' file; do
        VIDEOS+=("$file")
    done < <(find "$DIR" -maxdepth 1 -type f -iname "*.mkv" -print0)

    UNPROCESSED=()
    for VIDEO in "${VIDEOS[@]}"; do
        BASENAME=$(basename "$VIDEO")
        if ! grep -Fxq "$BASENAME" "$LOG_FILE"; then
            UNPROCESSED+=("$VIDEO")
        fi
    done

    [ ${#UNPROCESSED[@]} -eq 0 ] && continue

    ((TOTAL_DIRS++))

    log ""
    log "Pasta: $DIR"
    log "Videos a processar: ${#UNPROCESSED[@]}"

    RELATIVE_PATH="${DIR#$BASE}"
    RELATIVE_PATH="${RELATIVE_PATH#/}"
    TEMP_SUBDIR="$TEMP_DIR/$RELATIVE_PATH"
    mkdir -p "$TEMP_SUBDIR"

    ALL_OK=true

    # Fase 1: compressao
    for VIDEO in "${UNPROCESSED[@]}"; do
        BASENAME=$(basename "$VIDEO")
        TEMP_FILE="$TEMP_SUBDIR/$BASENAME"

        log "Convertendo: $BASENAME -> TEMP"

        ffmpeg -y -i "$VIDEO" \
            -map 0 \
            -c copy \
            -c:v libx265 -crf "$CRF" -preset "$PRESET" \
            "$TEMP_FILE" </dev/null

        if [ $? -ne 0 ] || [ ! -f "$TEMP_FILE" ]; then
            log "FALHA na conversao: $BASENAME"
            rm -f "$TEMP_FILE"
            ALL_OK=false
            ((TOTAL_FAILED++))
            break
        else
            log "Sucesso na compressao: $BASENAME"
            ((TOTAL_CONVERTED++))
        fi
    done

    # Fase 2: substituir
    if $ALL_OK; then
        log "Substituindo arquivos originais..."

        for VIDEO in "${UNPROCESSED[@]}"; do
            BASENAME=$(basename "$VIDEO")
            TEMP_FILE="$TEMP_SUBDIR/$BASENAME"

            mv -f "$TEMP_FILE" "$VIDEO"

            if [ $? -eq 0 ] && [ -f "$VIDEO" ] && [ ! -f "$TEMP_FILE" ]; then
                echo "$BASENAME" >> "$LOG_FILE"
                log "Substituido: $BASENAME"
            else
                log "Erro ao mover: $BASENAME"
                ALL_OK=false
                ((TOTAL_FAILED++))
            fi
        done

        rmdir --ignore-fail-on-non-empty "$TEMP_SUBDIR" 2>/dev/null

        if $ALL_OK; then
            log "Pasta concluida com sucesso"
        else
            log "Pasta concluida com erros"
        fi
    else
        log "Pasta ignorada devido a erro"
    fi

    log "----------------------------------------------"

done

# Limpeza final
find "$TEMP_DIR" -type d -empty -delete 2>/dev/null

END_TIME=$(date '+%Y-%m-%d %H:%M:%S')

log ""
log "=============================================="
log "Resumo da execucao"
log "Inicio: $START_TIME"
log "Fim:    $END_TIME"
log "Pastas processadas: $TOTAL_DIRS"
log "Arquivos convertidos: $TOTAL_CONVERTED"
log "Falhas: $TOTAL_FAILED"
log "=============================================="
