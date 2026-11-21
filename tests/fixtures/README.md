# Fixtures

Saídas de comandos usadas nos testes. Nenhum teste depende da rede real.

| Arquivo | Origem |
|---|---|
| `ping/pt_ok.txt`, `ping/pt_timeout.txt` | Capturadas no Windows 11 pt-BR (estendidas para 4 pacotes) |
| `ping/pt_partial_lt1ms.txt`, `ping/pt_unreachable.txt` | Montadas no formato pt-BR real |
| `ping/en_*.txt` | Montadas no formato en-US conhecido. **Substituir por capturas reais de um Windows em inglês.** |
| `adapter/wifi_with_virtualbox.json` | Capturada (script do `adapter.py`) e anonimizada |
| `adapter/*.json` (demais) | Derivadas da captura para cada cenário |

Anonimização: IPs locais trocados para `192.168.0.x` e DNS da operadora para `203.0.113.x` (faixa de documentação).

| Arquivo | Origem |
|---|---|
| `wifi/pt_connected.txt` | Capturada no Windows 11 pt-BR (`netsh wlan show interfaces`) e anonimizada (SSID, BSSID, MAC, GUID) |
| `wifi/pt_connected_weak.txt` | Mesma captura, com sinal/RSSI alterados |
| `wifi/pt_disconnected.txt`, `wifi/pt_no_interface.txt` | Montadas no formato pt-BR real |
| `wifi/*_location.txt` | **Montadas.** Não há texto oficial documentado; substituir por captura real com a Localização desligada |
| `wifi/en_*.txt` | Montadas no formato en-US conhecido. **Substituir por capturas reais.** |

### Modo Técnico

| Arquivo | Origem |
|---|---|
| `neighbors/pt_single.txt` | Capturada no Windows 11 pt-BR (`netsh wlan show networks mode=bssid`) e anonimizada (SSID, BSSID) |
| `neighbors/pt_multi.txt`, `neighbors/en_multi.txt` | **Montadas** no formato da captura, com a própria rede em duas bandas, 4 vizinhas e 1 oculta. A EN segue o formato en-US conhecido. |
| `hops/pt_ok.txt` | Capturada (`tracert -d -h 15 -w 500 1.1.1.1`) e anonimizada. IPs do caminho trocados por faixas de documentação, mantendo o tipo de cada salto (privado, CGNAT, público). |
| `hops/*` (demais) | **Montadas** no formato real (PT) e no formato en-US conhecido |
| `devices/*.json` | Formato do script de `devices.py` (`Get-NetNeighbor` → JSON). MACs da faixa de documentação da IANA (00-00-5E-00-53-xx) e um MAC aleatório fictício. Não depende do idioma. |
