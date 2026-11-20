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

## Empacotamento (Marco 6)

- **CustomTkinter + PyInstaller:** o wiki do CustomTkinter manda usar `--onedir` com `--add-data` manual. **Isso está desatualizado.** O `pyinstaller-hooks-contrib` hoje inclui `hook-customtkinter.py`, que coleta sozinho os dados da biblioteca (`collect_data_files("customtkinter")`). Então `--onefile --windowed` deve funcionar sem `--add-data`. Validar no build real.
- **Modo `--windowed`:** `sys.stdin`, `sys.stdout` e `sys.stderr` ficam `None` (PyInstaller 6.x, igual ao `pythonw.exe`).
  - Nenhum código pode usar `print` ou `sys.stderr.flush` sem checar antes.
  - Testar a UI com `pythonw.exe` antes de empacotar.
  - Nos `subprocess`, redirecionar todas as streams (`stdin=DEVNULL`, `capture_output=True`) e usar `CREATE_NO_WINDOW`.
- Versão de referência consultada: PyInstaller v6.22.3.

## IA (Marco 5)

- **Groq:** API compatível com OpenAI em `https://api.groq.com/openai/v1`. Dá para usar o SDK `openai` com `base_url` trocada, o que facilita trocar de provedor (Groq/OpenAI/Ollama).
- **Modelos:** listar com `GET https://api.groq.com/openai/v1/models`. A lista muda com frequência, então o modelo fica só em `NETDOCTOR_LLM_MODEL` e nunca fixo no código. Conferir a lista no momento do Marco 5.
