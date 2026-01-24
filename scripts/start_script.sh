LOG="$HOME/boot.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG"
}

log "Boot iniciado"

termux-wake-lock

sshd

sleep 5

mount_hd mount

sleep 5

jellyfin

#sleep 120

#log "Iniciando watchdog do HD"
#sudo watchdog_hd &

#sleep 5

#log "Iniciando watchdog da bateria"
#sudo watchdog_bateria &

#log "Boot finalizado"