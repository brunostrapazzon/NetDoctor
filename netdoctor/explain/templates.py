"""Explicações offline (pt-BR) por código de achado.

Funcionam sempre, sem internet e sem IA. Regras de escrita:
- 1 frase de causa, para quem não é técnico;
- 1 a 3 ações concretas;
- sem jargão: nada de "gateway", "DNS", "DHCP", "IP", "ping", "latência";
- nunca citar causa que não esteja nos achados.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from netdoctor.core.models import Diagnosis, Finding, ProbeResult

SEND_REPORT = "Se continuar, salve o relatório e envie ao suporte técnico."


@dataclass(frozen=True)
class Template:
    headline: str
    detail: str
    actions: tuple[str, ...]
    short: str  # rótulo curto, usado quando o achado é secundário


TEMPLATES: dict[str, Template] = {
    "NO_LINK": Template(
        headline="Seu computador não está conectado a nenhuma rede.",
        detail="O cabo está solto ou o Wi-Fi está desligado ou desconectado.",
        actions=(
            "Se usa cabo, confira se ele está bem encaixado no computador e no roteador.",
            "Se usa Wi-Fi, ligue o Wi-Fi do computador e conecte-se à sua rede.",
            SEND_REPORT,
        ),
        short="computador desconectado da rede",
    ),
    "NO_DHCP": Template(
        headline="O roteador não está deixando o computador entrar na rede.",
        detail="O computador conectou, mas o roteador não entregou um endereço para ele.",
        actions=(
            "Desligue o roteador da tomada, espere 30 segundos e ligue de novo.",
            "Espere 2 minutos e teste outra vez.",
            SEND_REPORT,
        ),
        short="roteador não liberou acesso ao computador",
    ),
    "GATEWAY_DOWN": Template(
        headline="O computador não consegue falar com o roteador.",
        detail="O problema está no roteador ou na conexão até ele, não na operadora.",
        actions=(
            "Desligue o roteador da tomada, espere 30 segundos e ligue de novo.",
            "Se estiver no Wi-Fi, chegue mais perto do roteador e teste de novo.",
            SEND_REPORT,
        ),
        short="roteador sem resposta",
    ),
    "ISP_DOWN": Template(
        headline="A internet da operadora está fora do ar.",
        detail=(
            "Seu computador e o roteador estão funcionando, mas o sinal da operadora não chega."
        ),
        actions=(
            "Ligue para o suporte da operadora e informe que a internet caiu.",
            "Confira se alguma luz do modem/roteador está vermelha ou apagada.",
            "Tenha o relatório em mãos para passar as informações ao atendente.",
        ),
        short="internet da operadora fora",
    ),
    "DNS_FAIL": Template(
        headline="A internet chega, mas os sites não abrem pelo nome.",
        detail=(
            "O serviço que transforma o nome dos sites (como google.com) em endereço "
            "não está respondendo na sua rede."
        ),
        actions=(
            "Desligue o roteador da tomada, espere 30 segundos e ligue de novo.",
            "Se continuar, peça ao suporte técnico para revisar a configuração do roteador "
            "e envie o relatório.",
        ),
        short="sites não abrem pelo nome",
    ),
    "CAPTIVE_PORTAL": Template(
        headline="Esta rede pede login antes de liberar a internet.",
        detail="É comum em hotéis, aeroportos, lojas e redes de visitantes.",
        actions=(
            "Abra o navegador e acesse qualquer site para ver a página de login da rede.",
            "Faça o login ou aceite os termos pedidos.",
            "Se a página não aparecer, peça ajuda a quem administra a rede.",
        ),
        short="rede pede login",
    ),
    "WIFI_WEAK": Template(
        headline="Seu Wi-Fi está fraco neste lugar.",
        detail="O sinal chega fraco ao computador, e isso deixa a internet lenta ou instável.",
        actions=(
            "Aproxime-se do roteador ou tire obstáculos do caminho (paredes, móveis, espelhos).",
            "Se puder, use cabo de rede.",
            "Se precisa de Wi-Fi forte neste cômodo, peça ao suporte uma avaliação de repetidor.",
        ),
        short="Wi-Fi fraco neste lugar",
    ),
    "LOCAL_INTERFERENCE": Template(
        headline="A conexão entre o computador e o roteador está instável.",
        detail=(
            "Pode ser interferência no Wi-Fi ou o roteador sobrecarregado com muitos aparelhos."
        ),
        actions=(
            "Desligue o roteador da tomada, espere 30 segundos e ligue de novo.",
            "Pause downloads, vídeos ou jogos em outros aparelhos e teste de novo.",
            SEND_REPORT,
        ),
        short="conexão instável até o roteador",
    ),
    "ALL_OK": Template(
        headline="Sua conexão está funcionando normalmente.",
        detail="Computador, roteador e internet da operadora responderam bem.",
        actions=(
            "Se um site ou aplicativo específico não funciona, o problema pode ser nele.",
            "Tente de novo daqui a alguns minutos ou em outro aparelho.",
        ),
        short="conexão normal",
    ),
    "INCONCLUSIVE": Template(
        headline="Não foi possível concluir o diagnóstico.",
        detail="Alguns testes não conseguiram rodar até o fim.",
        actions=(
            "Feche programas pesados e rode o diagnóstico de novo.",
            SEND_REPORT,
        ),
        short="diagnóstico incompleto",
    ),
}

# Observações quando um teste não mediu por um motivo que o usuário resolve.
PROBE_NOTES: dict[tuple[str, str], str] = {
    ("wifi", "LOCATION_PERMISSION"): (
        "Para medir o sinal do Wi-Fi, o Windows exige a Localização ativada: "
        "Configurações > Privacidade e segurança > Localização."
    ),
}


@dataclass
class Explanation:
    code: str
    severity: str
    headline: str
    detail: str
    actions: list[str]
    also: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    source: str = "template"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_text(self) -> str:
        lines = [self.headline, self.detail]
        lines += self.numbers
        if self.also:
            lines.append("Também notamos: " + "; ".join(self.also) + ".")
        lines.append("")
        lines.append("O que fazer:")
        lines += [f"  {i}. {a}" for i, a in enumerate(self.actions, 1)]
        if self.notes:
            lines.append("")
            lines += [f"Obs.: {n}" for n in self.notes]
        return "\n".join(lines)


def _numbers(finding: Finding) -> list[str]:
    """Números da evidência em linguagem simples (sem jargão)."""
    e = finding.evidence
    if finding.code == "WIFI_WEAK":
        return [f"Força do sinal: {e['signal_pct']}% (o ideal é acima de {e['threshold_pct']}%)."]
    if finding.code == "LOCAL_INTERFERENCE":
        out = []
        if e.get("gateway_loss_pct"):
            out.append(f"{e['gateway_loss_pct']:g}% das tentativas até o roteador se perderam.")
        if e.get("gateway_avg_rtt_ms") is not None:
            out.append(f"Tempo de resposta do roteador: {e['gateway_avg_rtt_ms']:g} ms.")
        return out
    return []


def explain(diagnosis: Diagnosis, results: list[ProbeResult] | None = None) -> Explanation:
    primary = diagnosis.primary
    tpl = TEMPLATES[primary.code]
    also = [TEMPLATES[f.code].short for f in diagnosis.findings[1:]]
    notes = [
        note
        for r in results or []
        if not r.ok and (note := PROBE_NOTES.get((r.name, str(r.error))))
    ]
    return Explanation(
        code=primary.code,
        severity=str(primary.severity),
        headline=tpl.headline,
        detail=tpl.detail,
        actions=list(tpl.actions),
        also=also,
        notes=notes,
        numbers=_numbers(primary),
    )
