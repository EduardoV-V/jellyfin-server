from flask import Flask, Response
import requests
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

SONARR_URL        = "http://127.0.0.1:8989"
SONARR_API        = "0c6aa6b47a1d479ba6f300a2da006d10"

JELLYFIN_INTERNAL = "http://127.0.0.1:8096"
JELLYFIN_PUBLIC   = "http://jellyfin.home"
JELLYFIN_API      = "0c661a146c1a49d793ff0bec5a58f4f4"

CALENDAR_DAYS_BACK = 30
MAX_ITEMS          = 15

# Cache do server_id e do mapa série→jellyfin_id
_jellyfin_server_id = None
_series_map         = None   # tvdbId → jellyfin series_id


def get_server_id() -> str:
    global _jellyfin_server_id
    if _jellyfin_server_id:
        return _jellyfin_server_id
    try:
        r = requests.get(f"{JELLYFIN_INTERNAL}/System/Info/Public", timeout=5)
        if r.status_code == 200:
            _jellyfin_server_id = r.json().get("Id", "")
    except Exception:
        pass
    return _jellyfin_server_id or ""


def get_series_map() -> dict:
    """Busca TODAS as séries do Jellyfin de uma vez e monta tvdbId → jellyfin_id."""
    global _series_map
    if _series_map is not None:
        return _series_map

    headers = {"X-Emby-Token": JELLYFIN_API}
    try:
        r = requests.get(
            f"{JELLYFIN_INTERNAL}/Items",
            params={
                "IncludeItemTypes": "Series",
                "Recursive":        "true",
                "Fields":           "ProviderIds",
            },
            headers=headers,
            timeout=10,
        )
        if r.status_code != 200:
            return {}

        _series_map = {}
        for item in r.json().get("Items", []):
            tvdb = item.get("ProviderIds", {}).get("Tvdb")
            if tvdb:
                _series_map[str(tvdb)] = item["Id"]

    except Exception as e:
        print("series_map error:", e)
        return {}

    return _series_map


def find_jellyfin_episode(tvdb_id: int, season: int, episode: int):
    """Retorna (item_id, server_id) do episódio no Jellyfin, ou (None, None)."""
    series_map = get_series_map()
    series_id  = series_map.get(str(tvdb_id))
    if not series_id:
        return None, None

    headers = {"X-Emby-Token": JELLYFIN_API}
    try:
        r = requests.get(
            f"{JELLYFIN_INTERNAL}/Shows/{series_id}/Episodes",
            params={
                "SeasonNumber": season,
                "Fields":       "Id,ServerId,IndexNumber",
            },
            headers=headers,
            timeout=10,
        )
        if r.status_code != 200:
            return None, None

        for ep in r.json().get("Items", []):
            if ep.get("IndexNumber") == episode:
                return ep["Id"], ep.get("ServerId")

    except Exception as e:
        print("find_episode error:", e)

    return None, None


def get_recent():
    now   = datetime.now(timezone.utc)
    start = (now - timedelta(days=CALENDAR_DAYS_BACK)).strftime("%Y-%m-%d")
    end   = now.strftime("%Y-%m-%d")

    try:
        r = requests.get(
            f"{SONARR_URL}/api/v3/calendar",
            params={
                "apikey":        SONARR_API,
                "start":         start,
                "end":           end,
                "includeSeries": "true",
                "unmonitored":   "false",
            },
            timeout=5,
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    # Pré-carrega o mapa de séries uma única vez para todos os episódios
    get_series_map()

    sid = get_server_id()
    recent = []

    for ep in data:
        air_date = ep.get("airDateUtc")
        if not air_date:
            continue
        try:
            air = datetime.fromisoformat(air_date.replace("Z", "+00:00"))
        except Exception:
            continue
        if air >= now:
            continue

        series  = ep.get("series", {})
        season  = ep.get("seasonNumber", 0)
        episode_num = ep.get("episodeNumber", 0)

        item_id, item_server_id = find_jellyfin_episode(
            series.get("tvdbId"), season, episode_num
        )

        if item_id:
            server_id_used = item_server_id or sid
            jellyfin_link  = (
                f"{JELLYFIN_PUBLIC}/web/#/details"
                f"?id={item_id}&context=tvshows&serverId={server_id_used}"
            )
            # Imagem diretamente do Jellyfin (sem proxy) usando JELLYFIN_PUBLIC
            # O browser do cliente consegue acessar JELLYFIN_PUBLIC normalmente
            thumb_url = (
                f"{JELLYFIN_PUBLIC}/Items/{item_id}/Images/Primary"
                f"?api_key={JELLYFIN_API}&fillWidth=300&quality=90"
            )
        else:
            jellyfin_link = JELLYFIN_PUBLIC
            thumb_url     = ""

        recent.append({
            "title":         series.get("title", "Unknown"),
            "episode_title": ep.get("title", ""),
            "season":        season,
            "episode":       episode_num,
            "label":         f"S{season:02d}E{episode_num:02d}",
            "thumb":         thumb_url,
            "unix_ts":       int(air.timestamp()),
            "has_file":      ep.get("hasFile", False),
            "link":          jellyfin_link,
        })

    recent.sort(key=lambda x: x["unix_ts"], reverse=True)
    return recent[:MAX_ITEMS]


# Dimensões base × 1.15
CARD_W   = 201   # 175 × 1.15
THUMB_H  = 113   # 98  × 1.15


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
    episodes  = get_recent()
    html_body = build_html(episodes)
    resp      = Response(html_body, mimetype="text/html")
    resp.headers["Widget-Title"]        = "Episódios Recentes"
    resp.headers["Widget-Content-Type"] = "html"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
