# Архитектура

## Схема работы

```
 [приложения на сервере: docker pull, apt, curl ...]
        │  обычный сокет (src 192.168.0.107)
        ▼
 [ip rules: 9001 -> таблица 2022]  (auto_route от sing-box)
        │
        ▼
 [tun0 (172.19.0.1/30), стек system]
        │
        ▼
 [sing-box: роутер по route.rules]
        │  не-private → final
        ▼
 [vless outbound → Reality-сервер узла]  (напр. 113.30.152.105:443, SNI perplexity.ai)
        │
        ▼
 [реальный интернет: api.anthropic.com, docker.io, ...]
```

## Ключевые решения

### 1. Глобальный TUN вместо локального SOCKS
Выбран `auto_route: true`, чтобы **весь** трафик сервера (включая демоны/контейнеры) шёл через VPN без настройки proxy в каждом приложении. Docker pulls работают сразу.

### 2. private-подсети — в direct
В `route.rules` первым правилом: `192.168.0.0/16, 10/8, 172.16/12, 127/8, 169.254/16 → direct`. Это сохраняет SSH и LAN-трафик мимо туннеля.

### 3. route_exclude_address — серверы узлов
IP всех Reality-серверов добавлены `/32` в `tun.route_exclude_address`, иначе собственные сокеты sing-box к узлу заворачиваются в свой же тун (self-loop) → VPN мёртв. Это критично, подробности: [[Networking-Troubleshooting]].

### 4. DNS-хендлинг (формат sing-box 1.14)
- В 1.14 legacy-формат DNS удалён. Рабочий сервер: `{"type":"https","server":"1.1.1.1","tag":"dn"}`.
- DNS-запросы приложений перехватываются в tun → sing-box отвечает через DoH 1.1.1.1.
- Без DNS-сервера в конфиге весь DNS молчит (признак: в логе тысячи `inbound DNS packet` и ничего не резолвится).

### 5. urltest-селектор с фильтром по стране
`use auto` в CLI собирает urltest только из узлов, у которых по кэшу тестов `exit_ip` есть и `country != "RU"` — чтобы auto не «улетал» в РФ (там egress бесполезен для OpenAI/Anthropic). См. [[CLI-Usage]].

### 6. fail-closed / fail-over
- `final = auto` (urltest) — при падении текущего узла sing-box сам переключится между рабочими.
- Если выбран конкретный мёртвый узел — интернет умрёт до ручного переключения (такое поведение принято осознанно).

## Взаимодействие с Docker/UFW
На хосте стоят **docker** (свои nftables-цепи, FORWARD policy drop) и **UFW** (INPUT policy drop). Они конфликтуют с TUN: см. [[Networking-Troubleshooting]] (пункт про UFW — главный грабли).

## Точки расширения
- Текущий глобальный конфиг: `/etc/sing-box/config.json` (генерируется CLI из шаблона, см. [[CLI-Usage]]).
- Состояние результатов тестов: `~/vpn-tool/cache/results.json`.
- Идеи развития: [[Roadmap]].
