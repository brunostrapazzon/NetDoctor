"""Relatório técnico em um único arquivo .html, sem nenhum recurso externo.

Abre offline em qualquer navegador e pode ser anexado num chamado.
Todo valor vindo das probes passa por html.escape (SSID e nomes de
adaptador são texto controlado por terceiros). Sem JavaScript: o sumário
usa âncoras e o JSON bruto fica num <details>.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from netdoctor.explain.templates import AI_DISCLOSURE

SEVERITY_LABEL = {"critical": "Problema", "warning": "Atenção", "info": "Normal"}
# Ícone + texto: a gravidade nunca depende só da cor.
SEVERITY_ICON = {"critical": "✖", "warning": "⚠", "info": "✔"}
PROBE_TITLE = {
    "adapter": "Conexão do computador",
    "wifi": "Wi-Fi",
    "ping": "Resposta do roteador e da internet (ping)",
    "dns": "Tradução de nomes (DNS)",
    "http": "Acesso a sites (HTTP/HTTPS)",
    "neighbors": "Redes Wi-Fi visíveis (canais)",
    "devices": "Aparelhos na rede (tabela ARP)",
    "hops": "Caminho até a internet (tracert)",
}
ROLE_LABEL = {
    "gateway": "Roteador",
    "public_cloudflare": "Internet (Cloudflare)",
    "public_google": "Internet (Google)",
    "configured": "Configurado",
    "public": "Público",
}

_CSS = """
:root{color-scheme:light dark;
--bg:#f4f5f7;--surface:#fff;--surface-2:#f8f9fb;--text:#151a23;--muted:#596273;
--line:rgba(21,26,35,.10);--line-strong:rgba(21,26,35,.16);--code:#eef0f4;
--crit:#b42318;--crit-bg:#fdeceb;--warn:#8a5a00;--warn-bg:#fff4d6;--ok:#16723a;--ok-bg:#e5f5eb;
--shadow:0 1px 2px rgba(21,26,35,.05);
--w-normal:400;--w-medium:500;--w-semibold:600;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--radius:12px}
@media screen and (prefers-color-scheme:dark){:root{
--bg:#0f1217;--surface:#171b23;--surface-2:#1c212b;--text:#e8ebf1;--muted:#9ca5b5;
--line:rgba(232,235,241,.09);--line-strong:rgba(232,235,241,.16);--code:#232934;
--crit:#ff8f85;--crit-bg:#3b1d1b;--warn:#f5c451;--warn-bg:#352b14;--ok:#6fdc98;--ok-bg:#16301f;
--shadow:none}}
@media print{:root{color-scheme:light}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.55 "Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
main{max-width:960px;margin:0 auto;
padding:var(--s6) max(var(--s4),env(safe-area-inset-right)) var(--s7)
max(var(--s4),env(safe-area-inset-left))}
h1,h2,h3{text-wrap:balance;margin:0;line-height:1.25}
h1{font-size:26px;font-weight:var(--w-semibold);letter-spacing:-.015em}
h2{font-size:18px;font-weight:var(--w-semibold);letter-spacing:-.005em}
h3{font-size:15px;font-weight:var(--w-semibold)}
p{margin:0}
p+p{margin-top:var(--s2)}
[id]{scroll-margin-top:var(--s4)}
:focus-visible{outline:2px solid var(--text);outline-offset:2px;border-radius:4px}
.page-head{margin-bottom:var(--s5)}
.eyebrow{font-size:13px;font-weight:var(--w-semibold);letter-spacing:.06em;
text-transform:uppercase;color:var(--muted);margin-bottom:var(--s1)}
.meta{display:flex;flex-wrap:wrap;gap:var(--s1) var(--s4);margin:var(--s2) 0 0;padding:0;
list-style:none;color:var(--muted);font-size:14px;font-variant-numeric:tabular-nums}
.toc{margin:0 0 var(--s5)}
.toc ul{display:flex;flex-wrap:wrap;gap:var(--s2);margin:0;padding:0;list-style:none}
.toc a{display:inline-flex;align-items:center;min-height:36px;padding:0 var(--s3);
border-radius:999px;background:var(--surface);box-shadow:0 0 0 1px var(--line-strong);
color:var(--text);font-size:14px;text-decoration:none;touch-action:manipulation}
@media (hover:hover) and (pointer:fine){.toc a:hover{background:var(--surface-2)}}
.card{background:var(--surface);border-radius:var(--radius);
box-shadow:0 0 0 1px var(--line),var(--shadow);padding:var(--s5);margin-bottom:var(--s4)}
.card-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;
gap:var(--s1) var(--s3);margin-bottom:var(--s4)}
.dur{color:var(--muted);font-size:13px;font-weight:var(--w-normal);
font-variant-numeric:tabular-nums;white-space:nowrap}
.result{--tone:var(--warn);--tone-bg:var(--warn-bg);border-left:4px solid var(--tone)}
.result.critical{--tone:var(--crit);--tone-bg:var(--crit-bg)}
.result.info{--tone:var(--ok);--tone-bg:var(--ok-bg)}
.result-top{display:flex;gap:var(--s4);align-items:flex-start}
.result-icon{flex:none;display:grid;place-items:center;width:44px;height:44px;border-radius:50%;
background:var(--tone-bg);color:var(--tone);font-size:22px;line-height:1;user-select:none}
.headline{font-size:22px;font-weight:var(--w-semibold);letter-spacing:-.01em;margin-top:var(--s1)}
.detail{color:var(--muted);margin-top:var(--s2);max-width:65ch}
.facts{margin:var(--s4) 0 0;padding:0;list-style:none;display:grid;gap:var(--s2)}
.facts li{background:var(--surface-2);box-shadow:0 0 0 1px var(--line);border-radius:8px;
padding:var(--s2) var(--s3);font-variant-numeric:tabular-nums}
.also{margin-top:var(--s4);padding:var(--s3) var(--s4);border-radius:8px;
background:var(--tone-bg)}
.result h3{margin-top:var(--s5)}
.steps{counter-reset:step;list-style:none;margin:var(--s3) 0 0;padding:0;display:grid;
gap:var(--s3);max-width:70ch}
.steps li{counter-increment:step;display:grid;grid-template-columns:28px 1fr;gap:var(--s3);
align-items:start}
.steps li::before{content:counter(step);display:grid;place-items:center;width:28px;height:28px;
border-radius:50%;background:var(--text);color:var(--surface);font-size:14px;
font-weight:var(--w-semibold);font-variant-numeric:tabular-nums}
.steps li>span{padding-top:2px}
.notes{margin-top:var(--s4);padding-top:var(--s3);border-top:1px solid var(--line);
color:var(--muted);font-size:14px}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:var(--w-semibold);
padding:2px 10px;border-radius:999px;white-space:nowrap;line-height:1.6}
.badge.critical{color:var(--crit);background:var(--crit-bg)}
.badge.warning{color:var(--warn);background:var(--warn-bg)}
.badge.info{color:var(--ok);background:var(--ok-bg)}
.muted{color:var(--muted)}
.intro{color:var(--muted);font-size:14px;margin-bottom:var(--s3)}
.alert{display:flex;gap:var(--s2);align-items:baseline;padding:var(--s3) var(--s4);
border-radius:8px;background:var(--crit-bg);color:var(--crit)}
.table-wrap{overflow-x:auto;margin:0 calc(-1*var(--s2));padding:0 var(--s2);
-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:var(--s2) var(--s3);vertical-align:top}
thead th{color:var(--muted);font-size:13px;font-weight:var(--w-semibold);white-space:nowrap;
border-bottom:1px solid var(--line-strong)}
tbody td{border-bottom:1px solid var(--line)}
tbody tr:last-child td{border-bottom:0}
tbody tr:nth-child(even){background:var(--surface-2)}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.nil{color:var(--muted)}
tbody td:first-child:not(.num){min-width:8.5em}
.kv td:first-child{color:var(--muted);white-space:nowrap;width:1%}
code,pre{font-family:"Cascadia Mono",Consolas,ui-monospace,monospace;font-size:13px}
code{background:var(--code);padding:1px 6px;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--code);padding:var(--s4);border-radius:8px;overflow:auto;max-height:70vh;
white-space:pre;margin:var(--s3) 0 0;line-height:1.45}
td code{white-space:nowrap;overflow-wrap:normal}
.ev{display:flex;flex-wrap:wrap;gap:var(--s1)}
summary{display:flex;align-items:center;gap:var(--s2);min-height:44px;cursor:pointer;
list-style:none;font-weight:var(--w-semibold);touch-action:manipulation;user-select:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";display:inline-block;color:var(--muted)}
details[open]>summary::before{transform:rotate(90deg)}
@media (prefers-reduced-motion:no-preference){summary::before{transition:transform .2s ease-out}}
.card.raw{padding-top:var(--s2);padding-bottom:var(--s2)}
footer{color:var(--muted);font-size:14px;margin-top:var(--s5);max-width:70ch}
@media (max-width:600px){
main{padding-top:var(--s5)}
h1{font-size:22px}
.card{padding:var(--s4)}
.headline{font-size:19px}
.result-icon{display:none}
.toc ul{flex-wrap:nowrap;overflow-x:auto;margin:0 calc(-1*var(--s4));padding:2px var(--s4);
scrollbar-width:none}
.toc li{flex:none}
.table-wrap{margin:0 calc(-1*var(--s4));padding:0 var(--s4)}}
@media print{
body{background:#fff;font-size:12pt}
main{max-width:none;padding:0}
.toc,.raw{display:none}
.card{box-shadow:0 0 0 1px #ccc;break-inside:avoid}
.table-wrap{overflow:visible}}
"""


def _e(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, list | dict):
        return escape(json.dumps(value, ensure_ascii=False))
    return escape(str(value))


def _cell(value: Any, numeric: bool) -> str:
    cls = ' class="num"' if numeric else ""
    if value is None:
        return f'<td{cls}><span class="nil">—</span></td>'
    return f"<td{cls}>{_e(value)}</td>"


def _table(
    headers: list[str], rows: list[list[Any]], label: str, numeric: frozenset[int] = frozenset()
) -> str:
    num_attr = ' class="num"'
    head = "".join(
        f'<th scope="col"{num_attr if i in numeric else ""}>{escape(h)}</th>'
        for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>" + "".join(_cell(c, i in numeric) for i, c in enumerate(row)) + "</tr>"
        for row in rows
    )
    return _wrap(label, f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody>")


def _wrap(label: str, inner: str, cls: str = "") -> str:
    # role/aria-label/tabindex: a tabela larga rola pelo teclado e o leitor de tela anuncia.
    cls_attr = f' class="{cls}"' if cls else ""
    return (
        f'<div class="table-wrap" role="region" aria-label="{escape(label)}" tabindex="0">'
        f"<table{cls_attr}>{inner}</table></div>"
    )


def _kv(data: dict[str, Any], label: str) -> str:
    body = "".join(f"<tr><td>{_e(k)}</td>{_cell(v, False)}</tr>" for k, v in data.items())
    return _wrap(label, f"<tbody>{body}</tbody>", "kv")


def _rtt(t: dict[str, Any], key: str) -> Any:
    return t["rtt_ms"][key] if t.get("rtt_ms") else None


def _badge(severity: str) -> str:
    icon = SEVERITY_ICON.get(severity, "•")
    label = SEVERITY_LABEL.get(severity, severity)
    return (
        f'<span class="badge {escape(severity)}"><span aria-hidden="true">{icon}</span>'
        f"{escape(label)}</span>"
    )


def _evidence(evidence: Any) -> str:
    if not evidence:
        return '<span class="nil">—</span>'
    if isinstance(evidence, dict):
        items = "".join(f"<code>{_e(k)}: {_e(v)}</code>" for k, v in evidence.items())
        return f'<span class="ev">{items}</span>'
    return f"<code>{_e(evidence)}</code>"


def _anchor(name: str) -> str:
    return "probe-" + re.sub(r"[^a-z0-9-]", "-", str(name).lower())


def _when(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return _e(iso)
    tz = dt.strftime("%z")
    zone = " (UTC)" if tz == "+0000" else (f" (UTC{tz[:3]}:{tz[3:]})" if tz else "")
    return f'<time datetime="{escape(iso)}">{dt:%d/%m/%Y às %H:%M}{zone}</time>'


def _probe_body(probe: dict[str, Any]) -> str:
    name, data = probe["name"], probe["data"]
    title = PROBE_TITLE.get(name, name)
    if not probe["ok"]:
        return (
            '<p class="alert"><span aria-hidden="true">✖</span>'
            f"<span>Não foi possível medir: <code>{_e(probe['error'])}</code></span></p>"
        )
    if name == "ping":
        rows = [
            [
                ROLE_LABEL.get(t["role"], t["role"]),
                t.get("host"),
                t.get("sent"),
                t.get("received"),
                f"{t['loss_pct']}%" if t.get("loss_pct") is not None else None,
                _rtt(t, "min"),
                _rtt(t, "avg"),
                _rtt(t, "max"),
                t.get("error"),
            ]
            for t in data["targets"]
        ]
        headers = ["Destino", "Endereço", "Enviados", "Recebidos", "Perda"]
        headers += ["Mín (ms)", "Média (ms)", "Máx (ms)", "Erro"]
        return _table(headers, rows, title, frozenset({2, 3, 4, 5, 6, 7}))
    if name == "dns":
        rows = [
            [s["server"], ROLE_LABEL.get(s["role"], s["role"]), s["ok"], s["ms"], s["error"]]
            for s in data["servers"]
        ]
        intro = f'<p class="intro">Nome consultado: <code>{_e(data["test_name"])}</code></p>'
        headers = ["Servidor", "Tipo", "Resolveu", "Tempo (ms)", "Erro"]
        return intro + _table(headers, rows, title, frozenset({3}))
    if name == "http":
        n, h = data["ncsi"], data["https"]
        rows = [
            [
                "Teste de conexão do Windows (NCSI)",
                n["status"],
                n["content_ok"],
                n["ms"],
                n["error"],
            ],
            ["HTTPS (resposta 204 esperada)", h["status"], h["ok"], h["ms"], h["error"]],
        ]
        extra = ""
        if n.get("redirect_host"):
            extra = (
                f'<p class="intro" style="margin:12px 0 0">Redirecionado para: '
                f"<code>{_e(n['redirect_host'])}</code></p>"
            )
        headers = ["Teste", "Status", "OK", "Tempo (ms)", "Erro"]
        return _table(headers, rows, title, frozenset({1, 3})) + extra
    if name == "neighbors" and "access_points" in data:
        rows = [
            [
                "esta rede" if ap["own"] else ("oculta" if ap["hidden"] else "vizinha"),
                ap["band"],
                ap["channel"],
                f"{ap['signal_pct']}%" if ap["signal_pct"] is not None else None,
                f"{ap['utilization_pct']}%" if ap["utilization_pct"] is not None else None,
                ap["stations"],
            ]
            for ap in sorted(
                data["access_points"], key=lambda a: (not a["own"], -(a["signal_pct"] or 0))
            )
        ]
        intro = '<p class="intro">Nomes e BSSIDs das redes vizinhas não são registrados.</p>'
        headers = ["Rede", "Banda", "Canal", "Sinal", "Utilização", "Aparelhos no AP"]
        return intro + _table(headers, rows, title, frozenset({2, 3, 4, 5}))
    if name == "devices" and "devices" in data:
        rows = [[d["ip"], d["mac"], d["gateway"], d["randomized_mac"]] for d in data["devices"]]
        intro = (
            '<p class="intro">Leitura passiva do cache do Windows: mostra quem conversou com '
            "este computador recentemente, não necessariamente todos os aparelhos.</p>"
        )
        return intro + _table(["IP", "MAC", "Roteador", "MAC aleatório"], rows, title)
    if name == "hops" and "hops" in data:
        rows = [
            [
                h["hop"],
                h["ip"],
                *[("*" if r is None else r) for r in h["rtt_ms"]],
                f"{h['loss_pct']:g}%",
                h["avg_ms"],
            ]
            for h in data["hops"]
        ]
        headers = ["Salto", "IP", "1 (ms)", "2 (ms)", "3 (ms)", "Perda", "Média (ms)"]
        status = "chegou" if data["reached"] else "não chegou"
        intro = f'<p class="intro">Destino <code>{_e(data["target"])}</code>: {status}.</p>'
        return intro + _table(headers, rows, title, frozenset({0, 2, 3, 4, 5, 6}))
    return _kv(data, title)


def _tech_section(tech: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{_badge(str(f['severity']))}</td>"
        f"<td>{_e(f['text'])}</td>{_cell(f['action_text'] or None, False)}"
        f"<td><code>{_e(f['code'])}</code></td></tr>"
        for f in tech["findings"]
    )
    head = (
        '<thead><tr><th scope="col">Gravidade</th><th scope="col">Observação</th>'
        '<th scope="col">Recomendação</th><th scope="col">Código</th></tr></thead>'
    )
    notes = "".join(f"<p>{_e(n)}</p>" for n in tech["notes"])
    notes_html = f'<div class="notes">{notes}</div>' if notes else ""
    table = _wrap("Laudo técnico", f"{head}<tbody>{rows}</tbody>") if rows else ""
    return (
        '<section class="card" id="laudo" aria-labelledby="laudo-t">'
        f'<div class="card-head"><h2 id="laudo-t">Laudo técnico</h2></div>'
        f"{table}{notes_html}</section>"
    )


def render_html(report: dict[str, Any]) -> str:
    ex = report["explanation"]
    sev = ex["severity"] if ex["severity"] in SEVERITY_LABEL else "warning"
    numbers = "".join(f"<li>{_e(n)}</li>" for n in ex["numbers"])
    numbers_html = f'<ul class="facts">{numbers}</ul>' if numbers else ""
    also = (
        f'<p class="also"><strong>Também notamos:</strong> {_e("; ".join(ex["also"]))}.</p>'
        if ex["also"]
        else ""
    )
    actions = "".join(f"<li><span>{_e(a)}</span></li>" for a in ex["actions"])
    actions_html = f'<h3>O que fazer</h3><ol class="steps">{actions}</ol>' if actions else ""
    notes = "".join(f"<p>Obs.: {_e(n)}</p>" for n in ex["notes"])
    if ex.get("source") == "llm":
        notes += f"<p>{_e(AI_DISCLOSURE)}</p>"
    notes_html = f'<div class="notes">{notes}</div>' if notes else ""

    findings_rows = "".join(
        f"<tr><td>{_badge(str(f['severity']))}</td><td><code>{_e(f['code'])}</code></td>"
        f"<td><code>{_e(f['action'])}</code></td><td>{_evidence(f['evidence'])}</td></tr>"
        for f in report["diagnosis"]["findings"]
    )
    findings_head = (
        '<thead><tr><th scope="col">Gravidade</th><th scope="col">Código</th>'
        '<th scope="col">Ação</th><th scope="col">Evidência</th></tr></thead>'
    )
    findings = _wrap("Achados", f"{findings_head}<tbody>{findings_rows}</tbody>")

    probes = "".join(
        f'<section class="card" id="{_anchor(p["name"])}" '
        f'aria-labelledby="{_anchor(p["name"])}-t"><div class="card-head">'
        f'<h2 id="{_anchor(p["name"])}-t">{escape(PROBE_TITLE.get(p["name"], p["name"]))}</h2>'
        f'<span class="dur">{_e(p["duration_ms"])} ms</span></div>{_probe_body(p)}</section>'
        for p in report["probes"]
    )
    tech = report.get("tech")
    tech_html = _tech_section(tech) if tech else ""
    kind = "Laudo técnico" if tech else "Relatório técnico"
    devices_note = " e dos aparelhos conectados (MAC)" if tech else ""
    raw = escape(json.dumps(report, ensure_ascii=False, indent=2))
    os_info = f"{report['os']['system']} {report['os']['release']}"

    toc_items = [("resultado", "Resultado"), ("achados", "Achados")]
    if tech:
        toc_items.append(("laudo", "Laudo técnico"))
    toc_items += [
        (_anchor(p["name"]), PROBE_TITLE.get(p["name"], p["name"]).split(" (")[0])
        for p in report["probes"]
    ]
    toc_items.append(("dados", "Dados brutos"))
    toc = "".join(f'<li><a href="#{a}">{escape(t)}</a></li>' for a, t in toc_items)

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>NetDoctor — {kind}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<header class="page-head">
<h1>NetDoctor — {kind}</h1>
<ul class="meta">
<li>Gerado em {_when(report["generated_at"])}</li>
<li>Versão {_e(report["version"])}</li>
<li>{_e(os_info)}</li>
</ul>
</header>

<nav class="toc" aria-label="Nesta página"><ul>{toc}</ul></nav>

<section class="card result {sev}" id="resultado" aria-labelledby="resultado-t">
<div class="result-top">
<span class="result-icon" aria-hidden="true">{SEVERITY_ICON[sev]}</span>
<div>
{_badge(sev)}
<h2 class="headline" id="resultado-t">{_e(ex["headline"])}</h2>
<p class="detail">{_e(ex["detail"])}</p>
</div>
</div>
{numbers_html}{also}
{actions_html}
{notes_html}
</section>

<section class="card" id="achados" aria-labelledby="achados-t">
<div class="card-head"><h2 id="achados-t">Achados</h2>
<span class="dur">para o suporte</span></div>
{findings}
</section>

{tech_html}

{probes}

<section class="card raw" id="dados"><details><summary>Dados brutos (JSON)</summary>
<pre tabindex="0">{raw}</pre>
</details></section>

<footer>Este relatório contém dados da sua rede (nome do Wi-Fi e endereços locais{devices_note}).
Envie apenas ao suporte técnico em quem você confia. Nada foi enviado pela internet
para gerá-lo.</footer>
</main>
</body>
</html>
"""


def write_html(report: dict[str, Any], path: Path) -> Path:
    path.write_text(render_html(report), encoding="utf-8")
    return path
