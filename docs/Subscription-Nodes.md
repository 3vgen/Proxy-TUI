# Подписка и узлы

## Источник
- URL подписки: файл `~/vpn-tool/sub_url` (одна строка, формата `https://user.<провайдер>/s/<KEY>`)
- Ответ — **base64** список строк `vless://`, каждая строка — узел Reality.
- Подписка **динамическая**: состав узлов меняется (первая загрузка = 14 узлов, вторая = 15). Перед анализом всегда делать `~/vpn-tool/vpn refresh` или удалять `cache/nodes.json`.

## Формат узла (vless Reality)
```
vless://UUID@HOST:PORT?encryption=none&flow=xtls-rprx-vision&type=tcp&security=reality&sni=perplexity.ai&fp=firefox&pbk=PUBLIC_KEY&sid=SHORT_ID&spx=%2F#%F0%9F%87%A7...%20Имя
```
- `sni` — фронт-домен (rutube.ru / perplexity.ai / ozon.ru ...) — для анти-DPI
- `fp` — отпечаток TLS (safari / chrome / firefox ...)
- `pbk` + `sid` — **у каждого узла свои**, не перепутать при копировании конфигов
- fragment `#...` — url-encoded имя с флагом страны

## Структура узла в коде/JSON (поля)
`uuid, host, port, flow(=xtls-rprx-vision), sni, fp, pbk, sid, name, tag`
Парсер: функция `parse_nodes()` в CLI `vpn`.

## Конвертация в outbound sing-box (важно!)
В sing-box **reality вложен внутрь tls**, а не рядом:
```json
{
  "type": "vless",
  "tag": "n13",
  "server": "113.30.152.105",
  "server_port": 443,
  "uuid": "<uuid>",
  "flow": "xtls-rprx-vision",
  "tls": {
    "enabled": true,
    "server_name": "perplexity.ai",
    "utls": { "enabled": true, "fingerprint": "firefox" },
    "reality": { "enabled": true, "public_key": "<pbk>", "short_id": "<sid>" }
  }
}
```

## Результаты тестов (снимок 2026-09-07)
Из 15 узлов реально **работают через прокси только 2**:

| Инд. | Имя | host:port | egress | задержка выхода |
|---|---|---|---|---|
| **2** | 🇳🇱 Нидерланды | 144.31.24.107:443 | NL Amsterdam (144.31.24.107) | ~363 ms |
| **13** | 🇧🇪 Бельгия | 113.30.152.105:443 | BE Brussels (113.30.152.105) | ~386 ms |

- Скорость #13: **~24.7 Mbps** (10 МБ за ~3.2 с).
- Остальные 13 узлов: TCP handshake проходит (1–49 мс), но реальный выход не работает.
- Узлы `201.34.132.43:*` (несколько портов, «2T RES») и часть «Нидерланды/Дания/США/...» — в handshake 1 мс, но не туннелируют.
- Раньше работали и РФ-узлы (`rus.hy100.su`, `185.147.27.11`, egress **RU Москва**) — бесполезны для OpenAI/Anthropic, т.к. выход в РФ.

## Причины отказа «мёртвых» узлов (уточнено 2026-09-07)

Диагностика с `log: debug` (не просто «reality-ошибка»):

| Причина | Узлы | Комментарий |
|---|---|---|
| `x509: certificate ... not ozone.ru` | #3, #9, #11 (`201.34.132.43`, sni `ozone.ru`) | SNI не совпадает с сертификатом фронта; перебор альтернатив (`ozon.ru`, `www.ozon.ru`, ...) не помог — дальше `reality verification failed` |
| `reality verification failed` | #4, #6, #7, #10, #12 | pbk/sid не совпадают с сервером (stale/другая подписка) — клиентски не чинится |
| `connection refused` | #14 (`81.17.159.174`) | сервер реально лежит |

Вывод: все «мёртвые» узлы чинятся только на стороне провайдера
(неверные/протухшие reality-ключи или упавшие серверы). Клиентскими правками
(sni/fp) их не разблокировать. Подписка меняется — периодически `refresh` + `test all`.

Полные данные: `cache/results.json` (ключ `host:port`).
Кэш узлов: `cache/nodes.json` (индекс в таблице `list` = `tag n<idx>` в live-конфиге).

## Вывод
Для целей проекта (Anthropic/OpenAI/docker) пригодны только не-RU узлы. Auto-режим в CLI использует именно их.
