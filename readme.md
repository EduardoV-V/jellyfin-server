Esse repositório contém todos os arquivos e scripts usados no meu servidor. Apenas para catalogação e backup.

- mount_hd.sh || /data/data/com.termux/files/usr/bin/mount_hd <br>
script que faz bind do hd externo na pasta storage do android, serve pra permitir que o temux acesse o hd sem dar su

- pd_jellyfin.sh || /opt/jellyfin/jellyfin.sh [DENTRO DO PROOT-DISTRO] <br>
script que faz o levantamento do jellyfin dentro do proot distro

- start_script.sh || ~/.termux/boot/start-services.sh <br>
script que inicia junto com o celular e levanta todos os scripts na ordem pro server ligar junto com o boot

- termux_jellyfin.sh || /data/data/com.termux/files/usr/bin/jellyfin <br>
script que executa o jellyfin e coloca o celular em modo desempenho para rodar o jellyfin o melhor possível

- watchdog_bateria.sh || /data/data/com.termux/files/usr/bin/watchdog_bateria <br>
script que verifica a bateria, carregando apenas quando o celular chega a 20% e parando aos 90%. funciona só quando o jellyfin funciona <br>
NAO FUNCIONA AINDA

- watchdog_hd.sh || /data/data/com.termux/files/usr/bin/watchdog_hd <br>
similar ao anterior, verifica se o hd entrou em modo sleep e ativa ele de volta para manter acesso completo <br>
NAO FUNCIONA AINDA