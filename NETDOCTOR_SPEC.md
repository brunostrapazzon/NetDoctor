# NetDoctor — Especificação do projeto

> Autor do projeto: Bruno Strapazzon (GitHub: brunostrapazzon).

## 1. O que é e por quê

NetDoctor é uma ferramenta para Windows que **diagnostica problemas de internet e explica a causa em português simples**.

Nasce de uma dor real: o autor trabalha há ~3 anos com suporte de TI e redes num representante de provedor de internet (≈100 clientes atendidos, ≈20 redes configuradas). A maior parte dos chamados "minha internet não funciona" é Wi-Fi fraco, roteador travado ou DNS, não falha da operadora — e descobrir isso exige um técnico.

É um **projeto de portfólio**: precisa funcionar de verdade, ser fácil de testar por qualquer pessoa e mostrar com clareza IA + automação + redes para recrutadores.

## 2. Objetivos, não-objetivos e anti-objetivos

**Objetivos**
- Modo Cliente: um clique, resultado em linguagem leiga, uma ação recomendada.
- Modo Técnico: varredura mais profunda e laudo técnico exportável.
- Relatório técnico gerado em ambos os modos (para enviar ao suporte).
- Distribuível como `.exe` que roda sem instalar Python.

**Não-objetivos (v1)**
- macOS/Linux (arquitetura deve permitir no futuro, mas não implementar agora).
- Acesso ao painel/admin do roteador, alteração de configurações, correção automática.
- Conta de usuário, servidor, banco de dados na nuvem.

**Anti-objetivos (seria fracasso mesmo funcionando)**
- A IA decidir o diagnóstico. **O diagnóstico vem de regras determinísticas e testáveis; a IA só redige a explicação.**
- Não funcionar quando a internet está fora — que é justamente quando o usuário precisa. **Tudo precisa funcionar offline**; a IA é um extra opcional.
- Enviar dados pessoais para terceiros (senhas, nome da rede, MACs, IPs públicos) sem o usuário saber.
- Varrer redes de terceiros. O Modo Técnico só analisa a rede à qual o computador está conectado.

## 3. Restrições

- Python 3.11+, Windows 10/11 como alvo.
- O autor tem pouco tempo por semana: entregar em marcos pequenos, cada um utilizável sozinho.
- Windows em português **e** em inglês: a saída de `netsh`, `ping`, `ipconfig` é traduzida conforme o idioma do sistema. Parsers precisam suportar os dois (ex.: `Signal`/`Sinal`, `Channel`/`Canal`). Preferir APIs/bibliotecas a parsing de texto quando houver alternativa confiável.
- Windows 11 24H2+: comandos `netsh wlan` podem exigir permissão de Localização ativada para mostrar SSID/BSSID. Detectar esse caso e orientar o usuário em vez de quebrar. (Verificar o comportamento atual na documentação da Microsoft.)
- Não exigir privilégios de administrador no Modo Cliente.

## 4. Arquitetura

```
netdoctor/
├── core/
│   ├── probes/          # coletam fatos (um arquivo por teste)
│   │   ├── adapter.py   # adaptador ativo, tipo (Wi-Fi/cabo), IP local, gateway, DNS configurado
│   │   ├── wifi.py      # sinal (%), canal, banda, padrão (netsh wlan show interfaces)
│   │   ├── ping.py      # latência e perda: gateway, IP externo (1.1.1.1 e 8.8.8.8)
│   │   ├── dns.py       # resolução via DNS configurado vs. DNS público, tempo de resposta
│   │   ├── http.py      # consegue abrir HTTPS? (detecta portal cativo / bloqueio)
│   │   └── speed.py     # velocidade de download/upload (opcional, pode demorar)
│   ├── rules.py         # motor de regras: fatos -> achados (findings)
│   ├── models.py        # dataclasses: ProbeResult, Finding, Diagnosis
│   └── runner.py        # executa probes com timeout, em paralelo quando possível
├── explain/
│   ├── templates.py     # explicações offline (pt-BR) por código de achado
│   └── llm.py           # explicação via LLM (opcional, com fallback para templates)
├── report/
│   ├── json_report.py
│   └── html_report.py   # relatório técnico autocontido (um arquivo .html)
├── tech/                # Modo Técnico (Marco 6)
│   ├── neighbors.py     # redes vizinhas e congestionamento de canal
│   ├── devices.py       # dispositivos na rede local (tabela ARP, passivo)
│   └── hops.py          # latência por salto (tracert)
├── ui/
│   └── app.py           # interface gráfica
└── cli.py               # `netdoctor diagnose`, `netdoctor tech`, `--json`
tests/
├── fixtures/            # saídas reais capturadas de netsh/ping/ipconfig (PT e EN)
└── ...
```

### Fluxo
1. `runner` executa as probes → lista de `ProbeResult` (fatos brutos + erro, se houver).
2. `rules` transforma fatos em `Finding` (código, severidade, evidência, ação recomendada).
3. `explain` gera o texto para leigos: templates sempre; LLM se houver chave e internet.
4. `report` gera JSON + HTML técnico.
5. `ui`/`cli` mostram o resultado.

### Motor de regras (árvore de decisão inicial)
A ordem importa — o primeiro ponto de falha na cadeia é a causa provável:

| Situação | Código | Causa provável para o leigo |
|---|---|---|
| Sem adaptador ativo / cabo desconectado / Wi-Fi desligado | `NO_LINK` | Computador não está conectado à rede |
| Sem IP válido (169.254.x.x) | `NO_DHCP` | Roteador não entregou endereço — reiniciar roteador |
| Gateway não responde | `GATEWAY_DOWN` | Problema no roteador ou no Wi-Fi |
| Gateway OK, IP externo falha | `ISP_DOWN` | Internet da operadora fora — ligar para o suporte |
| IP externo OK, DNS configurado falha, DNS público OK | `DNS_FAIL` | Problema de DNS — orientação de troca |
| HTTPS redireciona/bloqueado | `CAPTIVE_PORTAL` | Rede exige login |
| Sinal Wi-Fi < limiar | `WIFI_WEAK` | Sinal fraco neste local |
| Perda/latência alta já no gateway | `LOCAL_INTERFERENCE` | Interferência ou roteador sobrecarregado |
| Tudo OK | `ALL_OK` | Conexão normal — problema pode ser no site/app |

Limiares (sinal, latência, perda) ficam em um arquivo de configuração, com valores iniciais justificados em comentário. Um diagnóstico pode ter vários achados; o principal é o primeiro da cadeia.

### IA (explain/llm.py)
- Provedor inicial: Groq (API compatível com OpenAI). Modelo configurável via `.env` (`NETDOCTOR_LLM_MODEL`); verificar no console da Groq quais modelos estão disponíveis no momento.
- Interface com provedor trocável (Groq, OpenAI, Ollama local).
- **Entrada da IA:** apenas o diagnóstico já decidido (códigos, números, severidade). Nunca SSID, MAC, IP público, nome do computador.
- Prompt pede: 1 frase de causa, 1–3 ações, sem jargão, sem inventar causas fora dos achados.
- Timeout curto; em qualquer falha, usa o template. O usuário nunca vê erro de IA.

### Interface (Modo Cliente)
```
┌─────────────────────────────────────────┐
│  NetDoctor            [ Diagnosticar ]  │
├─────────────────────────────────────────┤
│  ⚠ Seu Wi-Fi está fraco neste cômodo.   │
│  A internet da operadora está normal.   │
│                                         │
│  O que fazer: aproxime-se do roteador   │
│  ou use cabo. Se continuar, envie o     │
│  relatório ao suporte.                  │
│                                         │
│  [ Salvar relatório ]  [ Copiar resumo ]│
└─────────────────────────────────────────┘
```
- Progresso visível enquanto testa ("Testando o roteador…").
- Teste de velocidade opcional (botão separado), porque demora.
- Biblioteca de GUI: escolha do builder (sugestão: CustomTkinter, por ser leve e empacotar bem com PyInstaller). Justificar a escolha no README.

## 5. Marcos (entregar e commitar um por vez)

1. **Núcleo + CLI:** probes `adapter`, `ping`, `dns`, `http`; `netdoctor diagnose --json` funciona.
2. **Regras + testes:** motor de regras com a tabela acima; testes com fixtures PT e EN; cada regra com teste.
3. **Wi-Fi + explicações offline:** probe `wifi`, templates pt-BR, relatórios JSON e HTML.
4. **Interface do Modo Cliente.**
5. **IA opcional** com fallback; `.env.example`; nada de chave no repositório.
6. **Empacotamento:** `.exe` via PyInstaller, GitHub Actions gerando o executável em release.
7. **Modo Técnico:** vizinhos/canais, dispositivos (ARP passivo), saltos, laudo HTML.

Cada marco termina com: testes passando, README atualizado, commit.

## 6. Qualidade e portfólio

- Testes com `pytest`; probes testadas com fixtures (sem depender da rede real). CI no GitHub Actions rodando os testes.
- Lint/format com `ruff`.
- Sem segredos no repositório; `.gitignore` cobrindo `.env`.
- **README** (português, com seção resumida em inglês para vagas remotas internacionais):
  - o problema, em 3 linhas, com a história do suporte técnico
  - GIF/vídeo curto do Modo Cliente
  - como baixar o `.exe` e usar
  - diagrama da arquitetura (probes → regras → explicação)
  - por que a IA não decide o diagnóstico (decisão de design)
  - privacidade: o que é coletado e o que vai para a IA
  - limitações conhecidas e roadmap
- Licença PolyForm Noncommercial 1.0.0: uso não comercial livre; uso comercial sob licença do autor.

## 7. Em aberto (decidir com o Bruno, não assumir)

- Nome final e se o repositório será público desde o início.
- Se haverá teste com clientes reais da AC Informática (para métricas do post no LinkedIn).
- Botão "Enviar ao suporte": na v1 é salvar/copiar; envio direto (e-mail/WhatsApp) fica para depois.
- Fonte do teste de velocidade (verificar termos de uso de cada serviço antes de escolher).

## 8. Fica a critério do builder

Estrutura interna das classes, bibliotecas auxiliares, paralelismo das probes, estilo visual da interface — desde que respeitem as seções 2 e 3. Registrar decisões relevantes em `docs/decisions.md`.
