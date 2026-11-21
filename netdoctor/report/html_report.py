"""Relatório técnico em um único arquivo .html, sem nenhum recurso externo.

Abre offline em qualquer navegador e pode ser anexado num chamado.
Todo valor vindo das probes passa por html.escape (SSID e nomes de
adaptador são texto controlado por terceiros).
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from netdoctor.explain.templates import AI_DISCLOSURE

SEVERITY_LABEL = {"critical": "Problema", "warning": "Atenção", "info": "Normal"}
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
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#5b6475;--border:#dde1e8;
--crit:#b42318;--crit-bg:#fdecea;--warn:#946200;--warn-bg:#fff6dc;--ok:#1b7a3d;--ok-bg:#e6f6ec;
--code:#eef0f4}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029;--text:#e6e9ef;
--muted:#9aa3b2;--border:#2c3340;--crit:#ff8a80;--crit-bg:#3a1f1f;--warn:#ffd36b;
--warn-bg:#3a321c;--ok:#7ee2a0;--ok-bg:#1c3326;--code:#242a35}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0 0 12px}
.meta{color:var(--muted);font-size:13px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;
padding:18px 20px;margin-bottom:16px}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 10px;
border-radius:999px;margin-bottom:8px}
.critical{color:var(--crit);background:var(--crit-bg)}
.warning{color:var(--warn);background:var(--warn-bg)}
.info{color:var(--ok);background:var(--ok-bg)}
.headline{font-size:19px;font-weight:600;margin:0 0 4px}
.muted{color:var(--muted)}
ol{padding-left:22px;margin:8px 0}
.table-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted);font-weight:600}
code,pre{font-family:Consolas,"Cascadia Mono",monospace;font-size:13px}
code{background:var(--code);padding:1px 5px;border-radius:4px}
pre{background:var(--code);padding:12px;border-radius:8px;overflow-x:auto;white-space:pre}
.fail{color:var(--crit)}
footer{color:var(--muted);font-size:13px;margin-top:24px}
"""


def _e(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, list | dict):
        return escape(json.dumps(value, ensure_ascii=False))
    return escape(str(value))


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><tr>{head}</tr>{body}</table></div>'


def _kv(data: dict[str, Any]) -> str:
    return _table(["Campo", "Valor"], [[k, v] for k, v in data.items()])


def _rtt(t: dict[str, Any], key: str) -> Any:
    return t["rtt_ms"][key] if t.get("rtt_ms") else None


def _probe_body(probe: dict[str, Any]) -> str:
    name, data = probe["name"], probe["data"]
    if not probe["ok"]:
        return f'<p class="fail">Não foi possível medir: <code>{_e(probe["error"])}</code></p>'
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
        return _table(headers, rows)
    if name == "dns":
        rows = [
            [s["server"], ROLE_LABEL.get(s["role"], s["role"]), s["ok"], s["ms"], s["error"]]
            for s in data["servers"]
        ]
        intro = f'<p class="muted">Nome consultado: <code>{_e(data["test_name"])}</code></p>'
        return intro + _table(["Servidor", "Tipo", "Resolveu", "Tempo (ms)", "Erro"], rows)
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
            extra = f"<p>Redirecionado para: <code>{_e(n['redirect_host'])}</code></p>"
        return _table(["Teste", "Status", "OK", "Tempo (ms)", "Erro"], rows) + extra
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
        intro = '<p class="muted">Nomes e BSSIDs das redes vizinhas não são registrados.</p>'
        headers = ["Rede", "Banda", "Canal", "Sinal", "Utilização", "Aparelhos no AP"]
        return intro + _table(headers, rows)
    if name == "devices" and "devices" in data:
        rows = [[d["ip"], d["mac"], d["gateway"], d["randomized_mac"]] for d in data["devices"]]
        intro = (
            '<p class="muted">Leitura passiva do cache do Windows: mostra quem conversou com '
            "este computador recentemente, não necessariamente todos os aparelhos.</p>"
        )
        return intro + _table(["IP", "MAC", "Roteador", "MAC aleatório"], rows)
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
        intro = f'<p class="muted">Destino <code>{_e(data["target"])}</code>: {status}.</p>'
        return intro + _table(headers, rows)
    return _kv(data)


def _tech_section(tech: dict[str, Any]) -> str:
    rows = "".join(
        f'<tr><td><span class="badge {escape(str(f["severity"]))}">'
        f"{escape(SEVERITY_LABEL.get(str(f['severity']), str(f['severity'])))}</span></td>"
        f"<td>{_e(f['text'])}</td><td>{_e(f['action_text'] or None)}</td>"
        f"<td><code>{_e(f['code'])}</code></td></tr>"
        for f in tech["findings"]
    )
    head = "<tr><th>Gravidade</th><th>Observação</th><th>Recomendação</th><th>Código</th></tr>"
    notes = "".join(f'<p class="muted">{_e(n)}</p>' for n in tech["notes"])
    table = f'<div class="table-wrap"><table>{head}{rows}</table></div>' if rows else ""
    return f'<section class="card"><h2>Laudo técnico</h2>{table}{notes}</section>'


def render_html(report: dict[str, Any]) -> str:
    ex = report["explanation"]
    sev = ex["severity"]
    numbers = "".join(f"<p>{_e(n)}</p>" for n in ex["numbers"])
    also = (
        f"<p><strong>Também notamos:</strong> {_e('; '.join(ex['also']))}.</p>"
        if ex["also"]
        else ""
    )
    actions = "".join(f"<li>{_e(a)}</li>" for a in ex["actions"])
    notes = "".join(f'<p class="muted">Obs.: {_e(n)}</p>' for n in ex["notes"])
    if ex.get("source") == "llm":
        notes += f'<p class="muted">{_e(AI_DISCLOSURE)}</p>'

    findings = _table(
        ["Código", "Gravidade", "Ação", "Evidência"],
        [
            [f["code"], f["severity"], f["action"], f["evidence"] or None]
            for f in report["diagnosis"]["findings"]
        ],
    )

    probes = "".join(
        f'<section class="card"><h2>{escape(PROBE_TITLE.get(p["name"], p["name"]))}'
        f' <span class="muted" style="font-weight:400;font-size:13px">'
        f"({_e(p['duration_ms'])} ms)</span></h2>{_probe_body(p)}</section>"
        for p in report["probes"]
    )
    tech = report.get("tech")
    tech_html = _tech_section(tech) if tech else ""
    kind = "Laudo técnico" if tech else "Relatório técnico"
    devices_note = " e dos aparelhos conectados (MAC)" if tech else ""
    raw = escape(json.dumps(report, ensure_ascii=False, indent=2))
    os_info = f"{report['os']['system']} {report['os']['release']}"

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetDoctor — {kind}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>NetDoctor — {kind}</h1>
<div class="meta">Gerado em {_e(report["generated_at"])} · versão {_e(report["version"])} ·
{_e(os_info)}</div>

<section class="card">
<span class="badge {escape(sev)}">{escape(SEVERITY_LABEL.get(sev, sev))}</span>
<p class="headline">{_e(ex["headline"])}</p>
<p class="muted">{_e(ex["detail"])}</p>
{numbers}{also}
<h2 style="margin-top:14px">O que fazer</h2>
<ol>{actions}</ol>
{notes}
</section>

<section class="card"><h2>Achados (para o suporte)</h2>{findings}</section>

{tech_html}

{probes}

<section class="card"><details><summary>Dados brutos (JSON)</summary><pre>{raw}</pre>
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
