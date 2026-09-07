# Онбординг для следующего агента

Прочитай **этот файл первым**, затем [[Home]] → карту и нужные разделы. Работа идёт удалённо с Mac через SSH; рабочая папка проекта — на сервере.

## 1. Как подключиться
```bash
ssh homeserver 'cmd'          # разовые команды
ssh homeserver                # интерактив (редко)
```
Конфиг SSH на Mac уже есть (`~/.ssh/config`, Host `homeserver`). Никаких паролей к SSH — только ключ.

## 2. Собрать контекст (всегда сначала)
```bash
ssh homeserver '~/vpn-tool/vpn status'      # active? egress?
ssh homeserver '~/vpn-tool/vpn list'        # узлы + прошлые результаты
ssh homeserver 'systemctl status sing-box --no-pager | head -15'
```
Свежие факты о сервере/путях/сети: [[Infrastructure]]. Свежие результаты узлов: [[Subscription-Nodes]].

## 3. Правила безопасности при работе
- Сначала прочитай [[Networking-Troubleshooting]] — там 4 «подводных камня», которые уже ломали сеть (UFW tun0, self-loop, DNS-формат, reality-в-tls).
- Пароль sudo для агентов: файл `~/.sudo_password` (chmod 600). Команда:
  ```bash
  ssh homeserver 'echo "$(<пароль из ~/.sudo_password>)" | sudo -S <cmd>'   # или через скрипты, которые сами читают файл
  ```
  Не выводи пароль в чат/логи без необходимости. Подробнее: [[Security]].
- Не удаляй `ufw allow in on tun0` и не запускай несколько sing-box одновременно (конфликт портов тестов).

## 4. Типовые операции
| Задача | Команда |
|---|---|
| Переключить VPN на узел | `~/vpn-tool/vpn use <n\|auto>` |
| Обновить подписку | `~/vpn-tool/vpn refresh` |
| Перетестировать узлы | `~/vpn-tool/vpn test all` (~1 мин) |
| Скорость узла | `~/vpn-tool/vpn speed <n>` |
| Выключить VPN (прямой инет) | `~/vpn-tool/vpn-off.sh` |
| Включить | `~/vpn-tool/vpn-on.sh` |
| Полный откат конфига | `sudo cp ~/vpn-tool/configs/singbox-last.json /etc/sing-box/config.json && sudo systemctl restart sing-box` |

Детали всех команд и как устроен `auto`: [[CLI-Usage]].

## 5. Признаки проблем → что делать
- `curl -s https://ipinfo.io/json` показывает **RU** или сайты 403 → VPN не на том узле → `vpn use auto` / `test all`.
- `systemctl is-active sing-box` = `failed`/`activating` → смотреть `journalctl -u sing-box -n 50` (нужен sudo); вероятно конфиг: проверь синтаксис `sing-box check -c /etc/sing-box/config.json`.
- Трафик через тун молчит при active → п.1 [[Networking-Troubleshooting]] (UFW!) и п.2 (route_exclude).
- Ты «потерял» сеть → `ssh homeserver 'systemctl stop sing-box'` (SSH на LAN/проброшенный порт не зависит от tun; вход по `homeserver` идёт на публичный IP роутера → останется доступен).

## 6. Что НЕ трогать без нужды
- `/etc/sing-box/config.json` руками (если не понимаешь генерацию); правильный путь — `vpn use …`.
- Правила UFW для tun0.
- `sub_url`, `cache/*` — приватные данные.

## 7. После работы
Обнови базу знаний: минимум [[Changelog]] (что сделал/сломал), при изменениях команд/архитектуры — соответствующие заметки. Правила в [[Roadmap]] («Как вливать изменения»).
