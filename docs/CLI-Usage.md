# CLI и скрипты

## CLI `~/vpn-tool/vpn` (python3)

Код разделён: общая логика в `vpntool.py` (stdlib), CLI — тонкая обёртка
`vpn`, полноэкранный TUI — `vpntui.py` (зависит от `textual`, ставится в
`.venv/`).

### Интерактивный режим (TUI на Textual)
```bash
~/vpn-tool/vpn          # нужен настоящий терминал (SSH в интерактиве / tmux)
```
Полноэкранный интерфейс на [Textual](https://textual.textualize.io)
(ставится в venv `.venv/`). Вверху — статусная строка: `VPN: ВКЛ/ВЫКЛ`,
к какому узлу подключен (`target`) и текущий egress (страна/IP). Навигация
стрелками; UI не блокируется во время операций (асинхронно + спиннер).

Клавиши:
| Клавиша | Действие |
|---|---|
| `↑` / `↓` (или `j` / `k`) | выбор узла |
| `Enter` | **подключиться** к выбранному узлу |
| `p` | ping выбранного узла (с анимацией) |
| `P` | ping всех узлов (по очереди, живое обновление) |
| `t` | полный тест выбранного узла (реальный egress) |
| `s` | speedtest выбранного узла (10 МБ) |
| `a` | подключить `auto` (urltest) |
| `b` | подключить `best` (лучший зарубежный) |
| `o` | **вкл/выкл VPN** (systemctl start/stop sing-box) |
| `r` | обновить подписку |
| `g` | обновить статус |
| `q` | выход |

Раскраска узлов: зелёный — рабочий зарубежный, жёлтый — egress RU,
красный — недоступен. Текущий узел помечается `●` и жирным.

### Неинтерактивные команды (для агентов/скриптов)
```bash
vpn list                 # таблица узлов + кэш результатов
vpn refresh              # обновить подписку
vpn pingall              # рукопожатия по всем
vpn test [n|all]         # полный тест (по умолчанию all, ~10 с вместо ~3.5 мин)
vpn speed <n>
vpn use <n|auto|best>
vpn status               # active + target + egress (IP/country)
vpn history              # история тестов
vpn autocheck            # тест всех + восстановление при деградации (для cron)
vpn cron install|remove  # поставить/снять ежечасную авто-проверку
```

### Что делает `use auto`
1. Собирает конфиг: `direct` + **все** узлы (tags `n0..n14`) + urltest `auto`.
2. В urltest `auto` включает **только** узлы, у которых в `results.json` есть `exit_ip` и `country != "RU"` (сейчас это n2, n13).
3. Пишет `/etc/sing-box/config.json` (через `sudo`), делает `systemctl restart sing-box`.
4. Проверяет active + egress через api.ipify.org. При неудаче — откат из `configs/singbox-last.json`.
5. Сохраняет успешный конфиг в `configs/singbox-last.json`.

### Что делает `use best`
Выбирает лучший рабочий зарубежный узел из `results.json` и применяет его
**статично** (single outbound, без urltest). Ранжирование: сначала узлы с
измеренной скоростью (выше Mbps = лучше), затем по минимальной задержке
выхода (`exit_ms`). В отличие от `auto`, `best` — фиксированный узел: при его
падении интернета нет до ручного переключения (fail-closed).

### Что делает `autocheck` (для cron)
1. Прогоняет `test all` (параллельно).
2. Читает текущий egress-country через ipinfo.
3. Если egress = RU или недоступен → восстанавливает: `use auto`, при неудаче `use best`.
4. Логирует по шагам; exit-code 1 при неудачном восстановлении.

Установка: `vpn cron install` (добавляет `0 * * * *` в crontab, лог в
`cache/autocheck.log`). Снять: `vpn cron remove`.

### Технические детали реализации
- Node-парсер: base64 → строки `vless://`, поля через `urllib.parse`.
- Тесты узла: запускается **отдельный** sing-box с конфигом только из socks-inbound + один vless-outbound, без TUN. Потом `curl -x socks5h://…`.
- **Параллельность:** у каждого узла свой socks-порт `10800 + индекс` и свой
  временный конфиг `_tmp_cfg_<порт>.json` (удаляется после теста). Потоки —
  `concurrent.futures.ThreadPoolExecutor` (по умолчанию 6).
- Тестовые/служебные конфиги: `_apply.json` (применение), `_tmp_cfg*.json`
  (тесты, авто-чистятся).
- Кэши: `cache/nodes.json`, `cache/results.json`, `cache/history.jsonl`
  (история, ротация не реализована — растёт со временем).

### Что делает `use auto`
1. Собирает конфиг: `direct` + **все** узлы (tags `n0..n14`) + urltest `auto`.
2. В urltest `auto` включает **только** узлы, у которых в `results.json` есть `exit_ip` и `country != "RU"` (сейчас это n2, n13).
3. Пишет `/etc/sing-box/config.json` (через `sudo`), делает `systemctl restart sing-box`.
4. Проверяет active + egress через api.ipify.org. При неудаче — откат из `configs/singbox-last.json`.
5. Сохраняет успешный конфиг в `configs/singbox-last.json`.

### Технические детали реализации
- Node-парсер: base64 → строки `vless://`, поля через `urllib.parse`.
- Тесты узла: запускается **отдельный** sing-box с конфигом только из socks-inbound (`127.0.0.1:10880`) + один vless-outbound, без TUN. Потом `curl -x socks5h://…`.
- Тестовые конфиги пишутся в корень проекта: `_tmp_cfg.json`, `_apply.json` (служебные, можно игнорировать/чистить).
- Кэши: `cache/nodes.json`, `cache/results.json`.

## Скрипты вкл/выкл
```bash
~/vpn-tool/vpn-on.sh     # systemctl start sing-box + проверка egress
~/vpn-tool/vpn-off.sh    # systemctl stop  sing-box (возврат прямого интернета)
```
Оба читают пароль sudo из `~/.sudo_password` (см. [[Security]]).

## Напрямую через systemd
```bash
systemctl {start|stop|restart|status} sing-box
```
`stop` полностью убирает tun/rules — сеть возвращается в исходное (проверено).

## Типовые сценарии
- «Поменять подписку» → переписать `sub_url`, затем `vpn refresh`, `vpn test all`, `vpn use auto`.
- «Проверить после ребута» → `vpn status`; сервис enabled, поднимется сам.
- «Узел умер в полёте» → `vpn use auto` (вернёт на рабочие), либо `vpn-off.sh`.
- «Найти самый быстрый узел» → `vpn test all`, потом `vpn use best`.
- «Автопилот» → `vpn cron install` (ежечасный `autocheck`).
