#!/home/evgeniy/vpn-tool/.venv/bin/python3
# -*- coding: utf-8 -*-
"""Textual TUI for the VLESS Reality subscription manager.

Full-screen interface: arrow-key navigation, ping (with animation), full exit
test, speed test, connect / auto / best, subscription refresh and a VPN
on/off toggle. Shows the currently connected node and egress in the status bar.
"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import vpntool as vt

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Header, Footer, Static, DataTable, LoadingIndicator
from textual import work
from rich.text import Text

COL_IDX = "idx"
COL_NAME = "name"
COL_HOST = "host"
COL_PING = "ping"
COL_EXIT = "exit"
COLUMNS = (COL_IDX, COL_NAME, COL_HOST, COL_PING, COL_EXIT)


class VpnApp(App):
    TITLE = "VLESS Reality Manager"
    SUB_TITLE = "Enter подключить · ↑/↓ или j/k выбор · o вкл/выкл VPN"

    BINDINGS = [
        Binding("p", "ping", "Ping"),
        Binding("P", "ping_all", "Ping все"),
        Binding("t", "test", "Тест"),
        Binding("s", "speed", "Скорость"),
        Binding("a", "auto", "Auto"),
        Binding("b", "best", "Best"),
        Binding("r", "refresh", "Обновить"),
        Binding("o", "toggle", "VPN on/off"),
        Binding("g", "status", "Статус"),
        Binding("j", "move_down", "", show=False),
        Binding("k", "move_up", "", show=False),
        Binding("q", "quit", "Выход"),
    ]

    CSS = """
    #statusbar { width: 1fr; height: 1; padding: 0 1; background: $boost; }
    #spinner { width: 3; height: 1; display: none; }
    #notify { height: 1; padding: 0 1; color: $text-muted; }
    DataTable { height: 1fr; }
    """

    def __init__(self):
        super().__init__()
        self.nodes = []
        self.results = {}
        self.status = {}
        self.target_idx = None
        self.busy = 0

    # ------------------------------------------------------------- compose
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            yield Static("", id="statusbar")
            yield LoadingIndicator(id="spinner")
        yield DataTable(id="nodes", cursor_type="row", zebra_stripes=True)
        yield Static("", id="notify")
        yield Footer()

    def _table(self) -> DataTable:
        return self.query_one("#nodes", DataTable)

    def _spinner(self) -> LoadingIndicator:
        return self.query_one("#spinner", LoadingIndicator)

    def on_mount(self):
        self.nodes = vt.load_nodes()
        self.results = vt.load_results()
        table = self._table()
        table.add_column("#", key=COL_IDX, width=4)
        table.add_column("Узел", key=COL_NAME, width=28)
        table.add_column("host:port", key=COL_HOST, width=22)
        table.add_column("ping", key=COL_PING, width=8)
        table.add_column("exit", key=COL_EXIT, width=16)
        self._rebuild_table()
        table.focus()
        self.refresh_status()

    # ------------------------------------------------------------- render
    def _node_style(self, i):
        r = self.results.get(vt.node_key(self.nodes[i]), {})
        if r.get("exit_ip") and r.get("country") != "RU":
            return "green"
        if r.get("exit_ip") and r.get("country") == "RU":
            return "yellow"
        if r.get("exit_ip") is None and r.get("handshake_ms") is None:
            return "red"
        return "default"

    def _row_cells(self, i):
        n = self.nodes[i]
        r = self.results.get(vt.node_key(n), {})
        st = self._node_style(i)
        connected = (self.target_idx == i)

        idx_t = Text(str(i), style="dim")
        name_t = Text(("● " if connected else "") + vt.short_name(n), style=st)
        if connected:
            name_t.stylize("bold")
        host_t = Text("%s:%d" % (n["host"], n["port"]), style="dim")

        hs = r.get("handshake_ms")
        ping_t = Text(("%dms" % hs) if hs is not None else "—",
                      style=("default" if hs is None else st))

        ex = r.get("exit_ms")
        if ex is not None:
            exit_t = Text("%s %dms" % (r.get("country") or "", ex), style=st)
        elif "exit_ip" in r and r.get("exit_ip") is None:
            exit_t = Text("✗", style="red")
        else:
            exit_t = Text("—", style="dim")
        return (idx_t, name_t, host_t, ping_t, exit_t)

    def _refresh_row(self, i):
        cells = self._row_cells(i)
        for col, val in zip(COLUMNS, cells):
            self._table().update_cell(str(i), col, val)

    def _refresh_all_rows(self):
        for i in range(len(self.nodes)):
            self._refresh_row(i)

    def _rebuild_table(self):
        table = self._table()
        table.clear()
        for i in range(len(self.nodes)):
            table.add_row(*self._row_cells(i), key=str(i))
        if self.nodes:
            table.move_cursor(row=0)

    def _render_statusbar(self):
        s = self.status or {}
        t = Text()
        t.append("VPN: ")
        if s.get("active") == "active":
            t.append("ВКЛ", style="bold green")
        else:
            t.append("ВЫКЛ", style="bold red")
        t.append("   подключён: ")
        t.append(s.get("target", "…"), style="bold")
        t.append("   egress: ")
        t.append("%s %s" % (s.get("country", "—"), s.get("egress", "—")),
                 style="cyan")
        self.query_one("#statusbar", Static).update(t)

    # ------------------------------------------------------------- helpers
    def _sel(self):
        row = self._table().cursor_row
        return row if self.nodes and 0 <= row < len(self.nodes) else None

    def _busy_start(self, msg):
        self.busy += 1
        self._spinner().display = True
        self.query_one("#notify", Static).update(msg)

    def _busy_end(self, msg):
        self.busy = max(0, self.busy - 1)
        if self.busy == 0:
            self._spinner().display = False
        self.query_one("#notify", Static).update(msg)

    def _target_idx_from_status(self):
        final = (self.status or {}).get("final", "")
        if final.startswith("n") and final[1:].isdigit():
            return int(final[1:])
        return None

    # ------------------------------------------------------------- status
    def refresh_status(self):
        self._status_worker()

    @work(thread=True)
    def _status_worker(self):
        s = vt.get_status(self.nodes)
        self.call_from_thread(self._apply_status, s)

    def _apply_status(self, s):
        self.status = s
        self.target_idx = self._target_idx_from_status()
        self._render_statusbar()
        self._refresh_all_rows()

    def action_status(self):
        self._busy_start("Обновляю статус…")
        self.refresh_status()

    # ------------------------------------------------------------- navigation
    def action_move_down(self):
        self._table().action_cursor_down()

    def action_move_up(self):
        self._table().action_cursor_up()

    # ------------------------------------------------------------- ping
    def action_ping(self):
        idx = self._sel()
        if idx is None:
            return
        self._busy_start("Пинг #%d %s…" % (idx, vt.short_name(self.nodes[idx])))
        self._ping_worker(idx)

    @work(thread=True)
    def _ping_worker(self, idx):
        ms = vt.handshake_ms(self.nodes[idx])
        self.call_from_thread(self._ping_done, idx, ms)

    def _ping_done(self, idx, ms):
        r = self.results.setdefault(vt.node_key(self.nodes[idx]), {})
        r["handshake_ms"] = ms
        vt.save_results(self.results)
        self._refresh_row(idx)
        self._busy_end("Пинг #%d: %s" % (idx, "%dms" % ms
                       if ms is not None else "недоступен"))

    def action_ping_all(self):
        self._busy_start("Пинг всех узлов…")
        self._ping_all_worker()

    @work(thread=True)
    def _ping_all_worker(self):
        for i in range(len(self.nodes)):
            ms = vt.handshake_ms(self.nodes[i])
            self.call_from_thread(self._ping_all_step, i, ms)
        self.call_from_thread(self._ping_all_done)

    def _ping_all_step(self, i, ms):
        r = self.results.setdefault(vt.node_key(self.nodes[i]), {})
        r["handshake_ms"] = ms
        self._refresh_row(i)

    def _ping_all_done(self):
        vt.save_results(self.results)
        self._busy_end("Пинг всех завершён")

    # ------------------------------------------------------------- test
    def action_test(self):
        idx = self._sel()
        if idx is None:
            return
        self._busy_start("Тест #%d %s…" % (idx, vt.short_name(self.nodes[idx])))
        self._test_worker(idx)

    @work(thread=True)
    def _test_worker(self, idx):
        res = vt.full_test(self.nodes[idx], port=vt.TEST_PORT_BASE + idx)
        self.call_from_thread(self._test_done, idx, res)

    def _test_done(self, idx, res):
        r = self.results.setdefault(vt.node_key(self.nodes[idx]), {})
        if res is None:
            r.update({"exit_ip": None, "country": None, "exit_ms": None})
            msg = "Тест #%d: ✗ не работает" % idx
        else:
            r.update(res)
            vt.record_history(self.nodes[idx], res)
            msg = "Тест #%d: ✓ %s %s %dms" % (idx, res.get("country"),
                                              res.get("exit_ip"),
                                              res.get("exit_ms"))
        vt.save_results(self.results)
        self._refresh_row(idx)
        self._busy_end(msg)

    # ------------------------------------------------------------- speed
    def action_speed(self):
        idx = self._sel()
        if idx is None:
            return
        self._busy_start("Скорость #%d %s…" % (idx, vt.short_name(self.nodes[idx])))
        self._speed_worker(idx)

    @work(thread=True)
    def _speed_worker(self, idx):
        res = vt.speed_test(self.nodes[idx], port=vt.TEST_PORT_BASE + idx)
        self.call_from_thread(self._speed_done, idx, res)

    def _speed_done(self, idx, res):
        r = self.results.setdefault(vt.node_key(self.nodes[idx]), {})
        if res is None:
            r["speed_mbps"] = None
            msg = "Скорость #%d: ✗ не измерилась" % idx
        else:
            r.update(res)
            vt.record_history(self.nodes[idx], res)
            msg = "Скорость #%d: %s Mbps" % (idx, res["speed_mbps"])
        vt.save_results(self.results)
        self._refresh_row(idx)
        self._busy_end(msg)

    # ------------------------------------------------------------- connect
    def on_data_table_row_selected(self, event):
        self._connect(event.cursor_row)

    def _connect(self, idx):
        if idx is None or not (0 <= idx < len(self.nodes)):
            return
        self._busy_start("Подключение к #%d %s…" %
                         (idx, vt.short_name(self.nodes[idx])))
        self._connect_worker(idx)

    @work(thread=True)
    def _connect_worker(self, idx):
        ok = vt.apply_node(self.nodes, str(idx), self.results)
        self.call_from_thread(self._connect_done, idx, ok)

    def _connect_done(self, idx, ok):
        name = vt.short_name(self.nodes[idx])
        self._busy_end(("✓ Подключено к #%d %s" % (idx, name)) if ok
                       else "✗ Не удалось подключиться к #%d" % idx)
        self.refresh_status()

    def action_auto(self):
        self._busy_start("Подключение auto…")
        self._select_worker("auto")

    def action_best(self):
        self._busy_start("Подключение best…")
        self._select_worker("best")

    @work(thread=True)
    def _select_worker(self, sel):
        ok = vt.apply_node(self.nodes, sel, self.results)
        self.call_from_thread(self._select_done, sel, ok)

    def _select_done(self, sel, ok):
        self._busy_end(("✓ Подключено: %s" % sel) if ok
                       else "✗ Не удалось: %s" % sel)
        self.refresh_status()

    # ------------------------------------------------------------- refresh
    def action_refresh(self):
        self._busy_start("Обновление подписки…")
        self._refresh_worker()

    @work(thread=True)
    def _refresh_worker(self):
        nodes = vt.load_nodes(refresh=True)
        self.call_from_thread(self._refresh_done, nodes)

    def _refresh_done(self, nodes):
        self.nodes = nodes
        self.results = vt.load_results()
        self._rebuild_table()
        self._busy_end("Подписка обновлена: %d узлов" % len(nodes))
        self.refresh_status()

    # ------------------------------------------------------------- toggle
    def action_toggle(self):
        on = (self.status or {}).get("active") == "active"
        target = not on
        self._busy_start("Отключение VPN…" if on else "Включение VPN…")
        self._toggle_worker(target)

    @work(thread=True)
    def _toggle_worker(self, on):
        vt.set_vpn_enabled(on)
        self.call_from_thread(self._toggle_done)

    def _toggle_done(self):
        self._busy_end("")
        self.refresh_status()


def main():
    if not sys.stdout.isatty():
        print("Нужен интерактивный терминал: запустите '~/vpn-tool/vpn' "
              "в SSH/tmux.")
        sys.exit(1)
    VpnApp().run()


if __name__ == "__main__":
    main()
