# Домашний сервер — VPN-проект (vpn-tool)

> База знаний проекта. Читай с этого файла: здесь карта всех заметок.
> Vault-совместимо с Obsidian (ссылки `[[Заметка]]` внутри этой папки).

## Коротко о проекте

На домашнем сервере **evgencomp** (Ubuntu 26.04, за NAT роутера) поднят **глобальный VPN** на базе **sing-box 1.14** с TUN-режимом. Весь исходящий трафик сервера (docker pull, apt, любые приложения) уходит через **VLESS Reality** узлы из платной подписки, чтобы обходить блокировки РФ (Anthropic, OpenAI и т.п.).

Управление — CLI-скрипт `vpn` в папке проекта: в интерактиве это полноэкранный
TUI (стрелки + Enter для подключения), в неинтерактивном режиме — команды
`list` / `test` / `use` / `status` и т.д. Тянет подписку, показывает все узлы,
тестирует их (ping / выход / скорость) и переключает глобальный конфиг.

## Карта заметок

| Заметка | О чём |
|---|---|
| [[Home]] | (этот файл) карта и быстрый старт |
| [[Architecture]] | Как устроено: глобальный TUN, потоки трафика |
| [[Infrastructure]] | Пути, сервис, сеть сервера, доступ по SSH |
| [[Subscription-Nodes]] | Подписка, формат узлов, результаты тестов |
| [[CLI-Usage]] | Команды CLI `vpn` и ручных скриптов |
| [[Networking-Troubleshooting]] | Сетевые грабли и как их решали (важно!) |
| [[Security]] | Пароль sudo, UFW, риски |
| [[Changelog]] | Хронология работ |
| [[Roadmap]] | Следующие шаги / идеи |
| [[Onboarding-Agent]] | Инструкция для следующего агента |

## Быстрый старт (для агента)

```bash
# 1. Интерактивный TUI (стрелки + Enter = подключение)
ssh homeserver                    # войти, затем:
~/vpn-tool/vpn

# 2. Проверить, что VPN работает и через какой узел идёт выход
ssh homeserver '~/vpn-tool/vpn status'

# 3. Посмотреть узлы + результаты прошлых тестов
ssh homeserver '~/vpn-tool/vpn list'

# 4. Полный тест всех узлов (~10 с, параллельно), потом переключение
ssh homeserver '~/vpn-tool/vpn test all'
ssh homeserver '~/vpn-tool/vpn use auto'      # urltest по зарубежным рабочим
ssh homeserver '~/vpn-tool/vpn use best'      # лучший по скорости/задержке
ssh homeserver '~/vpn-tool/vpn use 13'        # конкретный узел по индексу

# 5. История тестов и авто-проверка
ssh homeserver '~/vpn-tool/vpn history'
ssh homeserver '~/vpn-tool/vpn cron install'  # ежечасный autocheck

# 6. Выключить/включить VPN (сеть вернётся в норму)
ssh homeserver './vpn-tool/vpn-off.sh'
ssh homeserver './vpn-tool/vpn-on.sh'
```

> **Стоп-краны:** если сломал VPN — `systemctl stop sing-box` вернёт прямой интернет
> (сервис на `Restart=on-failure`, но `stop` останавливает). Бекап рабочего конфига —
> `~/vpn-tool/configs/singbox-last.json`.

## Ключевые факты (в двух словах)

- Проект: `~/vpn-tool` (на сервере). Старый `~/proxy` мигрирован сюда.
- Рабочих узлов сейчас **2 из 15**: `#2 NL Amsterdam` (144.31.24.107) и `#13 BE Brussels` (113.30.152.105). Остальные падают на reality-проверке/лежат (причины — см. [[Changelog]]).
- Подписка **меняется** (была 14 узлов, стала 15) — всегда делать `refresh` перед анализом.
- Egress сейчас NL (Amsterdam), конфиг `auto` (urltest). Проверено: Anthropic 404, OpenAI 421, Docker Hub 401.
- **Авто-ротация включена**: cron каждый час гоняет `vpn autocheck` (лог `cache/autocheck.log`).
- Ошибки, которые уже решены и легко могут вернуться: см. [[Networking-Troubleshooting]].
