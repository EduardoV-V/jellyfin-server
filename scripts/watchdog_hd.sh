#!/data/data/com.termux/files/usr/bin/bash

SRC="/mnt/media_rw/6B67-FA2F"
DST="/storage/emulated/0/hd"
LOG="$HOME/hd_watchdog.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG"
}

is_mounted() {
    mount | grep -q "on $DST "
}

io_ok() {
    ls "$DST" >/dev/null 2>&1
}

mount_bind() {
    mkdir -p "$DST"
    sudo mount --rbind "$SRC" "$DST"
    sudo mount --make-slave "$DST"
}

remount_bind() {
    log "I/O error detectado, remontando..."
    sudo umount -l "$DST" 2>/dev/null
    sleep 2
    mount_bind
    log "Remontagem concluída"
}

log "Watchdog iniciado"

while true; do
    if is_mounted; then
        if ! io_ok; then
            remount_bind
        fi
    else
        log "Bind não ativo, montando..."
        mount_bind
    fi
    sleep 150
done