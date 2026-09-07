# Инфраструктура

## Сервер
- Hostname: `evgencomp`, Ubuntu **26.04 LTS** x86_64
- Пользователь: `evgeniy` (uid 1001, группы: sudo, docker, users)
- Сеть: Wi-Fi `wlp1s0` = `192.168.0.107/24`, шлюз `192.168.0.1`; `eno1` DOWN
- Docker установлен (v29.6.1), есть bridge-сети `docker0`, `br-6ca68cbb5e74`
- Фаервол: **UFW active**, INPUT policy **drop**
- За NAT роутера; наружу публичный IP роутера проброшен на сервер (см. `~/.ssh/config` на Mac)

## Доступ (с Mac)
`~/.ssh/config` (локально на Mac):
```
Host homeserver
    HostName <PUBLIC_IP>
    Port <SSH_PORT>
    User evgeniy
    IdentityFile ~/.ssh/mac-home-server
    IdentitiesOnly yes
```
```bash
ssh homeserver            # в интерактиве
ssh homeserver 'cmd'      # одна команда (основной режим агентов)
```

## Файлы проекта (`~/vpn-tool` на сервере)
| Путь | Назначение |
|---|---|
| `vpn` | CLI (неинтерактивные команды; без аргументов запускает TUI) |
| `vpntool.py` | Общая логика (узлы, тесты, apply, статус) — stdlib |
| `vpntui.py` | Полноэкранный TUI на Textual (запускается через `.venv`) |
| `.venv/` | venv с `textual` (для TUI) |
| `vpn-on.sh` / `vpn-off.sh` | Вкл/выкл глобального VPN |
| `ssh-bypass.sh` | Маркировка входящего SSH + ip rule (обходит TUN, см. ниже) |
| `sing-box` | Бинарник sing-box (копия; основной в `/usr/local/bin`) |
| `sub_url` | URL подписки (одна строка) |
| `cache/sub.raw` | Сырой ответ подписки |
| `cache/sub.txt` | Base64-декодированный список `vless://` строк |
| `cache/nodes.json` | Распарсенные узлы (кэш; обновляется `refresh`) |
| `cache/results.json` | Результаты тестов по `host:port` (кэш для `list`) |
| `cache/history.jsonl` | История тестов (для `vpn history`) |
| `configs/singbox-last.json` | **Бекап последнего применённого конфига** |
| `docs/` | Эта база знаний (Obsidian) |

## Зависимости
- CLI и `vpntool.py` — чистый stdlib Python 3.
- TUI (`vpntui.py`) — пакет `textual`, установлен в venv:
  ```bash
  ~/vpn-tool/.venv/bin/python -c "import textual; print(textual.__version__)"
  ```
  pip/venv ставились через `sudo apt-get install python3-pip python3-venv`.
  Shebang `vpntui.py` указывает на `.venv/bin/python3` абсолютным путём.

## Системные компоненты
- Бинарник: `/usr/local/bin/sing-box` (v1.14.0, go1.26.7 linux/amd64; сборка с `with_quic, with_utls, with_reality…`)
- Конфиг: `/etc/sing-box/config.json` (root, генерируется CLI)
- Сервис: `/etc/systemd/system/sing-box.service`, **enabled** (автостарт)

```ini
[Service]
ExecStart=/usr/local/bin/sing-box run -c /etc/sing-box/config.json
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
NoNewPrivileges=true
LimitNOFILE=65535
[Install]
WantedBy=multi-user.target
```

## Сеть sing-box
- Интерфейс: `tun0`, адрес `172.19.0.1/30`, MTU 1500, стек `system`
- `auto_route: true`, `strict_route: true`
- ip rules: `9001` всё → таблица `2022` (default через tun), `9002` dport 53 → main, спец-правила для lo
- Таблица `2022` содержит разбитый default-маршрут через `172.19.0.2 dev tun0`, из которого «вырезаны»/исключены адреса узлов (см. route_exclude_address)

## SSH-bypass (входящий SSH мимо TUN)
Чтобы входящий SSH (`ssh homeserver`) работал, когда VPN на сервере включён,
ответы на SSH-соединения маршрутизируются **напрямую** (мимо tun), иначе уходят
в тун с IP узла → асимметричный маршрут → рукопожатие рвётся (см.
[[Networking-Troubleshooting]] п.8).

- nftables-таблица `inet vpn_ssh_bypass`: prerouting `tcp dport 22 → ct mark 0x1`,
  output `ct mark 0x1 → meta mark 0x1`.
- ip rule `8500: fwmark 0x1 lookup main` (pref < 9000, выигрывает у правил sing-box).
- Скрипт: `~/vpn-tool/ssh-bypass.sh` (`install|uninstall|status`).
- Юнит: `/etc/systemd/system/vpn-ssh-bypass.service` (oneshot, enabled — ставит
  правило при загрузке; независим от sing-box, переживает его restart).

```bash
sudo ~/vpn-tool/ssh-bypass.sh status
systemctl status vpn-ssh-bypass --no-pager
```

## Проверка здоровья
```bash
systemctl is-active sing-box                 # active
curl -s https://ipinfo.io/json | grep country  # должен быть не RU
~/vpn-tool/vpn status
```
