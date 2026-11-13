
from flask import Flask, Response
from html import escape
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
_jellyfin_server_id_cache = {}
_series_map_cache = {}


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
    """Busca TODAS as séries do Jellyfin e monta tvdbId → jellyfin_id."""
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

            dbg(
                f"get_series_map({key}): {total_items} séries retornadas, "
                f"{len(series_map)} com Tvdb preenchido (cache recarregado)"
            )

        else:
            dbg(
                f"get_series_map({key}): HTTP {r.status_code} em "
                f"{server['internal']}/Items (provável API key errada ou sem permissão)"
            )

            if cached is not None:
                dbg(f"get_series_map({key}): mantendo cache anterior")
                return cached["data"]

    except Exception as e:
        dbg(f"get_series_map({key}): FALHA DE CONEXÃO -> {e}")
        print(f"series_map error ({key}):", e)

        if cached is not None:
            dbg(f"get_series_map({key}): mantendo cache anterior")
            return cached["data"]

    _series_map_cache[key] = {"data": series_map, "ts": now}
    return series_map


def find_jellyfin_episode(server: dict, tvdb_id: int, season: int, episode: int):
    """Retorna (item_id, server_id) do episódio no Jellyfin, ou (None, None)."""
    series_map = get_series_map(server)
    series_id = series_map.get(str(tvdb_id))

    if not series_id:
        dbg(
            f"find_episode({server['key']}): tvdbId={tvdb_id} NÃO está no series_map "
            f"({len(series_map)} séries no cache)"
        )
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
            dbg(
                f"find_episode({server['key']}): HTTP {r.status_code} "
                f"ao buscar episódios da série {series_id}"
            )
            return None, None

        for ep in r.json().get("Items", []):
            if ep.get("IndexNumber") == episode:
                dbg(
                    f"find_episode({server['key']}): achou "
                    f"S{season:02d}E{episode:02d} (item_id={ep['Id']})"
                )
                return ep["Id"], ep.get("ServerId")

        dbg(
            f"find_episode({server['key']}): série encontrada, mas "
            f"S{season:02d}E{episode:02d} não está na lista"
        )

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

    # Pré-carrega o mapa de séries de todos os servidores
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
CARD_W = 201
THUMB_H = 113


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
            f'style="display:flex;flex-direction:column;gap:8px;'
            f'text-decoration:none;color:inherit;">'

            f'<div style="position:relative;width:{CARD_W}px;height:{THUMB_H}px;'
            f'border-radius:7px;overflow:hidden;'
            f'background:var(--color-widget-background-alt,#1e1e1e);">'
            f'{thumb_inner}'
            f'{badge}'
            f'<span style="position:absolute;bottom:6px;right:7px;font-size:0.7rem;'
            f'padding:2px 6px;border-radius:4px;background:rgba(0,0,0,0.72);'
            f'backdrop-filter:blur(4px);color:#fff;font-weight:600;'
            f'letter-spacing:0.02em;">{ep["label"]}</span>'
            f'</div>'

            f'<div style="display:flex;flex-direction:column;gap:3px;padding:0 2px;">'
            f'<p class="size-h4" style="margin:0;line-height:1.3;overflow:hidden;'
            f'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;'
            f'font-weight:500;">{display_title}</p>'
            f'<p class="size-h6 color-subdue" style="margin:0;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;">{ep["title"]}</p>'
            f'<p class="size-h6 color-subdue" style="margin:0;">'
            f'<span data-dynamic-relative-time="{ep["unix_ts"]}"></span></p>'
            f'</div></a></li>'
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


# ---------------------------------------------------------------------------
# Feed de filmes e séries adicionados recentemente ao Jellyfin
# ---------------------------------------------------------------------------

RECENT_MEDIA_MAX_ITEMS = 15
RECENT_MEDIA_CACHE_TTL_SECONDS = 60

_recent_media_cache = {"data": [], "ts": 0}
_library_map_cache = {}


def parse_jellyfin_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return None


def get_library_map(server: dict) -> dict:
    """Retorna um mapa ID da biblioteca -> nome da biblioteca no Jellyfin."""
    key = server["key"]
    now_ts = datetime.now(timezone.utc).timestamp()

    cached = _library_map_cache.get(key)

    if cached and now_ts - cached["ts"] < 15 * 60:
        return cached["data"]

    library_map = {}

    try:
        r = requests.get(
            f"{server['internal']}/Library/VirtualFolders",
            headers=auth_header(server),
            timeout=10,
        )

        r.raise_for_status()

        for library in r.json():
            item_id = library.get("ItemId")
            name = library.get("Name") or ""

            if item_id and name:
                library_map[str(item_id)] = name

    except Exception as e:
        dbg(f"get_library_map({key}): falha -> {e}")

    if library_map:
        _library_map_cache[key] = {
            "data": library_map,
            "ts": now_ts,
        }

    elif cached:
        return cached["data"]

    return library_map


def classify_recent_media(item: dict, library_map: dict) -> str:
    """Classifica filmes e animes usando o nome da biblioteca de origem."""

    if item.get("Type") == "Movie":
        return "FILME"

    parent_id = str(item.get("ParentId") or "")
    library_name = library_map.get(parent_id, "")

    if "anime" in library_name.casefold():
        return "ANIME"

    return "SÉRIE"


def get_recent_media():
    """Busca os itens Series e Movie mais recentemente adicionados."""
    now_ts = datetime.now(timezone.utc).timestamp()

    if (
        _recent_media_cache["data"]
        and now_ts - _recent_media_cache["ts"] < RECENT_MEDIA_CACHE_TTL_SECONDS
    ):
        return _recent_media_cache["data"]

    collected = []

    for server in JELLYFIN_SERVERS:
        try:
            r = requests.get(
                f"{server['internal']}/Items",
                params={
                    "IncludeItemTypes": "Series,Movie",
                    "Recursive": "true",
                    "SortBy": "DateCreated",
                    "SortOrder": "Descending",
                    "Limit": RECENT_MEDIA_MAX_ITEMS,
                    "Fields": "DateCreated,ProductionYear,ParentId",
                },
                headers=auth_header(server),
                timeout=12,
            )

            if r.status_code != 200:
                dbg(
                    f"get_recent_media({server['key']}): "
                    f"HTTP {r.status_code} ao consultar /Items"
                )
                continue

            server_id = get_server_id(server)
            library_map = get_library_map(server)
            public_url = server["public"].rstrip("/")

            for item in r.json().get("Items", []):
                if item.get("Type") not in ("Series", "Movie"):
                    continue

                created = parse_jellyfin_datetime(item.get("DateCreated"))
                item_id = item.get("Id")

                if created is None or not item_id:
                    continue

                image_url = (
                    f"{public_url}/Items/{item_id}/Images/Primary"
                    f"?ApiKey={server['api_key']}&fillWidth=300&quality=90"
                )

                jellyfin_link = (
                    f"{public_url}/web/#/details"
                    f"?id={item_id}&serverId={server_id}"
                )

                collected.append({
                    "id": item_id,
                    "server_key": server["key"],
                    "title": item.get("Name") or "Sem título",
                    "type": item["Type"],
                    "kind": classify_recent_media(item, library_map),
                    "library": library_map.get(
                        str(item.get("ParentId") or ""), ""
                    ),
                    "year": item.get("ProductionYear"),
                    "unix_ts": int(created.timestamp()),
                    "thumb": image_url,
                    "link": jellyfin_link,
                })

        except Exception as e:
            dbg(f"get_recent_media({server['key']}): falha -> {e}")
            print(f"recent_media error ({server['key']}):", e)

    # Consolida os resultados dos servidores e ordena por DateCreated.
    unique = {
        (item["server_key"], item["id"]): item
        for item in collected
    }

    recent = sorted(
        unique.values(),
        key=lambda item: item["unix_ts"],
        reverse=True,
    )[:RECENT_MEDIA_MAX_ITEMS]

    # Se todos os servidores falharem, mantém o último resultado válido.
    if recent:
        _recent_media_cache["data"] = recent
        _recent_media_cache["ts"] = now_ts

    return _recent_media_cache["data"]


def build_recent_media_html(media_items):
    if not media_items:
        return (
            '<p class="color-subdue">'
            'Nenhum filme ou série recente encontrado.</p>'
        )

    card_width = 150
    poster_height = 225
    cards = []

    for item in media_items:
        title = escape(str(item["title"]), quote=True)
        link = escape(str(item["link"]), quote=True)
        thumb = escape(str(item["thumb"]), quote=True)

        kind = escape(
            str(
                item.get("kind")
                or ("FILME" if item["type"] == "Movie" else "SÉRIE")
            ),
            quote=True,
        )

        year = escape(str(item.get("year") or ""), quote=True)

        poster = (
            f'<img src="{thumb}" alt="" loading="lazy" '
            f'style="width:100%;height:100%;object-fit:cover;display:block;">'
        )

        cards.append(
            f'<li style="flex:0 0 auto;width:{card_width}px;">'
            f'<a href="{link}" target="_blank" rel="noopener" '
            f'style="display:flex;flex-direction:column;gap:8px;'
            f'text-decoration:none;color:inherit;">'

            f'<div style="position:relative;width:{card_width}px;'
            f'height:{poster_height}px;border-radius:7px;overflow:hidden;'
            f'background:var(--color-widget-background-alt,#1e1e1e);">'
            f'{poster}'

            f'<span style="position:absolute;top:6px;left:6px;'
            f'font-size:0.65rem;padding:3px 6px;border-radius:4px;'
            f'background:rgba(0,0,0,0.75);color:#fff;font-weight:700;'
            f'letter-spacing:0.04em;">{kind}</span>'
            f'</div>'

            f'<div style="display:flex;flex-direction:column;gap:3px;padding:0 2px;">'
            f'<p class="size-h4" style="margin:0;line-height:1.3;'
            f'overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;'
            f'-webkit-box-orient:vertical;font-weight:500;">{title}</p>'

            f'<p class="size-h6 color-subdue" style="margin:0;">{year}</p>'

            f'<p class="size-h6 color-subdue" style="margin:0;">'
            f'<span data-dynamic-relative-time="{item["unix_ts"]}"></span></p>'
            f'</div></a></li>'
        )

    return (
        '<ul style="display:flex;flex-direction:row;gap:16px;overflow-x:auto;'
        'padding:2px 0 10px 0;margin:0;list-style:none;scrollbar-width:thin;'
        'scrollbar-color:var(--color-widget-background-alt) transparent;">'
        + "\n".join(cards)
        + "</ul>"
    )


@app.route("/recent-media")
def recent_media():
    html_body = build_recent_media_html(get_recent_media())

    resp = Response(html_body, mimetype="text/html")
    resp.headers["Widget-Title"] = "Adicionados Recentemente"
    resp.headers["Widget-Content-Type"] = "html"

    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)

