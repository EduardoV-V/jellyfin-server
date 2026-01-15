#!/data/data/com.termux/files/usr/bin/bash

# ===== CONFIGURAÇÕES =====
DISTRO="ubuntu"
BIND_STORAGE="/sdcard:/storage"
HD_MOUNT="/mnt/media_rw/6B67-FA2F:/mnt/hd_externo"
JELLYFIN_SCRIPT="/opt/jellyfin/jellyfin.sh"
LOG_FILE="$HOME/jellyfin.log"

# Governor padrão do sistema (normalmente schedutil)
DEFAULT_GOVERNOR="schedutil"

# ===== VERIFICAÇÕES =====
if ! command -v proot-distro >/dev/null 2>&1; then
    echo "proot-distro não encontrado"
    exit 1
fi

if ! command -v termux-wake-lock >/dev/null 2>&1; then
    echo "termux-api não instalado"
    exit 1
fi

# ===== FUNÇÕES =====
set_performance_mode() {
    echo "Ativando modo desempenho..."

    termux-wake-lock

    su -c '
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo performance > "$cpu" 2>/dev/null
    done
    '
}

restore_normal_mode() {
    echo "Restaurando modo normal..."

    su -c '
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo "$DEFAULT_GOVERNOR" > "$cpu" 2>/dev/null
    done
    '

    termux-wake-unlock
}

start() {
    set_performance_mode

    echo "Iniciando Jellyfin em background..."
    nohup proot-distro login "$DISTRO" \
        --bind "$BIND_STORAGE" \
        --bind "$HD_MOUNT" \
        -- bash -lc "
            export DOTNET_GCHeapHardLimit=40000000
            export DOTNET_EnableDiagnostics=0
            cd /opt/jellyfin
            exec $JELLYFIN_SCRIPT
        " >"$LOG_FILE" 2>&1 &

    echo "Jellyfin iniciado! Logs em $LOG_FILE"
}

stop() {
    echo "Parando Jellyfin..."
    proot-distro login "$DISTRO" -- bash -c "pkill -f jellyfin"

    sleep 2

    restore_normal_mode

    echo "Jellyfin parado!"
}

# ===== CONTROLE =====
if [ "$1" = "stop" ]; then
    stop
else
    start
fi