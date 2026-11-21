# Decisões e fatos verificados

Fatos confirmados na documentação oficial em 2026-11-20. Rever antes dos marcos 5 e 6.

## Marco 1: núcleo e CLI

- **Adaptador via PowerShell + JSON, não `ipconfig`.** `Get-NetAdapter`, `Get-NetIPAddress`, `Get-NetRoute` e `Get-DnsClientServerAddress` não exigem administrador. Status e MediaType vêm de enums, então não mudam com o idioma. Custo: cerca de 3 s de carga do PowerShell. O script vai via `-EncodedCommand` para evitar problemas de aspas. O JSON é normalizado porque o PowerShell 5.1 pode transformar uma lista de 1 item em objeto.
- **Adaptador ativo = rota padrão de menor métrica.** Adaptadores virtuais sem rota padrão (VirtualBox, Hyper-V) são ignorados, porque senão um host-only "Up" pareceria conexão.
- **Ping pela marca `TTL=`.** Só respostas válidas têm `TTL=` em qualquer idioma. "Host de destino inacessível" conta como perda, ao contrário das estatísticas do Windows, que contam como recebido. `<1ms` vira 1 ms (limite superior).
- **DNS direto a cada servidor (`dnspython`).** O resolvedor do sistema mistura todos os servidores e o cache. Consultando cada um separadamente dá para distinguir `DNS_FAIL` de `ISP_DOWN`.
- **HTTP com o teste NCSI do Windows + HTTPS 204**, sem seguir redirecionamentos, para enxergar o portal cativo.
- **Falha de probe ≠ fato negativo.** `ok=False` quer dizer "não deu para medir". O runner isola exceções e travamentos (timeout global de 30 s).
- **Ambiente:** `venv` + `pip` com `pyproject.toml`, porque o `uv` não está instalado na máquina. Dá para migrar para `uv` depois sem mudar o código. Venv em Python 3.12 por compatibilidade com o PyInstaller; o código suporta 3.11+.

## Marco 2: motor de regras

- **Regras puras sobre `Facts`.** `Facts.from_results` só aceita probes com `ok=True`. O que não foi medido vira `None` e nenhuma regra dispara por falta de dado.
- **Todas as regras rodam e o principal é o primeiro da cadeia.** As pré-condições impedem achados redundantes (ex.: com o gateway fora, `ISP_DOWN` não dispara). Achados de qualidade continuam aparecendo junto (`GATEWAY_DOWN` + `WIFI_WEAK`).
- **Desvios da tabela da especificação, todos com teste:**
  - `INCONCLUSIVE` (novo): quando `adapter`, `ping` ou `http` não mediu, não dá para afirmar `ALL_OK`.
  - `GATEWAY_DOWN` não dispara se a internet responde (alguns roteadores bloqueiam ping). Também dispara quando há IP válido mas nenhuma rota padrão.
  - `ISP_DOWN` exige que ping público **e** HTTPS falhem **e** que o NCSI não tenha recebido nenhuma resposta HTTP. Assim o portal cativo que bloqueia ping não é confundido com queda da operadora, mesmo vindo antes na cadeia.
  - `DNS_FAIL` só dispara se algum DNS público resolve. Também cobre o caso "nenhum DNS configurado".
  - `CAPTIVE_PORTAL`: redirecionamento ou conteúdo diferente no NCSI, ou erro de TLS no HTTPS (interceptação).
- **Limiares** em `netdoctor/core/thresholds.toml` (Wi-Fi fraco < 50%, perda no gateway ≥ 20%, média até o gateway ≥ 50 ms), com a justificativa em comentário. O arquivo vai como package data; no Marco 6 o PyInstaller precisa incluí-lo.
- **Ações** são códigos (`RESTART_ROUTER`, `CALL_ISP`...). O texto para leigos fica nos templates do Marco 3.
- `WIFI_WEAK` já está implementado e testado, mas só dispara de verdade quando a probe `wifi` existir (Marco 3).

## Marco 3: Wi-Fi, explicações offline e relatórios

- **Wi-Fi via `netsh wlan show interfaces`.** É o único caminho sem administrador e sem `ctypes` para ler o sinal. Os rótulos ficam numa tabela PT/EN, normalizados sem acento e comparados de forma exata, para que `SSID` não case com `AP BSSID`. Com mais de uma interface, vale a que está conectada. Em conexão por cabo a probe nem roda o `netsh` (`skipped: not_wifi`).
- **Fato verificado na captura real (Windows 11 pt-BR):** o `netsh` escreve **UTF-8** quando a saída é redirecionada, enquanto o `ping` escreve cp850. Por isso `proc.decode_output` tenta UTF-8 estrito e cai para OEM.
- **Localização (24H2+).** A doc oficial da Microsoft ("Changes to API behavior for Wi-Fi access and location", atualizada em 2025-06-06) lista as APIs `wlanapi` afetadas (`WlanQueryInterface` com `current_connection` devolve `ERROR_ACCESS_DENIED`), mas não cita o `netsh` nem o texto exato da mensagem. A detecção é por palavras-chave ("location"+"permission" / "localização"+"permiss") → `LOCATION_PERMISSION`. A explicação orienta ativar Configurações > Privacidade e segurança > Localização. **Os textos dos exemplos de Localização em PT e EN foram montados, não capturados: substituir por capturas reais.**
- **Wi-Fi sem leitura ≠ Wi-Fi fraco.** Localização negada, sem interface ou timeout viram `ok=False`, e a regra `WIFI_WEAK` não dispara.
- **Templates pt-BR** em `explain/templates.py`: frase de causa + detalhe + 1–3 ações + rótulo curto para achados secundários ("Também notamos: …"). Um teste barra jargão (gateway, DNS, DHCP, IP, ping, latência...). Os números da evidência aparecem em linguagem simples (ex.: "Força do sinal: 38%").
- **Relatório HTML autocontido.** Um arquivo só, CSS embutido, tema claro/escuro, nenhum recurso externo (testado). Todo valor passa por `html.escape`, porque o SSID é texto de terceiros (testado com `<script>`). Rodapé avisando que o arquivo contém dados da rede local. O JSON inclui diagnóstico, explicação e fatos brutos.

## Marco 4: interface do Modo Cliente

- **CustomTkinter (6.0.0 instalado; API conferida na documentação oficial).** É leve, roda sobre o Tkinter que já vem com o Python e tem tema claro/escuro automático e escala HiDPI no Windows. O PyInstaller já tem hook oficial para ele (ver Marco 6). Alternativas descartadas: PySide6/Qt (ótimo, mas acrescenta ~60–100 MB ao `.exe` e a licença LGPL complica o empacotamento) e Tkinter puro (visual datado para um projeto de portfólio).
- **Três camadas:** `presenter.py` (texto e cores, sem Tk), `worker.py` (thread do diagnóstico que fala com a tela por uma fila) e `app.py` (só widgets). O Tk só é tocado pela thread principal: a janela lê a fila a cada 100 ms com `after()`. As duas primeiras camadas têm testes, sem abrir janela.
- **Progresso real por etapa.** O runner ganhou `on_done(resultado)`, além de `on_progress(nome)`, e a tela marca ✔ em cada teste conforme termina, em vez de só uma mensagem genérica.
- **"Copiar resumo" não leva dados da rede.** Leva só o texto da explicação, os códigos e a data, para colar no WhatsApp ou e-mail (testado). O nome do Wi-Fi e os endereços ficam no relatório salvo, que o usuário escolhe enviar.
- **"Salvar relatório"** grava o HTML (para pessoas) e um `.json` com o mesmo nome (para o suporte).
- **Verificado com `pythonw.exe`** (sem console, igual ao `.exe --windowed`): a janela abre, diagnostica, mostra o resultado e copia o resumo. `_ensure_std_streams()` cobre `sys.stdout`/`stderr` vazios (`None`).
- **Fora deste marco:** o botão de teste de velocidade. A fonte do teste ainda está em aberto na especificação (termos de uso de cada serviço). O botão "Enviar ao suporte" fica para depois; na v1 é salvar/copiar.

## Marco 5: IA opcional

- **Sem SDK, só `urllib`.** Groq, OpenAI e Ollama aceitam `POST {base_url}/chat/completions` no formato da OpenAI (conferido na documentação oficial: base da Groq `https://api.groq.com/openai/v1`; Ollama `http://localhost:11434/v1`, que aceita `response_format` `json_object` e ignora a chave). Assim o `.exe` não ganha dependência nova e a troca de provedor é só configuração. O limite de tokens não é enviado: Groq e OpenAI preferem `max_completion_tokens`, o Ollama usa `max_tokens`, e a resposta já é curta pelo prompt.
- **Privacidade por allowlist, não por denylist.** `build_llm_payload` monta o JSON só com código, gravidade, tipo de conexão (`wifi`/`ethernet`), uma lista fechada de campos de evidência (sinal %, perda %, ms, códigos de erro) e o texto do template como base. Um campo novo com identificador **não vaza por esquecimento**. Testado com todos os identificadores preenchidos (SSID, BSSID, MAC, IPs, hostname, host do portal, nome do adaptador) e verificado de ponta a ponta com um servidor falso local e os dados reais desta máquina: 7 identificadores reais checados, nenhum enviado.
- **A IA só reescreve.** Recebe o diagnóstico decidido e o texto do template; devolve `{"headline", "actions"}`. O detalhe, os números, "Também notamos" e as observações continuam vindo do template. A resposta é validada (frase não vazia, 1–3 ações, até 220 caracteres) e qualquer desvio cai no template.
- **Fallback silencioso.** Sem configuração, chave ausente, HTTP 401/429, timeout (padrão 8 s), sem rede, JSON inválido → template. O usuário nunca vê erro de IA. Com IA configurada mas inalcançável, o diagnóstico só demora até o timeout.
- **Sem internet, sem chamada à nuvem.** Se o achado principal é de "sem internet" (`NO_LINK` … `CAPTIVE_PORTAL`), o provedor na nuvem nem é chamado (seria só esperar o timeout). Um Ollama local continua sendo usado.
- **Transparência.** Quando a IA reescreve, a tela, o texto da CLI e o HTML mostram "Texto reescrito por IA a partir do diagnóstico automático." O JSON registra `explanation.source = "llm"`.
- **Configuração:** variáveis `NETDOCTOR_LLM_*`, que têm prioridade, ou um `.env` na pasta atual ou em `%APPDATA%\NetDoctor\.env` (onde o `.exe` vai procurar). Leitor de `.env` próprio, sem `python-dotenv`. `.env.example` vem com `PROVIDER=none` e é o único commitado. `--sem-ia` na CLI desliga a IA.
- **Fluxo único** em `netdoctor/pipeline.py`, usado pela CLI e pela interface (antes estava duplicado).
- **Não verificado:** chamada a um provedor real (Groq/OpenAI/Ollama), porque não há chave nesta máquina. A lista de modelos da Groq muda; o modelo fica só no `.env`.

## Empacotamento (Marco 6)

- **CustomTkinter + PyInstaller:** o wiki do CustomTkinter manda usar `--onedir` com `--add-data` manual. **Isso está desatualizado.** O `pyinstaller-hooks-contrib` hoje inclui `hook-customtkinter.py`, que coleta sozinho os dados da biblioteca (`collect_data_files("customtkinter")`). Então `--onefile --windowed` deve funcionar sem `--add-data`. Validar no build real.
- **Modo `--windowed`:** `sys.stdin`, `sys.stdout` e `sys.stderr` ficam `None` (PyInstaller 6.x, igual ao `pythonw.exe`).
  - Nenhum código pode usar `print` ou `sys.stderr.flush` sem checar antes.
  - Testar a UI com `pythonw.exe` antes de empacotar.
  - Nos `subprocess`, redirecionar todas as streams (`stdin=DEVNULL`, `capture_output=True`) e usar `CREATE_NO_WINDOW`.
- Versão de referência consultada: PyInstaller v6.22.3.

### O que foi feito e verificado no build real

- **PyInstaller 6.22.3 fixo** (extra `build`), com `pyinstaller-hooks-contrib` 2026.10. O hook do customtkinter funcionou: `--onefile` sem `--add-data`, e o dnspython também tem hook.
- **Dois executáveis de arquivo único** a partir de [`packaging/netdoctor.spec`](../packaging/netdoctor.spec): `NetDoctor.exe` (interface, `console=False`, 12,9 MB) e `netdoctor-cli.exe` (console, 9,4 MB). O `.spec` é commitado (o `.gitignore` ignora só `build/` e `dist/`).
  - `onefile`, e não `onedir`, porque o público é leigo: um arquivo para baixar e clicar.
  - `onedir` abriria mais rápido, mas exige descompactar uma pasta.
- **Dados do pacote** entram por `collect_data_files("netdoctor")`: `core/thresholds.toml`, lido com `importlib.resources`, e `ui/netdoctor.ico`. Eles também estão no `package-data` do `pyproject.toml`, para a instalação via pip funcionar igual. Há um teste que garante isso.
- **Ícone** gerado por script (`packaging/make_icon.py`, Pillow só na hora de gerar), aplicado ao `.exe` e à janela. A janela chama `iconbitmap` no `__init__`, porque o CTk 6.0.0 troca pelo ícone dele após 200 ms se ninguém chamou antes. Conferi isso no código instalado (`ctk_tk.py`).
- **Informações de versão do Windows** (Propriedades > Detalhes) montadas no `.spec` com `VSVersionInfo`, a partir de `netdoctor.__version__`. Por isso a versão precisa ser `X.Y.Z` (há teste).
- **Sem UPX:** compactar o `.exe` com UPX aumenta os falsos positivos de antivírus.
- **Exclusões** (`pytest`, `PIL`, `numpy`, `unittest`…) para o `.exe` não levar o que só serve ao desenvolvimento.
- **Sem assinatura digital.** Um certificado de assinatura de código custa caro para um projeto pessoal. O README explica o aviso do SmartScreen e o release publica `SHA256SUMS.txt` para conferir o arquivo.
- **GitHub Actions:**
  - `ci.yml` roda lint e testes em `windows-latest` a cada push ou PR.
  - `release.yml` dispara com a tag `v*`. Ele confere se a tag bate com `__version__`, testa, gera os `.exe`, roda `netdoctor-cli.exe --help` como teste rápido e publica com `gh release create` (o `gh` vem no runner; o token é o `GITHUB_TOKEN`, com `contents: write`). Não usa action de terceiros para publicar.
- **Verificado nesta máquina:**
  - `netdoctor-cli.exe diagnose --sem-ia --html … -o …` levou 11 s.
  - As 5 probes deram ok, o diagnóstico foi ALL_OK, os limiares foram lidos de dentro do `.exe` e o HTML e o JSON foram gravados.
  - Nas propriedades do arquivo aparecem a descrição, a versão e o copyright.
  - `NetDoctor.exe` abre a janela com o ícone novo.
- **Não verificado:**
  - O clique em Diagnosticar dentro do `NetDoctor.exe`: o teste da janela fica com o Bruno.
  - Os workflows rodando no GitHub (repositório ainda não publicado).
  - O aviso do SmartScreen num computador limpo.

## Marco 7: Modo Técnico

- **Só pela linha de comando (`netdoctor tech`).** Quem usa é o técnico, a especificação pede um "laudo exportável" e a interface do Modo Cliente continua com um botão só. O botão na interface fica para depois, porque precisa ser testado com a janela aberta.
- **Mesmo fluxo do cliente:** `run_pipeline(tech=True)` roda as 5 probes do cliente e as 3 técnicas em paralelo, com tempo limite de 37 s (o `tracert` domina). O diagnóstico do cliente não muda; o relatório ganha a chave `tech`. A IA recebe exatamente o mesmo payload do Modo Cliente (testado).
- **Redes vizinhas sem identificar ninguém.**
  - `netsh wlan show networks mode=bssid` só lê a lista que o Windows já tem.
  - O SSID das redes é usado só para marcar quais pontos de acesso são da própria rede (as duas bandas e os nós de mesh) e é descartado. Nome e BSSID de vizinhos nunca entram no relatório (há teste).
  - Isso atende ao anti-objetivo "não varrer redes de terceiros": medimos o espectro, não as redes dos outros.
- **Canal:**
  - Em 2,4 GHz, canais de 20 MHz se sobrepõem a menos de 5 canais de distância. Em 5 GHz conta só o mesmo canal; canais de 40/80 MHz não são considerados (limitação).
  - "Forte" = sinal ≥ 50%, a mesma régua do Wi-Fi fraco.
  - A sugestão de canal se limita a 1/6/11 e aos de 5 GHz sem DFS permitidos no Brasil (36–48, 149–161). Só sugere se o canal novo for estritamente melhor.
  - A utilização do canal vem do BSS Load que o roteador anuncia ("Utilização do canal: 0 (0 %)"), quando há.
- **Aparelhos:** `Get-NetNeighbor`, e não `arp -a`, porque o estado vem como número de enum e não muda com o idioma.
  - Filtra multicast, broadcast, endereços fora da sub-rede, entradas mortas (Unreachable/Incomplete) e MAC zerado.
  - O nome do adaptador vai ao PowerShell por variável de ambiente (`env_extra` em `run_command`), nunca colado no script (há teste com um nome malicioso).
  - O MAC aleatório (bit de administração local) é sinalizado, porque explica "aparelhos desconhecidos", que costumam ser celulares.
- **Saltos:** `tracert -d -h 15 -w 500 1.1.1.1`.
  - `-d` evita resolver nomes: mais rápido e sem hostnames no laudo.
  - O parsing usa o número do salto, as três colunas "N ms"/"<1 ms"/"*" e o IP, igual em PT e EN.
- **Análise de rota:**
  - Perda ou latência só contam se começam num salto e **persistem até o destino**. Um salto do meio que some depois é só ICMP com baixa prioridade.
  - Local × operadora se decide pelo IP do roteador (o gateway). A rede real desta máquina mostrou CGNAT (100.64/10) e IPs privados dentro da operadora, então a faixa de IP não serve para isso.
  - Latência: +60 ms em relação ao roteador. Perda: ≥ 20%.
  - Não chegar ao destino é só informativo.
- **Verificado nesta máquina:** `netdoctor tech --html … -o …` (código-fonte, só no terminal) levou 12,6 s.
  - As 8 probes deram ok: canal 36 sem disputa, 8 saltos sem problema, 4 aparelhos (1 com MAC aleatório).
  - O HTML tem todas as seções e nenhum recurso externo.
- **Fixtures:** `pt_single` (redes) e `pt_ok` (tracert) foram capturados aqui e anonimizados. Os IPs do caminho foram trocados por faixas de documentação, mantendo o tipo de cada salto. Os MACs usam 00-00-5E-00-53-xx, a faixa de documentação da IANA.
- **Não verificado:**
  - As saídas EN e o caso com várias redes vizinhas, que foram montados.
  - Rede com canal congestionado de verdade.
  - Perda real na operadora.
  - `netdoctor-cli.exe tech` no `.exe` (o `.exe` não foi gerado de novo neste marco).

## Redesign do relatório e da janela

Feito com os princípios de design engineering (Emil Kowalski) que cabem em cada meio.

- **Relatório HTML:**
  - Continua um arquivo só, sem recurso externo e sem JavaScript (o teste barra `<script src`, `<link`, `http(s)://`, `@import` e `url(` antes do JSON bruto). Por isso a fonte é a do sistema (Segoe UI no Windows) e o sumário usa âncoras.
  - Cores como variáveis em `:root`, trocadas por `prefers-color-scheme: dark` só na tela (`@media screen`), então a impressão sai sempre clara. `color-scheme: light dark` deixa barras de rolagem e controles no tema certo.
  - Escala de espaçamento fixa (4/8/12/16/24/32/48 px) e pesos de fonte em variáveis.
  - Ordem de leitura: resultado → achados → laudo → testes → JSON. O resultado tem barra lateral na cor da gravidade, selo com ícone + palavra (nunca só cor) e "O que fazer" em passos numerados.
  - Tabelas com `<thead>`/`scope="col"`, números alinhados à direita com `tabular-nums`, vazio como "—" esmaecido. Cada tabela fica num `role="region"` com `aria-label` e `tabindex="0"`, então rola de lado pelo teclado no celular sem empurrar a página.
  - Evidência dos achados como pares `chave: valor` em vez de um JSON numa célula (cada parte passa por `html.escape`).
  - Foco visível em cinza/texto (`:focus-visible`), alvos de toque de 36–44 px, hover só em `(hover: hover) and (pointer: fine)`, `scroll-margin-top` nas âncoras, `text-wrap: balance` nos títulos.
  - A única animação é a seta do `<details>` (rotação, 200 ms, ease-out), só com `prefers-reduced-motion: no-preference`. Nada de `transition: all`.
  - Celular (≤ 600 px): o ícone grande some (o selo já tem ícone), o sumário vira uma linha que rola de lado e as tabelas usam a largura toda.
  - Data em formato brasileiro com o fuso gravado (`<time datetime>` guarda o ISO original).
  - Conferido com dados falsos dos testes no painel de navegador: claro e escuro a 1100–1200 px e escuro a 375 px, sem rolagem horizontal da página.
- **Janela (CustomTkinter 6.0.0), segunda versão.** O Bruno achou que a primeira versão ainda tinha "cara de IA". O HTML ficou como estava; a janela foi refeita com outra direção: **utilitário do Windows, não página de produto**.
  - **Fonte do sistema.** O tema padrão do CustomTkinter usa Roboto; agora é Segoe UI (Semibold nos títulos), a fonte do próprio Windows.
  - **Cores do sistema do Windows 11** (neutros #f3f3f3/#202020, destaque #005fb8/#60cdff, estados de sucesso, cuidado e erro do Fluent), em vez da paleta de "SaaS".
  - **Sem cartão nem selo.** O conteúdo fica direto no fundo da janela, entre duas linhas finas. A gravidade é uma faixa de cor de 4 px ao lado do resultado mais a palavra (Normal, Atenção, Problema).
  - **Sem emoji ou símbolos decorativos** (✔ ⚠ ✖ ○ …). Há teste que barra esses símbolos nos textos da janela.
  - **Etapas com status de verdade:** cada linha mostra o resultado da própria probe ("ok", "não mediu", "não se aplica" no cabo, "testando…"), em vez de um ícone de progresso. Para isso o worker passa o `ProbeResult` no evento `finished`.
  - **Layout de caixa de diálogo:** botões embaixo, com o principal (Diagnosticar) à direita; versão e mensagens de status à esquerda; cantos de 4 px; Enter aciona o principal.
  - **Textos diretos:** "Teste da conexão" em vez de "Vamos testar sua internet?", e sem slogan.
  - Não muda: thread do worker + fila + `after(100)`, Salvar grava HTML e `.json`, o resumo copiado não leva nenhum identificador da rede.
  - `tests/test_ui_app.py` monta a janela de verdade com widgets falsos. Eles aceitam só os parâmetros da assinatura do widget instalado, então um parâmetro errado quebra o teste. O teste passa por esperando → testando → resultado → copiar, e pelo erro. **A janela em si não foi aberta**: falta conferir à vista.
  - As capturas em `docs/img/` são da janela antiga e precisam ser refeitas.

## IA (Marco 5)

- **Groq:** API compatível com OpenAI em `https://api.groq.com/openai/v1`. Dá para usar o SDK `openai` com `base_url` trocada, o que facilita trocar de provedor (Groq/OpenAI/Ollama).
- **Modelos:** listar com `GET https://api.groq.com/openai/v1/models`. A lista muda com frequência, então o modelo fica só em `NETDOCTOR_LLM_MODEL` e nunca fixo no código. Conferir a lista no momento do Marco 5.
