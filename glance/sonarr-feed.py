from flask import Flask, Response
import requests
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

SONARR_URL = "http://127.0.0.1:8989"
SONARR_API = "2f5c60a16faa446c8888fd6dabcc2365"

# Jellyfin 12+ removeu os métodos legados de autenticação
# (header X-Emby-Token e query param ?api_key=). Agora é preciso usar
# o header Authorization no formato MediaBrowser, ou o query param
# ApiKey (com A e K maiúsculos) quando não é possível enviar header,
# como no caso das imagens carregadas via <img src="...">.

# Cada servidor tem uma lista de "root_paths": prefixos do campo
# "path" da série no Sonarr que indicam que aquela série (e portanto
# seus episódios) vive fisicamente nesse servidor.
JELLYFIN_SERVERS = [
    {
        "key": "server1",
        "internal": "http://127.0.0.1:8096",
        "public": "http://jellyfin.home",
        "api_key": "746affae5a3646a18bb45c970cef4fa2",
        "root_paths": [
            "/data/data/com.termux/files/home/storage/downloads/Animes",
            "/mnt/media/Download/Animes",
	    "/mnt/media_rw/6BF1-F2CE/Animes",
        ],
    },
]

CALENDAR_DAYS_BACK = 30
MAX_ITEMS = 15
CACHE_TTL_SECONDS = 15 * 60  # recarrega o mapa de séries a cada 15 minutos

DEBUG = True  # coloque False depois de resolver o problema


def dbg(*args):
    if DEBUG:
        print("[DEBUG]", *args)

# Caches por servidor
_jellyfin_server_id_cache = {}   # server_key -> Id
_series_map_cache = {}           # server_key -> {"data": {tvdbId: jellyfin_series_id}, "ts": epoch_seconds}


def auth_header(server: dict) -> dict:
    return {"Authorization": f'MediaBrowser Token="{server["api_key"]}"'}


def pick_server(series_path: str) -> dict:
    """Decide em qual servidor a série está, com base no path retornado pelo Sonarr."""
    if series_path:
        for server in JELLYFIN_SERVERS:
            for root in server["root_paths"]:
                if series_path.startswith(root):
                    dbg(f"path='{series_path}' -> {server['key']} (bateu com root '{root}')")
                    return server
    # fallback: se não bater com nenhum root_path conhecido, usa o primeiro servidor
    dbg(f"path='{series_path}' -> NENHUM root_path bateu, usando fallback {JELLYFIN_SERVERS[0]['key']}")
    return JELLYFIN_SERVERS[0]


def get_server_id(server: dict) -> str:
    key = server["key"]
    if key in _jellyfin_server_id_cache:
        return _jellyfin_server_id_cache[key]
    try:
        r = requests.get(
            f"{server['internal']}/System/Info/Public",
            timeout=5,
        )
        if r.status_code == 200:
            _jellyfin_server_id_cache[key] = r.json().get("Id", "")
    except Exception:
        pass
    return _jellyfin_server_id_cache.get(key, "")


def get_series_map(server: dict) -> dict:
    """Busca TODAS as séries do Jellyfin (de um servidor) e monta tvdbId → jellyfin_id.
    Recarrega automaticamente a cada CACHE_TTL_SECONDS, para pegar séries/episódios
    novos que o Jellyfin escaneou depois que o script já estava rodando."""
    key = server["key"]
    now = datetime.now(timezone.utc).timestamp()

    cached = _series_map_cache.get(key)
    if cached is not None and (now - cached["ts"]) < CACHE_TTL_SECONDS:
        return cached["data"]

    series_map = {}
    try:
        r = requests.get(
            f"{server['internal']}/Items",
            params={
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "Fields": "ProviderIds",
            },
            headers=auth_header(server),
            timeout=10,
        )
        if r.status_code == 200:
            total_items = len(r.json().get("Items", []))
            for item in r.json().get("Items", []):
                tvdb = item.get("ProviderIds", {}).get("Tvdb")
                if tvdb:
                    series_map[str(tvdb)] = item["Id"]
            dbg(f"get_series_map({key}): {total_items} séries retornadas, "
                f"{len(series_map)} com Tvdb preenchido (cache recarregado)")
        else:
            dbg(f"get_series_map({key}): HTTP {r.status_code} em {server['internal']}/Items "
                f"(provável API key errada ou sem permissão)")
            if cached is not None:
                # falhou a atualização: mantém o cache antigo em vez de zerar tudo
                dbg(f"get_series_map({key}): mantendo cache anterior (falha ao atualizar)")
                return cached["data"]
    except Exception as e:
        dbg(f"get_series_map({key}): FALHA DE CONEXÃO com {server['internal']} -> {e}")
        print(f"series_map error ({key}):", e)
        if cached is not None:
            dbg(f"get_series_map({key}): mantendo cache anterior (falha ao atualizar)")
            return cached["data"]

    _series_map_cache[key] = {"data": series_map, "ts": now}
    return series_map


def find_jellyfin_episode(server: dict, tvdb_id: int, season: int, episode: int):
    """Retorna (item_id, server_id) do episódio no Jellyfin (servidor específico), ou (None, None)."""
    series_map = get_series_map(server)
    series_id = series_map.get(str(tvdb_id))
    if not series_id:
        dbg(f"find_episode({server['key']}): tvdbId={tvdb_id} NÃO está no series_map "
            f"({len(series_map)} séries no cache) -> série não existe nesse Jellyfin "
            f"ou não tem Tvdb id preenchido")
        return None, None

    try:
        r = requests.get(
            f"{server['internal']}/Shows/{series_id}/Episodes",
            params={
                "SeasonNumber": season,
                "Fields": "Id,ServerId,IndexNumber",
            },
            headers=auth_header(server),
            timeout=10,
        )
        if r.status_code != 200:
            dbg(f"find_episode({server['key']}): HTTP {r.status_code} ao buscar episódios "
                f"da série {series_id}")
            return None, None

        for ep in r.json().get("Items", []):
            if ep.get("IndexNumber") == episode:
                dbg(f"find_episode({server['key']}): achou S{season:02d}E{episode:02d} "
                    f"(item_id={ep['Id']})")
                return ep["Id"], ep.get("ServerId")

        dbg(f"find_episode({server['key']}): série encontrada mas S{season:02d}E{episode:02d} "
            f"não está na lista de episódios (talvez ainda não escaneado no Jellyfin)")

    except Exception as e:
        dbg(f"find_episode({server['key']}): FALHA DE CONEXÃO -> {e}")
        print(f"find_episode error ({server['key']}):", e)

    return None, None


def get_recent():
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=CALENDAR_DAYS_BACK)).strftime("%Y-%m-%d")
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        r = requests.get(
            f"{SONARR_URL}/api/v3/calendar",
            params={
                "apikey": SONARR_API,
                "start": start,
                "end": end,
                "includeSeries": "true",
                "unmonitored": "false",
            },
            timeout=5,
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    # Pré-carrega o mapa de séries de todos os servidores de uma vez
    for server in JELLYFIN_SERVERS:
        get_series_map(server)

    recent = []

    for ep in data:
        air_date = ep.get("airDateUtc")
        if not air_date:
            continue
        try:
            air = datetime.fromisoformat(air_date.replace("Z", "+00:00"))
        except Exception:
            continue
        if air >= now and not ep.get("hasFile", False):
            continue

        series = ep.get("series", {})
        season = ep.get("seasonNumber", 0)
        episode_num = ep.get("episodeNumber", 0)
        series_path = series.get("path", "")

        server = pick_server(series_path)
        sid = get_server_id(server)

        item_id, item_server_id = find_jellyfin_episode(
            server, series.get("tvdbId"), season, episode_num
        )

        if item_id:
            server_id_used = item_server_id or sid
            jellyfin_link = (
                f"{server['public']}/web/#/details"
                f"?id={item_id}&context=tvshows&serverId={server_id_used}"
            )
            # Imagem diretamente do Jellyfin (sem proxy) usando o endereço público do servidor.
            # O browser do cliente não envia headers customizados numa tag <img>,
            # então usamos o query param moderno "ApiKey" (não confundir com o
            # antigo "api_key", que o Jellyfin 12+ não aceita mais).
            thumb_url = (
                f"{server['public']}/Items/{item_id}/Images/Primary"
                f"?ApiKey={server['api_key']}&fillWidth=300&quality=90"
            )
        else:
            jellyfin_link = server["public"]
            thumb_url = ""

        recent.append({
            "title": series.get("title", "Unknown"),
            "episode_title": ep.get("title", ""),
            "season": season,
            "episode": episode_num,
            "label": f"S{season:02d}E{episode_num:02d}",
            "thumb": thumb_url,
            "unix_ts": int(air.timestamp()),
            "has_file": ep.get("hasFile", False),
            "link": jellyfin_link,
        })

    recent.sort(key=lambda x: x["unix_ts"], reverse=True)
    return recent[:MAX_ITEMS]


# Dimensões base × 1.15
CARD_W = 201   # 175 × 1.15
THUMB_H = 113  # 98  × 1.15


def build_html(episodes):
    if not episodes:
        return '<p class="color-subdue">Nenhum episódio recente encontrado.</p>'

    items = []
    for ep in episodes:
        if ep["thumb"]:
            thumb_inner = (
                f'<img src="{ep["thumb"]}" alt="" loading="lazy" '
                f'style="width:100%;height:100%;object-fit:cover;display:block;">'
            )
        else:
            thumb_inner = (
                '<div style="width:100%;height:100%;'
                'background:var(--color-widget-background-alt);'
                'display:flex;align-items:center;justify-content:center;">'
                '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" '
                'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
                'style="opacity:0.25;">'
                '<rect x="2" y="2" width="20" height="20" rx="2.5"/>'
                '<polygon points="10,8 16,12 10,16"/>'
                '</svg>'
                '</div>'
            )

        badge = ""
        if ep["has_file"]:
            badge = (
                '<span style="position:absolute;bottom:6px;left:6px;'
                'font-size:0.67rem;padding:2px 7px;border-radius:4px;'
                'background:rgba(0,0,0,0.72);backdrop-filter:blur(4px);'
                'color:var(--color-positive,#6dffb0);font-weight:700;'
                'letter-spacing:0.04em;white-space:nowrap;">▶ DISPONÍVEL</span>'
            )

        display_title = ep["episode_title"] if ep["episode_title"] else ep["label"]

        items.append(
            f'<li style="flex:0 0 auto;width:{CARD_W}px;">'
            f'<a href="{ep["link"]}" target="_blank" rel="noopener" '
            f'style="display:flex;flex-direction:column;gap:8px;text-decoration:none;color:inherit;">'

            # Thumbnail 16:9
            f'<div style="position:relative;width:{CARD_W}px;height:{THUMB_H}px;'
            f'border-radius:7px;overflow:hidden;'
            f'background:var(--color-widget-background-alt,#1e1e1e);">'
            f'{thumb_inner}'
            f'{badge}'
            f'<span style="position:absolute;bottom:6px;right:7px;font-size:0.7rem;'
            f'padding:2px 6px;border-radius:4px;background:rgba(0,0,0,0.72);'
            f'backdrop-filter:blur(4px);color:#fff;font-weight:600;letter-spacing:0.02em;">'
            f'{ep["label"]}</span>'
            f'</div>'

            # Texto
            f'<div style="display:flex;flex-direction:column;gap:3px;padding:0 2px;">'
            f'<p class="size-h4" style="margin:0;line-height:1.3;overflow:hidden;'
            f'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;font-weight:500;">'
            f'{display_title}</p>'
            f'<p class="size-h6 color-subdue" style="margin:0;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;">{ep["title"]}</p>'
            f'<p class="size-h6 color-subdue" style="margin:0;">'
            f'<span data-dynamic-relative-time="{ep["unix_ts"]}"></span></p>'
            f'</div>'

            f'</a></li>'
        )

    return (
        '<ul style="display:flex;flex-direction:row;gap:18px;overflow-x:auto;'
        'padding:2px 0 10px 0;margin:0;list-style:none;scrollbar-width:thin;'
        'scrollbar-color:var(--color-widget-background-alt) transparent;">\n'
        + "\n".join(items)
        + '\n</ul>'
    )


@app.route("/")
def home():
    episodes = get_recent()
    html_body = build_html(episodes)
    resp = Response(html_body, mimetype="text/html")
    resp.headers["Widget-Title"] = "Episódios Recentes"
    resp.headers["Widget-Content-Type"] = "html"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
