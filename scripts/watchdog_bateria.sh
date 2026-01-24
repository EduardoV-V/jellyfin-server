#!/data/data/com.termux/files/usr/bin/bash

[ "$(id -u)" -eq 0 ] || exit 1

LOG="/data/local/tmp/battery_watchdog.log"
PIDFILE="/data/data/com.termux/files/home/jellyfin/jellyfin.pid"

BATTERY_CAP="/sys/class/power_supply/battery/capacity"
CHARGE_CTRL="/sys/class/power_supply/battery/charging_enabled"

MAX_CHARGE=90
MIN_CHARGE=20

log() {
    echo "$(date '+%F %T') - $1" >> "$LOG"
}

jellyfin_running() {
    [ -f "$PIDFILE" ] || return 1
    PID=$(cat "$PIDFILE" 2>/dev/null)
    [ -n "$PID" ] && ps -p "$PID" >/dev/null 2>&1
}

enable_charging() {
    echo 1 | tee "$CHARGE_CTRL" > /dev/null
}

disable_charging() {
    echo 0 | tee "$CHARGE_CTRL" > /dev/null
}

log "Battery watchdog iniciado"

LIMIT_MODE=0   # 0 = carregamento normal | 1 = carregamento bloqueado (>=90)

while true; do
    CAP=$(cat "$BATTERY_CAP")
    CHG=$(cat "$CHARGE_CTRL")

    if jellyfin_running; then
        # Jellyfin ativo > aplica política de bateria

        if [ "$LIMIT_MODE" -eq 0 ] && [ "$CAP" -ge "$MAX_CHARGE" ]; then
            disable_charging
            LIMIT_MODE=1
            log "Bateria ${CAP}% > carregamento DESATIVADO (Jellyfin ativo)"
        fi

        if [ "$LIMIT_MODE" -eq 1 ] && [ "$CAP" -le "$MIN_CHARGE" ]; then
            enable_charging
            LIMIT_MODE=0
            log "Bateria ${CAP}% > carregamento REATIVADO (nível crítico)"
        fi

    else
        # Jellyfin parado > garante estado normal
        if [ "$LIMIT_MODE" -eq 1 ]; then
            enable_charging
            sleep 1
            CHG_NOW=$(cat "$CHARGE_CTRL")

            if [ "$CHG_NOW" -eq 1 ]; then
                LIMIT_MODE=0
                log "Jellyfin parado > carregamento de volta ao normal"
            else
                log "ERRO> TENTATIVA DE RESTAURAR CARREGAMENTO FALHOU"
            fi
        fi
    fi

    sleep 60
done