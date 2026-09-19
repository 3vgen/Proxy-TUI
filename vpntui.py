#!/home/evgeniy/vpn-tool/.venv/bin/python3
# -*- coding: utf-8 -*-
"""Textual TUI for the VLESS Reality subscription manager.

Modern dashboard-style interface: a top status bar, a split view (node list /
test history on the left, a live detail panel on the right) and a footer with
contextual key bindings. Fully keyboard-driven. The connected node is green,
everything else is gray; a spinner appears on the row while connecting.
"""
import datetime
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import vpntool as vt

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, LoadingIndicator, Static
from textual import on, work
from rich.text import Text

# node table columns
C_IDX = "idx"
C_NAME = "name"
C_HOST = "host"
C_PING = "ping"
C_EXIT = "exit"
C_SPEED = "speed"
NODE_COLS = (C_IDX, C_NAME, C_HOST, C_PING, C_EXIT, C_SPEED)

# history table columns
H_TIME = "time"
H_NAME = "name"
H_COUNTRY = "country"
H_IP = "ip"
H_MS = "ms"
H_SPEED = "speed"
HIST_COLS = (H_TIME, H_NAME, H_COUNTRY, H_IP, H_MS, H_SPEED)

SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

HELP_TEXT = """\
keys
────────────────────────────────────────────
↑ / ↓  or  j / k   select
enter              connect to selected node
p                  ping selected node
P                  ping all nodes
t                  full test (egress) of selected node
s                  speed test of selected node
a                  connect auto (urltest, non-RU)
b                  connect best (fastest foreign)
o                  vpn on / off
r                  refresh subscription
g                  refresh status
h                  switch view: nodes ↔ history
?                  this help
q                  quit

legend
────────────────────────────────────────────
green    currently connected node
spinner  connecting to a node
gray     everything else
"""


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,question_mark,q", "dismiss", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Container(id="help"):
            yield Static(HELP_TEXT, id="help-text")

    def action_dismiss(self):
        self.dismiss()


class VpnApp(App):
    TITLE = "vpn"

    BINDINGS = [
        Binding("p", "ping", "Ping", show=False),
        Binding("P", "ping_all", "Ping all", show=False),
        Binding("t", "test", "Test", show=False),
        Binding("s", "speed", "Speed", show=False),
        Binding("a", "auto", "Auto", show=False),
        Binding("b", "best", "Best", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("o", "toggle", "VPN on/off", show=False),
        Binding("g", "status", "Status", show=False),
        Binding("h", "switch_view", "History", show=False),
        Binding("question_mark", "help", "Help", show=False),
        Binding("j", "move_down", "", show=False),
        Binding("k", "move_up", "", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    CSS = """
    #statusbar {
        height: 1;
        padding: 0 1;
        border-bottom: solid $panel;
        background: $boost;
    }
    #statustext { width: 1fr; }
    #statusright { width: auto; color: $text-muted; }
    #spinner { width: 2; height: 1; display: none; }

    #body { height: 1fr; }

    #left { width: 1fr; height: 1fr; }
    #left-title {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        text-style: bold;
    }
    #nodes, #history { height: 1fr; border: none; padding: 0 1; }

    DataTable { background: transparent; }
    DataTable > .datatable--header {
        background: transparent;
        color: $text-muted;
        text-style: bold;
    }
    DataTable > .datatable--cursor { background: $boost; }

    #detail {
        width: 34;
        height: 1fr;
        border-left: solid $panel;
        padding: 0 1;
        background: transparent;
    }
    #detail-title {
        height: 1;
        color: $text-muted;
        text-style: bold;
    }
    #detail-content { height: 1fr; }

    #notify {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        border-top: solid $panel;
    }

    HelpScreen { align: center middle; }
    #help {
        width: 62;
        max-height: 80%;
        border: round $panel;
        background: $surface;
        padding: 1 2;
    }
    #help-text { height: auto; }
    """

    HINT = ("↑↓ select   enter connect   p ping   P ping all   t test   "
            "s speed   a auto   b best   o vpn   r refresh   g status   "
            "h nodes/history   ? help   q quit")

    def __init__(self):
        super().__init__()
        self.nodes = []
        self.results = {}
        self.hist = []
        self._recent = {}
        self.status = {}
        self.target_idx = None
        self.connecting_idx = None
        self.busy = 0
        self.view = "nodes"
        self._spin_frame = 0
        self._spin_timer = None
        self._detail_key = None

    # ------------------------------------------------------------- compose
    def compose(self) -> ComposeResult:
        with Horizontal(id="statusbar"):
            yield Static("", id="statustext")
            yield LoadingIndicator(id="spinner")
            yield Static("", id="statusright")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Static("", id="left-title")
                yield DataTable(id="nodes", cursor_type="row")
                yield DataTable(id="history", cursor_type="row")
            with Vertical(id="detail"):
                yield Static("details", id="detail-title")
                yield Static("", id="detail-content")
        yield Static(self.HINT, id="notify")

    def _nodes_table(self) -> DataTable:
        return self.query_one("#nodes", DataTable)

    def _history_table(self) -> DataTable:
        return self.query_one("#history", DataTable)

    def _spinner(self) -> LoadingIndicator:
        return self.query_one("#spinner", LoadingIndicator)

    def _notify(self) -> Static:
        return self.query_one("#notify", Static)

    # ------------------------------------------------------------- mount
    def on_mount(self):
        self.nodes = vt.load_nodes()
        self.results = vt.load_results()
        self.hist = list(reversed(vt.load_history()))
        self._build_recent()

        nodes = self._nodes_table()
        nodes.add_column("#", key=C_IDX, width=3)
        nodes.add_column("node", key=C_NAME, width=22)
        nodes.add_column("host", key=C_HOST, width=20)
        nodes.add_column("ping", key=C_PING, width=7)
        nodes.add_column("exit", key=C_EXIT, width=13)
        nodes.add_column("speed", key=C_SPEED, width=7)

        hist = self._history_table()
        hist.add_column("time", key=H_TIME, width=12)
        hist.add_column("node", key=H_NAME, width=26)
        hist.add_column("country", key=H_COUNTRY, width=8)
        hist.add_column("exit ip", key=H_IP, width=16)
        hist.add_column("ms", key=H_MS, width=7)
        hist.add_column("speed", key=H_SPEED, width=8)

        self._rebuild_nodes()
        self._rebuild_history()
        self._apply_view()
        nodes.focus()
        self.refresh_status()

    def _build_recent(self):
        self._recent = {}
        for h in self.hist:
            key = "%s:%d" % (h["host"], h["port"])
            lst = self._recent.setdefault(key, [])
            if len(lst) < 4:
                lst.append(h)

    # ------------------------------------------------------------- view
    def _apply_view(self):
        nodes = self._nodes_table()
        hist = self._history_table()
        title = self.query_one("#left-title", Static)
        if self.view == "nodes":
            nodes.display = True
            hist.display = False
            title.update("nodes")
            nodes.focus()
        else:
            nodes.display = False
            hist.display = True
            title.update("history")
            hist.focus()
        self._detail_key = None
        self._render_detail()

    def action_switch_view(self):
        self.view = "history" if self.view == "nodes" else "nodes"
        self._apply_view()

    def action_help(self):
        self.push_screen(HelpScreen())

    def _active_table(self) -> DataTable:
        return self._nodes_table() if self.view == "nodes" else self._history_table()

    def _sel(self):
        table = self._active_table()
        row = table.cursor_row
        rows = len(self.nodes) if self.view == "nodes" else len(self.hist)
        return row if 0 <= row < rows else None

    def _node_sel(self):
        return self._sel() if self.view == "nodes" else None

    # ------------------------------------------------------------- spinner
    def _start_spinner(self):
        if self._spin_timer is None:
            self._spin_timer = self.set_interval(0.09, self._tick_spinner)

    def _stop_spinner(self):
        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

    def _tick_spinner(self):
        self._spin_frame = (self._spin_frame + 1) % len(SPIN)
        if self.connecting_idx is not None:
            self._refresh_node_row(self.connecting_idx)
        self._render_detail(force=True)

    # ------------------------------------------------------------- render: nodes
    def _node_row_cells(self, i):
        n = self.nodes[i]
        r = self.results.get(vt.node_key(n), {})
        connected = (self.target_idx == i)
        connecting = (self.connecting_idx == i)

        if connecting:
            prefix = SPIN[self._spin_frame] + " "
            name_style = "green"
        elif connected:
            prefix = "▸ "
            name_style = "bold green"
        else:
            prefix = "  "
            name_style = "dim"

        idx_t = Text(str(i), style="dim")
        name_t = Text(prefix + vt.short_name(n), style=name_style)
        host_t = Text("%s:%d" % (n["host"], n["port"]), style="dim")

        hs = r.get("handshake_ms")
        ping_t = Text(("%dms" % hs) if hs is not None else "—", style="dim")

        ex = r.get("exit_ms")
        if ex is not None:
            exit_t = Text("%s %dms" % (r.get("country") or "", ex), style="dim")
        elif "exit_ip" in r and r.get("exit_ip") is None:
            exit_t = Text("✗", style="dim")
        else:
            exit_t = Text("—", style="dim")

        spd = r.get("speed_mbps")
        speed_t = Text(("%.0f" % spd) if spd else "—", style="dim")

        return (idx_t, name_t, host_t, ping_t, exit_t, speed_t)

    def _refresh_node_row(self, i):
        cells = self._node_row_cells(i)
        for col, val in zip(NODE_COLS, cells):
            self._nodes_table().update_cell(str(i), col, val)

    def _rebuild_nodes(self):
        t = self._nodes_table()
        t.clear()
        for i in range(len(self.nodes)):
            t.add_row(*self._node_row_cells(i), key=str(i))
        if self.nodes:
            t.move_cursor(row=0)

    # ------------------------------------------------------------- render: history
    def _hist_row_cells(self, i):
        rec = self.hist[i]
        ts = datetime.datetime.fromtimestamp(rec["ts"]).strftime("%m-%d %H:%M")
        name = rec.get("name") or ("%s:%d" % (rec["host"], rec["port"]))
        country = rec.get("country") or "—"
        ip = rec.get("exit_ip") or "—"
        ms = ("%d" % rec["exit_ms"]) if rec.get("exit_ms") is not None else "—"
        spd = ("%.0f" % rec["speed_mbps"]) if rec.get("speed_mbps") else "—"
        return (Text(ts, style="dim"), Text(name), Text(country),
                Text(ip, style="dim"), Text(ms), Text(spd, style="dim"))

    def _rebuild_history(self):
        t = self._history_table()
        t.clear()
        for i in range(len(self.hist)):
            t.add_row(*self._hist_row_cells(i), key=str(i))
        if self.hist:
            t.move_cursor(row=0)

    # ------------------------------------------------------------- render: detail
    def _detail(self) -> Static:
        return self.query_one("#detail-content", Static)

    def _render_detail(self, force=False):
        key = (self.view, self._sel())
        if not force and key == self._detail_key:
            return
        self._detail_key = key
        if self.view == "nodes":
            self._render_node_detail()
        else:
            self._render_history_detail()

    def _kv(self, key, value, style=None):
        t = Text()
        t.append(" %s" % key.ljust(8), style="dim")
        t.append(value, style=style)
        t.append("\n")
        return t

    def _divider(self):
        t = Text()
        t.append(" " + "─" * 30 + "\n", style="dim")
        return t

    def _render_node_detail(self):
        d = self._detail()
        idx = self._node_sel()
        if idx is None:
            d.update(Text(""))
            return
        n = self.nodes[idx]
        r = self.results.get(vt.node_key(n), {})
        connected = (self.target_idx == idx)
        connecting = (self.connecting_idx == idx)

        t = Text()
        if connecting:
            t.append(SPIN[self._spin_frame] + " ")
            t.append(vt.short_name(n), style="green")
            t.append("  connecting…", style="green")
            t.append("\n")
        elif connected:
            t.append("▸ " + vt.short_name(n) + "\n", style="bold green")
        else:
            t.append("  " + vt.short_name(n) + "\n", style="dim")
        t.append(self._divider())
        t.append(self._kv("host", "%s:%d" % (n["host"], n["port"])))
        t.append(self._kv("sni", n["sni"]))
        t.append(self._kv("fp", n["fp"]))
        t.append(self._kv("flow", n["flow"]))
        t.append(self._kv("uuid", n["uuid"][:12] + "…"))
        t.append(self._divider())
        t.append(self._kv("exit", "%s %s" % (r.get("country") or "—",
                                             r.get("city") or "")))
        t.append(self._kv("ip", r.get("exit_ip") or "—"))
        t.append(self._kv("latency", ("%d ms" % r["exit_ms"])
                          if r.get("exit_ms") is not None else "—"))
        t.append(self._kv("speed", ("%.1f Mbps" % r["speed_mbps"])
                          if r.get("speed_mbps") else "—"))
        t.append(self._divider())
        t.append(" " + "recent" + "\n", style="bold")
        recent = self._recent.get(vt.node_key(n), [])
        if recent:
            for h in recent:
                ts = datetime.datetime.fromtimestamp(h["ts"]).strftime("%H:%M")
                line = "  %s  %s  %dms  %s" % (
                    ts, h.get("country") or "--",
                    h.get("exit_ms") or 0,
                    ("%.0fM" % h["speed_mbps"]) if h.get("speed_mbps") else "")
                t.append(line + "\n", style="dim")
        else:
            t.append("  no tests yet\n", style="dim")
        d.update(t)

    def _render_history_detail(self):
        d = self._detail()
        idx = self._sel()
        if idx is None:
            d.update(Text(""))
            return
        rec = self.hist[idx]
        ts = datetime.datetime.fromtimestamp(rec["ts"]).strftime("%Y-%m-%d %H:%M:%S")
        t = Text()
        t.append(rec.get("name") or ("%s:%d" % (rec["host"], rec["port"])))
        t.append("\n")
        t.append(self._divider())
        t.append(self._kv("time", ts))
        t.append(self._kv("host", "%s:%d" % (rec["host"], rec["port"])))
        t.append(self._kv("country", rec.get("country") or "—"))
        t.append(self._kv("exit ip", rec.get("exit_ip") or "—"))
        t.append(self._kv("latency", ("%d ms" % rec["exit_ms"])
                          if rec.get("exit_ms") is not None else "—"))
        t.append(self._kv("speed", ("%.1f Mbps" % rec["speed_mbps"])
                          if rec.get("speed_mbps") else "—"))
        d.update(t)

    # ------------------------------------------------------------- status bar
    def _render_statusbar(self):
        s = self.status or {}
        on = s.get("active") == "active"
        target = s.get("target") or s.get("final") or "—"

        left = Text()
        left.append("vpn ", style="bold")
        left.append("●", style="green" if on else "red")
        left.append(" %s" % ("on" if on else "off"),
                    style="bold green" if on else "bold red")
        left.append("   ")
        left.append(target, style="bold")
        left.append("   ")
        left.append("%s · %s" % (s.get("country") or "—", s.get("egress") or "—"),
                    style="cyan")
        self.query_one("#statustext", Static).update(left)

        up = sum(1 for n in self.nodes
                 if self.results.get(vt.node_key(n), {}).get("exit_ip")
                 and self.results.get(vt.node_key(n), {}).get("country") != "RU")
        self.query_one("#statusright", Static).update(
            "%d nodes · %d up" % (len(self.nodes), up))

    # ------------------------------------------------------------- helpers
    def _busy_start(self, msg):
        self.busy += 1
        self._spinner().display = True
        self._notify().update(msg)

    def _busy_end(self, msg):
        self.busy = max(0, self.busy - 1)
        if self.busy == 0:
            self._spinner().display = False
        self._notify().update(msg or self.HINT)

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
        new_target = self._target_idx_from_status()
        prev = self.target_idx
        self.target_idx = new_target
        self._render_statusbar()
        for i in {prev, new_target}:
            if i is not None and 0 <= i < len(self.nodes):
                self._refresh_node_row(i)
        self._render_detail(force=True)

    def action_status(self):
        self._busy_start("refreshing status…")
        self.refresh_status()

    # ------------------------------------------------------------- navigation
    def action_move_down(self):
        self._active_table().action_cursor_down()

    def action_move_up(self):
        self._active_table().action_cursor_up()

    @on(DataTable.RowHighlighted)
    def _on_row_highlighted(self):
        self._render_detail()

    # ------------------------------------------------------------- ping
    def action_ping(self):
        idx = self._node_sel()
        if idx is None:
            self._notify().update("switch to nodes view (h)")
            return
        self._busy_start("ping #%d %s…" % (idx, vt.short_name(self.nodes[idx])))
        self._ping_worker(idx)

    @work(thread=True)
    def _ping_worker(self, idx):
        ms = vt.handshake_ms(self.nodes[idx])
        self.call_from_thread(self._ping_done, idx, ms)

    def _ping_done(self, idx, ms):
        r = self.results.setdefault(vt.node_key(self.nodes[idx]), {})
        r["handshake_ms"] = ms
        vt.save_results(self.results)
        self._refresh_node_row(idx)
        self._render_detail(force=True)
        self._busy_end("ping #%d: %s" % (idx, "%dms" % ms
                       if ms is not None else "unreachable"))

    def action_ping_all(self):
        self._busy_start("ping all nodes…")
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
        self._refresh_node_row(i)

    def _ping_all_done(self):
        vt.save_results(self.results)
        self._render_detail(force=True)
        self._busy_end("ping all done")

    # ------------------------------------------------------------- test
    def action_test(self):
        idx = self._node_sel()
        if idx is None:
            self._notify().update("switch to nodes view (h)")
            return
        self._busy_start("test #%d %s…" % (idx, vt.short_name(self.nodes[idx])))
        self._test_worker(idx)

    @work(thread=True)
    def _test_worker(self, idx):
        res = vt.full_test(self.nodes[idx], port=vt.TEST_PORT_BASE + idx)
        self.call_from_thread(self._test_done, idx, res)

    def _test_done(self, idx, res):
        r = self.results.setdefault(vt.node_key(self.nodes[idx]), {})
        if res is None:
            r.update({"exit_ip": None, "country": None, "exit_ms": None})
            msg = "test #%d: ✗ failed" % idx
        else:
            r.update(res)
            vt.record_history(self.nodes[idx], res)
            self.hist = list(reversed(vt.load_history()))
            self._build_recent()
            self._rebuild_history()
            msg = "test #%d: ✓ %s %s %dms" % (idx, res.get("country"),
                                              res.get("exit_ip"),
                                              res.get("exit_ms"))
        vt.save_results(self.results)
        self._refresh_node_row(idx)
        self._render_detail(force=True)
        self._busy_end(msg)

    # ------------------------------------------------------------- speed
    def action_speed(self):
        idx = self._node_sel()
        if idx is None:
            self._notify().update("switch to nodes view (h)")
            return
        self._busy_start("speed #%d %s…" % (idx, vt.short_name(self.nodes[idx])))
        self._speed_worker(idx)

    @work(thread=True)
    def _speed_worker(self, idx):
        res = vt.speed_test(self.nodes[idx], port=vt.TEST_PORT_BASE + idx)
        self.call_from_thread(self._speed_done, idx, res)

    def _speed_done(self, idx, res):
        r = self.results.setdefault(vt.node_key(self.nodes[idx]), {})
        if res is None:
            r["speed_mbps"] = None
            msg = "speed #%d: ✗ failed" % idx
        else:
            r.update(res)
            vt.record_history(self.nodes[idx], res)
            self.hist = list(reversed(vt.load_history()))
            self._build_recent()
            self._rebuild_history()
            msg = "speed #%d: %s Mbps" % (idx, res["speed_mbps"])
        vt.save_results(self.results)
        self._refresh_node_row(idx)
        self._render_detail(force=True)
        self._busy_end(msg)

    # ------------------------------------------------------------- connect
    def on_data_table_row_selected(self, event):
        if self.view == "nodes":
            self._connect(event.cursor_row)

    def _connect(self, idx):
        if idx is None or not (0 <= idx < len(self.nodes)):
            return
        if self.connecting_idx is not None:
            return
        self.connecting_idx = idx
        self._spin_frame = 0
        self._start_spinner()
        self._refresh_node_row(idx)
        self._render_detail(force=True)
        self._busy_start("connecting #%d %s…" %
                         (idx, vt.short_name(self.nodes[idx])))
        self._connect_worker(idx)

    @work(thread=True)
    def _connect_worker(self, idx):
        ok = vt.apply_node(self.nodes, str(idx), self.results)
        self.call_from_thread(self._connect_done, idx, ok)

    def _connect_done(self, idx, ok):
        self.connecting_idx = None
        self._stop_spinner()
        name = vt.short_name(self.nodes[idx])
        self._busy_end(("✓ connected #%d %s" % (idx, name)) if ok
                       else "✗ failed to connect #%d" % idx)
        self._refresh_node_row(idx)
        self._render_detail(force=True)
        self.refresh_status()

    def action_auto(self):
        self._busy_start("connecting auto…")
        self._select_worker("auto")

    def action_best(self):
        self._busy_start("connecting best…")
        self._select_worker("best")

    @work(thread=True)
    def _select_worker(self, sel):
        ok = vt.apply_node(self.nodes, sel, self.results)
        self.call_from_thread(self._select_done, sel, ok)

    def _select_done(self, sel, ok):
        self._busy_end(("✓ connected: %s" % sel) if ok
                       else "✗ failed: %s" % sel)
        self.refresh_status()

    # ------------------------------------------------------------- refresh
    def action_refresh(self):
        self._busy_start("refreshing subscription…")
        self._refresh_worker()

    @work(thread=True)
    def _refresh_worker(self):
        nodes = vt.load_nodes(refresh=True)
        self.call_from_thread(self._refresh_done, nodes)

    def _refresh_done(self, nodes):
        self.nodes = nodes
        self.results = vt.load_results()
        self._rebuild_nodes()
        self._busy_end("subscription refreshed: %d nodes" % len(nodes))
        self.refresh_status()

    # ------------------------------------------------------------- toggle
    def action_toggle(self):
        on = (self.status or {}).get("active") == "active"
        target = not on
        self._busy_start("disabling vpn…" if on else "enabling vpn…")
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
