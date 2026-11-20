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
