#!/data/data/com.termux/files/usr/bin/bash

SRC="/mnt/media_rw/6B67-FA2F"
DST="/storage/emulated/0/hd"

mount() {
    echo "Ativando bind do HD..."

    # garante que o destino existe
    mkdir -p "$DST"

    # verifica se já está montado
    if sudo mount | grep -q "on $DST "; then
        echo "Bind já está ativo em $DST"
        exit 0
    fi

    sudo mount --bind $SRC $DST

    if sudo mount | grep -q "on $DST "; then
        echo "Bind ativo com sucesso: $DST"
    else
        echo "Falha ao montar bind"
        exit 1
    fi
}

umount() {
    echo "Desfazendo bind do HD..."

    if ! sudo mount | grep -q "on $DST "; then
        echo "Bind não está ativo"
        exit 0
    fi

    sudo umount $DST

    if sudo mount | grep -q "on $DST "; then
        echo "Falha ao desmontar"
        exit 1
    else
        echo "Bind removido com sucesso"
    fi
}

case "$1" in
    mount)
        mount
        ;;
    umount)
        umount
        ;;
    *)
        echo "Uso: $0 {mount|umount}"
        ;;
esac