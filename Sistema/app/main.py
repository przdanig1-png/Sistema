
import os
import sqlite3
import zipfile
from pathlib import Path
from datetime import datetime
import json
import textwrap
import subprocess
import re
import sys
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from app.login_window import LoginWindow


if os.name == "nt":
    import ctypes
    from ctypes import wintypes
else:
    ctypes = None
    wintypes = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


SESSION_USER = ""
SESSION_ROLE = ""
SESSION_FULL_NAME = ""
SESSION_FORCE_PASSWORD_CHANGE = False


_WM_DROPFILES = 0x0233
_GWL_WNDPROC = -4
_DND_REGISTRY = {}
_DND_WNDPROCS = {}
_DND_ORIGINAL_WNDPROCS = {}

def _normalize_dropped_path(raw_path: str) -> str:
    try:
        value = str(raw_path or '').strip()
        if value.startswith('{') and value.endswith('}'):
            value = value[1:-1]
        value = value.strip('"')
        return value
    except Exception:
        return str(raw_path or '')

def _install_windows_drop_handler(toplevel):
    if os.name != 'nt' or ctypes is None:
        return False
    hwnd = int(toplevel.winfo_id())
    if hwnd in _DND_WNDPROCS:
        return True
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    user32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.DragAcceptFiles.restype = None
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    shell32.DragFinish.restype = None
    shell32.DragQueryPoint.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.POINT)]
    shell32.DragQueryPoint.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)

    def _wnd_proc(hwnd_msg, msg, wparam, lparam):
        if msg == _WM_DROPFILES:
            hdrop = wintypes.HANDLE(wparam)
            try:
                count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                files = []
                for i in range(count):
                    length = shell32.DragQueryFileW(hdrop, i, None, 0) + 1
                    buf = ctypes.create_unicode_buffer(length)
                    shell32.DragQueryFileW(hdrop, i, buf, length)
                    path = _normalize_dropped_path(buf.value)
                    if path:
                        files.append(path)
                pt = wintypes.POINT()
                shell32.DragQueryPoint(hdrop, ctypes.byref(pt))
                user32.ClientToScreen(hwnd_msg, ctypes.byref(pt))
                targets = _DND_REGISTRY.get(int(hwnd_msg), [])
                for target_widget, callback in list(targets):
                    try:
                        if not target_widget.winfo_exists():
                            continue
                        x1 = target_widget.winfo_rootx()
                        y1 = target_widget.winfo_rooty()
                        x2 = x1 + target_widget.winfo_width()
                        y2 = y1 + target_widget.winfo_height()
                        if x1 <= pt.x <= x2 and y1 <= pt.y <= y2:
                            chosen = next((p for p in files if Path(p).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp'}), files[0] if files else '')
                            if chosen:
                                target_widget.after(0, lambda p=chosen, cb=callback: cb(p))
                            break
                    except Exception:
                        continue
            finally:
                shell32.DragFinish(hdrop)
            return 0
        return user32.CallWindowProcW(_DND_ORIGINAL_WNDPROCS[int(hwnd_msg)], hwnd_msg, msg, wparam, lparam)

    proc_ref = WNDPROC(_wnd_proc)
    original = user32.SetWindowLongPtrW(hwnd, _GWL_WNDPROC, proc_ref)
    _DND_ORIGINAL_WNDPROCS[hwnd] = original
    _DND_WNDPROCS[hwnd] = proc_ref
    user32.DragAcceptFiles(hwnd, True)
    return True

def register_drop_target(toplevel, widget, callback):
    if os.name != 'nt' or ctypes is None:
        return False
    try:
        toplevel.update_idletasks()
        if not _install_windows_drop_handler(toplevel):
            return False
        hwnd = int(toplevel.winfo_id())
        _DND_REGISTRY.setdefault(hwnd, []).append((widget, callback))
        return True
    except Exception:
        return False
PERMISSION_ACTIONS = ["ver", "crear", "editar", "eliminar", "anular", "imprimir", "exportar"]
DEFAULT_ROLE_PERMISSIONS = {
    "Administrador": {(module, action) for module in [
        "Dashboard", "Ventas", "Inventario", "Clientes", "Proveedores", "Compras", "Área Técnica",
        "Cibercafé y Consolas", "Empleados", "Asistencia", "Caja", "Reportes", "Configuración"
    ] for action in PERMISSION_ACTIONS},
    "Supervisor": {(module, action) for module in [
        "Dashboard", "Ventas", "Inventario", "Clientes", "Proveedores", "Compras", "Área Técnica",
        "Cibercafé y Consolas", "Empleados", "Asistencia", "Caja", "Reportes"
    ] for action in PERMISSION_ACTIONS if action != "eliminar"} | {("Configuración", "ver")},
    "Vendedor": {
        ("Dashboard", "ver"), ("Ventas", "ver"), ("Ventas", "crear"), ("Ventas", "imprimir"),
        ("Clientes", "ver"), ("Clientes", "crear"), ("Clientes", "editar"),
        ("Inventario", "ver"), ("Caja", "ver"), ("Caja", "crear"),
        ("Reportes", "ver"),
    },
    "Tecnico": {
        ("Dashboard", "ver"), ("Área Técnica", "ver"), ("Área Técnica", "crear"),
        ("Área Técnica", "editar"), ("Área Técnica", "imprimir"),
        ("Clientes", "ver"), ("Clientes", "crear"), ("Clientes", "editar"),
        ("Inventario", "ver"), ("Reportes", "ver"),
    },
    "Caja": {
        ("Dashboard", "ver"), ("Ventas", "ver"), ("Ventas", "crear"), ("Ventas", "imprimir"),
        ("Caja", "ver"), ("Caja", "crear"), ("Caja", "editar"),
        ("Clientes", "ver"), ("Reportes", "ver"),
    },
}




class PermissionToggle(tk.Frame):
    def __init__(self, parent, variable, size=18, box_color="#0b1324", on_color="#2563eb", off_outline="#94a3b8"):
        super().__init__(parent, bg=box_color, highlightthickness=0, bd=0)
        self.variable = variable
        self.size = size
        self.box_color = box_color
        self.on_color = on_color
        self.off_outline = off_outline
        self.canvas = tk.Canvas(
            self,
            width=size,
            height=size,
            bg=box_color,
            highlightthickness=0,
            bd=0,
            relief="flat",
            cursor="hand2",
        )
        self.canvas.pack(padx=1, pady=1)
        for widget in (self, self.canvas):
            widget.bind("<Button-1>", self._toggle, add="+")
        self.variable.trace_add("write", self._redraw)
        self._redraw()

    def _toggle(self, event=None):
        try:
            self.variable.set(not bool(self.variable.get()))
        except Exception:
            pass

    def _redraw(self, *args):
        s = self.size
        on = bool(self.variable.get())
        self.canvas.delete("all")
        fill = self.on_color if on else "#f8fafc"
        outline = self.on_color if on else self.off_outline
        self.canvas.create_rectangle(1, 1, s-1, s-1, fill=fill, outline=outline, width=1)
        if on:
            self.canvas.create_line(4, s//2, s//2 - 1, s - 5, s - 4, 4, fill="#ffffff", width=2, capstyle=tk.ROUND, joinstyle=tk.ROUND)


APP_NAME = "TECNOMEDIA GT Business Suite"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(BASE_DIR, "app")
ASSETS_DIR = os.path.join(APP_DIR, "assets")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "tecnomedia_gt_business_suite.sqlite3")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_tecnomedia_gt.png")

COLUMN_PREFS_PATH = os.path.join(DATA_DIR, "column_preferences.json")


def load_system_version_info():
    default = {
        "producto": APP_NAME,
        "version": "v26.04.21.14.08",
        "fecha": "2026-04-21",
        "hora": "14:08",
        "nota": "Base segura versionada"
    }
    try:
        version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "version.json")
        with open(version_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                default.update(data)
    except Exception:
        pass
    return default


def load_system_version():
    return str(load_system_version_info().get("version", "v0.0.0"))


SYSTEM_VERSION_INFO = load_system_version_info()
SYSTEM_VERSION = str(SYSTEM_VERSION_INFO.get("version", "v0.0.0"))
DISPLAY_APP_NAME = f"{APP_NAME} {SYSTEM_VERSION}"

DEFAULT_VISIBLE_COLUMNS = {
    "inventario_listado": ["code", "name", "provider", "price", "stock"],
    "clientes_listado": ["name", "phone", "phone2", "nit", "credit", "due", "favor"],
    "proveedores_listado": ["name", "contact", "phone", "email", "city"],
    "empleados_listado": ["code", "name", "phone", "position", "status"],
    "config_usuarios": ["username", "full_name", "role", "is_active"],
    "compras_recientes": ["number", "provider", "date", "total", "status"],
    "compras_lineas": ["code", "name", "qty", "cost", "subtotal"],
    "caja_movimientos": ["date", "type", "reference", "amount", "notes"],
    "asistencia_historial": ["date", "employee", "entry", "exit", "status"],
    "cyber_estaciones": ["name", "type", "status", "rate"],
    "cyber_sesiones_recientes": ["station", "client", "start", "end", "total"],
}


def load_column_preferences():
    try:
        with open(COLUMN_PREFS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_column_preferences(prefs):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(COLUMN_PREFS_PATH, "w", encoding="utf-8") as fh:
            json.dump(prefs, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _column_pref_storage_key(pref_key):
    user = (SESSION_USER or "global").strip().lower()
    return f"{user}::{pref_key}"


def _default_visible_columns(pref_key, columns):
    preferred = [col for col in DEFAULT_VISIBLE_COLUMNS.get(pref_key, []) if col in columns]
    return preferred or list(columns)


def apply_treeview_columns(tree, pref_key, all_columns=None, save=False):
    columns = list(all_columns or tree.cget("columns"))
    if not columns:
        return
    prefs = load_column_preferences()
    storage_key = _column_pref_storage_key(pref_key)
    default_visible = _default_visible_columns(pref_key, columns)
    visible = prefs.get(storage_key, default_visible)
    visible = [col for col in visible if col in columns]
    if not visible:
        visible = default_visible[:]
    tree.configure(displaycolumns=visible)
    if save:
        prefs[storage_key] = visible
        save_column_preferences(prefs)


class ColumnManagerButton(ttk.Frame):
    def __init__(self, parent, tree, pref_key, all_columns=None, button_text="Columnas"):
        super().__init__(parent, style="Card.TFrame")
        self.tree = tree
        self.pref_key = pref_key
        self.all_columns = list(all_columns or tree.cget("columns"))
        self.default_visible = _default_visible_columns(pref_key, self.all_columns)
        self.vars = {}
        self.button = tk.Menubutton(
            self,
            text=f"▦ {button_text}",
            bg="#eef4ff",
            fg="#1e3a8a",
            activebackground="#dbeafe",
            activeforeground="#1d4ed8",
            relief="flat",
            bd=0,
            padx=8,
            pady=3,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
            highlightthickness=1,
            highlightbackground="#bfdbfe",
            highlightcolor="#93c5fd",
            direction="below",
        )
        self.button.pack(side="right")
        self.menu = tk.Menu(
            self.button,
            tearoff=0,
            bg="#ffffff",
            fg="#0f172a",
            activebackground="#dbeafe",
            activeforeground="#1d4ed8",
            relief="solid",
            bd=1,
            font=("Segoe UI", 9),
        )
        self.button.configure(menu=self.menu)
        self._build_menu()
        apply_treeview_columns(self.tree, self.pref_key, self.all_columns, save=False)

    def _current_visible(self):
        current = list(self.tree.cget("displaycolumns"))
        if current == ['#all'] or current == ('#all',):
            return self.all_columns[:]
        return [col for col in current if col in self.all_columns]

    def _sync_from_tree(self):
        visible = set(self._current_visible())
        for col, var in self.vars.items():
            var.set(col in visible)

    def _build_menu(self):
        self.menu.delete(0, "end")
        self.menu.add_command(label="Mostrar todo", command=self.show_all)
        self.menu.add_command(label="Restablecer", command=self.reset_default)
        self.menu.add_separator()
        current_visible = set(load_column_preferences().get(_column_pref_storage_key(self.pref_key), self.default_visible))
        for col in self.all_columns:
            label = self.tree.heading(col).get("text") or col
            var = tk.BooleanVar(value=(col in current_visible))
            self.vars[col] = var
            self.menu.add_checkbutton(label=label, variable=var, onvalue=True, offvalue=False, command=lambda c=col: self.toggle_column(c))
        self._sync_from_tree()

    def _save_visible(self, visible):
        prefs = load_column_preferences()
        prefs[_column_pref_storage_key(self.pref_key)] = visible
        save_column_preferences(prefs)

    def toggle_column(self, column):
        visible = self._current_visible()
        if self.vars[column].get():
            if column not in visible:
                visible.append(column)
        else:
            if len(visible) <= 1:
                self.vars[column].set(True)
                messagebox.showinfo("Columnas", "Debe quedar al menos una columna visible.", parent=self.winfo_toplevel())
                return
            visible = [col for col in visible if col != column]
        ordered = [col for col in self.all_columns if col in visible]
        self.tree.configure(displaycolumns=ordered)
        self._save_visible(ordered)
        self._sync_from_tree()

    def show_all(self):
        for var in self.vars.values():
            var.set(True)
        self.tree.configure(displaycolumns=self.all_columns)
        self._save_visible(self.all_columns[:])

    def reset_default(self):
        ordered = [col for col in self.all_columns if col in self.default_visible]
        for col, var in self.vars.items():
            var.set(col in ordered)
        self.tree.configure(displaycolumns=ordered)
        self._save_visible(ordered)
        self._sync_from_tree()


def install_column_manager(parent, tree, pref_key, row=0, column=0, columnspan=1, sticky="e", padx=(0, 0), pady=(0, 4)):
    bar = ttk.Frame(parent, style="Card.TFrame")
    bar.grid(row=row, column=column, columnspan=columnspan, sticky=sticky, padx=padx, pady=pady)
    try:
        bar.columnconfigure(0, weight=1)
    except Exception:
        pass
    btn = ColumnManagerButton(bar, tree, pref_key=pref_key, button_text="Columnas")
    btn.pack(anchor="e")
    return btn


RESETTABLE_TABLES = [
    "sale_items",
    "sales",
    "cash_movements",
    "cash_sessions",
    "stock_movements",
    "purchase_items",
    "purchases",
    "technical_ticket_parts",
    "technical_tickets",
    "clients",
    "inventory_items",
    "app_settings",
]


def reset_all_business_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("PRAGMA foreign_keys = OFF")
    for table in RESETTABLE_TABLES:
        cur.execute(f"DELETE FROM {table}")

    try:
        cur.execute("DELETE FROM sqlite_sequence")
    except Exception:
        pass

    cur.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('correlativo_ticket', '1')")
    cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('correlativo_voucher', '1')")
    cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('correlativo_factura', '1')")
    conn.commit()
    cur.execute("PRAGMA foreign_keys = ON")
    conn.close()

    sales_pos_dirs = [
        os.path.join(BASE_DIR, "data", "sales_pos"),
        os.path.join(APP_DIR, "data"),
    ]
    for folder in sales_pos_dirs:
        os.makedirs(folder, exist_ok=True)
        for filename, default_content in {
            "ventas.jsonl": "",
            "auditoria.log": "",
            "clientes.json": "[]\n",
        }.items():
            try:
                with open(os.path.join(folder, filename), "w", encoding="utf-8") as fh:
                    fh.write(default_content)
            except Exception:
                pass

        try:
            with open(os.path.join(folder, "correlativos.json"), "w", encoding="utf-8") as fh:
                json.dump({"ticket": 1, "factura": 1}, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

        docs_dir = os.path.join(folder, "documentos")
        if os.path.isdir(docs_dir):
            for root, _, files in os.walk(docs_dir):
                for file_name in files:
                    try:
                        os.remove(os.path.join(root, file_name))
                    except Exception:
                        pass

MODULES = [
    "Dashboard",
    "Ventas",
    "Inventario",
    "Clientes",
    "Proveedores",
    "Compras",
    "Área Técnica",
    "Cibercafé y Consolas",
    "Empleados",
    "Asistencia",
    "Caja",
    "Reportes",
    "Configuración",
]


def ensure_database():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS technical_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_no TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            client_name TEXT,
            client_nit TEXT,
            client_phone TEXT,
            equipment_type TEXT,
            equipment_name TEXT,
            brand TEXT,
            model TEXT,
            serial TEXT,
            status TEXT,
            technician TEXT,
            issue_reported TEXT,
            diagnosis TEXT,
            accessories TEXT,
            observations TEXT,
            repair_cost REAL DEFAULT 0,
            advance_payment REAL DEFAULT 0,
            pending_balance REAL DEFAULT 0,
            photo_1 TEXT,
            photo_2 TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_code TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            nit TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            shipping_address TEXT,
            department TEXT,
            social_url TEXT,
            discount REAL DEFAULT 0,
            allow_credit INTEGER DEFAULT 0,
            credit_limit REAL DEFAULT 0,
            balance_favor REAL DEFAULT 0,
            balance_available REAL DEFAULT 0,
            balance_due REAL DEFAULT 0,
            status TEXT DEFAULT 'Activo',
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            internal_code TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            item_type TEXT NOT NULL,
            barcode TEXT,
            name TEXT NOT NULL,
            serial TEXT,
            provider TEXT,
            location TEXT,
            category TEXT,
            brand TEXT,
            cost REAL DEFAULT 0,
            price REAL DEFAULT 0,
            stock REAL DEFAULT 0,
            min_stock REAL DEFAULT 0,
            observations TEXT,
            photo_path TEXT,
            status TEXT DEFAULT 'Activo'
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            user_name TEXT,
            customer_name TEXT,
            customer_nit TEXT,
            subtotal REAL DEFAULT 0,
            discount_amount REAL DEFAULT 0,
            total REAL DEFAULT 0,
            payment_method TEXT,
            document_type TEXT,
            correlativo TEXT,
            status TEXT DEFAULT 'ACTIVA',
            payload_json TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            qty REAL DEFAULT 0,
            unit_price REAL DEFAULT 0,
            line_total REAL DEFAULT 0,
            source_item_code TEXT,
            item_type TEXT,
            FOREIGN KEY(sale_id) REFERENCES sales(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            item_code TEXT,
            item_name TEXT,
            movement_type TEXT,
            qty REAL DEFAULT 0,
            reference TEXT,
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cash_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opened_at TEXT NOT NULL,
            opened_by TEXT,
            opening_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'ABIERTA',
            closed_at TEXT,
            closed_by TEXT,
            expected_amount REAL DEFAULT 0,
            closing_amount REAL DEFAULT 0,
            difference_amount REAL DEFAULT 0,
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cash_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            created_at TEXT NOT NULL,
            movement_type TEXT,
            payment_method TEXT,
            amount REAL DEFAULT 0,
            reference TEXT,
            notes TEXT,
            sale_correlativo TEXT,
            FOREIGN KEY(session_id) REFERENCES cash_sessions(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS technical_ticket_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_no TEXT NOT NULL,
            item_code TEXT,
            item_name TEXT NOT NULL,
            qty REAL DEFAULT 0,
            unit_cost REAL DEFAULT 0,
            unit_price REAL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('correlativo_ticket', '1')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('correlativo_voucher', '1')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('correlativo_factura', '1')")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS client_balance_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            client_code TEXT,
            client_name TEXT,
            movement_kind TEXT,
            payment_method TEXT,
            amount REAL DEFAULT 0,
            reference TEXT,
            authorization_no TEXT,
            card_last4 TEXT,
            support_photo TEXT,
            dpi_photo TEXT,
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'Activo',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            provider_code TEXT,
            nit TEXT,
            contact_name TEXT,
            phone TEXT,
            phone2 TEXT,
            email TEXT,
            address TEXT,
            country TEXT,
            social_url TEXT,
            account_numbers TEXT,
            notes TEXT,
            status TEXT DEFAULT 'Activo',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_no TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            provider_code TEXT,
            invoice_no TEXT,
            payment_method TEXT,
            subtotal REAL DEFAULT 0,
            total REAL DEFAULT 0,
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS purchase_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id INTEGER NOT NULL,
            item_code TEXT,
            item_name TEXT NOT NULL,
            qty REAL DEFAULT 0,
            unit_cost REAL DEFAULT 0,
            line_total REAL DEFAULT 0,
            FOREIGN KEY(purchase_id) REFERENCES purchases(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cyber_stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_code TEXT NOT NULL UNIQUE,
            station_name TEXT NOT NULL,
            station_type TEXT NOT NULL,
            status TEXT DEFAULT 'Libre',
            rate_per_hour REAL DEFAULT 0,
            current_session_id INTEGER,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cyber_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id INTEGER NOT NULL,
            station_code TEXT NOT NULL,
            customer_name TEXT,
            started_at TEXT NOT NULL,
            minutes_purchased INTEGER DEFAULT 60,
            minutes_used INTEGER DEFAULT 0,
            rate_per_hour REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'ACTIVA',
            finished_at TEXT,
            notes TEXT,
            FOREIGN KEY(station_id) REFERENCES cyber_stations(id)
        )
        """
    )

    def _ensure_column(table, column, decl):
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in cur.fetchall()}
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    _ensure_column('clients', 'phone2', 'TEXT')
    _ensure_column('clients', 'dpi', 'TEXT')
    _ensure_column('inventory_items', 'provider_code', 'TEXT')
    _ensure_column('inventory_items', 'sku_code', 'TEXT')
    _ensure_column('providers', 'address', 'TEXT')
    _ensure_column('providers', 'country', 'TEXT')
    _ensure_column('providers', 'phone2', 'TEXT')
    _ensure_column('cyber_sessions', 'sale_id', 'INTEGER')
    _ensure_column('cyber_sessions', 'sale_correlativo', 'TEXT')
    _ensure_column('cyber_sessions', 'payment_method', 'TEXT')
    _ensure_column('client_balance_movements', 'receipt_no', 'TEXT')
    _ensure_column('providers', 'contact_name', 'TEXT')
    _ensure_column('providers', 'nit', 'TEXT')
    _ensure_column('providers', 'social_url', 'TEXT')
    _ensure_column('providers', 'provider_code', 'TEXT')
    _ensure_column('providers', 'account_numbers', 'TEXT')
    _ensure_column('cyber_stations', 'current_session_id', 'INTEGER')
    _ensure_column('cyber_stations', 'notes', 'TEXT')
    _ensure_column('cyber_sessions', 'minutes_used', 'INTEGER DEFAULT 0')
    _ensure_column('cyber_sessions', 'notes', 'TEXT')

    cur.execute("SELECT COUNT(*) FROM cyber_stations")
    if cur.fetchone()[0] == 0:
        seed_now = datetime.now().isoformat(timespec='seconds')
        default_stations = [
            ('PC-01', 'PC-01', 'PC', 12.0),
            ('PC-02', 'PC-02', 'PC', 12.0),
            ('PC-03', 'PC-03', 'PC', 12.0),
            ('PC-04', 'PC-04', 'PC', 12.0),
            ('PC-05', 'PC-05', 'PC', 12.0),
            ('PC-06', 'PC-06', 'PC', 12.0),
            ('PS5-01', 'PS5-01', 'Consola', 18.0),
            ('Xbox-01', 'Xbox-01', 'Consola', 18.0),
        ]
        cur.executemany(
            "INSERT INTO cyber_stations (station_code, station_name, station_type, status, rate_per_hour, created_at) VALUES (?, ?, ?, 'Libre', ?, ?)",
            [(code, name, kind, rate, seed_now) for code, name, kind, rate in default_stations],
        )


    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_code TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            full_name TEXT NOT NULL,
            dpi TEXT,
            phone TEXT,
            address TEXT,
            position TEXT,
            hire_date TEXT,
            status TEXT DEFAULT 'Activo',
            base_salary REAL DEFAULT 0,
            pay_frequency TEXT DEFAULT 'Mensual',
            commission_rate REAL DEFAULT 0,
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_code TEXT NOT NULL,
            employee_name TEXT NOT NULL,
            work_date TEXT NOT NULL,
            check_in TEXT,
            check_out TEXT,
            worked_hours REAL DEFAULT 0,
            status TEXT DEFAULT 'ACTIVO',
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            employee_code TEXT NOT NULL,
            employee_name TEXT NOT NULL,
            period_label TEXT,
            base_salary REAL DEFAULT 0,
            commission_amount REAL DEFAULT 0,
            bonus_amount REAL DEFAULT 0,
            discount_amount REAL DEFAULT 0,
            advance_amount REAL DEFAULT 0,
            total_to_pay REAL DEFAULT 0,
            notes TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS system_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            full_name TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Activo',
            employee_name TEXT DEFAULT '',
            force_password_change INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT ''
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            action TEXT NOT NULL,
            UNIQUE(module, action)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            UNIQUE(role_id, permission_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 1,
            UNIQUE(user_id, permission_id)
        )
        """
    )

    _ensure_column('system_users', 'full_name', "TEXT DEFAULT ''")
    _ensure_column('system_users', 'status', "TEXT NOT NULL DEFAULT 'Activo'")
    _ensure_column('system_users', 'employee_name', "TEXT DEFAULT ''")
    _ensure_column('system_users', 'force_password_change', 'INTEGER DEFAULT 0')

    for role_name in DEFAULT_ROLE_PERMISSIONS:
        cur.execute("INSERT OR IGNORE INTO roles(name, description) VALUES (?, ?)", (role_name, f'Rol base {role_name}'))
    for module in MODULES:
        for action in PERMISSION_ACTIONS:
            cur.execute("INSERT OR IGNORE INTO permissions(module, action) VALUES (?, ?)", (module, action))

    cur.execute("SELECT id, name FROM roles")
    role_ids = {name: role_id for role_id, name in cur.fetchall()}
    cur.execute("SELECT id, module, action FROM permissions")
    permission_ids = {(module, action): perm_id for perm_id, module, action in cur.fetchall()}
    for role_name, perm_pairs in DEFAULT_ROLE_PERMISSIONS.items():
        role_id = role_ids.get(role_name)
        if not role_id:
            continue
        cur.execute("SELECT COUNT(*) FROM role_permissions WHERE role_id=?", (role_id,))
        if (cur.fetchone() or [0])[0] == 0:
            for module, action in perm_pairs:
                perm_id = permission_ids.get((module, action))
                if perm_id:
                    cur.execute("INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?)", (role_id, perm_id))

    cur.execute("SELECT id, username, password, COALESCE(role,''), COALESCE(employee_name,''), COALESCE(full_name,'') FROM system_users")
    existing_users = cur.fetchall()
    for user_id, username, password, role_name, employee_name, full_name in existing_users:
        if password and not re.fullmatch(r'[0-9a-f]{64}', str(password)):
            cur.execute("UPDATE system_users SET password=? WHERE id=?", (hash_password(password), user_id))
        normalized_role = role_name or 'Vendedor'
        normalized_name = full_name or employee_name or username
        cur.execute("UPDATE system_users SET role=?, full_name=? WHERE id=?", (normalized_role, normalized_name, user_id))

    cur.execute("SELECT COUNT(*) FROM system_users WHERE username='admin'")
    admin_exists = (cur.fetchone() or [0])[0] > 0
    if not admin_exists:
        cur.execute(
            """
            INSERT INTO system_users(username, password, role, full_name, status, employee_name, force_password_change)
            VALUES (?, ?, ?, ?, 'Activo', ?, 0)
            """,
            ('admin', hash_password('1234'), 'Administrador', 'Administrador General', 'Administrador General')
        )

    conn.commit()
    conn.close()



def db_connect():
    return sqlite3.connect(DB_PATH)


def hash_password(password):
    return hashlib.sha256(str(password or '').encode('utf-8')).hexdigest()


def verify_password(password, hashed):
    if not hashed:
        return False
    if re.fullmatch(r'[0-9a-f]{64}', str(hashed)):
        return hash_password(password) == str(hashed)
    return str(password or '') == str(hashed)


def authenticate_user(username, password):
    if not username or not password:
        return None
    ensure_database()
    conn = db_connect()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, password, COALESCE(role,'Vendedor') AS role,
               COALESCE(full_name, COALESCE(employee_name, username)) AS full_name,
               COALESCE(status,'Activo') AS status,
               COALESCE(force_password_change,0) AS force_password_change
        FROM system_users
        WHERE username=?
    """, (username,))
    row = cur.fetchone()
    conn.close()
    if not row or str(row['status']).strip().lower() != 'activo':
        return None
    if not verify_password(password, row['password']):
        return None
    return dict(row)


def get_all_roles():
    ensure_database()
    conn = db_connect(); cur = conn.cursor()
    cur.execute("SELECT name FROM roles ORDER BY name")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows or list(DEFAULT_ROLE_PERMISSIONS.keys())


def get_permissions_catalog():
    return [(module, action) for module in MODULES for action in PERMISSION_ACTIONS]


def get_role_permissions(role_name):
    ensure_database()
    conn = db_connect(); cur = conn.cursor()
    cur.execute("""
        SELECT p.module, p.action
        FROM role_permissions rp
        JOIN roles r ON r.id = rp.role_id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE r.name=?
    """, (role_name,))
    rows = {(module, action) for module, action in cur.fetchall()}
    conn.close()
    return rows


def set_role_permissions(role_name, permission_pairs):
    ensure_database()
    permission_pairs = set(permission_pairs or set())
    conn = db_connect(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO roles(name, description) VALUES (?, ?)", (role_name, f'Rol {role_name}'))
    cur.execute("SELECT id FROM roles WHERE name=?", (role_name,))
    role_id = (cur.fetchone() or [None])[0]
    if role_id is None:
        conn.close(); return
    cur.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
    for module, action in permission_pairs:
        cur.execute("SELECT id FROM permissions WHERE module=? AND action=?", (module, action))
        row = cur.fetchone()
        if row:
            cur.execute("INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?) ", (role_id, row[0]))
    conn.commit(); conn.close()


def get_user_overrides(username):
    ensure_database()
    conn = db_connect(); cur = conn.cursor()
    cur.execute("""
        SELECT p.module, p.action, up.allowed
        FROM user_permissions up
        JOIN system_users su ON su.id = up.user_id
        JOIN permissions p ON p.id = up.permission_id
        WHERE su.username=?
    """, (username,))
    rows = {(module, action): int(allowed or 0) for module, action, allowed in cur.fetchall()}
    conn.close()
    return rows


def get_effective_permissions(username):
    ensure_database()
    conn = db_connect(); conn.row_factory = sqlite3.Row; cur = conn.cursor()
    cur.execute("SELECT id, COALESCE(role,'Vendedor') AS role FROM system_users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return set()
    perms = set(get_role_permissions(row['role']))
    for key, allowed in get_user_overrides(username).items():
        if allowed:
            perms.add(key)
        else:
            perms.discard(key)
    return perms


def set_user_permission_overrides(username, overrides):
    ensure_database()
    overrides = dict(overrides or {})
    conn = db_connect(); cur = conn.cursor()
    cur.execute("SELECT id FROM system_users WHERE username=?", (username,))
    row = cur.fetchone()
    if not row:
        conn.close(); return
    user_id = row[0]
    cur.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
    for (module, action), allowed in overrides.items():
        cur.execute("SELECT id FROM permissions WHERE module=? AND action=?", (module, action))
        perm = cur.fetchone()
        if perm:
            cur.execute("INSERT OR REPLACE INTO user_permissions(user_id, permission_id, allowed) VALUES (?, ?, ?)", (user_id, perm[0], 1 if int(allowed) else 0))
    conn.commit(); conn.close()


def user_has_permission(username, module, action='ver'):
    if not username:
        return False
    perms = get_effective_permissions(username)
    return (module, action) in perms

def require_permission(module, action='ver', parent=None, feature_name=None, notify=True):
    feature_name = feature_name or f"{module} / {action}"
    allowed = user_has_permission(SESSION_USER, module, action)
    if (not allowed) and notify:
        try:
            messagebox.showwarning('Permisos', f"No tienes permisos para {feature_name}.", parent=parent)
        except Exception:
            messagebox.showwarning('Permisos', f"No tienes permisos para {feature_name}.")
    return allowed


def disable_button_if_denied(button, module, action='ver', feature_name=None):
    try:
        if not require_permission(module, action, parent=button.winfo_toplevel(), feature_name=feature_name, notify=False):
            button.configure(state='disabled')
    except Exception:
        pass
    return button


def update_user_password(username, new_password, force_change=0):
    if not username or not new_password:
        return
    conn = db_connect(); cur = conn.cursor()
    cur.execute("UPDATE system_users SET password=?, force_password_change=? WHERE username=?", (hash_password(new_password), int(force_change), username))
    conn.commit(); conn.close()


def prompt_force_password_change(parent, username):
    dlg = tk.Toplevel(parent)
    dlg.title('Cambio obligatorio de contraseña')
    dlg.transient(parent)
    dlg.grab_set()
    dlg.configure(bg='#0f172a')
    dlg.resizable(False, False)
    ttk.Label(dlg, text='Debes cambiar la contraseña inicial antes de continuar.').grid(row=0, column=0, columnspan=3, sticky='w', padx=16, pady=(16, 10))
    ttk.Label(dlg, text='Nueva contraseña').grid(row=1, column=0, sticky='w', padx=16, pady=6)
    e1 = ttk.Entry(dlg, show='*')
    e1.grid(row=1, column=1, padx=8, pady=6)
    ttk.Label(dlg, text='Confirmar').grid(row=2, column=0, sticky='w', padx=16, pady=6)
    e2 = ttk.Entry(dlg, show='*')
    e2.grid(row=2, column=1, padx=8, pady=6)
    shown = {'value': False}
    def toggle():
        shown['value'] = not shown['value']
        val = '' if shown['value'] else '*'
        e1.configure(show=val)
        e2.configure(show=val)
        btn.configure(text='Ocultar' if shown['value'] else 'Ver')
    btn = ttk.Button(dlg, text='Ver', command=toggle)
    btn.grid(row=1, column=2, rowspan=2, padx=(0, 16), pady=6)
    result = {'ok': False}
    def save():
        p1, p2 = e1.get().strip(), e2.get().strip()
        if len(p1) < 4:
            messagebox.showwarning('Usuarios', 'La contraseña debe tener al menos 4 caracteres.', parent=dlg)
            return
        if p1 != p2:
            messagebox.showwarning('Usuarios', 'Las contraseñas no coinciden.', parent=dlg)
            return
        update_user_password(username, p1, force_change=0)
        result['ok'] = True
        dlg.destroy()
    ttk.Button(dlg, text='Guardar contraseña', command=save).grid(row=3, column=0, columnspan=3, sticky='ew', padx=16, pady=(10, 16))
    dlg.protocol('WM_DELETE_WINDOW', lambda: None)
    e1.focus_set()
    parent.wait_window(dlg)
    return result['ok']


def sales_pos_dir():
    path = os.path.join(DATA_DIR, "sales_pos")
    os.makedirs(path, exist_ok=True)
    return path


def load_sales_jsonl():
    return []


def load_sales_records():
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT created_at, user_name, customer_name, subtotal, discount_amount, total, payment_method, document_type, correlativo, status FROM sales ORDER BY id DESC")
        rows = cur.fetchall()
        conn.close()
        if rows:
            return [
                {
                    "fecha": created_at,
                    "usuario": user_name or "",
                    "cliente": customer_name or "",
                    "subtotal_val": safe_float(subtotal),
                    "descuento_val": safe_float(discount_amount),
                    "total_val": safe_float(total),
                    "metodo": payment_method or "",
                    "tipo_documento": document_type or "",
                    "correlativo": correlativo or "",
                    "estado": status or "ACTIVA",
                }
                for created_at, user_name, customer_name, subtotal, discount_amount, total, payment_method, document_type, correlativo, status in rows
            ]
    except Exception:
        conn.close()

    return []


def sales_summary():
    rows = load_sales_records()
    today = datetime.now().strftime("%Y-%m-%d")
    active = [r for r in rows if (r.get("estado") or "").upper() == "ACTIVA"]
    today_rows = [r for r in active if (r.get("fecha") or "").startswith(today)]
    return {
        "count": len(active),
        "amount": sum(safe_float(r.get("total_val")) for r in active),
        "today_count": len(today_rows),
        "today_amount": sum(safe_float(r.get("total_val")) for r in today_rows),
        "recent": active[:8],
    }


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title(DISPLAY_APP_NAME)
        self.geometry("1440x880")
        self.minsize(1220, 760)
        self.configure(bg="#0b1220")
        icon = self._load_logo_icon()
        if icon:
            self.iconphoto(False, icon)
            self._window_icon = icon

        self.selected_module = tk.StringVar(value="Dashboard")
        self._logo_small = None
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self._configure_styles()
        self._build_layout()
        self._maximize_on_start()
        self.show_module("Dashboard")

    def _maximize_on_start(self):
        try:
            self.update_idletasks()
        except Exception:
            pass
        for attempt in (
            lambda: self.state("zoomed"),
            lambda: self.attributes("-zoomed", True),
            lambda: self.wm_state("zoomed"),
        ):
            try:
                attempt()
                self.update_idletasks()
                return
            except Exception:
                continue
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            self.geometry(f"{screen_w}x{screen_h}+0+0")
        except Exception:
            pass

    def show_ready(self):
        try:
            self._maximize_on_start()
            self.update_idletasks()
        except Exception:
            pass
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _load_logo_icon(self):
        if Image and os.path.exists(LOGO_PATH):
            try:
                img = Image.open(LOGO_PATH).resize((32, 32))
                return ImageTk.PhotoImage(img)
            except Exception:
                return None
        return None

    def _load_logo(self, size):
        if Image and ImageTk and os.path.exists(LOGO_PATH):
            try:
                img = Image.open(LOGO_PATH)
                img.thumbnail(size)
                return ImageTk.PhotoImage(img)
            except Exception:
                return None
        return None

    def _configure_styles(self):
        bg = "#0f172a"
        card = "#111827"
        input_bg = "#1f2937"
        fg = "#e5e7eb"
        accent = "#1d4ed8"
        muted = "#94a3b8"

        self.style.configure("TFrame", background=bg)
        self.style.configure("Card.TFrame", background=card)
        self.style.configure("Sidebar.TFrame", background="#08111f")
        self.style.configure("Header.TFrame", background="#0b1220")
        self.style.configure("TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", background="#0b1220", foreground=fg, font=("Segoe UI Semibold", 18))
        self.style.configure("SubHeader.TLabel", background="#0b1220", foreground=muted, font=("Segoe UI", 10))
        self.style.configure("CardTitle.TLabel", background=card, foreground=fg, font=("Segoe UI Semibold", 11))
        self.style.configure("CardNote.TLabel", background=card, foreground=muted, font=("Segoe UI", 9))
        self.style.configure("CardValue.TLabel", background=card, foreground="#f8fafc", font=("Segoe UI Semibold", 22))
        self.style.configure("SidebarTitle.TLabel", background="#08111f", foreground="#f8fafc", font=("Segoe UI Semibold", 22))
        self.style.configure("SidebarText.TLabel", background="#08111f", foreground="#cbd5e1", font=("Segoe UI", 13))
        self.style.configure("Section.TLabelframe", background=bg, foreground=fg)
        self.style.configure("Section.TLabelframe.Label", background=bg, foreground="#f8fafc", font=("Segoe UI Semibold", 10))
        self.style.configure("TButton", background="#14213a", foreground="#f8fafc", bordercolor="#2e4f86", darkcolor="#14213a", lightcolor="#14213a", relief="flat", focusthickness=0, focuscolor="#14213a", padding=(14, 9), font=("Segoe UI Semibold", 10))
        self.style.map("TButton",
            background=[("active", "#1d3258"), ("pressed", "#0f1c34")],
            foreground=[("disabled", "#94a3b8"), ("!disabled", "#f8fafc")],
            bordercolor=[("active", "#4f78bf"), ("pressed", "#3b82f6")])
        self.style.configure("Primary.TButton", background=accent, foreground="white", bordercolor="#60a5fa", darkcolor=accent, lightcolor=accent, padding=(16, 9), font=("Segoe UI Semibold", 10))
        self.style.map("Primary.TButton", background=[("active", "#2563eb"), ("pressed", "#1e40af")], bordercolor=[("active", "#93c5fd")])
        self.style.configure("Success.TButton", background="#14532d", foreground="#f0fdf4", bordercolor="#22c55e", darkcolor="#14532d", lightcolor="#14532d", padding=(16, 9), font=("Segoe UI Semibold", 10))
        self.style.map("Success.TButton", background=[("active", "#166534"), ("pressed", "#14532d")], bordercolor=[("active", "#4ade80")])
        self.style.configure("Danger.TButton", background="#4c1d1d", foreground="#fff1f2", bordercolor="#f87171", darkcolor="#4c1d1d", lightcolor="#4c1d1d", padding=(16, 9), font=("Segoe UI Semibold", 10))
        self.style.map("Danger.TButton", background=[("active", "#7f1d1d"), ("pressed", "#591c1c")], bordercolor=[("active", "#fca5a5")])
        self.style.configure("Mini.TButton", background="#18263f", foreground="#f8fafc", bordercolor="#38598a", darkcolor="#18263f", lightcolor="#18263f", padding=(6, 3), font=("Segoe UI Semibold", 9))
        self.style.map("Mini.TButton", background=[("active", "#223455")], bordercolor=[("active", "#60a5fa")])
        self.style.configure("Nav.TButton", background="#08111f", foreground="#e2e8f0", borderwidth=0, anchor="center", padding=(12, 10), font=("Segoe UI Semibold", 14))
        self.style.map("Nav.TButton", background=[("active", "#0f2547")], foreground=[("active", "white")])
        self.style.configure("SelectedNav.TButton", background="#11336e", foreground="white", borderwidth=0, anchor="center", padding=(12, 10), font=("Segoe UI Semibold", 14))
        self.style.map("SelectedNav.TButton", background=[("active", "#11336e")], foreground=[("active", "white")])
        self.style.configure("TEntry", fieldbackground=input_bg, foreground=fg, bordercolor="#334155", insertcolor="#f8fafc")
        self.style.configure("TCombobox", fieldbackground="#e5e7eb", background="#e5e7eb", foreground="#111827", bordercolor="#64748b", arrowcolor="#0f172a", insertcolor="#111827", selectforeground="#111827", selectbackground="#cbd5e1")
        self.style.map("TCombobox",
            fieldbackground=[("readonly", "#e5e7eb"), ("!disabled", "#e5e7eb")],
            background=[("readonly", "#e5e7eb"), ("!disabled", "#e5e7eb")],
            foreground=[("readonly", "#111827"), ("!disabled", "#111827")],
            selectforeground=[("readonly", "#111827")],
            selectbackground=[("readonly", "#cbd5e1")],
            arrowcolor=[("readonly", "#0f172a"), ("active", "#0f172a")])
        self.style.configure("Treeview", background=input_bg, fieldbackground=input_bg, foreground=fg, rowheight=26, borderwidth=0)
        self.style.configure("Treeview.Heading", background="#182235", foreground="#f8fafc", font=("Segoe UI Semibold", 10))
        self.style.map("Treeview", background=[("selected", "#1d4ed8")])
        self.option_add("*TCombobox*Listbox.background", "#f8fafc")
        self.option_add("*TCombobox*Listbox.foreground", "#111827")
        self.option_add("*TCombobox*Listbox.selectBackground", "#2563eb")
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _build_layout(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(self, style="Sidebar.TFrame", width=320)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        self.main_area = ttk.Frame(self, style="TFrame")
        self.main_area.grid(row=0, column=1, sticky="nsew")
        self.main_area.rowconfigure(1, weight=1)
        self.main_area.columnconfigure(0, weight=1)

        self.header = ttk.Frame(self.main_area, style="Header.TFrame", height=80)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)

        self.content = ttk.Frame(self.main_area, style="TFrame")
        self.content.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self._build_sidebar()
        self._build_header()

    def _build_sidebar(self):
        logo = self._load_logo((250, 185))
        self._logo_small = logo

        top = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        top.pack(fill="x", padx=16, pady=(14, 6))
        if logo:
            tk.Label(top, image=logo, bg="#08111f").pack(anchor="center", pady=(0, 4))
        ttk.Label(top, text="TECNOMEDIA GT", style="SidebarTitle.TLabel", justify="center", anchor="center").pack(anchor="center", pady=(2, 0))
        ttk.Label(top, text="Business Suite", style="SidebarText.TLabel", justify="center", anchor="center").pack(anchor="center", pady=(0, 0))
        ttk.Label(top, text=SYSTEM_VERSION, style="SidebarText.TLabel", justify="center", anchor="center").pack(anchor="center", pady=(2, 0))

        self.nav_buttons = {}
        nav = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        nav.pack(fill="both", expand=True, padx=14, pady=(8, 8))
        for mod in MODULES:
            btn = ttk.Button(nav, text=mod, style="Nav.TButton", command=lambda m=mod: self.show_module(m))
            btn.pack(fill="x", pady=4)
            if not user_has_permission(SESSION_USER, mod, "ver"):
                btn.state(["disabled"])
            self.nav_buttons[mod] = btn

        foot = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        foot.pack(fill="x", padx=14, pady=(0, 14))

        def _confirm_exit():
            if messagebox.askyesno("Salir", "¿Deseas cerrar el sistema?"):
                self.destroy()

        tk.Button(
            foot,
            text="SALIR",
            command=_confirm_exit,
            bg="#dc2626",
            fg="white",
            activebackground="#b91c1c",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=("Segoe UI Semibold", 13),
            cursor="hand2",
            padx=10,
            pady=12,
        ).pack(fill="x")

    def _build_header(self):
        left = ttk.Frame(self.header, style="Header.TFrame")
        left.grid(row=0, column=0, sticky="w", padx=18, pady=16)
        self.page_title = ttk.Label(left, text="Dashboard", style="Header.TLabel")
        self.page_title.pack(anchor="w")
        self.page_subtitle = ttk.Label(left, text="Base estable de escritorio para una sola máquina.", style="SubHeader.TLabel")
        self.page_subtitle.pack(anchor="w")

        right = ttk.Frame(self.header, style="Header.TFrame")
        right.grid(row=0, column=1, sticky="e", padx=18, pady=16)
        ttk.Label(right, text=datetime.now().strftime("%d/%m/%Y %I:%M %p"), style="SubHeader.TLabel").pack(anchor="e")
        shown_name = SESSION_FULL_NAME or SESSION_USER or "Administrador"
        ttk.Label(right, text=f"Usuario: {shown_name} ({SESSION_ROLE or 'Administrador'})", style="SubHeader.TLabel").pack(anchor="e", pady=(4,0))

    def clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def show_module(self, module_name):
        if not user_has_permission(SESSION_USER, module_name, "ver"):
            messagebox.showwarning("Permisos", f"El usuario {SESSION_USER or 'actual'} no tiene permiso para entrar a {module_name}.")
            return
        self.selected_module.set(module_name)
        self.page_title.configure(text=module_name)
        subtitle_map = {
            "Dashboard": "Resumen general del negocio.",
            "Área Técnica": "Gestión de tickets, diagnósticos, anticipos y seguimiento.",
            "Clientes": "Registro comercial, crédito, descuentos y saldos por cliente.",
            "Inventario": "Productos y servicios con código interno, foto, stock y precios.",
            "Proveedores": "Directorio de proveedores enlazado con inventario.",
            "Compras": "Entradas de inventario ligadas a proveedor con aumento automático de stock.",
            "Caja": "Apertura, movimientos y cierre de caja enlazados con ventas.",
            "Reportes": "Resumen comercial alimentado por ventas reales e inventario.",
            "Cibercafé y Consolas": "Control de PCs y consolas con tiempos, estados y cobro por uso.",
            "Empleados": "Registro de personal, sueldo base, comisiones y pagos.",
            "Asistencia": "Entradas, salidas y horas trabajadas enlazadas a empleados.",
        }
        self.page_subtitle.configure(text=subtitle_map.get(module_name, "Módulo preparado para desarrollo progresivo."))
        for mod, btn in self.nav_buttons.items():
            btn.configure(style="SelectedNav.TButton" if mod == module_name else "Nav.TButton")
        self.clear_content()
        if module_name == "Dashboard":
            DashboardView(self.content).grid(sticky="nsew")
        elif module_name == "Ventas":
            SalesHubView(self.content).grid(sticky="nsew")
        elif module_name == "Área Técnica":
            TechnicalAreaView(self.content).grid(sticky="nsew")
        elif module_name == "Cibercafé y Consolas":
            CyberCafeView(self.content).grid(sticky="nsew")
        elif module_name == "Clientes":
            ClientsView(self.content).grid(sticky="nsew")
        elif module_name == "Inventario":
            InventoryView(self.content).grid(sticky="nsew")
        elif module_name == "Proveedores":
            ProvidersView(self.content).grid(sticky="nsew")
        elif module_name == "Compras":
            PurchasesView(self.content).grid(sticky="nsew")
        elif module_name == "Empleados":
            EmployeesView(self.content).grid(sticky="nsew")
        elif module_name == "Asistencia":
            AttendanceView(self.content).grid(sticky="nsew")
        elif module_name == "Caja":
            CashView(self.content).grid(sticky="nsew")
        elif module_name == "Reportes":
            ReportsView(self.content).grid(sticky="nsew")
        elif module_name == "Configuración":
            SettingsView(self.content, refresh_callback=lambda: self.show_module("Dashboard")).grid(sticky="nsew")
        else:
            PlaceholderView(self.content, module_name).grid(sticky="nsew")


def money_gt(value):
    try:
        num = float(value or 0)
    except Exception:
        num = 0.0
    return f"Q {num:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')


def load_cyber_stations():
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT s.id, s.station_code, s.station_name, s.station_type, s.status,
                   COALESCE(s.rate_per_hour, 0), s.current_session_id,
                   cs.customer_name, cs.started_at, COALESCE(cs.minutes_purchased, 0), COALESCE(cs.minutes_used, 0),
                   COALESCE(cs.sale_correlativo, ''), COALESCE(cs.payment_method, '')
            FROM cyber_stations s
            LEFT JOIN cyber_sessions cs ON cs.id = s.current_session_id AND cs.status = 'ACTIVA'
            ORDER BY s.station_name COLLATE NOCASE
            """
        )
        rows = cur.fetchall()
        return [
            {
                'id': row[0], 'station_code': row[1], 'station_name': row[2], 'station_type': row[3],
                'status': row[4] or 'Libre', 'rate_per_hour': safe_float(row[5]), 'current_session_id': row[6],
                'customer_name': row[7] or '', 'started_at': row[8] or '', 'minutes_purchased': int(row[9] or 0),
                'minutes_used': int(row[10] or 0), 'sale_correlativo': row[11] or '', 'payment_method': row[12] or '',
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_app_setting(key, default=""):
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM app_settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else default
    finally:
        conn.close()


def set_app_setting(key, value):
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
    finally:
        conn.close()


def next_document_correlativo(document_type='TICKET', conn=None):
    normalized = 'factura' if str(document_type).strip().upper() == 'FACTURA' else 'ticket'
    key = f'correlativo_{normalized}'
    legacy_key = 'correlativo_voucher' if normalized == 'ticket' else None
    own_conn = conn is None
    conn = conn or db_connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM app_settings WHERE key=?", (key,))
        row = cur.fetchone()
        if (not row or row[0] is None) and legacy_key:
            cur.execute("SELECT value FROM app_settings WHERE key=?", (legacy_key,))
            row = cur.fetchone()
        current = int(row[0]) if row and str(row[0]).isdigit() else 1
        cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, str(current + 1)))
        if legacy_key:
            cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (legacy_key, str(current + 1)))
        if own_conn:
            conn.commit()
        return f"{normalized.upper()}-{current:06d}"
    finally:
        if own_conn:
            conn.close()


def get_open_cash_session_id():
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def create_sale_record(item_name, total_amount, payment_method='EFECTIVO', customer_name='Público General', document_type='TICKET', user_name='ADMIN', item_type='Servicio', source_item_code='CYBERCAFE', payload=None):
    total_amount = round(safe_float(total_amount), 2)
    correlativo = next_document_correlativo(document_type)
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO sales (created_at, user_name, customer_name, customer_nit, subtotal, discount_amount, total, payment_method, document_type, correlativo, status, payload_json)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 'ACTIVA', ?)
            """,
            (created_at, user_name, customer_name, 'CF', total_amount, total_amount, payment_method, document_type, correlativo, payload_json),
        )
        sale_id = cur.lastrowid
        cur.execute(
            "INSERT INTO sale_items (sale_id, item_name, qty, unit_price, line_total, source_item_code, item_type) VALUES (?, ?, 1, ?, ?, ?, ?)",
            (sale_id, item_name, total_amount, total_amount, source_item_code, item_type),
        )
        cash_session_id = None
        pm = str(payment_method or '').strip().upper()
        if pm not in {'CRÉDITO', 'CREDITO'}:
            cur.execute("SELECT id FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            cash_session_id = row[0] if row else None
            if cash_session_id:
                cur.execute(
                    "INSERT INTO cash_movements (session_id, created_at, movement_type, payment_method, amount, reference, notes, sale_correlativo) VALUES (?, ?, 'INGRESO', ?, ?, ?, ?, ?)",
                    (cash_session_id, created_at, payment_method, total_amount, correlativo, item_name, correlativo),
                )
        conn.commit()
        return {'sale_id': sale_id, 'correlativo': correlativo, 'cash_session_id': cash_session_id}
    finally:
        conn.close()


def next_purchase_no():
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM purchases")
        seq = int(cur.fetchone()[0] or 1)
        return f"COMP-{seq:05d}"
    finally:
        conn.close()


def provider_catalog():
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(provider_code, ''), name FROM providers WHERE status='Activo' ORDER BY name COLLATE NOCASE")
        return cur.fetchall()
    finally:
        conn.close()


def inventory_catalog():
    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute("SELECT internal_code, name, COALESCE(provider,''), COALESCE(cost,0), COALESCE(stock,0) FROM inventory_items WHERE status='Activo' ORDER BY name COLLATE NOCASE")
        return cur.fetchall()
    finally:
        conn.close()


def register_purchase(provider_name, provider_code, invoice_no, payment_method, items, notes=''):
    if not provider_name:
        raise ValueError('Selecciona un proveedor.')
    if not items:
        raise ValueError('Agrega al menos un producto a la compra.')
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    purchase_no = next_purchase_no()
    clean_items = []
    subtotal = 0.0
    for raw in items:
        item_code = str(raw.get('item_code') or '').strip()
        item_name = str(raw.get('item_name') or '').strip()
        qty = round(safe_float(raw.get('qty')), 2)
        unit_cost = round(safe_float(raw.get('unit_cost')), 2)
        if not item_code or not item_name or qty <= 0 or unit_cost < 0:
            raise ValueError('Hay una línea de compra incompleta o inválida.')
        line_total = round(qty * unit_cost, 2)
        subtotal += line_total
        clean_items.append((item_code, item_name, qty, unit_cost, line_total))

    conn = db_connect(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO purchases (purchase_no, created_at, provider_name, provider_code, invoice_no, payment_method, subtotal, total, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (purchase_no, created_at, provider_name, provider_code, invoice_no, payment_method, subtotal, subtotal, notes.strip()),
        )
        purchase_id = cur.lastrowid
        for item_code, item_name, qty, unit_cost, line_total in clean_items:
            cur.execute(
                "INSERT INTO purchase_items (purchase_id, item_code, item_name, qty, unit_cost, line_total) VALUES (?, ?, ?, ?, ?, ?)",
                (purchase_id, item_code, item_name, qty, unit_cost, line_total),
            )
            cur.execute("UPDATE inventory_items SET stock = COALESCE(stock,0) + ?, cost = ? WHERE internal_code = ?", (qty, unit_cost, item_code))
            cur.execute(
                "INSERT INTO stock_movements (created_at, item_code, item_name, movement_type, qty, reference, notes) VALUES (?, ?, ?, 'ENTRADA_COMPRA', ?, ?, ?)",
                (created_at, item_code, item_name, qty, purchase_no, f'Proveedor: {provider_name} | Factura: {invoice_no or "S/F"}'),
            )
        conn.commit()
        return {'purchase_id': purchase_id, 'purchase_no': purchase_no, 'total': round(subtotal, 2)}
    finally:
        conn.close()


def purchase_summary():
    conn = db_connect(); cur = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        cur.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM purchases")
        total_docs, total_amount = cur.fetchone()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM purchases WHERE created_at LIKE ?", (f'{today}%',))
        today_docs, today_amount = cur.fetchone()
        cur.execute("SELECT purchase_no, created_at, provider_name, total FROM purchases ORDER BY id DESC LIMIT 20")
        recent = cur.fetchall()
        return {
            'count': int(total_docs or 0),
            'amount': safe_float(total_amount),
            'today_count': int(today_docs or 0),
            'today_amount': safe_float(today_amount),
            'recent': recent,
        }
    finally:
        conn.close()


def cyber_summary():
    stations = load_cyber_stations()
    conn = db_connect(); cur = conn.cursor()
    summary = {'stations': stations, 'active_sessions': 0, 'today_sessions': 0, 'today_amount': 0.0, 'in_use': 0, 'free': 0, 'maintenance': 0, 'recent_sessions': []}
    try:
        cur.execute("SELECT COUNT(*) FROM cyber_sessions WHERE status='ACTIVA'")
        summary['active_sessions'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount),0) FROM cyber_sessions WHERE date(started_at)=date('now','localtime')")
        row = cur.fetchone() or (0,0)
        summary['today_sessions'] = row[0] or 0
        summary['today_amount'] = safe_float(row[1])
        cur.execute(
            """
            SELECT station_code, customer_name, started_at, finished_at, total_amount, status
            FROM cyber_sessions
            ORDER BY id DESC
            LIMIT 8
            """
        )
        summary['recent_sessions'] = [
            {'station_code': r[0], 'customer_name': r[1] or 'Público General', 'started_at': r[2] or '', 'finished_at': r[3] or '', 'total_amount': safe_float(r[4]), 'status': r[5] or 'ACTIVA'}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()
    for st in stations:
        status=(st['status'] or 'Libre').lower()
        if 'uso' in status:
            summary['in_use'] += 1
        elif 'manten' in status:
            summary['maintenance'] += 1
        else:
            summary['free'] += 1
    return summary


class DashboardView(ttk.Frame):
    PANEL_BG = "#24384d"
    PANEL_HEADER = "#223247"
    PANEL_BORDER = "#1a2937"
    SURFACE = "#f1f4f8"
    TEXT_DARK = "#223040"
    MUTED_DARK = "#617080"
    WHITE = "#ffffff"

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.configure(padding=0)
        self.stats = self._load_stats()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.top_strip = tk.Frame(self, bg=self.SURFACE)
        self.top_strip.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.top_strip.columnconfigure((0, 1, 2, 3, 4), weight=1)

        cards = [
            ("💰", "Ventas Hoy", f"Q {self.stats['today_amount']:.2f}", "#f0c94f"),
            ("🖥", "PCs en Uso", str(self.stats['pcs_in_use']), "#4ea0ff"),
            ("📦", "Stock Bajo", str(self.stats['low_stock']), "#62c46d"),
            ("🛠", "Tickets Pendientes", str(self.stats['pending_tickets']), "#e06b6b"),
        ]
        for idx, (icon, title, value, accent) in enumerate(cards):
            self._create_metric_card(self.top_strip, idx, icon, title, value, accent)
        self._create_date_card(self.top_strip, 4)

        body = tk.Frame(self, bg=self.SURFACE)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=11)
        body.columnconfigure(1, weight=17)
        body.columnconfigure(2, weight=12)
        body.rowconfigure(0, weight=11)
        body.rowconfigure(1, weight=5)

        self._build_pos_panel(body).grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
        self._build_cyber_panel(body).grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=(0, 12))
        self._build_service_panel(body).grid(row=0, column=2, sticky="nsew", pady=(0, 12))

        self._build_inventory_summary(body).grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self._build_sales_summary(body).grid(row=1, column=1, sticky="nsew", padx=(0, 10))
        self._build_finance_summary(body).grid(row=1, column=2, sticky="nsew")

    def _create_panel(self, parent, title, icon="", actions=None):
        frame = tk.Frame(parent, bg=self.PANEL_BG, highlightthickness=1, highlightbackground=self.PANEL_BORDER)
        header = tk.Frame(frame, bg=self.PANEL_HEADER, height=42)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_lbl = tk.Label(
            header,
            text=f"{icon}  {title}" if icon else title,
            bg=self.PANEL_HEADER,
            fg=self.WHITE,
            font=("Segoe UI Semibold", 13),
            anchor="w",
            padx=14,
        )
        title_lbl.pack(side="left", fill="both", expand=True)
        for action in actions or []:
            tk.Label(
                header,
                text=action,
                bg=self.PANEL_HEADER,
                fg="#c9d4df",
                font=("Segoe UI Symbol", 12),
                padx=8,
            ).pack(side="right", pady=6)
        return frame

    def _create_metric_card(self, parent, column, icon, title, value, accent):
        card = tk.Frame(parent, bg=self.PANEL_BG, highlightthickness=1, highlightbackground=self.PANEL_BORDER)
        card.grid(row=0, column=column, sticky="ew", padx=(0, 8 if column < 4 else 0))
        icon_box = tk.Label(card, text=icon, bg=accent, fg="#102030", font=("Segoe UI Emoji", 18), width=2)
        icon_box.pack(side="left", padx=12, pady=10)
        text_box = tk.Frame(card, bg=self.PANEL_BG)
        text_box.pack(side="left", fill="both", expand=True, pady=8)
        tk.Label(text_box, text=title, bg=self.PANEL_BG, fg="#f1f5f9", font=("Segoe UI Semibold", 11), anchor="w").pack(anchor="w")
        tk.Label(text_box, text=value, bg=self.PANEL_BG, fg=self.WHITE, font=("Segoe UI Semibold", 20), anchor="w").pack(anchor="w")
        return card

    def _create_date_card(self, parent, column):
        card = tk.Frame(parent, bg=self.PANEL_BG, highlightthickness=1, highlightbackground=self.PANEL_BORDER)
        card.grid(row=0, column=column, sticky="ew")
        self.date_label = tk.Label(card, bg=self.PANEL_BG, fg="#dbe4ee", font=("Segoe UI", 12), anchor="center")
        self.date_label.pack(fill="both", expand=True, padx=10, pady=16)
        self._refresh_datetime()
        return card

    def _refresh_datetime(self):
        months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        now = datetime.now()
        label = f"{days[now.weekday()]}, {now.day} de {months[now.month-1].title()}\nAdministrador | {now.strftime('%I:%M:%S %p')}"
        if hasattr(self, 'date_label'):
            self.date_label.configure(text=label)
            self.after(1000, self._refresh_datetime)

    def _build_pos_panel(self, parent):
        panel = self._create_panel(parent, "Punto de Venta", "🧾", actions=["⚙", "⟳"])
        inner = tk.Frame(panel, bg=self.SURFACE)
        inner.pack(fill="both", expand=True, padx=12, pady=12)

        search_wrap = tk.Frame(inner, bg="#dfe5ec", highlightthickness=1, highlightbackground="#c3ccd6")
        search_wrap.pack(fill="x")
        tk.Label(search_wrap, text="Search...", bg="#ffffff", fg="#7b8794", font=("Segoe UI", 11), anchor="w", padx=12).pack(side="left", fill="x", expand=True, ipady=8)
        tk.Label(search_wrap, text="🔍", bg="#ffffff", fg="#223040", font=("Segoe UI Emoji", 16), width=3).pack(side="right", pady=2)

        lines = self.stats["pos_preview"]
        list_box = tk.Frame(inner, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
        list_box.pack(fill="x", pady=(12, 10))
        for idx, row in enumerate(lines):
            line = tk.Frame(list_box, bg="#ffffff")
            line.pack(fill="x")
            tk.Label(line, text=row["name"], bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 10 if idx == 0 else 11), anchor="w").pack(side="left", padx=12, pady=10)
            tk.Label(line, text=row["price"], bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 11), anchor="e").pack(side="right", padx=12)
            if idx < len(lines) - 1:
                tk.Frame(list_box, bg="#e7edf3", height=1).pack(fill="x")

        total_box = tk.Frame(inner, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
        total_box.pack(fill="x")
        tk.Label(total_box, text="Total:", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 18), anchor="w").pack(side="left", padx=12, pady=12)
        tk.Label(total_box, text=f"Q {self.stats['today_amount']:.2f}", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 18), anchor="e").pack(side="right", padx=12)

        btn_row = tk.Frame(inner, bg=self.SURFACE)
        btn_row.pack(fill="x", pady=(12, 10))
        for text, color in [("Efectivo", "#53a95a"), ("Tarjeta", "#5cbf61"), ("Mixto", "#60bf6f")]:
            tk.Button(btn_row, text=text, bg=color, fg="white", activebackground=color, activeforeground="white", relief="flat", font=("Segoe UI Semibold", 11), bd=0).pack(side="left", fill="x", expand=True, padx=(0, 6) if text != "Mixto" else 0, ipady=8)

        tk.Button(inner, text="Cobrar", bg="#16a34a", fg="white", activebackground="#15803d", activeforeground="white", relief="flat", font=("Segoe UI Semibold", 18), bd=0).pack(fill="x", ipady=10)

        footer = tk.Frame(inner, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
        footer.pack(fill="x", pady=(10, 0))
        tk.Label(footer, text=f"Cliente: {self.stats['top_customer']}", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 11), anchor="w").pack(side="left", padx=12, pady=10)
        tk.Button(footer, text="Devolución  ❯", bg="#bb5a5a", fg="white", activebackground="#a84444", activeforeground="white", relief="flat", font=("Segoe UI Semibold", 11), bd=0).pack(side="right", padx=10, pady=8)
        return panel

    def _build_cyber_panel(self, parent):
        panel = self._create_panel(parent, "Cibercafé / Consolas", "🎮", actions=["▦", "☷"])
        inner = tk.Frame(panel, bg=self.PANEL_BG)
        inner.pack(fill="both", expand=True, padx=12, pady=12)
        inner.columnconfigure((0, 1, 2, 3), weight=1)

        tabs = tk.Frame(inner, bg=self.PANEL_BG)
        tabs.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        tk.Label(tabs, text="Estaciones", bg=self.PANEL_BG, fg=self.WHITE, font=("Segoe UI Semibold", 11), padx=8).pack(side="left")
        tk.Frame(tabs, bg="#cf8d6a", width=36, height=2).pack(side="left", pady=(20, 0))
        for ico in ["📄", "🕘", "⚙"]:
            tk.Label(tabs, text=ico, bg=self.PANEL_BG, fg="#d6dee7", font=("Segoe UI Emoji", 11), padx=6).pack(side="left")

        for idx, station in enumerate(self.stats['stations'][:8]):
            card = tk.Frame(inner, bg=station['color'], highlightthickness=1, highlightbackground="#214b78")
            r, c = divmod(idx, 4)
            card.grid(row=r + 1, column=c, sticky="nsew", padx=6, pady=6, ipadx=6, ipady=4)
            tk.Label(card, text=station['icon'], bg=station['color'], fg="#0f2438", font=("Segoe UI Emoji", 30)).pack(pady=(8, 0))
            tk.Label(card, text=station['name'], bg=station['color'], fg="white", font=("Segoe UI Semibold", 16)).pack(pady=(4, 0))
            tk.Label(card, text=station['status'], bg=station['color'], fg="#dceefe", font=("Segoe UI", 9)).pack(pady=(0, 1))
            extra = station.get('customer_name') or (money_gt(station.get('rate_per_hour', 0)) + '/h')
            tk.Label(card, text=extra, bg=station['color'], fg="#eaf4ff", font=("Segoe UI", 8)).pack(pady=(0, 8))

        action_bar = tk.Frame(inner, bg="#2b4158")
        action_bar.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 8))
        tk.Label(action_bar, text=f"⏱  Sesiones activas  {self.stats['active_sessions']}", bg="#2b4158", fg="white", font=("Segoe UI Semibold", 11)).pack(side="left", padx=10, pady=10)
        tk.Button(action_bar, text="Agregar Tiempo", bg="#3b82f6", fg="white", activebackground="#2563eb", activeforeground="white", relief="flat", font=("Segoe UI Semibold", 10), bd=0).pack(side="left", padx=8, pady=8, ipady=4)
        tk.Button(action_bar, text="Venta Snacks", bg="#718096", fg="white", activebackground="#5f6b7a", activeforeground="white", relief="flat", font=("Segoe UI Semibold", 10), bd=0).pack(side="left", pady=8, ipady=4)

        sub_bar = tk.Frame(inner, bg=self.PANEL_BG)
        sub_bar.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        tk.Label(sub_bar, text=f"🖨  Sesiones hoy: {self.stats['cyber_today_sessions']}", bg=self.PANEL_BG, fg="#edf2f7", font=("Segoe UI Semibold", 10)).pack(side="left", padx=10)
        tk.Label(sub_bar, text=f"📄  Libres: {self.stats['free_sessions']} | Mantenimiento: {self.stats['maintenance_stations']}", bg=self.PANEL_BG, fg="#edf2f7", font=("Segoe UI Semibold", 10)).pack(side="left", padx=18)

        image_zone = tk.Frame(inner, bg="#5d6a79", height=152)
        image_zone.grid(row=5, column=0, columnspan=4, sticky="nsew")
        image_zone.grid_propagate(False)
        try:
            if Image and os.path.exists(LOGO_PATH):
                img = Image.open(LOGO_PATH).convert("RGBA")
                img.thumbnail((520, 140))
                self.cyber_img = ImageTk.PhotoImage(img)
                tk.Label(image_zone, image=self.cyber_img, bg="#5d6a79").pack(expand=True)
            else:
                raise RuntimeError("Sin imagen")
        except Exception:
            tk.Label(image_zone, text="Zona operativa del cibercafé y consolas\nLista para conectarse a sesiones reales en la siguiente fase.", bg="#5d6a79", fg="white", font=("Segoe UI Semibold", 14), justify="center").pack(expand=True)
        return panel

    def _build_service_panel(self, parent):
        panel = self._create_panel(parent, "Servicio Técnico", "🛠", actions=["⚙", "⟳"])
        inner = tk.Frame(panel, bg=self.PANEL_BG)
        inner.pack(fill="both", expand=True, padx=12, pady=12)

        ticket_list = tk.Frame(inner, bg=self.SURFACE)
        ticket_list.pack(fill="x")
        accent_map = {
            "En Proceso": "#d35d5d",
            "Listo para Entrega": "#d9aa45",
            "En Diagnóstico": "#616b78",
            "En Reparación": "#cf6a4c",
        }
        for ticket in self.stats["recent_tickets"][:3]:
            card = tk.Frame(ticket_list, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
            card.pack(fill="x", pady=(0, 8))
            row = tk.Frame(card, bg="#ffffff")
            row.pack(fill="x", padx=10, pady=10)
            tk.Label(row, text="▣", bg=accent_map.get(ticket['status'], "#7a8794"), fg="white", font=("Segoe UI Symbol", 14), width=2).pack(side="left", padx=(0, 8))
            txt = tk.Frame(row, bg="#ffffff")
            txt.pack(side="left", fill="both", expand=True)
            tk.Label(txt, text=f"Ticket {ticket['ticket_no']} {ticket['equipment_name']}", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 11), anchor="w").pack(anchor="w")
            tk.Label(txt, text=ticket['status'], bg="#ffffff", fg="#b65353", font=("Segoe UI", 10), anchor="w").pack(anchor="w")
            tk.Label(row, text="❯", bg="#ffffff", fg="#637385", font=("Segoe UI Symbol", 16)).pack(side="right")

        detail_wrap = tk.Frame(inner, bg=self.PANEL_BG)
        detail_wrap.pack(fill="both", expand=True, pady=(6, 0))
        tk.Label(detail_wrap, text="◀  Detalles de Servicio", bg=self.PANEL_BG, fg="white", font=("Segoe UI Semibold", 11), anchor="w").pack(fill="x", pady=(0, 8))

        selected = self.stats["selected_ticket"]
        detail_card = tk.Frame(detail_wrap, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
        detail_card.pack(fill="both", expand=True)
        for label, value in [
            ("Cliente", selected.get("client_name") or "Sin cliente"),
            ("Equipo", selected.get("equipment_name") or selected.get("equipment_type") or "Sin equipo"),
            ("Problema", selected.get("issue_reported") or "Sin detalle"),
            ("Estado", selected.get("status") or "Sin estado"),
        ]:
            row = tk.Frame(detail_card, bg="#ffffff")
            row.pack(fill="x")
            tk.Label(row, text=f"{label}:", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 11), width=10, anchor="w").pack(side="left", padx=12, pady=10)
            fg = "#b65353" if label == "Estado" else self.TEXT_DARK
            tk.Label(row, text=value, bg="#ffffff", fg=fg, font=("Segoe UI", 11), anchor="w").pack(side="left", padx=(0, 10), pady=10)
            tk.Frame(detail_card, bg="#ebeff4", height=1).pack(fill="x")

        btns = tk.Frame(detail_wrap, bg=self.PANEL_BG)
        btns.pack(fill="x", pady=(10, 0))
        tk.Button(btns, text="Actualizar Estado", bg="#3182ce", fg="white", activebackground="#2b6cb0", activeforeground="white", relief="flat", font=("Segoe UI Semibold", 11), bd=0).pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=8)
        tk.Button(btns, text="Ver Historial", bg="#c05656", fg="white", activebackground="#9b2c2c", activeforeground="white", relief="flat", font=("Segoe UI Semibold", 11), bd=0).pack(side="left", fill="x", expand=True, ipady=8)
        return panel

    def _build_inventory_summary(self, parent):
        panel = self._create_panel(parent, "Inventario", "▦", actions=["⚙"])
        inner = tk.Frame(panel, bg=self.SURFACE)
        inner.pack(fill="both", expand=True, padx=12, pady=12)
        for label, value, tone in [
            ("Productos en Stock", str(self.stats['items']), self.TEXT_DARK),
            ("Stock Bajo", str(self.stats['low_stock']), "#b44f5d"),
        ]:
            row = tk.Frame(inner, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
            row.pack(fill="x", pady=(0, 8))
            tk.Label(row, text=label, bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 11), anchor="w").pack(side="left", padx=12, pady=12)
            tk.Label(row, text=value, bg="#ffffff", fg=tone, font=("Segoe UI Semibold", 18)).pack(side="right", padx=12)
        return panel

    def _build_sales_summary(self, parent):
        panel = self._create_panel(parent, "Ventas del Día", "▤")
        inner = tk.Frame(panel, bg=self.SURFACE)
        inner.pack(fill="both", expand=True, padx=12, pady=12)
        card = tk.Frame(inner, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
        card.pack(fill="both", expand=True)
        tk.Label(card, text="Ingresos Totales", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 12), anchor="w").pack(anchor="w", padx=12, pady=(12, 0))
        tk.Label(card, text=f"Q {self.stats['today_amount']:.2f}", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 26), anchor="w").pack(anchor="w", padx=12)
        canvas = tk.Canvas(card, bg="#ffffff", height=86, highlightthickness=0)
        canvas.pack(fill="x", padx=8, pady=(2, 10))
        values = self.stats['sales_bars']
        w = 520
        h = 80
        max_v = max(values) if values else 1
        prev = None
        spacing = w / max(1, len(values))
        for i, val in enumerate(values):
            x = 24 + i * spacing
            bar_h = (val / max_v) * 44
            canvas.create_rectangle(x, h - bar_h, x + 28, h, fill="#8dc4f5", outline="#8dc4f5")
            y = h - bar_h - 8
            canvas.create_oval(x + 8, y - 4, x + 16, y + 4, fill="#5aa1dc", outline="#5aa1dc")
            if prev is not None:
                canvas.create_line(prev[0], prev[1], x + 12, y, fill="#6ea9d8", width=2)
            prev = (x + 12, y)
        return panel

    def _build_finance_summary(self, parent):
        panel = self._create_panel(parent, "Caja / Finanzas", "💼", actions=["☰", "⚙"])
        inner = tk.Frame(panel, bg=self.SURFACE)
        inner.pack(fill="both", expand=True, padx=12, pady=12)
        for order in self.stats['finance_cards']:
            card = tk.Frame(inner, bg="#ffffff", highlightthickness=1, highlightbackground="#d5dbe3")
            card.pack(side="left", fill="both", expand=True, padx=(0, 8) if order != self.stats['finance_cards'][-1] else 0)
            tk.Label(card, text=order['provider'], bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=12, pady=(10, 4))
            tk.Label(card, text=order['order'], bg="#ffffff", fg=self.MUTED_DARK, font=("Segoe UI", 10)).pack(anchor="w", padx=12)
            tk.Label(card, text=f"Recibida  {order['amount']}", bg="#ffffff", fg=self.TEXT_DARK, font=("Segoe UI Semibold", 17)).pack(anchor="w", padx=12, pady=(12, 2))
            tk.Label(card, text=f"Utilidad Neta  {order['profit']}", bg="#ffffff", fg="#43936d", font=("Segoe UI Semibold", 15)).pack(anchor="w", padx=12, pady=(0, 12))
        return panel

    def _station_visual(self, station):
        status = (station.get('status') or 'Libre').lower()
        station_type = (station.get('station_type') or 'PC').lower()
        if 'manten' in status:
            color = '#8b6f47'
        elif 'uso' in status:
            color = '#67c65c'
        else:
            color = '#3e92e0'
        icon = '🎮' if 'consola' in station_type or 'ps' in station.get('station_name', '').lower() or 'xbox' in station.get('station_name', '').lower() else '🖥'
        return {
            'name': station.get('station_name') or station.get('station_code') or 'Estación',
            'status': station.get('status') or 'Libre',
            'color': color,
            'icon': icon,
            'customer_name': station.get('customer_name') or '',
            'rate_per_hour': station.get('rate_per_hour') or 0,
        }

    def _load_stats(self):
        conn = db_connect()
        cur = conn.cursor()
        stats = {
            "tickets": 0,
            "clients": 0,
            "items": 0,
            "low_stock": 0,
            "pending_tickets": 0,
            "recent_tickets": [],
            "selected_ticket": {},
            "top_customer": "Público General",
        }
        try:
            cur.execute("SELECT COUNT(*) FROM technical_tickets")
            stats["tickets"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM clients WHERE status='Activo'")
            stats["clients"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM inventory_items")
            stats["items"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM inventory_items WHERE item_type='Producto' AND stock <= min_stock")
            stats["low_stock"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM technical_tickets WHERE COALESCE(status,'') NOT IN ('Entregado','Cancelado')")
            stats["pending_tickets"] = cur.fetchone()[0]
            cur.execute(
                """
                SELECT ticket_no, client_name, equipment_type, equipment_name, status, issue_reported, created_at
                FROM technical_tickets
                ORDER BY id DESC
                LIMIT 6
                """
            )
            rows = cur.fetchall()
            stats["recent_tickets"] = [
                {
                    "ticket_no": ticket_no or "#----",
                    "client_name": client_name or "",
                    "equipment_type": equipment_type or "",
                    "equipment_name": equipment_name or equipment_type or "Equipo",
                    "status": status or "Pendiente",
                    "issue_reported": issue_reported or "",
                    "created_at": created_at or "",
                }
                for ticket_no, client_name, equipment_type, equipment_name, status, issue_reported, created_at in rows
            ]
            if stats["recent_tickets"]:
                stats["selected_ticket"] = stats["recent_tickets"][0]
            cur.execute(
                """
                SELECT customer_name, COUNT(*) as c
                FROM sales
                WHERE COALESCE(status,'ACTIVA')='ACTIVA' AND COALESCE(customer_name,'')<>''
                GROUP BY customer_name
                ORDER BY c DESC, customer_name ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row and row[0]:
                stats["top_customer"] = row[0]
        finally:
            conn.close()

        s = sales_summary()
        cyber = cyber_summary()
        sales_values = [safe_float(r.get("total_val")) for r in s["recent"][:7]]
        if len(sales_values) < 7:
            filler = [1200, 900, 1450, 980, 1800, 1600, 2100]
            sales_values.extend(filler[len(sales_values):])
        today_count = s["today_count"]
        active_stations = cyber['in_use']
        free_sessions = cyber['free']
        finance_cards = [
            {"provider": "HP Distribuciones", "order": "Orden #0212", "amount": f"Q {max(s['today_amount'] * 4.2, 15250):,.2f}".replace(',', '_').replace('.', ',').replace('_', '.'), "profit": f"Q {max(s['today_amount'] * 1.8, 7052):,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')},
            {"provider": "Compusupply S.A.", "order": "Orden #0205", "amount": f"Q {max(s['today_amount'] * 2.6, 8500):,.2f}".replace(',', '_').replace('.', ',').replace('_', '.'), "profit": f"Q {max(s['today_amount'] * 1.15, 7052):,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')},
        ]
        preview = []
        for row in s["recent"][:3]:
            preview.append({
                "name": row.get("cliente") or "Venta mostrador",
                "price": f"Q{safe_float(row.get('total_val')):,.2f}".replace(',', '_').replace('.', ',').replace('_', '.'),
            })
        if not preview:
            preview = [
                {"name": "Laptop Dell Inspiron", "price": "Q5,000"},
                {"name": "Mouse Logitech G203", "price": "Q125"},
                {"name": "Descuento", "price": "-Q50.00"},
            ]
        elif len(preview) == 1:
            preview.extend([
                {"name": "Servicio técnico", "price": "Q350"},
                {"name": "Descuento", "price": "-Q25.00"},
            ])
        elif len(preview) == 2:
            preview.append({"name": "Descuento", "price": "-Q25.00"})

        return {
            **stats,
            "sales_count": s["count"],
            "sales_amount": s["amount"],
            "today_sales": s["today_count"],
            "today_amount": s["today_amount"],
            "recent_sales": s["recent"],
            "pcs_in_use": active_stations,
            "free_sessions": free_sessions,
            "maintenance_stations": cyber["maintenance"],
            "active_sessions": cyber["active_sessions"],
            "cyber_today_sessions": cyber["today_sessions"],
            "cyber_today_amount": cyber["today_amount"],
            "stations": [self._station_visual(st) for st in cyber["stations"]],
            "active_time": "01:15:23",
            "sales_bars": sales_values,
            "finance_cards": finance_cards,
            "pos_preview": preview,
        }


class CyberCafeView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style='Card.TFrame', padding=14)
        self.station_map = {}
        self.selected_station_id = None
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style='Card.TFrame')
        header.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 12))
        for i in range(4):
            header.columnconfigure(i, weight=1)
        self.metric_cards = []
        for idx in range(4):
            card = ttk.Frame(header, style='Metric.TFrame', padding=12)
            card.grid(row=0, column=idx, sticky='ew', padx=(0, 10) if idx < 3 else 0)
            title = ttk.Label(card, text='-', style='Small.TLabel')
            title.pack(anchor='w')
            value = ttk.Label(card, text='0', style='MetricValue.TLabel')
            value.pack(anchor='w', pady=(4,0))
            self.metric_cards.append((title, value))

        left = ttk.Frame(self, style='Card.TFrame', padding=14)
        left.grid(row=1, column=0, sticky='nsew', padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        station_top = ttk.Frame(left, style='Card.TFrame')
        station_top.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        station_top.columnconfigure(0, weight=1)
        ttk.Label(station_top, text='Estaciones', style='Section.TLabel').grid(row=0, column=0, sticky='w')
        cols = ('codigo', 'tipo', 'estado', 'tarifa', 'cliente')
        self.station_tree = ttk.Treeview(left, columns=cols, show='headings', height=14)
        for col, txt, w in [('codigo','Código',110),('tipo','Tipo',100),('estado','Estado',120),('tarifa','Tarifa/h',90),('cliente','Cliente actual',180)]:
            self.station_tree.heading(col, text=txt)
            self.station_tree.column(col, width=w, anchor='w')
        install_column_manager(station_top, self.station_tree, 'cyber_estaciones', row=0, column=1, padx=(0, 0), pady=(0, 0))
        self.station_tree.grid(row=1, column=0, sticky='nsew')
        self.station_tree.bind('<<TreeviewSelect>>', self._on_station_select)
        sb = ttk.Scrollbar(left, orient='vertical', command=self.station_tree.yview)
        sb.grid(row=1, column=1, sticky='ns')
        self.station_tree.configure(yscrollcommand=sb.set)
        left.rowconfigure(1, weight=1)

        actions = ttk.Frame(left, style='Card.TFrame')
        actions.grid(row=2, column=0, sticky='ew', pady=(10,0))
        for i in range(5):
            actions.columnconfigure(i, weight=1)
        ttk.Button(actions, text='Iniciar', command=self.start_session).grid(row=0,column=0,sticky='ew',padx=(0,6))
        ttk.Button(actions, text='Agregar tiempo', command=self.add_time).grid(row=0,column=1,sticky='ew',padx=(0,6))
        ttk.Button(actions, text='Finalizar', command=self.finish_session).grid(row=0,column=2,sticky='ew',padx=(0,6))
        ttk.Button(actions, text='Mantenimiento', command=self.toggle_maintenance).grid(row=0,column=3,sticky='ew',padx=(0,6))
        ttk.Button(actions, text='Refrescar', command=self.refresh_data).grid(row=0,column=4,sticky='ew')

        right = ttk.Frame(self, style='Card.TFrame', padding=14)
        right.grid(row=1, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)
        ttk.Label(right, text='Detalle de estación', style='Section.TLabel').grid(row=0, column=0, sticky='w')
        self.detail_text = tk.Text(right, height=10, wrap='word', relief='flat', bg='#f8fafc', fg='#223040', font=('Segoe UI', 10))
        self.detail_text.grid(row=1, column=0, sticky='nsew', pady=(8,12))
        self.detail_text.configure(state='disabled')
        recent_top = ttk.Frame(right, style='Card.TFrame')
        recent_top.grid(row=2, column=0, sticky='ew', pady=(0, 6))
        recent_top.columnconfigure(0, weight=1)
        ttk.Label(recent_top, text='Sesiones recientes', style='Section.TLabel').grid(row=0, column=0, sticky='w')
        cols2=('estacion','cliente','inicio','estado','total')
        self.recent_tree = ttk.Treeview(right, columns=cols2, show='headings', height=10)
        for col, txt, w in [('estacion','Estación',90),('cliente','Cliente',140),('inicio','Inicio',130),('estado','Estado',90),('total','Total',90)]:
            self.recent_tree.heading(col, text=txt)
            self.recent_tree.column(col, width=w, anchor='w')
        install_column_manager(recent_top, self.recent_tree, 'cyber_sesiones_recientes', row=0, column=1, padx=(0, 0), pady=(0, 0))
        self.recent_tree.grid(row=3, column=0, sticky='nsew', pady=(0,0))
        right.rowconfigure(3, weight=1)

        self.refresh_data()

    def refresh_data(self):
        summary = cyber_summary()
        labels = [
            ('Estaciones en uso', str(summary['in_use'])),
            ('Estaciones libres', str(summary['free'])),
            ('Sesiones hoy', str(summary['today_sessions'])),
            ('Ingreso hoy', money_gt(summary['today_amount'])),
        ]
        for idx, (title, value) in enumerate(labels):
            self.metric_cards[idx][0].configure(text=title)
            self.metric_cards[idx][1].configure(text=value)
        self.station_map = {row['id']: row for row in summary['stations']}
        for iid in self.station_tree.get_children():
            self.station_tree.delete(iid)
        for row in summary['stations']:
            iid = str(row['id'])
            self.station_tree.insert('', 'end', iid=iid, values=(row['station_name'], row['station_type'], row['status'], money_gt(row['rate_per_hour']), row['customer_name'] or '—'))
        for iid in self.recent_tree.get_children():
            self.recent_tree.delete(iid)
        for row in summary['recent_sessions']:
            self.recent_tree.insert('', 'end', values=(row['station_code'], row['customer_name'], (row['started_at'] or '').replace('T',' '), row['status'], money_gt(row['total_amount'])))
        if self.selected_station_id and str(self.selected_station_id) in self.station_tree.get_children():
            self.station_tree.selection_set(str(self.selected_station_id))
            self.station_tree.focus(str(self.selected_station_id))
        elif summary['stations']:
            first = str(summary['stations'][0]['id'])
            self.station_tree.selection_set(first)
            self.station_tree.focus(first)
            self.selected_station_id = int(first)
        self._render_detail()

    def _on_station_select(self, event=None):
        sel = self.station_tree.selection()
        if not sel:
            return
        self.selected_station_id = int(sel[0])
        self._render_detail()

    def _render_detail(self):
        row = self.station_map.get(self.selected_station_id)
        if not row:
            text = 'Selecciona una estación para ver su detalle.'
        else:
            text = "\n".join([
                f"Estación: {row['station_name']}",
                f"Tipo: {row['station_type']}",
                f"Estado: {row['status']}",
                f"Tarifa por hora: {money_gt(row['rate_per_hour'])}",
                f"Cliente actual: {row['customer_name'] or 'Público General'}",
                f"Minutos comprados: {row['minutes_purchased']}",
                f"Minutos usados: {row['minutes_used']}",
                f"Inicio sesión: {(row['started_at'] or '—').replace('T', ' ')}",
                f"Venta ligada: {row.get('sale_correlativo') or 'Pendiente de cobro'}",
                f"Método de pago: {row.get('payment_method') or 'Pendiente'}",
            ])
        self.detail_text.configure(state='normal')
        self.detail_text.delete('1.0', 'end')
        self.detail_text.insert('1.0', text)
        self.detail_text.configure(state='disabled')

    def _selected_station(self):
        if not self.selected_station_id:
            messagebox.showwarning('Cibercafé', 'Selecciona una estación primero.')
            return None
        row = self.station_map.get(self.selected_station_id)
        if not row:
            messagebox.showwarning('Cibercafé', 'No se encontró la estación seleccionada.')
        return row

    def start_session(self):
        row = self._selected_station()
        if not row:
            return
        if row['current_session_id']:
            messagebox.showinfo('Cibercafé', 'La estación ya tiene una sesión activa.')
            return
        customer = simpledialog.askstring('Iniciar sesión', f"Cliente para {row['station_name']}:", initialvalue='Público General', parent=self)
        if customer is None:
            return
        minutes = simpledialog.askinteger('Tiempo', 'Minutos a cargar:', initialvalue=60, minvalue=15, maxvalue=720, parent=self)
        if not minutes:
            return
        now = datetime.now().isoformat(timespec='seconds')
        total_amount = (safe_float(row['rate_per_hour']) / 60.0) * minutes
        conn = db_connect(); cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO cyber_sessions (station_id, station_code, customer_name, started_at, minutes_purchased, minutes_used, rate_per_hour, total_amount, status) VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'ACTIVA')",
                (row['id'], row['station_code'], customer.strip() or 'Público General', now, int(minutes), safe_float(row['rate_per_hour']), total_amount),
            )
            session_id = cur.lastrowid
            cur.execute("UPDATE cyber_stations SET status='En uso', current_session_id=? WHERE id=?", (session_id, row['id']))
            conn.commit()
        finally:
            conn.close()
        self.refresh_data()

    def add_time(self):
        row = self._selected_station()
        if not row:
            return
        if not row['current_session_id']:
            messagebox.showinfo('Cibercafé', 'La estación no tiene una sesión activa.')
            return
        extra = simpledialog.askinteger('Agregar tiempo', 'Minutos extra a sumar:', initialvalue=30, minvalue=5, maxvalue=720, parent=self)
        if not extra:
            return
        conn = db_connect(); cur = conn.cursor()
        try:
            new_minutes = int(row['minutes_purchased']) + int(extra)
            total_amount = (safe_float(row['rate_per_hour']) / 60.0) * new_minutes
            cur.execute('UPDATE cyber_sessions SET minutes_purchased=?, total_amount=? WHERE id=?', (new_minutes, total_amount, row['current_session_id']))
            conn.commit()
        finally:
            conn.close()
        self.refresh_data()

    def finish_session(self):
        row = self._selected_station()
        if not row:
            return
        if not row['current_session_id']:
            messagebox.showinfo('Cibercafé', 'La estación no tiene sesión activa.')
            return

        total_amount = round(safe_float(row['rate_per_hour']) / 60.0 * int(row['minutes_purchased'] or 0), 2)
        payment_method = simpledialog.askstring(
            'Cobro de sesión',
            f"Método de pago para {row['station_name']}\nEscribe: EFECTIVO, TARJETA, TRANSFERENCIA, DEPOSITO o CREDITO",
            initialvalue='EFECTIVO',
            parent=self,
        )
        if payment_method is None:
            return
        payment_method = (payment_method or 'EFECTIVO').strip().upper()
        valid_methods = {'EFECTIVO', 'TARJETA', 'TRANSFERENCIA', 'DEPOSITO', 'CRÉDITO', 'CREDITO'}
        if payment_method not in valid_methods:
            messagebox.showwarning('Cibercafé', 'Método inválido. Usa EFECTIVO, TARJETA, TRANSFERENCIA, DEPOSITO o CREDITO.')
            return

        document_type = simpledialog.askstring(
            'Documento',
            'Tipo de documento: TICKET o FACTURA',
            initialvalue='TICKET',
            parent=self,
        )
        if document_type is None:
            return
        document_type = 'FACTURA' if str(document_type).strip().upper() == 'FACTURA' else 'TICKET'

        customer_name = (row.get('customer_name') or 'Público General').strip() or 'Público General'
        if not messagebox.askyesno('Finalizar sesión', f"Cerrar sesión de {row['station_name']} y registrar cobro por {money_gt(total_amount)}?"):
            return

        sale_info = create_sale_record(
            item_name=f"Servicio Cibercafé {row['station_name']}",
            total_amount=total_amount,
            payment_method=payment_method,
            customer_name=customer_name,
            document_type=document_type,
            user_name='ADMIN',
            item_type='Servicio',
            source_item_code=row['station_code'],
            payload={
                'origin': 'cybercafe',
                'station_code': row['station_code'],
                'station_name': row['station_name'],
                'minutes_purchased': int(row['minutes_purchased'] or 0),
            },
        )

        finished_at = datetime.now().isoformat(timespec='seconds')
        conn = db_connect(); cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE cyber_sessions SET status='FINALIZADA', finished_at=?, minutes_used=minutes_purchased, sale_id=?, sale_correlativo=?, payment_method=? WHERE id=?",
                (finished_at, sale_info['sale_id'], sale_info['correlativo'], payment_method, row['current_session_id'])
            )
            cur.execute("UPDATE cyber_stations SET status='Libre', current_session_id=NULL WHERE id=?", (row['id'],))
            conn.commit()
        finally:
            conn.close()

        self.refresh_data()
        caja_msg = f"Caja abierta #{sale_info['cash_session_id']}" if sale_info['cash_session_id'] else 'Sin caja abierta: la venta sí quedó registrada, pero no se agregó movimiento de caja.'
        messagebox.showinfo(
            'Cibercafé',
            f"Sesión cerrada correctamente.\nVenta: {sale_info['correlativo']}\nMonto: {money_gt(total_amount)}\nPago: {payment_method}\n{caja_msg}"
        )

    def toggle_maintenance(self):
        row = self._selected_station()
        if not row:
            return
        new_status = 'Libre' if (row['status'] or '').lower().startswith('manten') else 'Mantenimiento'
        if row['current_session_id'] and new_status == 'Mantenimiento':
            messagebox.showwarning('Cibercafé', 'Finaliza la sesión activa antes de enviar a mantenimiento.')
            return
        conn = db_connect(); cur = conn.cursor()
        try:
            cur.execute('UPDATE cyber_stations SET status=? WHERE id=?', (new_status, row['id']))
            conn.commit()
        finally:
            conn.close()
        self.refresh_data()


class SalesHubView(ttk.Frame):
    POS_PROCESS = None

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        card = ttk.Frame(self, style="Card.TFrame", padding=24)
        card.grid(row=0, column=0, sticky="nsew")

        ttk.Label(card, text="Módulo de Ventas", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text=(
                "El punto de venta se abre automáticamente al entrar a este módulo. "
                "Si ya está abierto, no se volverá a abrir otra ventana."
            ),
            style="CardTitle.TLabel",
            wraplength=900,
        ).pack(anchor="w", pady=(12, 18))

        self.status = ttk.Label(card, text="Abriendo POS de ventas...", style="CardNote.TLabel")
        self.status.pack(anchor="w", pady=(8, 0))

        self.after(150, self.open_sales_pos)

    def open_sales_pos(self):
        base_dir = os.path.dirname(__file__)
        target = os.path.join(base_dir, "sales_pos_module.py")
        try:
            proc = SalesHubView.POS_PROCESS
            if proc is not None and proc.poll() is None:
                self.status.configure(text="El POS de ventas ya está abierto.")
                return
            env = os.environ.copy()
            env['TECNOMEDIA_SESSION_USER'] = SESSION_USER or 'admin'
            env['TECNOMEDIA_SESSION_ROLE'] = SESSION_ROLE or 'Administrador'
            SalesHubView.POS_PROCESS = subprocess.Popen([sys.executable, target], cwd=base_dir, env=env)
            self.status.configure(text="POS de ventas abierto correctamente.")
        except Exception as e:
            messagebox.showerror("Ventas", f"No se pudo abrir el POS de ventas: {e}")

class CashView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.columnconfigure(0, weight=2)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build()
        self.refresh()

    def _build(self):
        left = ttk.Frame(self, style="Card.TFrame", padding=18)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0,10))
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="Caja", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(left, text="Apertura y cierre enlazados con los ingresos de ventas no crédito.", style="CardTitle.TLabel", wraplength=700).grid(row=1, column=0, sticky="w", pady=(10,16))

        controls = ttk.Frame(left, style="Card.TFrame")
        controls.grid(row=2, column=0, sticky="ew")
        self.btn_open_cash = ttk.Button(controls, text="Abrir caja", style="Primary.TButton", command=self.open_session)
        self.btn_open_cash.pack(side="left", padx=(0,8))
        self.btn_close_cash = ttk.Button(controls, text="Cerrar caja", command=self.close_session)
        self.btn_close_cash.pack(side="left", padx=(0,8))
        self.btn_refresh_cash = ttk.Button(controls, text="Actualizar", command=self.refresh)
        self.btn_refresh_cash.pack(side="left")
        disable_button_if_denied(self.btn_open_cash, 'Caja', 'crear', 'abrir caja')
        disable_button_if_denied(self.btn_close_cash, 'Caja', 'editar', 'cerrar caja')

        self.session_label = ttk.Label(left, text="Sin sesión abierta", style="CardValue.TLabel")
        self.session_label.grid(row=3, column=0, sticky="w", pady=(16, 10))
        self.session_note = ttk.Label(left, text="", style="CardNote.TLabel", wraplength=760)
        self.session_note.grid(row=4, column=0, sticky="w", pady=(0, 14))

        cols = ("fecha", "tipo", "metodo", "monto", "referencia")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=14)
        headers = {"fecha": "Fecha", "tipo": "Movimiento", "metodo": "Método", "monto": "Monto", "referencia": "Referencia"}
        widths = {"fecha": 160, "tipo": 140, "metodo": 100, "monto": 100, "referencia": 140}
        for col in cols:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor="w")
        install_column_manager(left, self.tree, 'caja_movimientos', row=5, column=0, padx=(0, 0), pady=(0, 8))
        self.tree.grid(row=6, column=0, sticky="nsew")
        left.rowconfigure(6, weight=1)

        right = ttk.Frame(self, style="Card.TFrame", padding=18)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew")
        ttk.Label(right, text="Resumen rápido", style="CardTitle.TLabel").pack(anchor="w")
        self.lbl_expected = ttk.Label(right, text="Q 0.00", style="CardValue.TLabel")
        self.lbl_expected.pack(anchor="w", pady=(12, 4))
        self.lbl_meta = ttk.Label(right, text="Esperado en caja", style="CardNote.TLabel")
        self.lbl_meta.pack(anchor="w")
        self.lbl_methods = ttk.Label(right, text="", style="CardTitle.TLabel", wraplength=280, justify="left")
        self.lbl_methods.pack(anchor="w", pady=(16, 0))

    def _active_session(self):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id, opened_at, opening_amount, opened_by FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close()
        return row

    def open_session(self):
        if not require_permission('Caja', 'crear', self, 'abrir caja'):
            return
        if self._active_session():
            messagebox.showinfo("Caja", "Ya existe una caja abierta en esta base.")
            return
        amount = simpledialog.askstring("Abrir caja", "Monto inicial de caja:", parent=self)
        if amount is None:
            return
        opening = safe_float(amount)
        conn = db_connect(); cur = conn.cursor()
        cur.execute("INSERT INTO cash_sessions (opened_at, opened_by, opening_amount, status) VALUES (?, ?, ?, 'ABIERTA')", (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'ADMIN', opening))
        conn.commit(); conn.close()
        self.refresh()
        messagebox.showinfo("Caja", "Caja abierta correctamente.")

    def close_session(self):
        if not require_permission('Caja', 'editar', self, 'cerrar caja'):
            return
        session = self._active_session()
        if not session:
            messagebox.showinfo("Caja", "No hay caja abierta para cerrar.")
            return
        session_id, opened_at, opening_amount, opened_by = session
        expected = self._expected_amount(session_id)
        amount = simpledialog.askstring("Cerrar caja", f"Monto contado en caja. Esperado: Q {expected:.2f}", parent=self)
        if amount is None:
            return
        closing = safe_float(amount)
        diff = closing - expected
        conn = db_connect(); cur = conn.cursor()
        cur.execute(
            """
            UPDATE cash_sessions
            SET status='CERRADA', closed_at=?, closed_by=?, expected_amount=?, closing_amount=?, difference_amount=?
            WHERE id=?
            """,
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'ADMIN', expected, closing, diff, session_id)
        )
        conn.commit(); conn.close()
        self.refresh()
        messagebox.showinfo("Caja", f"Caja cerrada. Diferencia: Q {diff:.2f}")

    def _expected_amount(self, session_id):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_movements WHERE session_id=?", (session_id,))
        movements = safe_float(cur.fetchone()[0])
        cur.execute("SELECT opening_amount FROM cash_sessions WHERE id=?", (session_id,))
        row = cur.fetchone(); conn.close()
        return safe_float(row[0] if row else 0) + movements

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        session = self._active_session()
        if not session:
            self.session_label.configure(text="Sin sesión abierta")
            self.session_note.configure(text="Puedes abrir caja desde aquí. Cuando el POS guarde ventas de contado, depósito, transferencia o tarjeta, se registrarán en los movimientos de esta sesión.")
            self.lbl_expected.configure(text="Q 0.00")
            self.lbl_methods.configure(text="No hay movimientos en una sesión activa.")
            return
        session_id, opened_at, opening_amount, opened_by = session
        expected = self._expected_amount(session_id)
        self.session_label.configure(text=f"Caja abierta desde {opened_at}")
        self.session_note.configure(text=f"Abierta por {opened_by or 'ADMIN'} | Apertura: Q {safe_float(opening_amount):.2f} | Esperado actual: Q {expected:.2f}")
        self.lbl_expected.configure(text=f"Q {expected:.2f}")

        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT created_at, movement_type, payment_method, amount, COALESCE(reference, '') FROM cash_movements WHERE session_id=? ORDER BY id DESC LIMIT 50", (session_id,))
        rows = cur.fetchall()
        cur.execute("SELECT payment_method, COALESCE(SUM(amount), 0) FROM cash_movements WHERE session_id=? GROUP BY payment_method ORDER BY payment_method", (session_id,))
        methods = cur.fetchall()
        conn.close()
        for created_at, movement_type, payment_method, amount, reference in rows:
            self.tree.insert("", "end", values=(created_at, movement_type, payment_method, f"Q {safe_float(amount):.2f}", reference))
        if methods:
            summary = "\n".join(f"• {method or 'sin método'}: Q {safe_float(amount):.2f}" for method, amount in methods)
        else:
            summary = "Sin movimientos aún en la caja activa."
        self.lbl_methods.configure(text=summary)


class ReportsView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self, style="TFrame")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,10))
        self.btn_refresh_reports = ttk.Button(top, text="Actualizar reportes", command=self.refresh)
        self.btn_refresh_reports.pack(side="left")
        disable_button_if_denied(self.btn_refresh_reports, 'Reportes', 'ver', 'actualizar reportes')

        self.summary_left = ttk.Frame(self, style="Card.TFrame", padding=18)
        self.summary_left.grid(row=1, column=0, sticky="nsew", padx=(0,10), pady=(0,10))
        self.summary_right = ttk.Frame(self, style="Card.TFrame", padding=18)
        self.summary_right.grid(row=1, column=1, sticky="nsew", pady=(0,10))

        ttk.Label(self.summary_left, text="Productos más vendidos", style="CardTitle.TLabel").pack(anchor="w")
        cols = ("producto", "cantidad", "monto")
        self.products_tree = ttk.Treeview(self.summary_left, columns=cols, show="headings", height=12)
        for col, width, title in [("producto", 240, "Producto"), ("cantidad", 90, "Cantidad"), ("monto", 100, "Monto")]:
            self.products_tree.heading(col, text=title)
            self.products_tree.column(col, width=width, anchor="w")
        report_bar = ttk.Frame(self.summary_left, style="Card.TFrame")
        report_bar.pack(fill="x", pady=(8, 0))
        ColumnManagerButton(report_bar, self.products_tree, 'reportes_productos').pack(anchor="e")
        self.products_tree.pack(fill="both", expand=True, pady=(8,0))

        ttk.Label(self.summary_right, text="Ventas por método de pago", style="CardTitle.TLabel").pack(anchor="w")
        cols2 = ("metodo", "ventas", "monto")
        self.methods_tree = ttk.Treeview(self.summary_right, columns=cols2, show="headings", height=12)
        for col, width, title in [("metodo", 150, "Método"), ("ventas", 90, "Ventas"), ("monto", 110, "Monto")]:
            self.methods_tree.heading(col, text=title)
            self.methods_tree.column(col, width=width, anchor="w")
        report_bar = ttk.Frame(self.summary_right, style="Card.TFrame")
        report_bar.pack(fill="x", pady=(8, 0))
        ColumnManagerButton(report_bar, self.methods_tree, 'reportes_metodos').pack(anchor="e")
        self.methods_tree.pack(fill="both", expand=True, pady=(8,0))

        self.mov_left = ttk.Frame(self, style="Card.TFrame", padding=18)
        self.mov_left.grid(row=2, column=0, sticky="nsew", padx=(0,10))
        self.mov_right = ttk.Frame(self, style="Card.TFrame", padding=18)
        self.mov_right.grid(row=2, column=1, sticky="nsew")

        ttk.Label(self.mov_left, text="Movimientos de clientes", style="CardTitle.TLabel").pack(anchor="w")
        cols3 = ("fecha", "cliente", "tipo", "metodo", "monto")
        self.client_mov_tree = ttk.Treeview(self.mov_left, columns=cols3, show="headings", height=10)
        for col, width, title in [("fecha", 120, "Fecha"), ("cliente", 180, "Cliente"), ("tipo", 120, "Movimiento"), ("metodo", 100, "Método"), ("monto", 100, "Monto")]:
            self.client_mov_tree.heading(col, text=title)
            self.client_mov_tree.column(col, width=width, anchor="w")
        report_bar = ttk.Frame(self.mov_left, style="Card.TFrame")
        report_bar.pack(fill="x", pady=(8, 0))
        ColumnManagerButton(report_bar, self.client_mov_tree, 'reportes_mov_clientes').pack(anchor="e")
        self.client_mov_tree.pack(fill="both", expand=True, pady=(8,0))

        ttk.Label(self.mov_right, text="Ventas por empleado", style="CardTitle.TLabel").pack(anchor="w")
        cols4 = ("empleado", "ventas", "monto", "comision")
        self.employee_tree = ttk.Treeview(self.mov_right, columns=cols4, show="headings", height=8)
        for col, width, title in [("empleado", 180, "Empleado"), ("ventas", 70, "Ventas"), ("monto", 110, "Monto"), ("comision", 110, "Comisión")]:
            self.employee_tree.heading(col, text=title)
            self.employee_tree.column(col, width=width, anchor="w")
        report_bar = ttk.Frame(self.mov_right, style="Card.TFrame")
        report_bar.pack(fill="x", pady=(8, 0))
        ColumnManagerButton(report_bar, self.employee_tree, 'reportes_ventas_empleado').pack(anchor="e")
        self.employee_tree.pack(fill="both", expand=True, pady=(8,10))

        self.lbl_clients_fin = ttk.Label(self.mov_right, text="Sin datos", style="CardTitle.TLabel", justify="left")
        self.lbl_clients_fin.pack(anchor="w", pady=(4, 0))

        self.lbl_report_head = ttk.Label(self, text="", style="CardTitle.TLabel")
        self.lbl_report_head.grid(row=3, column=0, columnspan=2, sticky="w", pady=(12,0))

    def refresh(self):
        if not require_permission('Reportes', 'ver', self, 'ver reportes'):
            return
        conn = db_connect(); cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM sales WHERE status='ACTIVA'")
            count, amount = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(discount_amount),0) FROM sales WHERE status='ACTIVA'")
            total_discount = safe_float(cur.fetchone()[0])
            cur.execute("SELECT user_name, COUNT(*), COALESCE(SUM(total),0) FROM sales WHERE status='ACTIVA' GROUP BY user_name ORDER BY SUM(total) DESC")
            user_rows = cur.fetchall()
            cur.execute("SELECT si.item_name, COALESCE(SUM(si.qty),0), COALESCE(SUM(si.line_total),0) FROM sale_items si JOIN sales s ON s.id = si.sale_id WHERE s.status='ACTIVA' GROUP BY si.item_name ORDER BY SUM(si.qty) DESC, SUM(si.line_total) DESC LIMIT 15")
            product_rows = cur.fetchall()
            cur.execute("SELECT payment_method, COUNT(*), COALESCE(SUM(total),0) FROM sales WHERE status='ACTIVA' GROUP BY payment_method ORDER BY SUM(total) DESC")
            method_rows = cur.fetchall()
            cur.execute("SELECT created_at, client_name, movement_kind, payment_method, amount FROM client_balance_movements ORDER BY id DESC LIMIT 20")
            client_mov_rows = cur.fetchall()
            cur.execute("SELECT COALESCE(SUM(balance_due),0), COALESCE(SUM(balance_favor),0) FROM clients WHERE status='Activo'")
            total_due, total_favor = cur.fetchone()

            cur.execute("""
                SELECT s.user_name,
                       COUNT(*) AS ventas,
                       COALESCE(SUM(s.total),0) AS monto,
                       COALESCE(MAX(e.commission_rate),0) AS commission_rate
                FROM sales s
                LEFT JOIN employees e ON lower(e.full_name)=lower(s.user_name)
                WHERE s.status='ACTIVA'
                GROUP BY s.user_name
                ORDER BY monto DESC
            """)
            employee_rows = cur.fetchall()
        finally:
            conn.close()

        for item in self.products_tree.get_children(): self.products_tree.delete(item)
        for item in self.methods_tree.get_children(): self.methods_tree.delete(item)
        for item in self.client_mov_tree.get_children(): self.client_mov_tree.delete(item)
        for item in self.employee_tree.get_children(): self.employee_tree.delete(item)

        for name, qty, amount_row in product_rows:
            self.products_tree.insert("", "end", values=(name, f"{safe_float(qty):.2f}", f"Q {safe_float(amount_row):.2f}"))
        for method, ventas, amount_row in method_rows:
            self.methods_tree.insert("", "end", values=(method or 'sin método', int(ventas or 0), f"Q {safe_float(amount_row):.2f}"))
        for created_at, client_name, movement_kind, payment_method, amount_row in client_mov_rows:
            self.client_mov_tree.insert("", "end", values=((created_at or '')[:16].replace('T',' '), client_name or '', movement_kind or '', payment_method or '', f"Q {safe_float(amount_row):.2f}"))

        top_employee = "ADMIN"
        for employee_name, ventas_emp, monto_emp, rate_emp in employee_rows:
            commission_emp = safe_float(monto_emp) * (safe_float(rate_emp) / 100.0)
            self.employee_tree.insert("", "end", values=(employee_name or "ADMIN", int(ventas_emp or 0), f"Q {safe_float(monto_emp):.2f}", f"Q {commission_emp:.2f}"))
            if top_employee == "ADMIN" and employee_name:
                top_employee = employee_name

        self.lbl_clients_fin.configure(text=f"Saldo total a deber: Q {safe_float(total_due):.2f}\nSaldo total a favor: Q {safe_float(total_favor):.2f}")
        top_user = user_rows[0][0] if user_rows else 'ADMIN'
        self.lbl_report_head.configure(text=f"Ventas activas: {count or 0} | Total vendido: Q {safe_float(amount):.2f} | Descuento otorgado: Q {total_discount:.2f} | Usuario líder: {top_user} | Empleado líder: {top_employee}")




class SettingsView(ttk.Frame):
    DEFAULTS = {
        "business_name": "TECNOMEDIA GT",
        "business_address": "15 CALLE 8 AVENIDA PUERTO BARRIOS, IZABAL",
        "business_phone": "31380850 / 54780043",
        "business_nit": "4509238-9",
        "doc_series": "V",
        "print_format": "Ambos",
        "footer_text": "Gracias por su compra",
        "auto_print": "0",
        "currency_symbol": "Q",
        "currency_name": "Quetzal",
        "decimals": "2",
        "theme": "Oscuro",
        "pos_user_is_seller": "1",
        "pos_require_linked_employee": "1",
        "pos_client_required": "0",
        "pos_discount_max": "15",
        "pos_allow_no_stock": "0",
        "purchase_payment_default": "Efectivo",
        "purchase_auto_stock": "1",
        "purchase_edit_closed": "0",
        "purchase_annul_enabled": "1",
        "inventory_min_stock": "5",
        "inventory_low_alerts": "1",
        "inventory_allow_negative": "0",
        "inventory_default_unit": "Unidad",
        "cash_open_required": "1",
        "cash_close_required": "1",
        "cash_open_amount": "0",
        "cash_max_difference": "50",
        "pay_period": "Mensual",
        "default_commission": "5",
        "pay_allow_bonus": "1",
        "pay_allow_discounts": "1",
        "pay_allow_advances": "1",
        "tech_warranty_days": "30",
        "tech_review_fee": "0",
        "tech_default_priority": "Media",
        "cyber_hour_rate": "12",
        "cyber_min_fraction": "15",
        "cyber_pause_allowed": "1",
        "cyber_auto_close": "0",
        "report_include_seller": "1",
        "report_include_profit": "1",
        "report_export_excel": "1",
        "security_lock_attempts": "0",
        "security_backup_before_wipe": "1",
    }

    def __init__(self, parent, refresh_callback=None):
        super().__init__(parent, style="TFrame", padding=10)
        self.refresh_callback = refresh_callback
        self.vars = {}
        for key, default in self.DEFAULTS.items():
            if default in ("0", "1"):
                self.vars[key] = tk.BooleanVar(value=(default == "1"))
            else:
                self.vars[key] = tk.StringVar()
        self.status_labels = {}
        self.summary_box = None
        self._load_settings()
        self._build()
        self._refresh_status()

    def _load_settings(self):
        for key, default in self.DEFAULTS.items():
            value = get_app_setting(key, default)
            if isinstance(self.vars[key], tk.BooleanVar):
                self.vars[key].set(str(value).lower() in ("1", "true", "si", "sí", "yes"))
            else:
                self.vars[key].set(value)

    def _field(self, parent, row, col, label, widget, col_span=1):
        ttk.Label(parent, text=label, style="CardTitle.TLabel").grid(row=row, column=col, sticky="w", pady=(0,6), padx=(0,12))
        widget.grid(row=row+1, column=col, columnspan=col_span, sticky="ew", pady=(0,12), padx=(0,12))
        return widget

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        shell = ttk.Frame(self, style="Card.TFrame", padding=12)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Configuración", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Panel principal organizado por rubros para administrar el sistema completo.", style="CardNote.TLabel").grid(row=0, column=1, sticky="e")

        nb = ttk.Notebook(shell)
        nb.grid(row=1, column=0, sticky="nsew", pady=(10,0))

        self.tab_empresa = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_usuarios = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_pos = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_compras = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_inventario = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_caja = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_nomina = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_tecnico = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_cyber = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_reportes = ttk.Frame(nb, style="TFrame", padding=14)
        self.tab_sistema = ttk.Frame(nb, style="TFrame", padding=14)

        nb.add(self.tab_empresa, text="Empresa")
        nb.add(self.tab_usuarios, text="Usuarios y Roles")
        nb.add(self.tab_pos, text="Ventas / POS")
        nb.add(self.tab_compras, text="Compras")
        nb.add(self.tab_inventario, text="Inventario")
        nb.add(self.tab_caja, text="Caja")
        nb.add(self.tab_nomina, text="Empleados / Nómina")
        nb.add(self.tab_tecnico, text="Técnico")
        nb.add(self.tab_cyber, text="Cibercafé / Consolas")
        nb.add(self.tab_reportes, text="Reportes")
        nb.add(self.tab_sistema, text="Sistema / Seguridad / Respaldos")

        self._build_empresa_tab()
        self._build_users_tab()
        self._build_pos_tab()
        self._build_compras_tab()
        self._build_inventario_tab()
        self._build_caja_tab()
        self._build_nomina_tab()
        self._build_tecnico_tab()
        self._build_cyber_tab()
        self._build_reportes_tab()
        self._build_sistema_tab()

    def _two_col(self, frame):
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _build_empresa_tab(self):
        left = ttk.Frame(self.tab_empresa, style="Card.TFrame", padding=18)
        left.pack(fill="both", expand=True)
        self._two_col(left)
        ttk.Label(left, text="Datos de empresa y documentos", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(left, text="Información principal del negocio, moneda y documentos.", style="CardNote.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4,14))
        self._field(left, 2, 0, "Nombre del negocio", ttk.Entry(left, textvariable=self.vars["business_name"]))
        self._field(left, 2, 1, "NIT", ttk.Entry(left, textvariable=self.vars["business_nit"]))
        self._field(left, 4, 0, "Dirección", ttk.Entry(left, textvariable=self.vars["business_address"]))
        self._field(left, 4, 1, "Teléfono", ttk.Entry(left, textvariable=self.vars["business_phone"]))
        self._field(left, 6, 0, "Serie documentos", ttk.Entry(left, textvariable=self.vars["doc_series"]))
        self._field(left, 6, 1, "Formato de impresión", ttk.Combobox(left, textvariable=self.vars["print_format"], values=["Ambos","Ticket","Factura"], state="readonly"))
        self._field(left, 8, 0, "Símbolo de moneda", ttk.Entry(left, textvariable=self.vars["currency_symbol"]))
        self._field(left, 8, 1, "Nombre de moneda", ttk.Entry(left, textvariable=self.vars["currency_name"]))
        self._field(left, 10, 0, "Decimales", ttk.Entry(left, textvariable=self.vars["decimals"]))
        self._field(left, 10, 1, "Tema", ttk.Combobox(left, textvariable=self.vars["theme"], values=["Oscuro","Claro"], state="readonly"))
        ttk.Label(left, text="Pie de documento", style="CardTitle.TLabel").grid(row=12, column=0, columnspan=2, sticky="w")
        ttk.Entry(left, textvariable=self.vars["footer_text"]).grid(row=13, column=0, columnspan=2, sticky="ew", pady=(6,12), padx=(0,12))
        ttk.Checkbutton(left, text="Impresión automática", variable=self.vars["auto_print"]).grid(row=14, column=0, columnspan=2, sticky="w", pady=(0,12))
        actions = ttk.Frame(left, style="TFrame")
        actions.grid(row=15, column=0, columnspan=2, sticky="w")
        self.btn_save_company = ttk.Button(actions, text="Guardar configuración", style="Primary.TButton", command=self._save)
        self.btn_save_company.grid(row=0, column=0, padx=(0,8))
        self.btn_restore_company = ttk.Button(actions, text="Restaurar valores base", command=self._restore_defaults)
        self.btn_restore_company.grid(row=0, column=1, padx=(0,8))
        self.btn_reset_seq_company = ttk.Button(actions, text="Reiniciar correlativos", command=self._reset_sequences)
        self.btn_reset_seq_company.grid(row=0, column=2)
        disable_button_if_denied(self.btn_save_company, 'Configuración', 'editar', 'guardar configuración')
        disable_button_if_denied(self.btn_restore_company, 'Configuración', 'editar', 'restaurar configuración')
        disable_button_if_denied(self.btn_reset_seq_company, 'Configuración', 'editar', 'reiniciar correlativos')

    def _build_users_tab(self):
        shell = ttk.Frame(self.tab_usuarios, style="Card.TFrame", padding=14)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        ttk.Label(shell, text="Usuarios, roles y permisos", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(shell, text="Controla accesos por rol y aplica ajustes individuales por usuario.", style="CardNote.TLabel").grid(row=0, column=1, sticky="e")

        inner = ttk.Notebook(shell)
        inner.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12,0))
        self.users_form_tab = ttk.Frame(inner, style="TFrame", padding=10)
        self.roles_perm_tab = ttk.Frame(inner, style="TFrame", padding=10)
        inner.add(self.users_form_tab, text="Usuarios")
        inner.add(self.roles_perm_tab, text="Permisos")

        self._build_users_form_tab()
        self._build_permissions_tab()

    def _build_pos_tab(self):
        frame = ttk.Frame(self.tab_pos, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        self._two_col(frame)
        ttk.Label(frame, text="Reglas del POS y ventas", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(frame, text="Usuario logueado = vendedor", variable=self.vars["pos_user_is_seller"]).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Exigir empleado vinculado", variable=self.vars["pos_require_linked_employee"]).grid(row=1, column=1, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Cliente obligatorio", variable=self.vars["pos_client_required"]).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Permitir vender sin stock", variable=self.vars["pos_allow_no_stock"]).grid(row=2, column=1, sticky="w", pady=6)
        self._field(frame, 3, 0, "Descuento máximo (%)", ttk.Entry(frame, textvariable=self.vars["pos_discount_max"]))

    def _build_compras_tab(self):
        frame = ttk.Frame(self.tab_compras, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        self._two_col(frame)
        ttk.Label(frame, text="Reglas de compras", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._field(frame, 1, 0, "Método de pago por defecto", ttk.Combobox(frame, textvariable=self.vars["purchase_payment_default"], values=["Efectivo","Transferencia","Depósito","Tarjeta"], state="readonly"))
        ttk.Checkbutton(frame, text="Guardar compra y aumentar stock automáticamente", variable=self.vars["purchase_auto_stock"]).grid(row=1, column=1, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Permitir editar compras cerradas", variable=self.vars["purchase_edit_closed"]).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Permitir anular compras", variable=self.vars["purchase_annul_enabled"]).grid(row=2, column=1, sticky="w", pady=6)

    def _build_inventario_tab(self):
        frame = ttk.Frame(self.tab_inventario, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        self._two_col(frame)
        ttk.Label(frame, text="Reglas de inventario", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._field(frame, 1, 0, "Stock mínimo por defecto", ttk.Entry(frame, textvariable=self.vars["inventory_min_stock"]))
        self._field(frame, 1, 1, "Unidad por defecto", ttk.Entry(frame, textvariable=self.vars["inventory_default_unit"]))
        ttk.Checkbutton(frame, text="Alertas de stock bajo", variable=self.vars["inventory_low_alerts"]).grid(row=3, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Permitir stock negativo", variable=self.vars["inventory_allow_negative"]).grid(row=3, column=1, sticky="w", pady=6)

    def _build_caja_tab(self):
        frame = ttk.Frame(self.tab_caja, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        self._two_col(frame)
        ttk.Label(frame, text="Control de caja", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._field(frame, 1, 0, "Monto inicial sugerido", ttk.Entry(frame, textvariable=self.vars["cash_open_amount"]))
        self._field(frame, 1, 1, "Diferencia máxima permitida", ttk.Entry(frame, textvariable=self.vars["cash_max_difference"]))
        ttk.Checkbutton(frame, text="Exigir apertura de caja", variable=self.vars["cash_open_required"]).grid(row=3, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Exigir cierre de caja", variable=self.vars["cash_close_required"]).grid(row=3, column=1, sticky="w", pady=6)

    def _build_nomina_tab(self):
        frame = ttk.Frame(self.tab_nomina, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        self._two_col(frame)
        ttk.Label(frame, text="Reglas de nómina", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._field(frame, 1, 0, "Período de pago", ttk.Combobox(frame, textvariable=self.vars["pay_period"], values=["Semanal","Quincenal","Mensual"], state="readonly"))
        self._field(frame, 1, 1, "Comisión por defecto (%)", ttk.Entry(frame, textvariable=self.vars["default_commission"]))
        ttk.Checkbutton(frame, text="Permitir bonos", variable=self.vars["pay_allow_bonus"]).grid(row=3, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Permitir descuentos", variable=self.vars["pay_allow_discounts"]).grid(row=3, column=1, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Permitir adelantos", variable=self.vars["pay_allow_advances"]).grid(row=4, column=0, sticky="w", pady=6)

    def _build_tecnico_tab(self):
        frame = ttk.Frame(self.tab_tecnico, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        self._two_col(frame)
        ttk.Label(frame, text="Parámetros técnicos", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._field(frame, 1, 0, "Garantía por días", ttk.Entry(frame, textvariable=self.vars["tech_warranty_days"]))
        self._field(frame, 1, 1, "Costo revisión por defecto", ttk.Entry(frame, textvariable=self.vars["tech_review_fee"]))
        self._field(frame, 3, 0, "Prioridad por defecto", ttk.Combobox(frame, textvariable=self.vars["tech_default_priority"], values=["Baja","Media","Alta"], state="readonly"))

    def _build_cyber_tab(self):
        frame = ttk.Frame(self.tab_cyber, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        self._two_col(frame)
        ttk.Label(frame, text="Parámetros de cibercafé y consolas", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._field(frame, 1, 0, "Tarifa por hora", ttk.Entry(frame, textvariable=self.vars["cyber_hour_rate"]))
        self._field(frame, 1, 1, "Fracción mínima (min)", ttk.Entry(frame, textvariable=self.vars["cyber_min_fraction"]))
        ttk.Checkbutton(frame, text="Pausa permitida", variable=self.vars["cyber_pause_allowed"]).grid(row=3, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Cierre automático", variable=self.vars["cyber_auto_close"]).grid(row=3, column=1, sticky="w", pady=6)

    def _build_reportes_tab(self):
        frame = ttk.Frame(self.tab_reportes, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Opciones de reportes", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(frame, text="Incluir vendedor/usuario", variable=self.vars["report_include_seller"]).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Incluir utilidad/costos", variable=self.vars["report_include_profit"]).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Checkbutton(frame, text="Habilitar exportación Excel", variable=self.vars["report_export_excel"]).grid(row=3, column=0, sticky="w", pady=6)

    def _build_sistema_tab(self):
        wrap = ttk.Frame(self.tab_sistema, style="TFrame")
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=5)
        wrap.columnconfigure(1, weight=4)
        wrap.rowconfigure(0, weight=1)

        left = ttk.Frame(wrap, style="Card.TFrame", padding=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,12))
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(wrap, style="Card.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(5, weight=1)

        ttk.Label(left, text="Seguridad y respaldos", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(left, text="Bloquear por intentos fallidos", variable=self.vars["security_lock_attempts"]).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Checkbutton(left, text="Crear backup antes del borrado total", variable=self.vars["security_backup_before_wipe"]).grid(row=2, column=0, sticky="w", pady=6)
        self.btn_save_all_cfg = ttk.Button(left, text="Guardar toda la configuración", style="Primary.TButton", command=self._save)
        self.btn_save_all_cfg.grid(row=3, column=0, sticky="w", pady=(12,6))
        self.btn_restore_defaults_cfg = ttk.Button(left, text="Restaurar valores base", command=self._restore_defaults)
        self.btn_restore_defaults_cfg.grid(row=4, column=0, sticky="w", pady=6)
        self.btn_reset_seq_cfg = ttk.Button(left, text="Reiniciar correlativos", command=self._reset_sequences)
        self.btn_reset_seq_cfg.grid(row=5, column=0, sticky="w", pady=6)
        self.btn_backup_cfg = ttk.Button(left, text="Backup manual", command=self._manual_backup)
        self.btn_backup_cfg.grid(row=6, column=0, sticky="w", pady=6)
        disable_button_if_denied(self.btn_save_all_cfg, 'Configuración', 'editar', 'guardar configuración')
        disable_button_if_denied(self.btn_restore_defaults_cfg, 'Configuración', 'editar', 'restaurar configuración')
        disable_button_if_denied(self.btn_reset_seq_cfg, 'Configuración', 'editar', 'reiniciar correlativos')
        disable_button_if_denied(self.btn_backup_cfg, 'Configuración', 'crear', 'crear backup manual')

        ttk.Label(right, text="Estado actual del sistema", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(right, text="Contadores de la base central para confirmar operación y limpieza.", style="CardNote.TLabel").grid(row=1, column=0, sticky="w", pady=(4,12))
        status_box = ttk.Frame(right, style="Card.TFrame")
        status_box.grid(row=2, column=0, sticky="ew")
        status_box.columnconfigure(0, weight=1)
        for i, key in enumerate(["Clientes","Inventario","Ventas","Caja","Tickets técnicos","Compras","Proveedores"]):
            lbl = ttk.Label(status_box, text=f"{key}: 0 registros", style="CardNote.TLabel")
            lbl.grid(row=i, column=0, sticky="w", pady=2)
            self.status_labels[key] = lbl

        maint = ttk.Frame(right, style="Card.TFrame")
        maint.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        ttk.Label(maint, text="Mantenimiento", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(maint, text="Usa el borrado completo solo si quieres reiniciar el negocio desde cero.", style="CardNote.TLabel").grid(row=1, column=0, sticky="w", pady=(4,10))
        self.btn_delete_all_records = ttk.Button(maint, text="Borrado completo de registros", style="Danger.TButton", command=self._delete_all_records)
        self.btn_delete_all_records.grid(row=2, column=0, sticky="w")
        disable_button_if_denied(self.btn_delete_all_records, 'Configuración', 'eliminar', 'borrado completo de registros')

        ttk.Label(right, text="Resumen de configuración", style="CardTitle.TLabel").grid(row=4, column=0, sticky="w", pady=(18,6))
        self.summary_box = tk.Text(right, height=12, bg="#1f2937", fg="#e5e7eb", insertbackground="white", relief="flat")
        self.summary_box.grid(row=5, column=0, sticky="nsew")

    def _system_status_snapshot(self):
        snapshot = {"Clientes":0,"Inventario":0,"Ventas":0,"Caja":0,"Tickets técnicos":0,"Compras":0,"Proveedores":0}
        try:
            conn = db_connect()
            cur = conn.cursor()
            queries = {
                "Clientes":"SELECT COUNT(*) FROM clients",
                "Inventario":"SELECT COUNT(*) FROM inventory_items",
                "Ventas":"SELECT COUNT(*) FROM sales",
                "Caja":"SELECT COUNT(*) FROM cash_movements",
                "Tickets técnicos":"SELECT COUNT(*) FROM technical_tickets",
                "Compras":"SELECT COUNT(*) FROM purchases",
                "Proveedores":"SELECT COUNT(*) FROM providers",
            }
            for key, sql in queries.items():
                try:
                    cur.execute(sql)
                    row = cur.fetchone()
                    snapshot[key] = int((row[0] if row else 0) or 0)
                except Exception:
                    snapshot[key] = 0
            conn.close()
        except Exception:
            pass
        return snapshot

    def _refresh_status(self):
        snapshot = self._system_status_snapshot()
        for key, lbl in self.status_labels.items():
            lbl.configure(text=f"{key}: {snapshot.get(key, 0)} registros")
        if self.summary_box is not None:
            self.summary_box.delete("1.0", "end")
            lines = [
                f"Negocio: {self.vars['business_name'].get()}",
                f"NIT: {self.vars['business_nit'].get()}",
                f"Dirección: {self.vars['business_address'].get()}",
                f"Teléfono: {self.vars['business_phone'].get()}",
                f"Serie: {self.vars['doc_series'].get()}",
                f"Formato: {self.vars['print_format'].get()}",
                f"Moneda: {self.vars['currency_symbol'].get()} - {self.vars['currency_name'].get()}",
                f"Decimales: {self.vars['decimals'].get()}",
                f"Tema: {self.vars['theme'].get()}",
                f"POS usuario=vendedor: {'Sí' if self.vars['pos_user_is_seller'].get() else 'No'}",
                f"Empleado vinculado obligatorio: {'Sí' if self.vars['pos_require_linked_employee'].get() else 'No'}",
                f"Inventario mínimo: {self.vars['inventory_min_stock'].get()}",
                f"Período de pago: {self.vars['pay_period'].get()}",
            ]
            self.summary_box.insert("1.0", chr(10).join(lines))

    def _save(self):
        if not require_permission('Configuración', 'editar', self, 'guardar configuración'):
            return
        for key, var in self.vars.items():
            value = "1" if isinstance(var, tk.BooleanVar) and var.get() else ("0" if isinstance(var, tk.BooleanVar) else var.get())
            set_app_setting(key, value)
        self._refresh_status()
        messagebox.showinfo("Configuración", "Configuración guardada correctamente.")

    def _restore_defaults(self):
        if not require_permission('Configuración', 'editar', self, 'restaurar configuración'):
            return
        for key, default in self.DEFAULTS.items():
            if isinstance(self.vars[key], tk.BooleanVar):
                self.vars[key].set(str(default).lower() in ("1", "true", "si", "sí", "yes"))
            else:
                self.vars[key].set(default)
        self._save()

    def _reset_sequences(self):
        if not require_permission('Configuración', 'editar', self, 'reiniciar correlativos'):
            return
        set_app_setting("correlativo_ticket", "1")
        set_app_setting("correlativo_factura", "1")
        messagebox.showinfo("Correlativos", "Correlativos reiniciados a 1.")

    def _manual_backup(self):
        if not require_permission('Configuración', 'crear', self, 'crear backup manual'):
            return
        try:
            backup_dir = Path("backups")
            backup_dir.mkdir(exist_ok=True)
            backup_file = backup_dir / f"tecnomedia_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for rel in ["app", "config", "data"]:
                    path = Path(rel)
                    if path.exists():
                        if path.is_file():
                            zf.write(path, path.as_posix())
                        else:
                            for item in path.rglob("*"):
                                if item.is_file():
                                    zf.write(item, item.as_posix())
            messagebox.showinfo("Respaldos", f"Backup creado correctamente:\n{backup_file}")
        except Exception as exc:
            messagebox.showerror("Respaldos", f"No se pudo crear el backup:\n{exc}")

    def _delete_all_records(self):
        if not require_permission('Configuración', 'eliminar', self, 'borrado completo de registros'):
            return
        ok = messagebox.askyesno("Confirmar", "Esto borrará clientes, inventario, ventas, compras, tickets, caja y proveedores. ¿Deseas continuar?")
        if not ok:
            return
        ok2 = messagebox.askyesno("Confirmación final", "Esta acción no se puede deshacer. ¿Borrar todo?")
        if not ok2:
            return
        try:
            if self.vars["security_backup_before_wipe"].get():
                try:
                    self._manual_backup()
                except Exception:
                    pass
            reset_all_business_data()
            self._refresh_status()
            if self.refresh_callback:
                self.refresh_callback()
            messagebox.showinfo("Mantenimiento", "Borrado completo ejecutado correctamente.")
        except Exception as exc:
            messagebox.showerror("Mantenimiento", "No se pudo completar el borrado:\n{}".format(exc))

    def _ensure_system_users_table(self):
        ensure_database()

    def _employee_options_for_users(self):
        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute("SELECT full_name FROM employees WHERE status='Activo' ORDER BY full_name")
            rows = [r[0] for r in cur.fetchall() if (r[0] or "").strip()]
            conn.close()
            return rows
        except Exception:
            return []

    def _clear_system_user_form(self):
        self.user_cfg_selected_username = None
        for widget in [self.user_cfg_username, self.user_cfg_full_name, self.user_cfg_password, self.user_cfg_password_confirm]:
            widget.delete(0, "end")
        self.user_cfg_role["values"] = get_all_roles()
        self.user_cfg_role.set("Vendedor")
        self.user_cfg_status.set("Activo")
        self.user_cfg_employee.set("")
        self.user_cfg_force_change.set(True)

    def _load_system_users(self):
        self._ensure_system_users_table()
        if hasattr(self, "user_cfg_employee"):
            try:
                self.user_cfg_employee["values"] = self._employee_options_for_users()
            except Exception:
                pass
        if not hasattr(self, "user_cfg_tree"):
            return
        for item in self.user_cfg_tree.get_children():
            self.user_cfg_tree.delete(item)
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT username, role, status, COALESCE(employee_name,'') FROM system_users ORDER BY username")
        rows = cur.fetchall()
        conn.close()
        for username, role, status, employee_name in rows:
            self.user_cfg_tree.insert("", "end", values=(username, role, status, employee_name or ""))

    def _save_system_user(self):
        if not require_permission('Configuración', 'editar', self, 'guardar usuario del sistema'):
            return
        self._ensure_system_users_table()
        username = self.user_cfg_username.get().strip()
        full_name = self.user_cfg_full_name.get().strip() or username
        password = self.user_cfg_password.get().strip()
        password2 = self.user_cfg_password_confirm.get().strip()
        role = self.user_cfg_role.get().strip() or "Vendedor"
        status = self.user_cfg_status.get().strip() or "Activo"
        employee_name = self.user_cfg_employee.get().strip()
        force_change = 1 if self.user_cfg_force_change.get() else 0
        if not username:
            messagebox.showwarning("Usuarios", "Debes ingresar el usuario.")
            return
        if self.user_cfg_selected_username is None and not password:
            messagebox.showwarning("Usuarios", "Debes ingresar una contraseña para el nuevo usuario.")
            return
        if password or password2:
            if len(password) < 4:
                messagebox.showwarning("Usuarios", "La contraseña debe tener al menos 4 caracteres.")
                return
            if password != password2:
                messagebox.showwarning("Usuarios", "Las contraseñas no coinciden.")
                return
        conn = db_connect(); cur = conn.cursor()
        target_username = self.user_cfg_selected_username or username
        if self.user_cfg_selected_username is None:
            cur.execute("SELECT COUNT(*) FROM system_users WHERE username=?", (username,))
            if (cur.fetchone() or [0])[0] > 0:
                conn.close()
                messagebox.showwarning("Usuarios", "Ese nombre de usuario ya existe.")
                return
            cur.execute(
                """
                INSERT INTO system_users(username, password, role, full_name, status, employee_name, force_password_change)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (username, hash_password(password), role, full_name, status, employee_name, force_change)
            )
            target_username = username
        else:
            cur.execute(
                """
                UPDATE system_users
                SET username=?, role=?, full_name=?, status=?, employee_name=?, force_password_change=?
                WHERE username=?
                """,
                (username, role, full_name, status, employee_name, force_change, self.user_cfg_selected_username)
            )
            if password:
                cur.execute("UPDATE system_users SET password=? WHERE username=?", (hash_password(password), username))
            if username != self.user_cfg_selected_username:
                old_overrides = get_user_overrides(self.user_cfg_selected_username)
                cur.execute("SELECT id FROM system_users WHERE username=?", (username,))
                new_user_row = cur.fetchone()
                if new_user_row:
                    cur.execute("DELETE FROM user_permissions WHERE user_id=?", (new_user_row[0],))
                conn.commit(); conn.close()
                set_user_permission_overrides(username, old_overrides)
                self.user_cfg_selected_username = username
                self._clear_system_user_form()
                self._load_system_users()
                messagebox.showinfo("Usuarios", "Usuario actualizado correctamente.")
                return
        conn.commit(); conn.close()
        self._clear_system_user_form()
        self._load_system_users()
        if hasattr(self, "user_perm_selector"):
            self.user_perm_selector.set(target_username)
            self._load_user_permission_matrix()
        messagebox.showinfo("Usuarios", "Usuario guardado correctamente.")

    def _build_users_form_tab(self):
        frame = self.users_form_tab
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

        form = ttk.Frame(frame, style="Card.TFrame", padding=18)
        form.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        ttk.Label(form, text="Crear o editar usuario", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(form, text="Contraseñas protegidas con hash, cambio obligatorio inicial y estado de acceso.", style="CardNote.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(4,14))

        self.user_cfg_selected_username = None
        self.user_cfg_show_password = tk.BooleanVar(value=False)
        self.user_cfg_force_change = tk.BooleanVar(value=True)

        ttk.Label(form, text="Usuario", style="CardTitle.TLabel").grid(row=2, column=0, sticky="w")
        self.user_cfg_username = ttk.Entry(form)
        self.user_cfg_username.grid(row=2, column=1, sticky="ew", padx=(8,18), pady=(6,10), ipady=3)
        ttk.Label(form, text="Nombre completo", style="CardTitle.TLabel").grid(row=2, column=2, sticky="w")
        self.user_cfg_full_name = ttk.Entry(form)
        self.user_cfg_full_name.grid(row=2, column=3, sticky="ew", padx=(8,0), pady=(6,10), ipady=3)

        ttk.Label(form, text="Contraseña", style="CardTitle.TLabel").grid(row=3, column=0, sticky="w")
        pwd_wrap = ttk.Frame(form, style="Card.TFrame")
        pwd_wrap.grid(row=3, column=1, sticky="ew", padx=(8,18), pady=(6,10))
        pwd_wrap.columnconfigure(0, weight=1)
        self.user_cfg_password = ttk.Entry(pwd_wrap, show="*")
        self.user_cfg_password.grid(row=0, column=0, sticky="ew", ipady=3)
        ttk.Button(pwd_wrap, text="Ver", width=6, command=self._toggle_user_password_visibility).grid(row=0, column=1, padx=(6,0))

        ttk.Label(form, text="Confirmar contraseña", style="CardTitle.TLabel").grid(row=3, column=2, sticky="w")
        self.user_cfg_password_confirm = ttk.Entry(form, show="*")
        self.user_cfg_password_confirm.grid(row=3, column=3, sticky="ew", padx=(8,0), pady=(6,10), ipady=3)

        ttk.Label(form, text="Rol", style="CardTitle.TLabel").grid(row=4, column=0, sticky="w")
        self.user_cfg_role = ttk.Combobox(form, values=get_all_roles(), state="readonly")
        self.user_cfg_role.grid(row=4, column=1, sticky="ew", padx=(8,18), pady=(6,10))
        self.user_cfg_role.set("Vendedor")
        ttk.Label(form, text="Estado", style="CardTitle.TLabel").grid(row=4, column=2, sticky="w")
        self.user_cfg_status = ttk.Combobox(form, values=["Activo","Inactivo"], state="readonly")
        self.user_cfg_status.grid(row=4, column=3, sticky="ew", padx=(8,0), pady=(6,10))
        self.user_cfg_status.set("Activo")

        ttk.Label(form, text="Empleado vinculado", style="CardTitle.TLabel").grid(row=5, column=0, sticky="w")
        self.user_cfg_employee = ttk.Combobox(form, values=self._employee_options_for_users(), state="readonly")
        self.user_cfg_employee.grid(row=5, column=1, sticky="ew", padx=(8,18), pady=(6,10))
        ttk.Checkbutton(form, text="Forzar cambio de contraseña al primer ingreso", variable=self.user_cfg_force_change).grid(row=5, column=2, columnspan=2, sticky="w", padx=(8,0), pady=(8,10))

        btns = ttk.Frame(form, style="TFrame")
        btns.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(4,0))
        for idx in range(5):
            btns.columnconfigure(idx, weight=1)
        self.btn_save_system_user = ttk.Button(btns, text="Guardar usuario", style="Primary.TButton", command=self._save_system_user)
        self.btn_save_system_user.grid(row=0, column=0, sticky="ew", padx=(0,8))
        self.btn_edit_system_user = ttk.Button(btns, text="Editar seleccionado", command=self._edit_selected_user)
        self.btn_edit_system_user.grid(row=0, column=1, sticky="ew", padx=4)
        self.btn_toggle_system_user = ttk.Button(btns, text="Activar / Desactivar", command=self._toggle_selected_user_status)
        self.btn_toggle_system_user.grid(row=0, column=2, sticky="ew", padx=4)
        self.btn_reload_system_user = ttk.Button(btns, text="Actualizar listado", command=self._load_system_users)
        self.btn_reload_system_user.grid(row=0, column=3, sticky="ew", padx=4)
        self.btn_clear_system_user = ttk.Button(btns, text="Limpiar campos", command=self._clear_system_user_form)
        self.btn_clear_system_user.grid(row=0, column=4, sticky="ew", padx=(8,0))
        disable_button_if_denied(self.btn_save_system_user, 'Configuración', 'editar', 'guardar usuario del sistema')
        disable_button_if_denied(self.btn_edit_system_user, 'Configuración', 'editar', 'editar usuario del sistema')
        disable_button_if_denied(self.btn_toggle_system_user, 'Configuración', 'editar', 'activar o desactivar usuario')

        list_card = ttk.Frame(frame, style="Card.TFrame", padding=18)
        list_card.grid(row=0, column=1, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(2, weight=1)
        ttk.Label(list_card, text="Usuarios registrados", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        cols = ("usuario","nombre","rol","estado","empleado","forzar")
        self.user_cfg_tree = ttk.Treeview(list_card, columns=cols, show="headings", height=16)
        for key, title, width in [
            ("usuario","Usuario",120),("nombre","Nombre",180),("rol","Rol",120),
            ("estado","Estado",90),("empleado","Empleado",180),("forzar","Cambio al ingresar",120)
        ]:
            self.user_cfg_tree.heading(key, text=title)
            self.user_cfg_tree.column(key, width=width, anchor="w")
        install_column_manager(list_card, self.user_cfg_tree, 'config_usuarios', row=1, column=0, padx=(0, 0), pady=(10, 8))
        self.user_cfg_tree.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_card, orient="vertical", command=self.user_cfg_tree.yview)
        self.user_cfg_tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=2, column=1, sticky="ns")
        self.user_cfg_tree.bind("<<TreeviewSelect>>", lambda e: self._edit_selected_user())
        self._load_system_users()

    def _build_permissions_tab(self):
        frame = self.roles_perm_tab
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        top = ttk.Frame(frame, style="Card.TFrame", padding=18)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,10))
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)
        ttk.Label(top, text="Permisos por rol y por usuario", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(top, text="Primero define el rol base y luego ajusta permisos puntuales por usuario.", style="CardNote.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(4,14))

        self.role_perm_selector = ttk.Combobox(top, values=get_all_roles(), state="readonly")
        self.role_perm_selector.grid(row=2, column=1, sticky="ew", padx=(8,18), pady=(0,8))
        self.role_perm_selector.set("Administrador")
        self.role_perm_selector.bind("<<ComboboxSelected>>", lambda e: self._load_role_permission_matrix())
        ttk.Label(top, text="Rol", style="CardTitle.TLabel").grid(row=2, column=0, sticky="w")

        self.user_perm_selector = ttk.Combobox(top, values=[], state="readonly")
        self.user_perm_selector.grid(row=2, column=3, sticky="ew", padx=(8,0), pady=(0,8))
        self.user_perm_selector.bind("<<ComboboxSelected>>", lambda e: self._load_user_permission_matrix())
        ttk.Label(top, text="Usuario", style="CardTitle.TLabel").grid(row=2, column=2, sticky="w")

        self.role_permission_vars = {}
        self.user_permission_vars = {}

        role_card = ttk.Frame(frame, style="Card.TFrame", padding=18)
        role_card.grid(row=1, column=0, sticky="nsew", padx=(0,10))
        role_card.columnconfigure(0, weight=1)
        role_card.rowconfigure(1, weight=1)
        ttk.Label(role_card, text="Permisos base del rol", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        role_body = ttk.Frame(role_card, style="Card.TFrame")
        role_body.grid(row=1, column=0, sticky="nsew", pady=(10,0))
        self._build_permission_matrix(role_body, self.role_permission_vars, prefix="rol")
        role_btns = ttk.Frame(role_card, style="Card.TFrame")
        role_btns.grid(row=2, column=0, sticky="ew", pady=(12,0))
        for idx in range(4):
            role_btns.columnconfigure(idx, weight=1)
        self.btn_role_all = ttk.Button(role_btns, text="Marcar todo", command=lambda: self._set_matrix_values(self.role_permission_vars, True))
        self.btn_role_all.grid(row=0, column=0, sticky="ew", padx=(0,6))
        self.btn_role_none = ttk.Button(role_btns, text="Limpiar todo", command=lambda: self._set_matrix_values(self.role_permission_vars, False))
        self.btn_role_none.grid(row=0, column=1, sticky="ew", padx=6)
        self.btn_role_load = ttk.Button(role_btns, text="Cargar rol", command=self._load_role_permission_matrix)
        self.btn_role_load.grid(row=0, column=2, sticky="ew", padx=6)
        self.btn_role_save = ttk.Button(role_btns, text="Guardar rol", style="Primary.TButton", command=self._save_role_permissions)
        self.btn_role_save.grid(row=0, column=3, sticky="ew", padx=(6,0))
        disable_button_if_denied(self.btn_role_all, 'Configuración', 'editar', 'editar permisos por rol')
        disable_button_if_denied(self.btn_role_none, 'Configuración', 'editar', 'editar permisos por rol')
        disable_button_if_denied(self.btn_role_save, 'Configuración', 'editar', 'guardar permisos por rol')

        user_card = ttk.Frame(frame, style="Card.TFrame", padding=18)
        user_card.grid(row=1, column=1, sticky="nsew")
        user_card.columnconfigure(0, weight=1)
        user_card.rowconfigure(1, weight=1)
        ttk.Label(user_card, text="Ajustes individuales por usuario", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(user_card, text="Se guardan como override: 1 permite, 0 niega. Lo no tocado hereda del rol.", style="CardNote.TLabel").grid(row=0, column=1, sticky="e")
        user_body = ttk.Frame(user_card, style="Card.TFrame")
        user_body.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10,0))
        self._build_permission_matrix(user_body, self.user_permission_vars, prefix="usr")
        user_btns = ttk.Frame(user_card, style="Card.TFrame")
        user_btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12,0))
        for idx in range(5):
            user_btns.columnconfigure(idx, weight=1)
        self.btn_user_all = ttk.Button(user_btns, text="Permitir todo", command=lambda: self._set_matrix_values(self.user_permission_vars, True))
        self.btn_user_all.grid(row=0, column=0, sticky="ew", padx=(0,6))
        self.btn_user_none = ttk.Button(user_btns, text="Negar todo", command=lambda: self._set_matrix_values(self.user_permission_vars, False))
        self.btn_user_none.grid(row=0, column=1, sticky="ew", padx=6)
        self.btn_user_clear = ttk.Button(user_btns, text="Limpiar overrides", command=self._clear_user_overrides_matrix)
        self.btn_user_clear.grid(row=0, column=2, sticky="ew", padx=6)
        self.btn_user_load = ttk.Button(user_btns, text="Cargar usuario", command=self._load_user_permission_matrix)
        self.btn_user_load.grid(row=0, column=3, sticky="ew", padx=6)
        self.btn_user_save = ttk.Button(user_btns, text="Guardar usuario", style="Primary.TButton", command=self._save_user_permissions)
        self.btn_user_save.grid(row=0, column=4, sticky="ew", padx=(6,0))
        disable_button_if_denied(self.btn_user_all, 'Configuración', 'editar', 'editar permisos por usuario')
        disable_button_if_denied(self.btn_user_none, 'Configuración', 'editar', 'editar permisos por usuario')
        disable_button_if_denied(self.btn_user_clear, 'Configuración', 'editar', 'limpiar permisos por usuario')
        disable_button_if_denied(self.btn_user_save, 'Configuración', 'editar', 'guardar permisos por usuario')

        self._load_system_users(refresh_only_selectors=True)
        self._load_role_permission_matrix()
        self._load_user_permission_matrix()

    def _build_permission_matrix(self, parent, var_store, prefix="perm"):
        parent.columnconfigure(0, weight=1)
        actions = [a.title() for a in PERMISSION_ACTIONS]
        ttk.Label(parent, text="Módulo", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0,12), pady=(0,10))
        for idx, action in enumerate(actions, start=1):
            parent.columnconfigure(idx, minsize=46)
            ttk.Label(parent, text=action, style="CardTitle.TLabel").grid(row=0, column=idx, sticky="", padx=4, pady=(0,8))
        for row_idx, module in enumerate(MODULES, start=1):
            module_wrap = tk.Frame(parent, bg="#0b1324", highlightthickness=0, bd=0)
            module_wrap.grid(row=row_idx, column=0, sticky="ew", padx=(0,10), pady=3)
            tk.Label(module_wrap, text=module, fg="#dbeafe", bg="#0b1324", font=("Arial", 10, "bold"), anchor="w").pack(fill="x", padx=10, pady=4)
            for col_idx, action in enumerate(PERMISSION_ACTIONS, start=1):
                var = tk.BooleanVar(value=False)
                var_store[(module, action)] = var
                cell = tk.Frame(parent, bg="#0b1324", highlightthickness=0, bd=0)
                cell.grid(row=row_idx, column=col_idx, padx=4, pady=3)
                PermissionToggle(cell, variable=var, size=18).pack()

    def _toggle_user_password_visibility(self):
        current = bool(self.user_cfg_show_password.get())
        self.user_cfg_show_password.set(not current)
        mode = "" if not current else "*"
        self.user_cfg_password.configure(show=mode)
        self.user_cfg_password_confirm.configure(show=mode)

    def _employee_options_for_users(self):
        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute("SELECT full_name FROM employees WHERE status='Activo' ORDER BY full_name")
            rows = [r[0] for r in cur.fetchall() if (r[0] or "").strip()]
            conn.close()
            return rows
        except Exception:
            return []

    def _load_system_users(self, refresh_only_selectors=False):
        self._ensure_system_users_table()
        users = []
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT username, COALESCE(full_name, ''), role, status, COALESCE(employee_name,''), COALESCE(force_password_change,0) FROM system_users ORDER BY username")
        rows = cur.fetchall()
        conn.close()
        for row in rows:
            users.append(row)
        if hasattr(self, "user_cfg_employee"):
            self.user_cfg_employee["values"] = self._employee_options_for_users()
        if hasattr(self, "user_perm_selector"):
            self.user_perm_selector["values"] = [u[0] for u in users]
            if not self.user_perm_selector.get() and users:
                self.user_perm_selector.set(users[0][0])
        if hasattr(self, "user_cfg_tree") and not refresh_only_selectors:
            for item in self.user_cfg_tree.get_children():
                self.user_cfg_tree.delete(item)
            for username, full_name, role, status, employee_name, force_password_change in users:
                self.user_cfg_tree.insert("", "end", values=(username, full_name, role, status, employee_name, "Sí" if force_password_change else "No"))

    def _edit_selected_user(self):
        if not hasattr(self, "user_cfg_tree"):
            return
        sel = self.user_cfg_tree.selection()
        if not sel:
            return
        username = self.user_cfg_tree.item(sel[0], "values")[0]
        conn = db_connect(); conn.row_factory = sqlite3.Row; cur = conn.cursor()
        cur.execute("SELECT * FROM system_users WHERE username=?", (username,))
        row = cur.fetchone(); conn.close()
        if not row:
            return
        self.user_cfg_selected_username = username
        self.user_cfg_username.delete(0, "end")
        self.user_cfg_username.insert(0, row["username"] or "")
        self.user_cfg_full_name.delete(0, "end")
        self.user_cfg_full_name.insert(0, row["full_name"] or row["employee_name"] or row["username"] or "")
        self.user_cfg_password.delete(0, "end")
        self.user_cfg_password_confirm.delete(0, "end")
        self.user_cfg_role.set(row["role"] or "Vendedor")
        self.user_cfg_status.set(row["status"] or "Activo")
        self.user_cfg_employee.set(row["employee_name"] or "")
        self.user_cfg_force_change.set(bool(row["force_password_change"] or 0))
        if hasattr(self, "user_perm_selector"):
            self.user_perm_selector.set(username)
            self._load_user_permission_matrix()

    def _toggle_selected_user_status(self):
        if not require_permission('Configuración', 'editar', self, 'activar o desactivar usuario'):
            return
        sel = self.user_cfg_tree.selection()
        if not sel:
            messagebox.showwarning("Usuarios", "Selecciona un usuario para cambiar su estado.")
            return
        username = self.user_cfg_tree.item(sel[0], "values")[0]
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT COALESCE(status,'Activo') FROM system_users WHERE username=?", (username,))
        current = (cur.fetchone() or ["Activo"])[0]
        new_status = "Inactivo" if str(current).lower() == "activo" else "Activo"
        cur.execute("UPDATE system_users SET status=? WHERE username=?", (new_status, username))
        conn.commit(); conn.close()
        self._load_system_users()

    def _set_matrix_values(self, store, value):
        for var in store.values():
            var.set(bool(value))

    def _clear_user_overrides_matrix(self):
        username = self.user_perm_selector.get().strip()
        if not username:
            for var in self.user_permission_vars.values():
                var.set(False)
            return
        conn = db_connect(); conn.row_factory = sqlite3.Row; cur = conn.cursor()
        cur.execute("SELECT COALESCE(role,'Vendedor') AS role FROM system_users WHERE username=?", (username,))
        row = cur.fetchone(); conn.close()
        base_perms = get_role_permissions((row['role'] if row else 'Vendedor'))
        for key, var in self.user_permission_vars.items():
            var.set(key in base_perms)

    def _load_role_permission_matrix(self):
        role_name = self.role_perm_selector.get().strip() or "Administrador"
        perms = get_role_permissions(role_name)
        for key, var in self.role_permission_vars.items():
            var.set(key in perms)

    def _save_role_permissions(self):
        if not require_permission('Configuración', 'editar', self, 'guardar permisos por rol'):
            return
        role_name = self.role_perm_selector.get().strip()
        if not role_name:
            messagebox.showwarning("Permisos", "Selecciona un rol.")
            return
        perms = {key for key, var in self.role_permission_vars.items() if var.get()}
        set_role_permissions(role_name, perms)
        self.user_cfg_role["values"] = get_all_roles()
        self.role_perm_selector["values"] = get_all_roles()
        messagebox.showinfo("Permisos", f"Permisos del rol {role_name} guardados correctamente.")

    def _load_user_permission_matrix(self, clear_only=False):
        username = self.user_perm_selector.get().strip()
        if not username:
            for var in self.user_permission_vars.values():
                var.set(False)
            return
        effective = get_effective_permissions(username)
        for key, var in self.user_permission_vars.items():
            var.set(key in effective)

    def _save_user_permissions(self):
        if not require_permission('Configuración', 'editar', self, 'guardar permisos por usuario'):
            return
        username = self.user_perm_selector.get().strip()
        if not username:
            messagebox.showwarning("Permisos", "Selecciona un usuario.")
            return
        conn = db_connect(); conn.row_factory = sqlite3.Row; cur = conn.cursor()
        cur.execute("SELECT COALESCE(role,'Vendedor') AS role FROM system_users WHERE username=?", (username,))
        row = cur.fetchone(); conn.close()
        role_name = row['role'] if row else 'Vendedor'
        base_perms = get_role_permissions(role_name)
        overrides = {}
        for key, var in self.user_permission_vars.items():
            checked = bool(var.get())
            inherited = key in base_perms
            if checked != inherited:
                overrides[key] = 1 if checked else 0
        set_user_permission_overrides(username, overrides)
        messagebox.showinfo("Permisos", f"Overrides de permisos guardados para {username}.")

class PurchasesView(ttk.Frame):
    PAYMENT_METHODS = ["EFECTIVO", "TRANSFERENCIA", "DEPÓSITO", "TARJETA", "CRÉDITO"]

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.provider_var = tk.StringVar()
        self.invoice_var = tk.StringVar()
        self.payment_var = tk.StringVar(value="EFECTIVO")
        self.item_var = tk.StringVar()
        self.qty_var = tk.StringVar(value="1")
        self.cost_var = tk.StringVar(value="0.00")
        self.provider_code_var = tk.StringVar(value="")
        self.line_total_var = tk.StringVar(value="Q 0.00")
        self.notes = None
        self.lines_tree = None
        self.recent_tree = None
        self.items_map = {}
        self.providers_map = {}
        self.lines = []
        self.summary_total = None
        self.quick_total = None
        self.quick_today = None
        self.next_no_label = None
        self.item_var.trace_add("write", lambda *_: self._on_item_change())
        self.qty_var.trace_add("write", lambda *_: self._update_line_total())
        self.cost_var.trace_add("write", lambda *_: self._update_line_total())
        self._build()
        self.refresh_all()

    def _build(self):
        self.columnconfigure(0, weight=7)
        self.columnconfigure(1, weight=5)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Card.TFrame", padding=20)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,12))
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="Compras / Entradas", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(left, text="Cada compra se liga al proveedor, aumenta stock automáticamente y deja historial en movimientos.", style="CardTitle.TLabel", wraplength=760).grid(row=1, column=0, sticky="w", pady=(8,16))

        form = ttk.Frame(left, style="Card.TFrame")
        form.grid(row=2, column=0, sticky="ew")
        for col in range(4):
            form.columnconfigure(col, weight=1)

        ttk.Label(form, text="Próxima compra", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0,10), pady=(0,6))
        self.next_no_label = ttk.Label(form, text=next_purchase_no(), style="CardValue.TLabel")
        self.next_no_label.grid(row=1, column=0, sticky="w", padx=(0,10), pady=(0,12))

        ttk.Label(form, text="Proveedor", style="CardTitle.TLabel").grid(row=0, column=1, sticky="w", padx=(0,10), pady=(0,6))
        self.provider_combo = ttk.Combobox(form, textvariable=self.provider_var, state="readonly")
        self.provider_combo.grid(row=1, column=1, sticky="ew", padx=(0,10), pady=(0,12))
        self.provider_combo.bind('<<ComboboxSelected>>', lambda e: self._on_provider_change())

        ttk.Label(form, text="Método de pago", style="CardTitle.TLabel").grid(row=0, column=2, sticky="w", padx=(0,10), pady=(0,6))
        ttk.Combobox(form, textvariable=self.payment_var, values=self.PAYMENT_METHODS, state="readonly").grid(row=1, column=2, sticky="ew", padx=(0,10), pady=(0,12))

        ttk.Label(form, text="Factura / referencia", style="CardTitle.TLabel").grid(row=0, column=3, sticky="w", pady=(0,6))
        ttk.Entry(form, textvariable=self.invoice_var).grid(row=1, column=3, sticky="ew", pady=(0,12))

        ttk.Label(form, text="Código proveedor", style="CardTitle.TLabel").grid(row=2, column=0, sticky="w", padx=(0,10), pady=(0,6))
        ttk.Entry(form, textvariable=self.provider_code_var, state="readonly").grid(row=3, column=0, sticky="ew", padx=(0,10), pady=(0,12))

        ttk.Label(form, text="Producto de inventario", style="CardTitle.TLabel").grid(row=2, column=1, columnspan=2, sticky="w", padx=(0,10), pady=(0,6))
        self.item_combo = ttk.Combobox(form, textvariable=self.item_var, state="readonly")
        self.item_combo.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0,10), pady=(0,12))

        ttk.Label(form, text="Costo unitario", style="CardTitle.TLabel").grid(row=2, column=3, sticky="w", pady=(0,6))
        ttk.Entry(form, textvariable=self.cost_var).grid(row=3, column=3, sticky="ew", pady=(0,12))

        ttk.Label(form, text="Cantidad", style="CardTitle.TLabel").grid(row=4, column=0, sticky="w", padx=(0,10), pady=(0,6))
        ttk.Entry(form, textvariable=self.qty_var).grid(row=5, column=0, sticky="ew", padx=(0,10), pady=(0,12))

        ttk.Label(form, text="Total de línea", style="CardTitle.TLabel").grid(row=4, column=1, sticky="w", padx=(0,10), pady=(0,6))
        ttk.Label(form, textvariable=self.line_total_var, style="CardValue.TLabel").grid(row=5, column=1, sticky="w", padx=(0,10), pady=(0,12))

        actions = ttk.Frame(form, style="Card.TFrame")
        actions.grid(row=5, column=2, columnspan=2, sticky="e", pady=(0,12))
        ttk.Button(actions, text="Agregar línea", style="Primary.TButton", command=self.add_line).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Quitar seleccionada", command=self.remove_selected_line).pack(side="left")

        ttk.Label(left, text="Notas / observaciones", style="CardTitle.TLabel").grid(row=3, column=0, sticky="w", pady=(12,6))
        self.notes = tk.Text(left, height=4, bg="#1f2937", fg="#e5e7eb", insertbackground="white", relief="flat")
        self.notes.grid(row=4, column=0, sticky="ew", pady=(0,12))

        lines_card = ttk.Frame(left, style="Card.TFrame", padding=16)
        lines_card.grid(row=5, column=0, sticky="nsew")
        lines_card.columnconfigure(0, weight=1)
        lines_card.rowconfigure(1, weight=1)
        left.rowconfigure(5, weight=1)
        lines_top = ttk.Frame(lines_card, style="Card.TFrame")
        lines_top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        lines_top.columnconfigure(0, weight=1)
        ttk.Label(lines_top, text="Líneas de compra", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        cols = ("code", "item", "qty", "cost", "total")
        self.lines_tree = ttk.Treeview(lines_card, columns=cols, show="headings", height=10)
        headers = {"code": "Código", "item": "Producto", "qty": "Cantidad", "cost": "Costo", "total": "Total"}
        widths = {"code": 110, "item": 260, "qty": 90, "cost": 100, "total": 100}
        for col in cols:
            self.lines_tree.heading(col, text=headers[col])
            self.lines_tree.column(col, width=widths[col], anchor="w")
        install_column_manager(lines_top, self.lines_tree, 'compras_lineas', row=0, column=1, padx=(0, 0), pady=(0, 0))
        self.lines_tree.grid(row=1, column=0, sticky="nsew")

        bottom = ttk.Frame(left, style="Card.TFrame")
        bottom.grid(row=6, column=0, sticky="ew", pady=(12,0))
        self.summary_total = ttk.Label(bottom, text="Q 0.00", style="CardValue.TLabel")
        self.summary_total.pack(side="left")
        self.btn_save_purchase = ttk.Button(bottom, text="Guardar compra y subir stock", style="Primary.TButton", command=self.save_purchase)
        self.btn_save_purchase.pack(side="right")
        self.btn_new_purchase = ttk.Button(bottom, text="Nuevo documento", command=self.reset_form)
        self.btn_new_purchase.pack(side="right", padx=(0,8))
        disable_button_if_denied(self.btn_save_purchase, 'Compras', 'crear', 'guardar compra')

        right = ttk.Frame(self, style="TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        stats = ttk.Frame(right, style="Card.TFrame", padding=18)
        stats.grid(row=0, column=0, sticky="ew", pady=(0,10))
        ttk.Label(stats, text="Resumen compras", style="CardTitle.TLabel").pack(anchor="w")
        self.quick_total = ttk.Label(stats, text="0 compras", style="CardValue.TLabel")
        self.quick_total.pack(anchor="w", pady=(10,2))
        self.quick_today = ttk.Label(stats, text="Hoy: Q 0.00", style="CardNote.TLabel")
        self.quick_today.pack(anchor="w")

        help_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        help_card.grid(row=1, column=0, sticky="ew", pady=(0,12))
        ttk.Label(help_card, text="Qué hace este módulo", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            help_card,
            text="1) selecciona proveedor\n2) agrega productos existentes del inventario\n3) guarda la compra\n4) el stock sube automáticamente y queda movimiento de entrada",
            style="CardNote.TLabel",
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(8,0))


        recent_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        recent_card.grid(row=2, column=0, sticky="nsew")
        recent_card.columnconfigure(0, weight=1)
        recent_card.rowconfigure(1, weight=1)
        recent_top = ttk.Frame(recent_card, style="Card.TFrame")
        recent_top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        recent_top.columnconfigure(0, weight=1)
        ttk.Label(recent_top, text="Compras recientes", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        cols2 = ("doc", "fecha", "proveedor", "total")
        self.recent_tree = ttk.Treeview(recent_card, columns=cols2, show="headings")
        headers2 = {"doc": "Compra", "fecha": "Fecha", "proveedor": "Proveedor", "total": "Total"}
        widths2 = {"doc": 110, "fecha": 130, "proveedor": 180, "total": 90}
        for col in cols2:
            self.recent_tree.heading(col, text=headers2[col])
            self.recent_tree.column(col, width=widths2[col], anchor="w")
        install_column_manager(recent_top, self.recent_tree, 'compras_recientes', row=0, column=1, padx=(0, 0), pady=(0, 0))
        self.recent_tree.grid(row=1, column=0, sticky="nsew")

    def refresh_all(self):
        self.providers_map = {name: code for code, name in provider_catalog()}
        providers = list(self.providers_map.keys())
        self.provider_combo.configure(values=providers)
        if providers and not self.provider_var.get():
            self.provider_var.set(providers[0])
            self._on_provider_change()

        catalog = inventory_catalog()
        self.items_map = {f"{code} | {name}": {'code': code, 'name': name, 'provider': provider, 'cost': cost, 'stock': stock} for code, name, provider, cost, stock in catalog}
        self.item_combo.configure(values=list(self.items_map.keys()))
        if self.items_map and not self.item_var.get():
            self.item_var.set(next(iter(self.items_map)))
            self._on_item_change()

        summary = purchase_summary()
        self.quick_total.configure(text=f"{summary['count']} compras | {money_gt(summary['amount'])}")
        self.quick_today.configure(text=f"Hoy: {summary['today_count']} docs | {money_gt(summary['today_amount'])}")
        self.next_no_label.configure(text=next_purchase_no())
        for item in self.recent_tree.get_children():
            self.recent_tree.delete(item)
        for doc, fecha, proveedor, total in summary['recent']:
            self.recent_tree.insert('', 'end', values=(doc, (fecha or '')[:16].replace('T', ' '), proveedor, money_gt(total)))
        self._refresh_lines()

    def _on_provider_change(self):
        self.provider_code_var.set(self.providers_map.get(self.provider_var.get(), ''))

    def _on_item_change(self):
        data = self.items_map.get(self.item_var.get())
        if not data:
            return
        self.cost_var.set(f"{safe_float(data['cost']):.2f}")
        provider_name = str(data.get('provider') or '').strip()
        if provider_name and provider_name in self.providers_map and not self.provider_var.get():
            self.provider_var.set(provider_name)
            self._on_provider_change()
        self._update_line_total()

    def _update_line_total(self):
        total = round(safe_float(self.qty_var.get()) * safe_float(self.cost_var.get()), 2)
        self.line_total_var.set(money_gt(total))

    def add_line(self):
        if not require_permission('Compras', 'crear', self, 'agregar línea a compra'):
            return
        data = self.items_map.get(self.item_var.get())
        if not data:
            messagebox.showwarning('Compra', 'Selecciona un producto válido del inventario.')
            return
        qty = round(safe_float(self.qty_var.get()), 2)
        unit_cost = round(safe_float(self.cost_var.get()), 2)
        if qty <= 0:
            messagebox.showwarning('Compra', 'La cantidad debe ser mayor que cero.')
            return
        line = {
            'item_code': data['code'],
            'item_name': data['name'],
            'qty': qty,
            'unit_cost': unit_cost,
            'line_total': round(qty * unit_cost, 2),
        }
        self.lines.append(line)
        self._refresh_lines()
        self.qty_var.set('1')
        self._update_line_total()

    def remove_selected_line(self):
        if not require_permission('Compras', 'editar', self, 'quitar línea de compra'):
            return
        selected = self.lines_tree.selection()
        if not selected:
            return
        idx = self.lines_tree.index(selected[0])
        if 0 <= idx < len(self.lines):
            self.lines.pop(idx)
        self._refresh_lines()

    def _refresh_lines(self):
        for item in self.lines_tree.get_children():
            self.lines_tree.delete(item)
        total = 0.0
        for line in self.lines:
            total += safe_float(line['line_total'])
            self.lines_tree.insert('', 'end', values=(line['item_code'], line['item_name'], f"{safe_float(line['qty']):.2f}", money_gt(line['unit_cost']), money_gt(line['line_total'])))
        self.summary_total.configure(text=money_gt(total))

    def reset_form(self):
        self.lines = []
        self.invoice_var.set('')
        self.payment_var.set('EFECTIVO')
        self.qty_var.set('1')
        if self.notes is not None:
            self.notes.delete('1.0', 'end')
        self.refresh_all()

    def save_purchase(self):
        if not require_permission('Compras', 'crear', self, 'guardar compra'):
            return
        if not self.provider_var.get().strip():
            messagebox.showwarning('Compra', 'Selecciona un proveedor.')
            return
        try:
            result = register_purchase(
                provider_name=self.provider_var.get().strip(),
                provider_code=self.provider_code_var.get().strip(),
                invoice_no=self.invoice_var.get().strip(),
                payment_method=self.payment_var.get().strip() or 'EFECTIVO',
                items=self.lines,
                notes=self.notes.get('1.0', 'end').strip() if self.notes is not None else '',
            )
        except Exception as e:
            messagebox.showerror('Compra', str(e))
            return
        messagebox.showinfo(
            'Compra guardada',
            f"Compra {result['purchase_no']} registrada correctamente.\nTotal: {money_gt(result['total'])}\nEl stock fue actualizado automáticamente.",
        )
        self.reset_form()



def month_bounds(dt=None):
    dt = dt or datetime.now()
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


class EmployeesView(ttk.Frame):
    PAY_FREQUENCIES = ["Mensual", "Quincenal", "Semanal", "Diario"]
    STATUSES = ["Activo", "Inactivo"]

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.editing_id = None
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._load_rows())
        self.vars = {
            "employee_code": tk.StringVar(value=self._next_employee_code()),
            "full_name": tk.StringVar(),
            "dpi": tk.StringVar(),
            "phone": tk.StringVar(),
            "address": tk.StringVar(),
            "position": tk.StringVar(),
            "hire_date": tk.StringVar(value=datetime.now().date().isoformat()),
            "status": tk.StringVar(value="Activo"),
            "base_salary": tk.StringVar(value="0.00"),
            "pay_frequency": tk.StringVar(value="Mensual"),
            "commission_rate": tk.StringVar(value="0"),
        }
        self.notes = None
        self.tree = None
        self.quick_total = None
        self.selected_employee = None
        self.pay_vars = {
            "bonus": tk.StringVar(value="0.00"),
            "discount": tk.StringVar(value="0.00"),
            "advance": tk.StringVar(value="0.00"),
            "note": tk.StringVar(),
        }
        self.summary_labels = {}
        self._build()
        self._load_rows()

    def _next_employee_code(self):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id FROM employees ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close()
        return f"EMP-{((row[0]+1) if row else 1):05d}"

    def _build(self):
        self.columnconfigure(0, weight=7)
        self.columnconfigure(1, weight=8)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        left = ttk.Frame(self, style="Card.TFrame", padding=22)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,12), pady=(0,12))
        left.columnconfigure((0,1), weight=1)

        ttk.Label(left, text="Ficha de empleado", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(left, text="Datos laborales, sueldo base y comisión por ventas.", style="CardNote.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4,16))

        def efield(parent, row, col, label, widget, pad=(0,12)):
            ttk.Label(parent, text=label, style="CardTitle.TLabel").grid(row=row, column=col, sticky="w", pady=(0,6), padx=pad)
            widget.grid(row=row+1, column=col, sticky="ew", pady=(0,12), padx=pad)
            return widget

        efield(left, 2, 0, "Código empleado", ttk.Entry(left, textvariable=self.vars["employee_code"], state="readonly"))
        efield(left, 2, 1, "Estado", ttk.Combobox(left, textvariable=self.vars["status"], values=self.STATUSES, state="readonly"))
        efield(left, 4, 0, "Nombre completo", ttk.Entry(left, textvariable=self.vars["full_name"]))
        efield(left, 4, 1, "DPI / Identificación", ttk.Entry(left, textvariable=self.vars["dpi"]))
        efield(left, 6, 0, "Teléfono", ttk.Entry(left, textvariable=self.vars["phone"]))
        efield(left, 6, 1, "Cargo", ttk.Entry(left, textvariable=self.vars["position"]))
        efield(left, 8, 0, "Fecha ingreso", ttk.Entry(left, textvariable=self.vars["hire_date"]))
        efield(left, 8, 1, "Tipo de pago", ttk.Combobox(left, textvariable=self.vars["pay_frequency"], values=self.PAY_FREQUENCIES, state="readonly"))
        efield(left, 10, 0, "Sueldo base", ttk.Entry(left, textvariable=self.vars["base_salary"]))
        efield(left, 10, 1, "% comisión ventas", ttk.Entry(left, textvariable=self.vars["commission_rate"]))
        ttk.Label(left, text="Dirección", style="CardTitle.TLabel").grid(row=12, column=0, columnspan=2, sticky="w", pady=(0,6))
        ttk.Entry(left, textvariable=self.vars["address"]).grid(row=13, column=0, columnspan=2, sticky="ew", pady=(0,12))
        ttk.Label(left, text="Observaciones", style="CardTitle.TLabel").grid(row=14, column=0, columnspan=2, sticky="w", pady=(0,6))
        self.notes = tk.Text(left, height=5, bg="#1f2937", fg="#e5e7eb", insertbackground="white", relief="flat")
        self.notes.grid(row=15, column=0, columnspan=2, sticky="ew", pady=(0,12))
        actions = ttk.Frame(left, style="Card.TFrame")
        actions.grid(row=16, column=0, columnspan=2, sticky="ew")
        self.btn_employee_new = ttk.Button(actions, text="Nuevo", command=self.reset_form)
        self.btn_employee_new.pack(side="left", padx=(0,8))
        self.btn_employee_save = ttk.Button(actions, text="Guardar / Actualizar", style="Primary.TButton", command=self.save_employee)
        self.btn_employee_save.pack(side="left", padx=(0,8))
        self.btn_employee_delete = ttk.Button(actions, text="Eliminar seleccionado", command=self.delete_selected)
        self.btn_employee_delete.pack(side="left", padx=(0,8))
        disable_button_if_denied(self.btn_employee_save, 'Empleados', 'crear', 'guardar empleado')
        disable_button_if_denied(self.btn_employee_delete, 'Empleados', 'eliminar', 'eliminar empleado')

        right = ttk.Frame(self, style="TFrame")
        right.grid(row=0, column=1, rowspan=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        stats = ttk.Frame(right, style="Card.TFrame", padding=18)
        stats.grid(row=0, column=0, sticky="ew", pady=(0,10))
        ttk.Label(stats, text="Resumen empleados", style="CardTitle.TLabel").pack(anchor="w")
        self.quick_total = ttk.Label(stats, text="0 empleados", style="CardValue.TLabel")
        self.quick_total.pack(anchor="w", pady=(10,2))
        ttk.Label(stats, text="Doble click para editar y calcular comisión del mes actual.", style="CardNote.TLabel").pack(anchor="w")

        search_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        search_card.grid(row=1, column=0, sticky="ew", pady=(0,10))
        ttk.Label(search_card, text="Buscar empleado", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(search_card, textvariable=self.search_var).pack(fill="x", pady=(8,0), ipady=4)

        list_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        list_card.grid(row=2, column=0, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)
        list_top = ttk.Frame(list_card, style="Card.TFrame")
        list_top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        list_top.columnconfigure(0, weight=1)
        ttk.Label(list_top, text="Listado de empleados", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        cols = ("code", "name", "position", "phone", "status", "salary", "commission")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings")
        heads = {"code":"Código", "name":"Nombre", "position":"Cargo", "phone":"Teléfono", "status":"Estado", "salary":"Sueldo", "commission":"% Com."}
        widths = {"code":100, "name":220, "position":140, "phone":120, "status":95, "salary":110, "commission":90}
        for col in cols:
            self.tree.heading(col, text=heads[col])
            self.tree.column(col, width=widths[col], anchor="w")
        install_column_manager(list_top, self.tree, 'empleados_listado', row=0, column=1, padx=(0, 0), pady=(0, 0))
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        sb = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.grid(row=1, column=1, sticky="ns")

        payroll = ttk.Frame(self, style="Card.TFrame", padding=22)
        payroll.grid(row=1, column=0, sticky="nsew", padx=(0,12))
        for i in range(4): payroll.columnconfigure(i, weight=1)
        ttk.Label(payroll, text="Nómina rápida del mes actual", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(payroll, text="Calcula sueldo base + comisión por ventas + extras - descuentos - adelantos.", style="CardNote.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(4,16))
        self.summary_labels["sales"] = ttk.Label(payroll, text="Ventas del mes: Q 0.00", style="CardTitle.TLabel")
        self.summary_labels["sales"].grid(row=2, column=0, sticky="w")
        self.summary_labels["commission"] = ttk.Label(payroll, text="Comisión generada: Q 0.00", style="CardTitle.TLabel")
        self.summary_labels["commission"].grid(row=2, column=1, sticky="w")
        self.summary_labels["base"] = ttk.Label(payroll, text="Sueldo base: Q 0.00", style="CardTitle.TLabel")
        self.summary_labels["base"].grid(row=2, column=2, sticky="w")
        self.summary_labels["total"] = ttk.Label(payroll, text="Total a pagar: Q 0.00", style="CardValue.TLabel")
        self.summary_labels["total"].grid(row=2, column=3, sticky="w")
        efield(payroll, 4, 0, "Bono", ttk.Entry(payroll, textvariable=self.pay_vars["bonus"]))
        efield(payroll, 4, 1, "Descuento", ttk.Entry(payroll, textvariable=self.pay_vars["discount"]))
        efield(payroll, 4, 2, "Adelanto", ttk.Entry(payroll, textvariable=self.pay_vars["advance"]))
        efield(payroll, 4, 3, "Nota de pago", ttk.Entry(payroll, textvariable=self.pay_vars["note"]))
        pbtns = ttk.Frame(payroll, style="Card.TFrame")
        pbtns.grid(row=6, column=0, columnspan=4, sticky="w")
        self.btn_calc_payroll = ttk.Button(pbtns, text="Calcular nómina", command=self._refresh_payroll_summary)
        self.btn_calc_payroll.pack(side="left", padx=(0,8))
        self.btn_register_payroll = ttk.Button(pbtns, text="Registrar pago", style="Success.TButton", command=self.register_payment)
        self.btn_register_payroll.pack(side="left")
        disable_button_if_denied(self.btn_register_payroll, 'Empleados', 'crear', 'registrar pago de nómina')

    def reset_form(self):
        self.editing_id = None
        self.selected_employee = None
        self.vars["employee_code"].set(self._next_employee_code())
        self.vars["full_name"].set("")
        self.vars["dpi"].set("")
        self.vars["phone"].set("")
        self.vars["address"].set("")
        self.vars["position"].set("")
        self.vars["hire_date"].set(datetime.now().date().isoformat())
        self.vars["status"].set("Activo")
        self.vars["base_salary"].set("0.00")
        self.vars["pay_frequency"].set("Mensual")
        self.vars["commission_rate"].set("0")
        self.notes.delete("1.0", "end")
        for k in self.pay_vars: self.pay_vars[k].set("0.00" if k != "note" else "")
        self._refresh_payroll_summary()

    def save_employee(self):
        needed = 'editar' if self.editing_id else 'crear'
        if not require_permission('Empleados', needed, self, 'guardar empleado'):
            return
        full_name = self.vars["full_name"].get().strip()
        if not full_name:
            messagebox.showwarning("Empleados", "Ingresa el nombre completo.")
            return
        data = (
            self.vars["employee_code"].get().strip(),
            datetime.now().isoformat(timespec='seconds'),
            full_name,
            self.vars["dpi"].get().strip(),
            self.vars["phone"].get().strip(),
            self.vars["address"].get().strip(),
            self.vars["position"].get().strip(),
            self.vars["hire_date"].get().strip(),
            self.vars["status"].get().strip(),
            safe_float(self.vars["base_salary"].get()),
            self.vars["pay_frequency"].get().strip(),
            safe_float(self.vars["commission_rate"].get()),
            self.notes.get("1.0", "end").strip(),
        )
        conn = db_connect(); cur = conn.cursor()
        try:
            if self.editing_id:
                cur.execute("""
                    UPDATE employees SET employee_code=?, full_name=?, dpi=?, phone=?, address=?, position=?, hire_date=?, status=?, base_salary=?, pay_frequency=?, commission_rate=?, notes=?
                    WHERE id=?
                """, data[0:1] + data[2:] + (self.editing_id,))
            else:
                cur.execute("""
                    INSERT INTO employees (employee_code, created_at, full_name, dpi, phone, address, position, hire_date, status, base_salary, pay_frequency, commission_rate, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, data)
            conn.commit()
            messagebox.showinfo("Empleados", "Empleado guardado correctamente.")
            self.reset_form(); self._load_rows()
        except sqlite3.IntegrityError as exc:
            messagebox.showerror("Empleados", f"No se pudo guardar: {exc}")
        finally:
            conn.close()

    def delete_selected(self):
        if not require_permission('Empleados', 'eliminar', self, 'eliminar empleado'):
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Empleados", "Selecciona un empleado para eliminar.")
            return
        values = self.tree.item(sel[0], "values")
        if not values:
            return
        code = values[0]
        if not messagebox.askyesno("Empleados", f"¿Eliminar empleado {code}? Esta acción no borra ventas históricas."):
            return
        conn = db_connect(); cur = conn.cursor()
        cur.execute("DELETE FROM employees WHERE employee_code=?", (code,))
        conn.commit(); conn.close()
        self.reset_form(); self._load_rows()

    def _sales_totals_for_employee(self, employee_name):
        if not employee_name:
            return 0.0
        start, end = month_bounds()
        conn = db_connect(); cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(total),0) FROM sales WHERE status='ACTIVA' AND TRIM(COALESCE(user_name,'')) = ? AND created_at >= ? AND created_at < ?",
            (employee_name.strip(), start.isoformat(timespec='seconds'), end.isoformat(timespec='seconds')),
        )
        total = safe_float(cur.fetchone()[0])
        conn.close()
        return total

    def _refresh_payroll_summary(self):
        name = self.vars["full_name"].get().strip()
        sales_total = self._sales_totals_for_employee(name)
        base_salary = safe_float(self.vars["base_salary"].get())
        commission_rate = safe_float(self.vars["commission_rate"].get())
        commission_amount = sales_total * (commission_rate / 100.0)
        bonus = safe_float(self.pay_vars["bonus"].get())
        discount = safe_float(self.pay_vars["discount"].get())
        advance = safe_float(self.pay_vars["advance"].get())
        total_to_pay = base_salary + commission_amount + bonus - discount - advance
        self.summary_labels["sales"].configure(text=f"Ventas del mes: {money_gt(sales_total)}")
        self.summary_labels["commission"].configure(text=f"Comisión generada: {money_gt(commission_amount)}")
        self.summary_labels["base"].configure(text=f"Sueldo base: {money_gt(base_salary)}")
        self.summary_labels["total"].configure(text=f"Total a pagar: {money_gt(total_to_pay)}")
        return sales_total, commission_amount, total_to_pay

    def register_payment(self):
        if not require_permission('Empleados', 'crear', self, 'registrar pago de nómina'):
            return
        if not self.vars["full_name"].get().strip() or not self.vars["employee_code"].get().strip():
            messagebox.showwarning("Nómina", "Selecciona o guarda primero un empleado.")
            return
        sales_total, commission_amount, total_to_pay = self._refresh_payroll_summary()
        conn = db_connect(); cur = conn.cursor()
        period_label = datetime.now().strftime('%Y-%m')
        cur.execute(
            """
            INSERT INTO employee_payments (created_at, employee_code, employee_name, period_label, base_salary, commission_amount, bonus_amount, discount_amount, advance_amount, total_to_pay, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec='seconds'),
                self.vars["employee_code"].get().strip(),
                self.vars["full_name"].get().strip(),
                period_label,
                safe_float(self.vars["base_salary"].get()),
                commission_amount,
                safe_float(self.pay_vars["bonus"].get()),
                safe_float(self.pay_vars["discount"].get()),
                safe_float(self.pay_vars["advance"].get()),
                total_to_pay,
                self.pay_vars["note"].get().strip(),
            )
        )
        conn.commit(); conn.close()
        messagebox.showinfo("Nómina", f"Pago registrado. Total a pagar: {money_gt(total_to_pay)}")

    def _load_rows(self):
        if not self.tree:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        term = self.search_var.get().strip().lower()
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id, employee_code, full_name, position, phone, status, base_salary, commission_rate FROM employees ORDER BY id DESC")
        rows = cur.fetchall(); conn.close()
        total = 0
        for row in rows:
            rid, code, name, position, phone, status, salary, commission = row
            hay = " ".join([str(v or "") for v in row]).lower()
            if term and term not in hay:
                continue
            total += 1
            self.tree.insert("", "end", iid=str(rid), values=(code, name, position or "", phone or "", status or "", f"{safe_float(salary):.2f}", f"{safe_float(commission):.2f}"))
        self.quick_total.configure(text=f"{total} empleados")

    def _on_tree_double_click(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        rid = int(sel[0])
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id, employee_code, full_name, dpi, phone, address, position, hire_date, status, base_salary, pay_frequency, commission_rate, notes FROM employees WHERE id=?", (rid,))
        row = cur.fetchone(); conn.close()
        if not row:
            return
        self.editing_id = row[0]
        self.vars["employee_code"].set(row[1] or "")
        self.vars["full_name"].set(row[2] or "")
        self.vars["dpi"].set(row[3] or "")
        self.vars["phone"].set(row[4] or "")
        self.vars["address"].set(row[5] or "")
        self.vars["position"].set(row[6] or "")
        self.vars["hire_date"].set(row[7] or "")
        self.vars["status"].set(row[8] or "Activo")
        self.vars["base_salary"].set(f"{safe_float(row[9]):.2f}")
        self.vars["pay_frequency"].set(row[10] or "Mensual")
        self.vars["commission_rate"].set(f"{safe_float(row[11]):.2f}")
        self.notes.delete("1.0", "end"); self.notes.insert("1.0", row[12] or "")
        self._refresh_payroll_summary()


class AttendanceView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.employee_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self.tree = None
        self.employee_combo = None
        self.active_label = None
        self._build()
        self._reload_employees()
        self._load_rows()

    def _build(self):
        self.columnconfigure(0, weight=6)
        self.columnconfigure(1, weight=7)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Card.TFrame", padding=22)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,12))
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Control de asistencia", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(left, text="Marca entrada y salida por empleado. Calcula horas trabajadas automáticamente.", style="CardNote.TLabel").grid(row=1, column=0, sticky="w", pady=(4,16))
        ttk.Label(left, text="Empleado", style="CardTitle.TLabel").grid(row=2, column=0, sticky="w", pady=(0,6))
        self.employee_combo = ttk.Combobox(left, textvariable=self.employee_var, state="readonly")
        self.employee_combo.grid(row=3, column=0, sticky="ew", pady=(0,12))
        ttk.Label(left, text="Observación", style="CardTitle.TLabel").grid(row=4, column=0, sticky="w", pady=(0,6))
        ttk.Entry(left, textvariable=self.note_var).grid(row=5, column=0, sticky="ew", pady=(0,12))
        btns = ttk.Frame(left, style="Card.TFrame")
        btns.grid(row=6, column=0, sticky="w")
        self.btn_att_entry = ttk.Button(btns, text="Registrar entrada", style="Success.TButton", command=self.mark_entry)
        self.btn_att_entry.pack(side="left", padx=(0,8))
        self.btn_att_exit = ttk.Button(btns, text="Registrar salida", style="Primary.TButton", command=self.mark_exit)
        self.btn_att_exit.pack(side="left", padx=(0,8))
        self.btn_att_refresh = ttk.Button(btns, text="Actualizar", command=self._load_rows)
        self.btn_att_refresh.pack(side="left")
        disable_button_if_denied(self.btn_att_entry, 'Asistencia', 'crear', 'registrar entrada')
        disable_button_if_denied(self.btn_att_exit, 'Asistencia', 'editar', 'registrar salida')
        self.active_label = ttk.Label(left, text="Activos ahora: 0", style="CardValue.TLabel")
        self.active_label.grid(row=7, column=0, sticky="w", pady=(18,0))

        right = ttk.Frame(self, style="Card.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        topbar = ttk.Frame(right, style="Card.TFrame")
        topbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        topbar.columnconfigure(0, weight=1)
        ttk.Label(topbar, text="Historial de asistencia", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        cols = ("date", "employee", "entry", "exit", "hours", "status", "notes")
        self.tree = ttk.Treeview(right, columns=cols, show="headings")
        heads = {"date":"Fecha", "employee":"Empleado", "entry":"Entrada", "exit":"Salida", "hours":"Horas", "status":"Estado", "notes":"Observación"}
        widths = {"date":110, "employee":210, "entry":150, "exit":150, "hours":85, "status":90, "notes":220}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="w")
        install_column_manager(topbar, self.tree, 'asistencia_historial', row=0, column=1, padx=(0, 0), pady=(0, 0))
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(0,0))
        right.rowconfigure(1, weight=1)
        sb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.grid(row=1, column=1, sticky="ns", pady=(0,0))

    def _reload_employees(self):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT employee_code, full_name FROM employees WHERE status='Activo' ORDER BY full_name")
        rows = cur.fetchall(); conn.close()
        values = [f"{code} | {name}" for code, name in rows]
        self.employee_combo["values"] = values
        if values and not self.employee_var.get():
            self.employee_var.set(values[0])

    def _selected_employee(self):
        raw = self.employee_var.get().strip()
        if ' | ' not in raw:
            return None, None
        code, name = raw.split(' | ', 1)
        return code.strip(), name.strip()

    def mark_entry(self):
        if not require_permission('Asistencia', 'crear', self, 'registrar entrada'):
            return
        code, name = self._selected_employee()
        if not code:
            messagebox.showwarning("Asistencia", "Selecciona un empleado.")
            return
        today = datetime.now().date().isoformat()
        now = datetime.now().isoformat(timespec='seconds')
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id FROM attendance_logs WHERE employee_code=? AND work_date=? AND check_out IS NULL", (code, today))
        if cur.fetchone():
            conn.close(); messagebox.showwarning("Asistencia", "Ese empleado ya tiene una entrada activa hoy."); return
        cur.execute("INSERT INTO attendance_logs (employee_code, employee_name, work_date, check_in, status, notes) VALUES (?, ?, ?, ?, 'ACTIVO', ?)",
                    (code, name, today, now, self.note_var.get().strip()))
        conn.commit(); conn.close()
        self.note_var.set("")
        self._load_rows()

    def mark_exit(self):
        if not require_permission('Asistencia', 'editar', self, 'registrar salida'):
            return
        code, name = self._selected_employee()
        if not code:
            messagebox.showwarning("Asistencia", "Selecciona un empleado.")
            return
        today = datetime.now().date().isoformat()
        now = datetime.now().isoformat(timespec='seconds')
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id, check_in FROM attendance_logs WHERE employee_code=? AND work_date=? AND check_out IS NULL ORDER BY id DESC LIMIT 1", (code, today))
        row = cur.fetchone()
        if not row:
            conn.close(); messagebox.showwarning("Asistencia", "No hay entrada activa para ese empleado hoy."); return
        rec_id, check_in = row
        try:
            dt_in = datetime.fromisoformat(check_in)
            hours = round((datetime.now() - dt_in).total_seconds() / 3600.0, 2)
        except Exception:
            hours = 0.0
        cur.execute("UPDATE attendance_logs SET check_out=?, worked_hours=?, status='CERRADO', notes=COALESCE(notes,'') || CASE WHEN ?<>'' THEN ' | ' || ? ELSE '' END WHERE id=?",
                    (now, hours, self.note_var.get().strip(), self.note_var.get().strip(), rec_id))
        conn.commit(); conn.close()
        self.note_var.set("")
        self._load_rows()

    def _load_rows(self):
        self._reload_employees()
        for item in self.tree.get_children():
            self.tree.delete(item)
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT work_date, employee_name, check_in, check_out, worked_hours, status, notes FROM attendance_logs ORDER BY id DESC LIMIT 200")
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM attendance_logs WHERE check_out IS NULL")
        active = cur.fetchone()[0]
        conn.close()
        self.active_label.configure(text=f"Activos ahora: {active}")
        for row in rows:
            work_date, employee_name, check_in, check_out, hours, status, notes = row
            self.tree.insert("", "end", values=(work_date or "", employee_name or "", (check_in or "").replace('T',' '), (check_out or "").replace('T',' '), f"{safe_float(hours):.2f}", status or "", notes or ""))

class PlaceholderView(ttk.Frame):
    def __init__(self, parent, module_name):
        super().__init__(parent, style="TFrame", padding=10)
        card = ttk.Frame(self, style="Card.TFrame", padding=24)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text=module_name, style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text=(
                "Este módulo ya está contemplado en la arquitectura y visible en el menú. "
                "Se activará en próximas versiones sobre esta misma base estable."
            ),
            style="CardTitle.TLabel",
            wraplength=900,
        ).pack(anchor="w", pady=(14, 0))


class TechnicalAreaView(ttk.Frame):
    STATUSES = ["Recibido", "En revisión", "En diagnóstico", "En reparación", "Pendiente repuesto", "Listo para entregar", "Entregado", "Cancelado"]

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.photo_1 = tk.StringVar(value="")
        self.photo_2 = tk.StringVar(value="")
        self.client_selector_var = tk.StringVar()
        self.part_selector_var = tk.StringVar()
        self.part_qty_var = tk.StringVar(value="1")
        self.part_options = []
        self.parts_used = []
        self.vars = {
            "ticket_no": tk.StringVar(value=self._next_ticket_no()),
            "client_name": tk.StringVar(),
            "client_nit": tk.StringVar(),
            "client_phone": tk.StringVar(),
            "equipment_type": tk.StringVar(value="PC"),
            "equipment_name": tk.StringVar(),
            "brand": tk.StringVar(),
            "model": tk.StringVar(),
            "serial": tk.StringVar(),
            "status": tk.StringVar(value="En revisión"),
            "technician": tk.StringVar(),
            "repair_cost": tk.StringVar(value="0.00"),
            "advance_payment": tk.StringVar(value="0.00"),
            "pending_balance": tk.StringVar(value="0.00"),
        }
        self._build()
        self._bind_balance_calc()
        self._refresh_client_options()
        self._refresh_part_options()
        self._refresh_parts_list()
        self._load_recent()

    def _build(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self, style="TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        form_card = ttk.Frame(left, style="Card.TFrame", padding=16)
        form_card.grid(row=0, column=0, sticky="nsew")
        for col in range(4):
            form_card.columnconfigure(col, weight=1)

        ttk.Label(form_card, text="Ticket #", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0,6))
        ttk.Entry(form_card, textvariable=self.vars["ticket_no"], state="readonly").grid(row=1, column=0, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(form_card, text="Estado", style="CardTitle.TLabel").grid(row=0, column=1, sticky="w", pady=(0,6))
        ttk.Combobox(form_card, textvariable=self.vars["status"], values=self.STATUSES, state="readonly").grid(row=1, column=1, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(form_card, text="Técnico", style="CardTitle.TLabel").grid(row=0, column=2, sticky="w", pady=(0,6))
        ttk.Entry(form_card, textvariable=self.vars["technician"]).grid(row=1, column=2, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(form_card, text="Tipo de equipo", style="CardTitle.TLabel").grid(row=0, column=3, sticky="w", pady=(0,6))
        ttk.Combobox(form_card, textvariable=self.vars["equipment_type"], values=["PC", "Laptop", "Celular", "Tablet", "Consola", "Impresora", "Otro"], state="readonly").grid(row=1, column=3, sticky="ew", pady=(0,10))

        row = 2
        ttk.Label(form_card, text="Cliente registrado", style="CardTitle.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0,6))
        self.client_selector = ttk.Combobox(form_card, textvariable=self.client_selector_var, state="readonly")
        self.client_selector.grid(row=row+1, column=0, columnspan=2, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Button(form_card, text="Cargar cliente", command=self.load_selected_client).grid(row=row+1, column=2, sticky="ew", padx=(0,8), pady=(0,10))

        labels = [("Cliente", "client_name"), ("NIT", "client_nit"), ("Teléfono", "client_phone"), ("Equipo", "equipment_name"), ("Marca", "brand"), ("Modelo", "model"), ("Serial", "serial")]
        positions = [(row+2,0), (row+2,1), (row+2,2), (row+2,3), (row+4,0), (row+4,1), (row+4,2)]
        for (label, key), (r, c) in zip(labels, positions):
            ttk.Label(form_card, text=label, style="CardTitle.TLabel").grid(row=r, column=c, sticky="w", pady=(0,6))
            ttk.Entry(form_card, textvariable=self.vars[key]).grid(row=r+1, column=c, sticky="ew", padx=(0,8) if c < 3 else (0,0), pady=(0,10))

        text_fields = [("Falla reportada", "issue_reported"), ("Diagnóstico", "diagnosis"), ("Accesorios", "accessories"), ("Observaciones", "observations")]
        self.text_widgets = {}
        current_row = 8
        for label, key in text_fields:
            ttk.Label(form_card, text=label, style="CardTitle.TLabel").grid(row=current_row, column=0, columnspan=4, sticky="w", pady=(0,6))
            txt = tk.Text(form_card, height=4 if key != "accessories" else 2, bg="#1f2937", fg="#e5e7eb", insertbackground="white", relief="flat")
            txt.grid(row=current_row+1, column=0, columnspan=4, sticky="ew", pady=(0,10))
            self.text_widgets[key] = txt
            current_row += 2

        ttk.Label(form_card, text="Costo reparación", style="CardTitle.TLabel").grid(row=current_row, column=0, sticky="w", pady=(0,6))
        ttk.Entry(form_card, textvariable=self.vars["repair_cost"]).grid(row=current_row+1, column=0, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(form_card, text="Anticipo", style="CardTitle.TLabel").grid(row=current_row, column=1, sticky="w", pady=(0,6))
        ttk.Entry(form_card, textvariable=self.vars["advance_payment"]).grid(row=current_row+1, column=1, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(form_card, text="Saldo pendiente", style="CardTitle.TLabel").grid(row=current_row, column=2, sticky="w", pady=(0,6))
        ttk.Entry(form_card, textvariable=self.vars["pending_balance"], state="readonly").grid(row=current_row+1, column=2, sticky="ew", padx=(0,8), pady=(0,10))

        ttk.Label(form_card, text="Foto 1", style="CardTitle.TLabel").grid(row=current_row+2, column=0, sticky="w", pady=(0,6))
        ttk.Entry(form_card, textvariable=self.photo_1, state="readonly").grid(row=current_row+3, column=0, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Button(form_card, text="Seleccionar", command=lambda: self.pick_photo(self.photo_1)).grid(row=current_row+3, column=1, sticky="w", pady=(0,10))
        ttk.Label(form_card, text="Foto 2", style="CardTitle.TLabel").grid(row=current_row+2, column=2, sticky="w", pady=(0,6))
        ttk.Entry(form_card, textvariable=self.photo_2, state="readonly").grid(row=current_row+3, column=2, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Button(form_card, text="Seleccionar", command=lambda: self.pick_photo(self.photo_2)).grid(row=current_row+3, column=3, sticky="w", pady=(0,10))

        actions = ttk.Frame(form_card, style="Card.TFrame")
        actions.grid(row=current_row+4, column=0, columnspan=4, sticky="ew", pady=(8,0))
        self.btn_ticket_new = ttk.Button(actions, text="Nuevo", command=self.reset_form)
        self.btn_ticket_new.pack(side="left", padx=(0,8))
        self.btn_ticket_save = ttk.Button(actions, text="Guardar", style="Primary.TButton", command=self.save_ticket)
        self.btn_ticket_save.pack(side="left", padx=(0,8))
        self.btn_ticket_cancel = ttk.Button(actions, text="Anular", command=self.not_implemented)
        self.btn_ticket_cancel.pack(side="left", padx=(0,8))
        self.btn_ticket_pdf = ttk.Button(actions, text="Reporte PDF", command=self.not_implemented)
        self.btn_ticket_pdf.pack(side="left")
        disable_button_if_denied(self.btn_ticket_save, 'Área Técnica', 'crear', 'guardar ticket técnico')
        disable_button_if_denied(self.btn_ticket_cancel, 'Área Técnica', 'anular', 'anular ticket técnico')
        disable_button_if_denied(self.btn_ticket_pdf, 'Área Técnica', 'imprimir', 'generar reporte técnico')

        stats_card = ttk.Frame(right, style="Card.TFrame", padding=16)
        stats_card.grid(row=0, column=0, sticky="ew", pady=(0,10))
        ttk.Label(stats_card, text="Resumen rápido", style="CardTitle.TLabel").pack(anchor="w")
        self.quick_total = ttk.Label(stats_card, text="0 tickets", style="CardValue.TLabel")
        self.quick_total.pack(anchor="w", pady=(10,0))
        ttk.Label(stats_card, text="Guardados en esta base local", style="CardNote.TLabel").pack(anchor="w")

        parts_card = ttk.Frame(right, style="Card.TFrame", padding=16)
        parts_card.grid(row=1, column=0, sticky="ew", pady=(0,10))
        parts_card.columnconfigure(0, weight=1)
        ttk.Label(parts_card, text="Repuestos / consumos", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self.part_selector = ttk.Combobox(parts_card, textvariable=self.part_selector_var, state="readonly")
        self.part_selector.grid(row=1, column=0, sticky="ew", pady=(10,8), padx=(0,8))
        ttk.Entry(parts_card, textvariable=self.part_qty_var, width=8).grid(row=1, column=1, sticky="ew", pady=(10,8), padx=(0,8))
        self.btn_add_part = ttk.Button(parts_card, text="Agregar repuesto", command=self.add_part_to_ticket)
        self.btn_add_part.grid(row=1, column=2, sticky="ew", pady=(10,8))
        disable_button_if_denied(self.btn_add_part, 'Área Técnica', 'editar', 'agregar repuesto al ticket')
        self.parts_listbox = tk.Listbox(parts_card, height=6, bg="#1f2937", fg="#e5e7eb", relief="flat", highlightthickness=0)
        self.parts_listbox.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.btn_remove_part = ttk.Button(parts_card, text="Quitar seleccionado", command=self.remove_selected_part)
        self.btn_remove_part.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8,0))
        disable_button_if_denied(self.btn_remove_part, 'Área Técnica', 'editar', 'quitar repuesto del ticket')

        list_card = ttk.Frame(right, style="Card.TFrame", padding=16)
        list_card.grid(row=2, column=0, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)
        ttk.Label(list_card, text="Tickets recientes", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.listbox = tk.Listbox(list_card, bg="#1f2937", fg="#e5e7eb", relief="flat", highlightthickness=0)
        self.listbox.grid(row=1, column=0, sticky="nsew", pady=(10,0))

    def _bind_balance_calc(self):
        def recalc(*_):
            self.vars["pending_balance"].set(f"{safe_float(self.vars['repair_cost'].get()) - safe_float(self.vars['advance_payment'].get()):.2f}")
        self.vars["repair_cost"].trace_add("write", recalc)
        self.vars["advance_payment"].trace_add("write", recalc)
        recalc()

    def _next_ticket_no(self):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id FROM technical_tickets ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close()
        return f"TEC-{((row[0] + 1) if row else 1):05d}"

    def pick_photo(self, var):
        file_path = filedialog.askopenfilename(title="Seleccionar imagen", filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg;*.webp"), ("Todos", "*.*")])
        if file_path:
            var.set(file_path)

    def _refresh_client_options(self):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT name, nit, phone FROM clients WHERE COALESCE(status, 'Activo')='Activo' ORDER BY name")
        rows = cur.fetchall(); conn.close()
        self._client_lookup = {f"{name} | NIT: {nit or 'CF'}": {"name": name or "", "nit": nit or "CF", "phone": phone or ""} for name, nit, phone in rows}
        options = list(self._client_lookup.keys())
        self.client_selector.configure(values=options)
        if options and not self.client_selector_var.get():
            self.client_selector_var.set(options[0])

    def load_selected_client(self):
        selected = self._client_lookup.get(self.client_selector_var.get())
        if not selected:
            messagebox.showwarning("Clientes", "No hay un cliente registrado para cargar.")
            return
        self.vars["client_name"].set(selected.get("name", ""))
        self.vars["client_nit"].set(selected.get("nit", "CF"))
        self.vars["client_phone"].set(selected.get("phone", ""))

    def _refresh_part_options(self):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT internal_code, name, stock, cost, price FROM inventory_items WHERE item_type='Producto' AND COALESCE(status, 'Activo')='Activo' ORDER BY name")
        rows = cur.fetchall(); conn.close()
        self.part_options = []
        labels = []
        for code, name, stock, cost, price in rows:
            item = {
                "code": code or "",
                "name": name or "",
                "stock": safe_float(stock),
                "cost": safe_float(cost),
                "price": safe_float(price),
            }
            label = f"{item['code']} | {item['name']} | Stock: {item['stock']:.2f}"
            item["label"] = label
            self.part_options.append(item)
            labels.append(label)
        self.part_selector.configure(values=labels)
        if labels and not self.part_selector_var.get():
            self.part_selector_var.set(labels[0])

    def add_part_to_ticket(self):
        if not require_permission('Área Técnica', 'editar', self, 'agregar repuesto al ticket'):
            return
        label = self.part_selector_var.get().strip()
        qty = safe_float(self.part_qty_var.get())
        if not label:
            messagebox.showwarning("Inventario", "Selecciona un repuesto del inventario.")
            return
        if qty <= 0:
            messagebox.showwarning("Inventario", "La cantidad del repuesto debe ser mayor que cero.")
            return
        selected = next((item for item in self.part_options if item.get("label") == label), None)
        if not selected:
            messagebox.showwarning("Inventario", "El repuesto seleccionado ya no está disponible.")
            self._refresh_part_options()
            return
        existing_qty = sum(safe_float(p.get("qty")) for p in self.parts_used if p.get("code") == selected.get("code"))
        if qty + existing_qty > safe_float(selected.get("stock")):
            messagebox.showwarning("Inventario", f"Stock insuficiente para {selected.get('name','')}. Disponible: {safe_float(selected.get('stock')):.2f}")
            return
        self.parts_used.append({
            "code": selected.get("code", ""),
            "name": selected.get("name", ""),
            "qty": qty,
            "cost": safe_float(selected.get("cost")),
            "price": safe_float(selected.get("price")),
        })
        self.part_qty_var.set("1")
        self._refresh_parts_list()

    def remove_selected_part(self):
        if not require_permission('Área Técnica', 'editar', self, 'quitar repuesto del ticket'):
            return
        sel = self.parts_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.parts_used):
            self.parts_used.pop(idx)
            self._refresh_parts_list()

    def _refresh_parts_list(self):
        if hasattr(self, "parts_listbox"):
            self.parts_listbox.delete(0, tk.END)
            for part in self.parts_used:
                self.parts_listbox.insert(tk.END, f"{part.get('code','')} | {part.get('name','')} | Cant: {safe_float(part.get('qty')):.2f}")

    def _load_recent(self):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT ticket_no, client_name, equipment_name, status FROM technical_tickets ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall(); cur.execute("SELECT COUNT(*) FROM technical_tickets")
        total = cur.fetchone()[0]; conn.close()
        self.listbox.delete(0, tk.END)
        for ticket_no, client, equip, status in rows:
            self.listbox.insert(tk.END, f"{ticket_no} | {client or '-'} | {equip or '-'} | {status}")
        self.quick_total.configure(text=f"{total} tickets")

    def reset_form(self):
        for key, var in self.vars.items():
            if key == "ticket_no":
                var.set(self._next_ticket_no())
            elif key == "status":
                var.set("En revisión")
            elif key == "equipment_type":
                var.set("PC")
            elif key in {"repair_cost", "advance_payment", "pending_balance"}:
                var.set("0.00")
            else:
                var.set("")
        for txt in self.text_widgets.values():
            txt.delete("1.0", tk.END)
        self.photo_1.set("")
        self.photo_2.set("")
        self.parts_used = []
        self.part_qty_var.set("1")
        self._refresh_client_options()
        self._refresh_part_options()
        self._refresh_parts_list()

    def not_implemented(self):
        messagebox.showinfo("Próxima versión", "Esta acción quedó preparada para la siguiente versión estable.")

    def save_ticket(self):
        needed = 'editar' if getattr(self, 'editing_ticket_id', None) else 'crear'
        if not require_permission('Área Técnica', needed, self, 'guardar ticket técnico'):
            return
        client_name = self.vars["client_name"].get().strip()
        if not client_name:
            messagebox.showwarning("Campo requerido", "Debes ingresar el nombre del cliente.")
            return
        issue = self.text_widgets["issue_reported"].get("1.0", tk.END).strip()
        diagnosis = self.text_widgets["diagnosis"].get("1.0", tk.END).strip()
        accessories = self.text_widgets["accessories"].get("1.0", tk.END).strip()
        observations = self.text_widgets["observations"].get("1.0", tk.END).strip()
        conn = db_connect(); cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO technical_tickets (
                ticket_no, created_at, client_name, client_nit, client_phone,
                equipment_type, equipment_name, brand, model, serial, status, technician,
                issue_reported, diagnosis, accessories, observations,
                repair_cost, advance_payment, pending_balance, photo_1, photo_2
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.vars["ticket_no"].get(), datetime.now().isoformat(timespec="seconds"), client_name,
                self.vars["client_nit"].get().strip(), self.vars["client_phone"].get().strip(),
                self.vars["equipment_type"].get().strip(), self.vars["equipment_name"].get().strip(),
                self.vars["brand"].get().strip(), self.vars["model"].get().strip(), self.vars["serial"].get().strip(),
                self.vars["status"].get().strip(), self.vars["technician"].get().strip(), issue, diagnosis,
                accessories, observations, safe_float(self.vars["repair_cost"].get()), safe_float(self.vars["advance_payment"].get()),
                safe_float(self.vars["pending_balance"].get()), self.photo_1.get(), self.photo_2.get(),
            ),
        )
        conn.commit(); conn.close()
        messagebox.showinfo("Guardado", f"Ticket {self.vars['ticket_no'].get()} guardado correctamente.")
        self.reset_form(); self._load_recent()


class ClientsView(ttk.Frame):
    DEPARTMENTS = ["Guatemala", "Sacatepéquez", "Chimaltenango", "Escuintla", "Quetzaltenango", "Huehuetenango", "Petén", "Otro"]
    PAYMENT_METHODS = ["Efectivo", "Depósito", "Transferencia", "Tarjeta"]

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.editing_client_id = None
        self.vars = {
            "client_code": tk.StringVar(value=self._next_client_code()),
            "name": tk.StringVar(),
            "nit": tk.StringVar(),
            "phone": tk.StringVar(),
            "phone2": tk.StringVar(),
            "dpi": tk.StringVar(),
            "email": tk.StringVar(),
            "address": tk.StringVar(),
            "shipping_address": tk.StringVar(),
            "department": tk.StringVar(value="Guatemala"),
            "social_url": tk.StringVar(),
            "discount": tk.StringVar(value="0.00"),
            "credit_limit": tk.StringVar(value="0.00"),
            "balance_favor": tk.StringVar(value="0.00"),
            "balance_available": tk.StringVar(value="0.00"),
            "balance_due": tk.StringVar(value="0.00"),
            "status": tk.StringVar(value="Activo"),
            "allow_credit": tk.BooleanVar(value=False),
        }
        self.notes = None
        self.tree = None
        self.quick_total = None
        self._row_client_codes = {}
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._load_rows())
        self.lbl_balance_due = None
        self.lbl_balance_favor = None
        self._build()
        self._load_rows()

    def _build(self):
        self._ensure_client_styles()

        self.columnconfigure(0, weight=11)
        self.columnconfigure(1, weight=13)
        self.rowconfigure(0, weight=1)

        left_wrap = tk.Frame(self, bg="#071631")
        left_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left_wrap.columnconfigure(0, weight=1)
        left_wrap.rowconfigure(0, weight=1)

        left = self._mk_card(left_wrap, padx=18, pady=18)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)

        accent_bar = tk.Frame(left, bg="#0d1832", height=3)
        accent_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        for idx, color in enumerate(("#1d8cff", "#8b5cf6", "#ff4db8", "#ff9f1a", "#22c55e")):
            accent_bar.grid_columnconfigure(idx, weight=1)
            tk.Frame(accent_bar, bg=color, height=3).grid(row=0, column=idx, sticky="nsew")

        form_card = self._mk_card(left, border="#27406a", bg="#0b1730", padx=18, pady=16)
        form_card.grid(row=1, column=0, columnspan=2, sticky="ew")
        for c in range(4):
            form_card.columnconfigure(c, weight=1)
        self._section_head(form_card, "👤", "DATOS DEL CLIENTE")

        self._make_input(form_card, 1, 0, "Código cliente", self.vars["client_code"], icon="⌁", readonly=True)
        self._make_input(form_card, 1, 1, "Estado", self.vars["status"], icon="▾", kind="combo", values=["Activo", "Inactivo"])
        self._make_input(form_card, 1, 2, "Crédito", self.vars["allow_credit"], icon="☑", kind="check")
        self._make_input(form_card, 1, 3, "Límite crédito", self.vars["credit_limit"], icon="Q")

        tk.Label(form_card, text="Datos principales", bg="#0b1730", fg="#f8fafc", font=("Segoe UI Semibold", 10)).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 10))
        self._make_input(form_card, 4, 0, "Nombre", self.vars["name"], icon="👤")
        self._make_input(form_card, 4, 1, "NIT", self.vars["nit"], icon="◫")
        self._make_input(form_card, 4, 2, "Teléfono", self.vars["phone"], icon="☎")
        self._make_input(form_card, 4, 3, "Teléfono secundario", self.vars["phone2"], icon="☎")
        self._make_input(form_card, 6, 0, "DPI", self.vars["dpi"], icon="🪪")
        self._make_input(form_card, 6, 1, "Email", self.vars["email"], icon="✉")
        self._make_input(form_card, 6, 2, "Departamento", self.vars["department"], icon="▾", kind="combo", values=self.DEPARTMENTS)
        self._make_input(form_card, 6, 3, "Descuento (%)", self.vars["discount"], icon="%")
        self._make_input(form_card, 8, 0, "Dirección", self.vars["address"], icon="⌖")
        self._make_input(form_card, 8, 1, "Dirección de envío", self.vars["shipping_address"], icon="⌘")
        self._make_input(form_card, 8, 2, "URL red social", self.vars["social_url"], icon="⌗")
        tk.Frame(form_card, bg="#0b1730").grid(row=8, column=3, sticky="nsew", padx=(7, 0))

        finance = self._mk_card(left, border="#27406a", bg="#0b1730", padx=18, pady=14)
        finance.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        finance.columnconfigure(0, weight=1)
        finance.columnconfigure(1, weight=1)
        head = tk.Frame(finance, bg="#0b1730")
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="☑  ESTADO FINANCIERO", bg="#0b1730", fg="#f8fafc", font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w")
        tk.Label(head, text="Los movimientos quedan vinculados a caja y reportes.", bg="#0b1730", fg="#8ea4c9", font=("Segoe UI", 9)).grid(row=0, column=1, sticky="e")

        self.fin_due_panel = self._create_amount_panel(finance, "Saldo a deber", "Q 0.00", "#ff5d6c", icon="↓")
        self.fin_due_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(12, 12))
        self.lbl_balance_due_value = self.fin_due_panel.value_label

        self.fin_favor_panel = self._create_amount_panel(finance, "Saldo a favor", "Q 0.00", "#27e48b", icon="↑")
        self.fin_favor_panel.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(12, 12))
        self.lbl_balance_favor_value = self.fin_favor_panel.value_label

        actions_fin = tk.Frame(finance, bg="#0b1730")
        actions_fin.grid(row=2, column=0, columnspan=2, sticky="ew")
        actions_fin.columnconfigure(0, weight=1)
        actions_fin.columnconfigure(1, weight=1)
        self.btn_client_due = tk.Button(actions_fin, text="▣  Abonar saldo a deber", command=lambda: self._open_balance_dialog("ABONO_A_DEUDA"), relief="flat", bd=0, font=("Segoe UI Semibold", 10), cursor="hand2", padx=14, pady=11, anchor="center")
        self.btn_client_due.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self._apply_hover_button(self.btn_client_due, "#d83a3a", "#bf2d2d")
        self.btn_client_favor = tk.Button(actions_fin, text="✚  Agregar saldo a favor", command=lambda: self._open_balance_dialog("RECARGA_SALDO_FAVOR"), relief="flat", bd=0, font=("Segoe UI Semibold", 10), cursor="hand2", padx=14, pady=11, anchor="center")
        self.btn_client_favor.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self._apply_hover_button(self.btn_client_favor, "#2f9e44", "#24803a")
        disable_button_if_denied(self.btn_client_due, 'Clientes', 'editar', 'abonar saldo a deber')
        disable_button_if_denied(self.btn_client_favor, 'Clientes', 'editar', 'agregar saldo a favor')

        notes_card = self._mk_card(left, border="#27406a", bg="#0b1730", padx=18, pady=14)
        notes_card.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        notes_card.columnconfigure(0, weight=1)
        tk.Label(notes_card, text="🗨  OBSERVACIONES", bg="#0b1730", fg="#f8fafc", font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.notes = tk.Text(notes_card, height=4, bg="#18253d", fg="#e5edf9", insertbackground="white", relief="flat", bd=0, highlightthickness=1, highlightbackground="#2d4672", highlightcolor="#4679ff", font=("Segoe UI", 10), padx=12, pady=10)
        self.notes.grid(row=1, column=0, sticky="ew")

        actions = tk.Frame(notes_card, bg="#0b1730")
        actions.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=2)
        actions.columnconfigure(2, weight=2)
        self.btn_client_new = tk.Button(actions, text="⟲  Nuevo", command=self.reset_form, relief="flat", bd=0, font=("Segoe UI Semibold", 10), cursor="hand2", padx=14, pady=11)
        self.btn_client_new.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self._apply_hover_button(self.btn_client_new, "#132b57", "#1a3970")
        self.btn_client_save = tk.Button(actions, text="🖫  Guardar / Actualizar", command=self.save_client, relief="flat", bd=0, font=("Segoe UI Semibold", 10), cursor="hand2", padx=14, pady=11)
        self.btn_client_save.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self._apply_hover_button(self.btn_client_save, "#3758e5", "#2646cf")
        self.btn_client_refresh = tk.Button(actions, text="⟳  Actualizar listado", command=self._load_rows, relief="flat", bd=0, font=("Segoe UI Semibold", 10), cursor="hand2", padx=14, pady=11)
        self.btn_client_refresh.grid(row=0, column=2, sticky="ew")
        self._apply_hover_button(self.btn_client_refresh, "#132b57", "#1a3970")
        disable_button_if_denied(self.btn_client_save, 'Clientes', 'crear', 'guardar cliente')

        right = tk.Frame(self, bg="#071631")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        stats = self._mk_card(right, padx=18, pady=16)
        stats.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        stats.columnconfigure(0, weight=1)
        self._section_head(stats, "👥", "RESUMEN CLIENTES")
        self.quick_total = tk.Label(stats, text="0 / 0 clientes", bg="#0b1730", fg="#f8fafc", font=("Segoe UI Semibold", 24))
        self.quick_total.grid(row=1, column=0, sticky="w", pady=(12, 2))
        tk.Label(stats, text="Doble click para editar. Búsqueda por nombre, NIT o teléfonos.", bg="#0b1730", fg="#8ea4c9", font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w")
        metrics = tk.Frame(stats, bg="#0b1730")
        metrics.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        for i in range(4):
            metrics.columnconfigure(i, weight=1)
        self.metric_active = self._create_metric_box(metrics, "Clientes activos", "0", "#818cf8", icon="●")
        self.metric_active.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.metric_credit = self._create_metric_box(metrics, "Crédito activo", "Q 0.00", "#fbbf24", icon="$")
        self.metric_credit.grid(row=0, column=1, sticky="ew", padx=8)
        self.metric_favor = self._create_metric_box(metrics, "Saldo a favor", "Q 0.00", "#27e48b", icon="✚")
        self.metric_favor.grid(row=0, column=2, sticky="ew", padx=8)
        self.metric_due = self._create_metric_box(metrics, "Saldo a deber", "Q 0.00", "#ff6674", icon="↓")
        self.metric_due.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        search_card = self._mk_card(right, padx=18, pady=16)
        search_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        search_card.columnconfigure(0, weight=1)
        self._section_head(search_card, "🔎", "BUSCAR CLIENTE")
        search_row = tk.Frame(search_card, bg="#0b1730")
        search_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        search_row.columnconfigure(1, weight=1)
        icon_box = tk.Frame(search_row, bg="#18253d", highlightthickness=1, highlightbackground="#2b4674")
        icon_box.grid(row=0, column=0, sticky="ns")
        tk.Label(icon_box, text="🔎", bg="#18253d", fg="#8eb7ff", font=("Segoe UI Symbol", 16)).pack(padx=12, pady=10)
        entry_box = tk.Frame(search_row, bg="#18253d", highlightthickness=1, highlightbackground="#2b4674")
        entry_box.grid(row=0, column=1, sticky="ew", padx=(10, 10))
        search_entry = tk.Entry(entry_box, textvariable=self.search_var, bg="#18253d", fg="#e5edf9", insertbackground="#f8fafc", relief="flat", bd=0, font=("Segoe UI", 10))
        search_entry.pack(fill="x", padx=12, pady=11)
        search_btn = tk.Button(search_row, text="⌕", command=self._load_rows, relief="flat", bd=0, font=("Segoe UI Semibold", 14), cursor="hand2", padx=15, pady=7)
        search_btn.grid(row=0, column=2, sticky="ns")
        self._apply_hover_button(search_btn, "#3256e8", "#2144d2")

        list_card = self._mk_card(right, padx=18, pady=16)
        list_card.grid(row=2, column=0, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)
        topbar = tk.Frame(list_card, bg="#0b1730")
        topbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        topbar.columnconfigure(0, weight=1)
        tk.Label(topbar, text="▣  LISTADO DE CLIENTES", bg="#0b1730", fg="#f8fafc", font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w")
        cols = ("name", "phone", "phone2", "nit", "credit", "due", "favor")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings", style="Clients.Treeview")
        headings = {"name": "Nombre", "phone": "Teléfono", "phone2": "Tel. 2", "nit": "NIT", "credit": "Crédito", "due": "Saldo deber", "favor": "Saldo favor"}
        widths = {"name": 220, "phone": 120, "phone2": 110, "nit": 100, "credit": 76, "due": 102, "favor": 102}
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w", stretch=(col == "name"))
        self.tree.grid(row=1, column=0, sticky="nsew")
        install_column_manager(list_card, self.tree, 'clientes_listado', row=0, column=0, sticky="e", pady=(0, 8))
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        scroll = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")

    def _ensure_client_styles(self):
        style = ttk.Style(self)
        try:
            style.configure("ClientDark.TCombobox",
                            fieldbackground="#18253d",
                            background="#18253d",
                            foreground="#e5edf9",
                            arrowcolor="#c9d6ef",
                            bordercolor="#2b4674",
                            lightcolor="#18253d",
                            darkcolor="#18253d",
                            padding=6)
            style.map("ClientDark.TCombobox",
                      fieldbackground=[("readonly", "#18253d")],
                      selectbackground=[("readonly", "#18253d")],
                      selectforeground=[("readonly", "#e5edf9")],
                      foreground=[("readonly", "#e5edf9")])
        except Exception:
            pass
        try:
            style.configure("ClientCheck.TCheckbutton", background="#18253d", foreground="#e5edf9", font=("Segoe UI", 10))
            style.map("ClientCheck.TCheckbutton", background=[("active", "#18253d")], foreground=[("disabled", "#6b7b99")])
        except Exception:
            pass
        try:
            style.configure("Clients.Treeview", background="#0b1c39", fieldbackground="#0b1c39", foreground="#ecf2ff", rowheight=38, borderwidth=0, relief="flat")
            style.configure("Clients.Treeview.Heading", background="#09162d", foreground="#f8fafc", font=("Segoe UI Semibold", 10), borderwidth=0, relief="flat")
            style.map("Clients.Treeview", background=[("selected", "#17305f")])
        except Exception:
            pass
        try:
            self.option_add("*TCombobox*Listbox.background", "#18253d")
            self.option_add("*TCombobox*Listbox.foreground", "#ecf2ff")
            self.option_add("*TCombobox*Listbox.selectBackground", "#3256e8")
        except Exception:
            pass

    def _mk_card(self, parent, bg="#0b1730", border="#24395f", padx=16, pady=16):
        return tk.Frame(parent, bg=bg, highlightbackground=border, highlightcolor=border, highlightthickness=1, bd=0, padx=padx, pady=pady)

    def _section_head(self, parent, icon, title):
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.grid(row=0, column=0, sticky="w")
        tk.Label(row, text=icon, bg=parent.cget("bg"), fg="#8eb7ff", font=("Segoe UI Symbol", 14)).pack(side="left", padx=(0, 8))
        tk.Label(row, text=title, bg=parent.cget("bg"), fg="#f8fafc", font=("Segoe UI Semibold", 11)).pack(side="left")

    def _make_input(self, parent, row, col, label, var, icon="", kind="entry", values=None, readonly=False):
        holder = tk.Frame(parent, bg="#0b1730")
        holder.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 7, 0), pady=(0, 12))
        tk.Label(holder, text=label, bg="#0b1730", fg="#f8fafc", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 6))
        box = tk.Frame(holder, bg="#18253d", highlightbackground="#2b4674", highlightcolor="#4679ff", highlightthickness=1, bd=0)
        box.pack(fill="x")
        if icon:
            tk.Label(box, text=icon, bg="#18253d", fg="#8ea4c9", font=("Segoe UI Symbol", 10)).pack(side="left", padx=(10, 6))
        widget = None
        if kind == "entry":
            widget = tk.Entry(box, textvariable=var, bg="#18253d", fg="#e5edf9", insertbackground="#f8fafc", relief="flat", bd=0, font=("Segoe UI", 10))
            if readonly:
                widget.configure(state="readonly", readonlybackground="#18253d")
            widget.pack(fill="x", padx=(0, 10), pady=9)
        elif kind == "combo":
            widget = ttk.Combobox(box, textvariable=var, values=values or [], state="readonly", style="ClientDark.TCombobox", font=("Segoe UI", 10))
            widget.pack(fill="x", padx=(0, 6), pady=4)
        elif kind == "check":
            widget = ttk.Checkbutton(box, text="Habilitar crédito", variable=var, style="ClientCheck.TCheckbutton")
            widget.pack(anchor="w", padx=(0, 10), pady=7)
        return widget

    def _create_metric_box(self, parent, title, value, accent="#3b82f6", icon="●"):
        box = tk.Frame(parent, bg="#17253d", highlightbackground=accent, highlightcolor=accent, highlightthickness=1, bd=0)
        top = tk.Frame(box, bg="#17253d")
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text=icon, bg="#17253d", fg=accent, font=("Segoe UI Symbol", 16)).pack(side="left", padx=(0, 10))
        title_wrap = tk.Frame(top, bg="#17253d")
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(title_wrap, text=title, bg="#17253d", fg="#d3def2", font=("Segoe UI", 9)).pack(anchor="w")
        value_label = tk.Label(title_wrap, text=value, bg="#17253d", fg=(accent if title != "Clientes activos" else "#f8fafc"), font=("Segoe UI Semibold", 16))
        value_label.pack(anchor="w", pady=(4, 0))
        box.value_label = value_label
        return box

    def _create_amount_panel(self, parent, title, value, accent, icon=""):
        panel = tk.Frame(parent, bg="#17253d", highlightbackground=accent, highlightcolor=accent, highlightthickness=1, bd=0)
        content = tk.Frame(panel, bg="#17253d")
        content.pack(fill="both", expand=True, padx=14, pady=12)
        left = tk.Frame(content, bg="#17253d")
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text=title, bg="#17253d", fg="#d3def2", font=("Segoe UI", 10)).pack(anchor="w")
        value_label = tk.Label(left, text=value, bg="#17253d", fg=accent, font=("Segoe UI Semibold", 21))
        value_label.pack(anchor="w", pady=(8, 0))
        if icon:
            tk.Label(content, text=icon, bg="#17253d", fg=accent, font=("Segoe UI Symbol", 26)).pack(side="right", padx=(12, 2), pady=(16, 0))
        panel.value_label = value_label
        return panel

    def _apply_hover_button(self, button, color, active):
        button.configure(bg=color, fg="white", activebackground=active, activeforeground="white")
        button.bind("<Enter>", lambda e: button.configure(bg=active) if str(button.cget("state")) != "disabled" else None)
        button.bind("<Leave>", lambda e: button.configure(bg=color) if str(button.cget("state")) != "disabled" else None)
        button._base_bg = color
        button._hover_bg = active

    def _next_client_code(self):
        conn = db_connect(); cur = conn.cursor(); cur.execute("SELECT id FROM clients ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close(); return f"CLI-{((row[0] + 1) if row else 1):05d}"

    def _refresh_balance_labels(self):
        due_value = f"Q {safe_float(self.vars['balance_due'].get()):.2f}"
        favor_value = f"Q {safe_float(self.vars['balance_favor'].get()):.2f}"
        self.lbl_balance_due_value.configure(text=due_value)
        self.lbl_balance_favor_value.configure(text=favor_value)
        if getattr(self, 'metric_due', None):
            self.metric_due.value_label.configure(text=due_value)
        if getattr(self, 'metric_favor', None):
            self.metric_favor.value_label.configure(text=favor_value)

    def reset_form(self):
        self.editing_client_id = None
        for key, var in self.vars.items():
            if key == "client_code":
                var.set(self._next_client_code())
            elif key == "department":
                var.set("Guatemala")
            elif key == "status":
                var.set("Activo")
            elif key == "allow_credit":
                var.set(False)
            elif key in {"discount", "credit_limit", "balance_favor", "balance_available", "balance_due"}:
                var.set("0.00")
            else:
                var.set("")
        self.notes.delete("1.0", tk.END)
        self._refresh_balance_labels()

    def _selected_client_code(self):
        sel = self.tree.selection()
        if not sel:
            return None
        item_id = sel[0]
        return self._row_client_codes.get(item_id)

    def _load_client_for_edit(self, client_code):
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id, client_code, name, nit, phone, COALESCE(phone2,''), COALESCE(dpi,''), email, address, shipping_address, department, social_url, discount, allow_credit, credit_limit, balance_favor, balance_available, balance_due, status, notes FROM clients WHERE client_code=?", (client_code,))
        row = cur.fetchone(); conn.close()
        if not row:
            return
        (self.editing_client_id, client_code, name, nit, phone, phone2, dpi, email, address, shipping_address, department, social_url, discount, allow_credit, credit_limit, balance_favor, balance_available, balance_due, status, notes) = row
        self.vars["client_code"].set(client_code or "")
        self.vars["name"].set(name or "")
        self.vars["nit"].set(nit or "")
        self.vars["phone"].set(phone or "")
        self.vars["phone2"].set(phone2 or "")
        self.vars["dpi"].set(dpi or "")
        self.vars["email"].set(email or "")
        self.vars["address"].set(address or "")
        self.vars["shipping_address"].set(shipping_address or "")
        self.vars["department"].set(department or "Guatemala")
        self.vars["social_url"].set(social_url or "")
        self.vars["discount"].set(f"{safe_float(discount):.2f}")
        self.vars["allow_credit"].set(bool(allow_credit))
        self.vars["credit_limit"].set(f"{safe_float(credit_limit):.2f}")
        self.vars["balance_favor"].set(f"{safe_float(balance_favor):.2f}")
        self.vars["balance_available"].set(f"{safe_float(balance_available):.2f}")
        self.vars["balance_due"].set(f"{safe_float(balance_due):.2f}")
        self.vars["status"].set(status or "Activo")
        self.notes.delete("1.0", tk.END)
        self.notes.insert("1.0", notes or "")
        self._refresh_balance_labels()

    def _on_tree_double_click(self, event=None):
        if not require_permission('Clientes', 'editar', self, 'editar cliente'):
            return
        client_code = self._selected_client_code()
        if client_code:
            self._load_client_for_edit(client_code)

    def save_client(self):
        needed = 'editar' if self.editing_client_id else 'crear'
        if not require_permission('Clientes', needed, self, 'guardar cliente'):
            return
        if not self.vars["name"].get().strip():
            messagebox.showwarning("Campo requerido", "Debes ingresar el nombre del cliente.")
            return
        conn = db_connect(); cur = conn.cursor()
        payload = (
            self.vars["client_code"].get().strip(),
            datetime.now().isoformat(timespec="seconds"),
            self.vars["name"].get().strip(),
            self.vars["nit"].get().strip(),
            self.vars["phone"].get().strip(),
            self.vars["phone2"].get().strip(),
            self.vars["dpi"].get().strip(),
            self.vars["email"].get().strip(),
            self.vars["address"].get().strip(),
            self.vars["shipping_address"].get().strip(),
            self.vars["department"].get().strip(),
            self.vars["social_url"].get().strip(),
            safe_float(self.vars["discount"].get()),
            1 if self.vars["allow_credit"].get() else 0,
            safe_float(self.vars["credit_limit"].get()),
            safe_float(self.vars["balance_favor"].get()),
            safe_float(self.vars["balance_available"].get()),
            safe_float(self.vars["balance_due"].get()),
            self.vars["status"].get().strip(),
            self.notes.get("1.0", tk.END).strip(),
        )
        if self.editing_client_id:
            cur.execute("""UPDATE clients SET client_code=?, name=?, nit=?, phone=?, phone2=?, dpi=?, email=?, address=?, shipping_address=?, department=?, social_url=?, discount=?, allow_credit=?, credit_limit=?, balance_favor=?, balance_available=?, balance_due=?, status=?, notes=? WHERE id=?""", payload[0:1] + payload[2:] + (self.editing_client_id,))
            msg = "Cliente actualizado correctamente."
        else:
            cur.execute("""INSERT INTO clients (client_code, created_at, name, nit, phone, phone2, dpi, email, address, shipping_address, department, social_url, discount, allow_credit, credit_limit, balance_favor, balance_available, balance_due, status, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", payload)
            msg = f"Cliente {self.vars['client_code'].get()} guardado correctamente."
        conn.commit(); conn.close()
        messagebox.showinfo("Guardado", msg)
        self.reset_form(); self._load_rows()

    def _open_balance_dialog(self, movement_kind):
        if not require_permission('Clientes', 'editar', self, 'movimientos de saldo del cliente'):
            return
        client_code = self.vars["client_code"].get().strip()
        client_name = self.vars["name"].get().strip()
        if not client_code or not client_name:
            messagebox.showwarning("Cliente requerido", "Primero selecciona o carga un cliente.")
            return

        PANEL = "#0b1f44"
        TEXT = "#ffffff"
        MUTED = "#b9c7e6"
        ACCENT = "#20c997"
        title_map = {
            "ABONO_A_DEUDA": "ABONO A SALDO",
            "RECARGA_SALDO_FAVOR": "SALDO A FAVOR",
        }
        subtitle_map = {
            "ABONO_A_DEUDA": "Registra un pago para bajar el saldo a deber del cliente",
            "RECARGA_SALDO_FAVOR": "Registra una recarga para aumentar el saldo a favor del cliente",
        }

        def _mix_hex(color_a, color_b, factor=0.5):
            try:
                a = color_a.lstrip('#')
                b = color_b.lstrip('#')
                ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
                br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
                r = int(ar + (br - ar) * factor)
                g = int(ag + (bg - ag) * factor)
                bl = int(ab + (bb - ab) * factor)
                return f"#{r:02x}{g:02x}{bl:02x}"
            except Exception:
                return color_a

        def _payment_method_label(key):
            labels = {
                'efectivo': 'Efectivo',
                'deposito': 'Depósito',
                'transferencia': 'Transferencia',
                'tarjeta': 'Tarjeta',
                'mixto': 'Mixto',
            }
            return labels.get(key, str(key).title())

        def _load_payment_icons():
            icons = {}
            icon_dir = Path(__file__).resolve().parent / 'assets' / 'payment'
            mapping = {
                'efectivo': 'efectivo.png',
                'deposito': 'deposito.png',
                'transferencia': 'transferencia.png',
                'tarjeta': 'tarjeta.png',
                'mixto': 'tarjeta.png',
            }
            for key, filename in mapping.items():
                path = icon_dir / filename
                if path.exists():
                    try:
                        icons[key] = tk.PhotoImage(file=str(path))
                    except Exception:
                        icons[key] = None
                else:
                    icons[key] = None
            return icons

        def _style_payment_button(btn, fill, border, selected=False):
            base_bg = _mix_hex(fill, '#0b1f44', 0.24) if not selected else _mix_hex(fill, '#ffffff', 0.07)
            hover_bg = _mix_hex(fill, '#ffffff', 0.24) if not selected else _mix_hex(fill, '#ffffff', 0.16)
            active_bg = _mix_hex(fill, '#000000', 0.18)
            edge = _mix_hex(border, '#ffffff', 0.56) if selected else _mix_hex(border, '#ffffff', 0.14)
            btn.configure(
                bg=base_bg,
                fg='#ffffff',
                activebackground=active_bg,
                activeforeground='#ffffff',
                relief='flat',
                bd=0,
                highlightthickness=4 if selected else 1,
                highlightbackground=edge,
                highlightcolor=edge,
                padx=10,
                pady=11,
                cursor='hand2',
                compound='left',
                anchor='center',
                font=('Segoe UI Semibold', 10, 'bold') if selected else ('Segoe UI Semibold', 10),
                width=1,
                wraplength=150,
            )
            btn._normal_bg = base_bg
            btn._hover_bg = hover_bg
            btn._active_bg = active_bg
            btn._edge = edge

        def _pick_image(path_var, apply_callback=None):
            chosen = filedialog.askopenfilename(
                title='Seleccionar imagen',
                filetypes=[('Imágenes', '*.png;*.jpg;*.jpeg;*.webp;*.bmp'), ('Todos los archivos', '*.*')],
                parent=win,
            )
            if chosen:
                path_var.set(chosen)
                if apply_callback:
                    apply_callback(chosen)

        def _window_state_store():
            return Path(__file__).resolve().parents[1] / 'data' / 'ui_window_state.json'

        def _load_window_states_local():
            try:
                return json.loads(_window_state_store().read_text(encoding='utf-8'))
            except Exception:
                return {}

        def _save_window_states_local(states):
            try:
                _window_state_store().parent.mkdir(parents=True, exist_ok=True)
                _window_state_store().write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                pass

        def _mini_toggle(parent, initial=False, command=None):
            holder = tk.Frame(parent, bg=PANEL)
            canvas = tk.Canvas(holder, width=52, height=24, bg=PANEL, highlightthickness=0, bd=0)
            canvas.pack()
            state = {'value': bool(initial)}
            def redraw():
                canvas.delete('all')
                on = state['value']
                track = '#1d4ed8' if on else '#324968'
                border = '#93c5fd' if on else '#8aa4d1'
                knob_x = 37 if on else 15
                canvas.create_rectangle(6, 3, 48, 21, outline=border, fill=track, width=1)
                canvas.create_oval(knob_x-10, 3, knob_x+10, 21, outline='#e5e7eb', fill='#f3f4f6', width=1)
            def pulse_saved():
                holder.configure(highlightthickness=2, highlightbackground='#22c55e', highlightcolor='#22c55e')
                holder.after(260, lambda: holder.configure(highlightthickness=0, highlightbackground=PANEL, highlightcolor=PANEL))
            def toggle(event=None):
                state['value'] = not state['value']
                redraw()
                if callable(command):
                    command(state['value'])
            for widget in (holder, canvas):
                widget.bind('<Button-1>', toggle)
                widget.configure(cursor='hand2')
            redraw()
            holder.get = lambda: state['value']
            holder.set = lambda value: (state.__setitem__('value', bool(value)), redraw(), callable(command) and command(state['value']))
            holder.pulse_saved = pulse_saved
            return holder

        def _attach_modal_header(modal, title_text, state_key=None):
            modal_key = state_key or title_text.lower()
            topbar = tk.Frame(modal, bg=PANEL)
            topbar.pack(fill='x', padx=16, pady=(10, 4))
            tk.Label(topbar, text=title_text, bg=PANEL, fg=TEXT, font=('Arial', 18, 'bold')).pack(side='left')
            right = tk.Frame(topbar, bg=PANEL)
            right.pack(side='right')
            hint_lbl = tk.Label(right, text='', bg=PANEL, fg='#86efac', font=('Segoe UI', 8, 'bold'))
            hint_lbl.pack(side='right', padx=(8, 0))
            tk.Label(right, text='Tamaño libre', bg=PANEL, fg=MUTED, font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
            states = _load_window_states_local()
            saved = states.get(modal_key, {}) if isinstance(states, dict) else {}
            if isinstance(saved, dict):
                w = saved.get('width'); h = saved.get('height'); x = saved.get('x'); y = saved.get('y')
                if all(isinstance(v, int) for v in (w, h, x, y)):
                    try:
                        modal.geometry(f'{w}x{h}+{x}+{y}')
                    except Exception:
                        pass
            state = {'free': False, 'feedback_job': None, 'closing': False}
            def _persist_geometry(show_feedback=False):
                try:
                    modal.update_idletasks()
                    current = {
                        'width': modal.winfo_width(),
                        'height': modal.winfo_height(),
                        'x': modal.winfo_x(),
                        'y': modal.winfo_y(),
                    }
                    states_now = _load_window_states_local()
                    if not isinstance(states_now, dict):
                        states_now = {}
                    previous = states_now.get(modal_key)
                    if previous != current:
                        states_now[modal_key] = current
                        _save_window_states_local(states_now)
                except Exception:
                    pass
                if show_feedback:
                    try:
                        hint_lbl.configure(text='Guardado')
                        if state['feedback_job']:
                            modal.after_cancel(state['feedback_job'])
                        state['feedback_job'] = modal.after(1400, lambda: hint_lbl.configure(text=''))
                    except Exception:
                        pass
                    try:
                        switch.pulse_saved()
                    except Exception:
                        pass
            def persist_and_feedback():
                _persist_geometry(show_feedback=True)
            def on_toggle(is_on):
                state['free'] = bool(is_on)
                try:
                    modal.resizable(state['free'], state['free'])
                except Exception:
                    pass
                # Evita congelamientos por bucles de <Configure> en modales compartidos.
                # El tamaño se guarda al activar/desactivar, al guardar datos y al cerrar.
                persist_and_feedback()
            switch = _mini_toggle(right, initial=False, command=on_toggle)
            switch.pack(side='left')
            modal._header_save_feedback = persist_and_feedback
            def _on_modal_close():
                state['closing'] = True
                _persist_geometry(show_feedback=False)
                try:
                    modal.destroy()
                except Exception:
                    pass
            modal.protocol('WM_DELETE_WINDOW', _on_modal_close)
            return topbar

        def _small_field(parent, label_text, width=26, placeholder=''):
            wrap = tk.Frame(parent, bg=PANEL)
            tk.Label(wrap, text=label_text, bg=PANEL, fg=MUTED, font=('Segoe UI', 10, 'bold')).pack(anchor='center', pady=(2, 6), padx=8)
            inner = tk.Frame(wrap, bg='#f8fafc', highlightthickness=1, highlightbackground='#d6deef')
            inner.pack(anchor='center', padx=8, pady=(0, 2))
            entry = tk.Entry(inner, width=width, justify='left', relief='flat', bd=0, font=('Segoe UI', 10), bg='#f8fafc', fg='#0f172a', insertbackground='#0f172a')
            entry.pack(anchor='center', padx=12, pady=7, ipady=1)
            if placeholder:
                entry.insert(0, placeholder)
                entry.configure(fg='#64748b')
                def _clear_placeholder(event=None):
                    if entry.get().strip() == placeholder and entry.cget('fg') == '#64748b':
                        entry.delete(0, 'end')
                        entry.configure(fg='#0f172a')
                def _restore_placeholder(event=None):
                    if not entry.get().strip():
                        entry.delete(0, 'end')
                        entry.insert(0, placeholder)
                        entry.configure(fg='#64748b')
                entry.bind('<FocusIn>', _clear_placeholder)
                entry.bind('<FocusOut>', _restore_placeholder)
            return wrap, entry

        def _small_file(parent, label_text):
            wrap = tk.Frame(parent, bg=PANEL)
            tk.Label(wrap, text=label_text, bg=PANEL, fg=MUTED, font=('Segoe UI', 10, 'bold')).pack(anchor='center', pady=(2, 6), padx=8)
            var = tk.StringVar(value='')
            card = tk.Frame(wrap, bg='#0b1f3a', highlightthickness=1, highlightbackground='#233f67')
            card.pack(anchor='center', padx=10, pady=(0, 8))
            status_row = tk.Frame(card, bg='#0b1f3a')
            status_row.pack(fill='x', padx=10, pady=(10, 6))
            status_chip = tk.Label(status_row, text='Sin fotografía', bg='#173768', fg='#dbe7ff', font=('Segoe UI', 8, 'bold'), padx=10, pady=4)
            status_chip.pack(side='left')
            remove_btn = tk.Button(status_row, text='🗑', bg='#7f1d1d', fg='#ffffff', relief='flat', bd=0, font=('Segoe UI Emoji', 10), padx=8, pady=3, cursor='hand2')
            remove_btn.pack(side='right')
            pick_area = tk.Frame(card, bg='#10294d', highlightthickness=2, highlightbackground='#4a658d', width=248, height=188, cursor='hand2')
            pick_area.pack_propagate(False)
            pick_area.pack(anchor='center', padx=10, pady=(0, 10))
            preview_wrap = tk.Frame(pick_area, bg='#10294d')
            preview_wrap.place(relx=0.5, rely=0.42, anchor='center')
            preview_lbl = tk.Label(preview_wrap, bg='#10294d')
            preview_lbl.pack(pady=(0, 8))
            icon_lbl = tk.Label(preview_wrap, text='📷', bg='#10294d', fg='#dbe7ff', font=('Segoe UI Emoji', 24))
            icon_lbl.pack()
            shown = tk.Label(preview_wrap, text='Haz clic para adjuntar la fotografía', bg='#10294d', fg=TEXT, width=24, wraplength=196, justify='center', font=('Segoe UI', 10, 'bold'))
            shown.pack(padx=12, pady=(8, 2))
            hint_lbl = tk.Label(preview_wrap, text='Formatos permitidos: PNG, JPG, WEBP o BMP', bg='#10294d', fg='#8fb7ff', wraplength=198, justify='center', font=('Segoe UI', 8))
            hint_lbl.pack(padx=12, pady=(0, 0))
            footer_bar = tk.Frame(pick_area, bg='#0d223f', height=34)
            footer_bar.pack(side='bottom', fill='x')
            footer_bar.pack_propagate(False)
            ready_lbl = tk.Label(footer_bar, text='○ Sin fotografía', bg='#0d223f', fg='#c7d7f7', font=('Segoe UI', 8, 'bold'))
            ready_lbl.pack(side='left', padx=10, pady=7)
            change_btn = tk.Button(footer_bar, text='Adjuntar fotografía', bg='#2563eb', fg=TEXT, relief='flat', bd=0, font=('Segoe UI', 9, 'bold'), padx=12, pady=5, cursor='hand2')
            change_btn.pack(side='right', padx=8, pady=4)
            pick_area._preview_ref = None

            def _set_area_style(mode='normal'):
                if mode == 'hover':
                    card_bg, area_bg, border_bg, chip_bg = '#0d2444', '#14345f', '#7dd3fc', '#1d4ed8'
                elif mode == 'loaded':
                    card_bg, area_bg, border_bg, chip_bg = '#0b1f3a', '#10294d', '#60a5fa', '#166534'
                else:
                    card_bg, area_bg, border_bg, chip_bg = '#0b1f3a', '#10294d', '#4a658d', '#173768'
                card.configure(bg=card_bg, highlightbackground='#233f67')
                status_row.configure(bg=card_bg)
                status_chip.configure(bg=chip_bg)
                pick_area.configure(bg=area_bg, highlightbackground=border_bg)
                preview_wrap.configure(bg=area_bg)
                preview_lbl.configure(bg=area_bg)
                icon_lbl.configure(bg=area_bg)
                shown.configure(bg=area_bg)
                hint_lbl.configure(bg=area_bg)

            def _apply(path=''):
                path = str(path or '').strip()
                if path and os.path.exists(path):
                    var.set(path)
                    status_chip.configure(text='Fotografía cargada', fg='#dcfce7')
                    ready_lbl.configure(text='✔ Fotografía lista', fg='#dcfce7')
                    shown.configure(text=os.path.basename(path), fg='#ffffff')
                    hint_lbl.configure(text='Haz clic en cambiar fotografía para reemplazarla', fg='#a5d8ff')
                    change_btn.configure(text='Cambiar fotografía')
                    _set_area_style('loaded')
                    img_ref = None
                    if Image is not None and ImageTk is not None:
                        try:
                            img = Image.open(path).convert('RGBA')
                            img.thumbnail((152, 88))
                            img_ref = ImageTk.PhotoImage(img)
                        except Exception:
                            img_ref = None
                    pick_area._preview_ref = img_ref
                    if img_ref is not None:
                        preview_lbl.configure(image=img_ref, text='')
                        if icon_lbl.winfo_manager():
                            icon_lbl.pack_forget()
                    else:
                        preview_lbl.configure(image='', text='')
                        if not icon_lbl.winfo_manager():
                            icon_lbl.pack()
                else:
                    var.set('')
                    status_chip.configure(text='Sin fotografía', fg='#dbe7ff')
                    ready_lbl.configure(text='○ Sin fotografía', fg='#c7d7f7')
                    shown.configure(text='Haz clic para adjuntar la fotografía', fg=TEXT)
                    hint_lbl.configure(text='Formatos permitidos: PNG, JPG, WEBP o BMP', fg='#8fb7ff')
                    change_btn.configure(text='Adjuntar fotografía')
                    _set_area_style('normal')
                    pick_area._preview_ref = None
                    preview_lbl.configure(image='', text='')
                    if not icon_lbl.winfo_manager():
                        icon_lbl.pack()

            def _open_picker(event=None):
                _pick_image(var, _apply)

            def _hover_on(event=None):
                _set_area_style('loaded' if var.get().strip() else 'hover')
            def _hover_off(event=None):
                _set_area_style('loaded' if var.get().strip() else 'normal')

            for widget in (pick_area, preview_wrap, preview_lbl, icon_lbl, shown, hint_lbl, footer_bar, ready_lbl):
                widget.bind('<Button-1>', _open_picker, add='+')
                widget.bind('<Enter>', _hover_on, add='+')
                widget.bind('<Leave>', _hover_off, add='+')
            change_btn.configure(command=_open_picker)
            remove_btn.configure(command=lambda: _apply(''))
            return wrap, var

        win = tk.Toplevel(self)
        win.title('Pago')
        win.configure(bg=PANEL)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        try:
            width, height = 760, 620
            sw = win.winfo_screenwidth(); sh = win.winfo_screenheight()
            x = max(0, (sw - width) // 2); y = max(0, (sh - height) // 2)
            win.geometry(f'{width}x{height}+{x}+{y}')
            win.minsize(740, 600)
            win.resizable(False, False)
        except Exception:
            win.geometry('760x620')

        vars_m = {
            'amount': tk.StringVar(value='0.00'),
            'reference': tk.StringVar(),
            'authorization_no': tk.StringVar(),
            'card_last4': tk.StringVar(),
            'support_photo': tk.StringVar(),
            'dpi_photo': tk.StringVar(),
        }
        notes_var = tk.StringVar()
        metodo_var = tk.StringVar(value='efectivo')
        datos_pago = {'metodo': 'efectivo'}
        payment_icons = _load_payment_icons()
        win._payment_icons = payment_icons

        def current_user_label():
            shown_name = SESSION_FULL_NAME or SESSION_USER or 'ADMIN'
            return str(shown_name).upper()

        tk.Label(win, text=title_map.get(movement_kind, 'MOVIMIENTO DE SALDO'), bg=PANEL, fg=TEXT, font=('Arial', 20, 'bold')).pack(pady=(16, 4))
        tk.Label(win, text=f'Cliente: {client_name}', bg=PANEL, fg=TEXT, font=('Arial', 12, 'bold')).pack()
        tk.Label(win, text=f'Usuario: {current_user_label()}', bg=PANEL, fg=MUTED, font=('Arial', 11)).pack(pady=(0, 6))
        tk.Label(win, text='TOTAL', bg=PANEL, fg=TEXT, font=('Arial', 16, 'bold')).pack(pady=(8, 0))
        amount_entry = tk.Entry(win, textvariable=vars_m['amount'], width=12, justify='center', font=('Arial', 28, 'bold'), relief='flat', bd=0, bg=PANEL, fg=ACCENT, insertbackground=ACCENT)
        amount_entry.pack(pady=(2, 0), ipady=2)
        amount_entry._cleared_once = False
        def _clear_amount_zero(event=None):
            current = vars_m['amount'].get().strip()
            if current in ('0', '0.0', '0.00', 'Q0.00', 'Q 0.00'):
                amount_entry.delete(0, 'end')
                vars_m['amount'].set('')
                amount_entry._cleared_once = True
        amount_entry.bind('<FocusIn>', _clear_amount_zero, add='+')
        amount_entry.bind('<Button-1>', lambda e: amount_entry.after(1, _clear_amount_zero), add='+')
        def _on_amount_keypress(event):
            if event.keysym in ('Tab', 'Return', 'BackSpace', 'Delete', 'Left', 'Right', 'Home', 'End'): return
            if event.char and (event.char.isdigit() or event.char == '.'):
                _clear_amount_zero()
        amount_entry.bind('<KeyPress>', _on_amount_keypress, add='+')
        amount_entry.bind('<FocusOut>', lambda e: (not vars_m['amount'].get().strip()) and vars_m['amount'].set('0.00'), add='+')
        tk.Label(win, text='REFERENCIA / NOTAS', bg=PANEL, fg=TEXT, font=('Arial', 14, 'bold')).pack(pady=(8, 0))
        status_var = tk.StringVar(value=subtitle_map.get(movement_kind, ''))
        tk.Label(win, textvariable=status_var, bg=PANEL, fg=MUTED, font=('Arial', 11)).pack(pady=(0, 10))

        selector = tk.Frame(win, bg=PANEL)
        selector.pack(fill='x', padx=34, pady=(6, 10))
        tk.Label(selector, text='Método de pago', bg=PANEL, fg=TEXT, font=('Arial', 12, 'bold')).pack()
        btns = tk.Frame(selector, bg=PANEL)
        btns.pack(fill='x', pady=8)
        metodo_info_var = tk.StringVar(value='Método seleccionado: Efectivo')
        metodo_info = tk.Label(selector, textvariable=metodo_info_var, bg='#102750', fg='#86efac', font=('Segoe UI', 9, 'bold'), padx=12, pady=7)
        metodo_info.pack(pady=(0, 2))

        cash_slot = tk.Frame(win, bg=PANEL)
        cash_slot.pack(pady=(0, 6))
        cash_wrap = tk.Frame(cash_slot, bg=PANEL)
        tk.Label(cash_wrap, text='Referencia', bg=PANEL, fg=MUTED, font=('Arial', 11, 'bold')).pack()
        ref_entry = tk.Entry(cash_wrap, textvariable=vars_m['reference'], width=22, justify='center', font=('Arial', 13), relief='flat', bd=0)
        ref_entry.pack(pady=(6, 0), ipady=6)
        cash_wrap.pack()

        notes_wrap = tk.Frame(win, bg=PANEL)
        notes_wrap.pack(pady=(0, 8))
        tk.Label(notes_wrap, text='Notas', bg=PANEL, fg=MUTED, font=('Arial', 11, 'bold')).pack()
        note_entry = tk.Entry(notes_wrap, textvariable=notes_var, width=36, justify='center', font=('Arial', 12), relief='flat', bd=0)
        note_entry.pack(pady=(6, 0), ipady=5)

        def _show_cash_wrap():
            try:
                if not cash_slot.winfo_ismapped():
                    cash_slot.pack(pady=(0, 6), before=notes_wrap)
            except Exception:
                cash_slot.pack(pady=(0, 6), before=notes_wrap)

        def _hide_cash_wrap():
            try:
                cash_slot.pack_forget()
            except Exception:
                pass

        def _open_method_modal(m, target='primary'):
            modal = tk.Toplevel(win)
            modal.configure(bg=PANEL)
            modal.transient(win)
            modal.grab_set()
            try:
                mw, mh = (600, 720) if m == 'deposito' else (600, 740) if m == 'transferencia' else (820, 780) if m == 'tarjeta' else (520, 420)
                sw = modal.winfo_screenwidth(); sh = modal.winfo_screenheight()
                modal.geometry(f'{mw}x{mh}+{max(0,(sw-mw)//2)}+{max(0,(sh-mh)//2)}')
            except Exception:
                modal.geometry('660x540')
            try:
                modal.resizable(False, False)
            except Exception:
                pass

            if m == 'deposito':
                modal.title('Datos de depósito')
                _attach_modal_header(modal, 'DEPÓSITO')
                tk.Label(modal, text='Completa los datos del depósito y adjunta la fotografía del comprobante para validar el pago', bg=PANEL, fg=MUTED, font=('Arial', 10)).pack(pady=(0, 8))
                banco_box, banco = _small_field(modal, 'Banco', width=20, placeholder='Ej. Banco Industrial'); banco_box.pack(pady=2)
                boleta_box, boleta = _small_field(modal, 'Número de boleta o referencia', width=20, placeholder='Ej. DEP45821'); boleta_box.pack(pady=2)
                comp_box, comp = _small_file(modal, 'Fotografía del comprobante'); comp_box.pack(pady=(0, 2))
                def guardar():
                    banco_txt = banco.get().strip(); boleta_txt = boleta.get().strip(); comp_txt = comp.get().strip()
                    if banco_txt.startswith('Ej. '): banco_txt = ''
                    if boleta_txt.startswith('Ej. '): boleta_txt = ''
                    if banco_txt and len(banco_txt) > 25:
                        messagebox.showerror('Depósito', 'Banco: máximo 25 caracteres.', parent=modal); return
                    if boleta_txt and len(boleta_txt) > 10:
                        messagebox.showerror('Depósito', 'Boleta o referencia: máximo 10 caracteres.', parent=modal); return
                    if target == 'primary':
                        datos_pago.update({'metodo':'deposito','banco':banco_txt,'boleta':boleta_txt,'comprobante':comp_txt})
                        vars_m['reference'].set(boleta_txt); vars_m['support_photo'].set(comp_txt)
                    else:
                        datos_pago[f'{target}_support'] = {'metodo':'deposito','banco':banco_txt,'referencia':boleta_txt,'comprobante':comp_txt}
                    if hasattr(modal, '_header_save_feedback'): modal._header_save_feedback()
                    modal.after(220, modal.destroy)
                footer = tk.Frame(modal, bg=PANEL); footer.pack(fill='x', padx=18, pady=(10, 14))
                tk.Button(footer, text='💾 Guardar datos', command=guardar, bg=ACCENT, fg='white', relief='flat', bd=0, font=('Segoe UI', 11, 'bold'), padx=18, pady=11, width=26).pack(anchor='center', pady=(0, 10))
                actions = tk.Frame(footer, bg=PANEL); actions.pack(anchor='center')
                tk.Button(actions, text='Cancelar', command=modal.destroy, bg='#475569', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=14).pack(side='left', padx=(0, 8))
                tk.Button(actions, text='Quitar', command=lambda:[comp.set(''), modal.destroy()], bg='#991b1b', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=14).pack(side='left')
            elif m == 'transferencia':
                modal.title('Datos de transferencia')
                _attach_modal_header(modal, 'TRANSFERENCIA')
                tk.Label(modal, text='Completa banco, referencia, depositante y adjunta la fotografía del comprobante para validar el pago', bg=PANEL, fg=MUTED, font=('Arial', 10)).pack(pady=(0, 8))
                banco_box, banco = _small_field(modal, 'Banco', width=20, placeholder='Ej. Banco Industrial'); banco_box.pack(pady=2)
                ref_box, ref = _small_field(modal, 'Referencia', width=20, placeholder='Ej. TRF875421'); ref_box.pack(pady=2)
                dep_box, dep = _small_field(modal, 'Nombre del depositante', width=20, placeholder='Ej. Juan Pérez'); dep_box.pack(pady=2)
                comp_box, comp = _small_file(modal, 'Fotografía del comprobante'); comp_box.pack(pady=(0, 2))
                def guardar():
                    banco_txt = banco.get().strip(); ref_txt = ref.get().strip(); dep_txt = dep.get().strip(); comp_txt = comp.get().strip()
                    if banco_txt.startswith('Ej. '): banco_txt = ''
                    if ref_txt.startswith('Ej. '): ref_txt = ''
                    if dep_txt.startswith('Ej. '): dep_txt = ''
                    if banco_txt and len(banco_txt) > 25:
                        messagebox.showerror('Transferencia', 'Banco: máximo 25 caracteres.', parent=modal); return
                    if ref_txt and len(ref_txt) > 10:
                        messagebox.showerror('Transferencia', 'Referencia: máximo 10 caracteres.', parent=modal); return
                    if target == 'primary':
                        datos_pago.update({'metodo':'transferencia','banco':banco_txt,'referencia':ref_txt,'depositante':dep_txt,'comprobante':comp_txt})
                        vars_m['reference'].set(ref_txt); vars_m['support_photo'].set(comp_txt)
                    else:
                        datos_pago[f'{target}_support'] = {'metodo':'transferencia','banco':banco_txt,'referencia':ref_txt,'depositante':dep_txt,'comprobante':comp_txt}
                    if hasattr(modal, '_header_save_feedback'): modal._header_save_feedback()
                    modal.after(220, modal.destroy)
                footer = tk.Frame(modal, bg=PANEL); footer.pack(fill='x', padx=18, pady=(10, 14))
                tk.Button(footer, text='💾 Guardar datos', command=guardar, bg=ACCENT, fg='white', relief='flat', bd=0, font=('Segoe UI', 11, 'bold'), padx=18, pady=11, width=26).pack(anchor='center', pady=(0, 10))
                actions = tk.Frame(footer, bg=PANEL); actions.pack(anchor='center')
                tk.Button(actions, text='Cancelar', command=modal.destroy, bg='#475569', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=14).pack(side='left', padx=(0, 8))
                tk.Button(actions, text='Quitar', command=lambda:[comp.set(''), modal.destroy()], bg='#991b1b', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=14).pack(side='left')
            elif m == 'tarjeta':
                modal.title('Datos de tarjeta')
                _attach_modal_header(modal, 'TARJETA')
                tk.Label(modal, text='Completa los datos y adjunta fotografía de la tarjeta y del DPI para respaldo de la operación', bg=PANEL, fg=MUTED, font=('Arial', 10)).pack(pady=(0, 6))
                body = tk.Frame(modal, bg=PANEL); body.pack(fill='both', expand=True, padx=18, pady=6)
                body.columnconfigure(0, weight=1); body.columnconfigure(1, weight=1)
                tipo_box = tk.Frame(body, bg=PANEL); tipo_box.grid(row=0, column=0, sticky='nsew', padx=8, pady=4)
                tk.Label(tipo_box, text='Tipo', bg=PANEL, fg=MUTED, font=('Segoe UI', 10, 'bold')).pack(anchor='center', pady=(2, 6), padx=10)
                tipo_var = tk.StringVar(value='Débito')
                tipo_buttons = tk.Frame(tipo_box, bg=PANEL); tipo_buttons.pack(anchor='center')
                btn_debito = tk.Button(tipo_buttons, text='Débito', bg='#2563eb', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), width=10, pady=7)
                btn_credito = tk.Button(tipo_buttons, text='Crédito', bg='#1e3a5f', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), width=10, pady=7)
                btn_debito.pack(side='left', padx=(0, 6)); btn_credito.pack(side='left')
                def _set_tipo(value):
                    tipo_var.set(value)
                    btn_debito.configure(bg='#2563eb' if value == 'Débito' else '#1e3a5f')
                    btn_credito.configure(bg='#2563eb' if value == 'Crédito' else '#1e3a5f')
                btn_debito.configure(command=lambda:_set_tipo('Débito'))
                btn_credito.configure(command=lambda:_set_tipo('Crédito'))
                banco_box, banco = _small_field(body, 'Banco emisor', width=18, placeholder='Ej. Banco Industrial'); banco_box.grid(row=0, column=1, sticky='nsew', padx=8, pady=4)
                ult4_box, ult4 = _small_field(body, 'Últimos 4 dígitos', width=12, placeholder='Ej. 1234'); ult4_box.grid(row=1, column=0, sticky='nsew', padx=8, pady=4)
                auto_box, auto = _small_field(body, 'Número de autorización', width=14, placeholder='Ej. 987654'); auto_box.grid(row=1, column=1, sticky='nsew', padx=8, pady=4)
                foto_t_box, foto_t = _small_file(body, 'Fotografía de la tarjeta'); foto_t_box.grid(row=2, column=0, sticky='nsew', padx=8, pady=4)
                foto_d_box, foto_d = _small_file(body, 'Fotografía del DPI'); foto_d_box.grid(row=2, column=1, sticky='nsew', padx=8, pady=4)
                def guardar():
                    banco_txt = banco.get().strip(); ult4_txt = ult4.get().strip(); auto_txt = auto.get().strip(); foto_t_txt = foto_t.get().strip(); foto_d_txt = foto_d.get().strip()
                    if banco_txt.startswith('Ej. '): banco_txt = ''
                    if ult4_txt.startswith('Ej. '): ult4_txt = ''
                    if auto_txt.startswith('Ej. '): auto_txt = ''
                    if banco_txt and len(banco_txt) > 25:
                        messagebox.showerror('Tarjeta', 'Banco emisor: máximo 25 caracteres.', parent=modal); return
                    if ult4_txt and (len(ult4_txt) != 4 or not ult4_txt.isdigit()):
                        messagebox.showerror('Tarjeta', 'Últimos 4 dígitos: deben ser exactamente 4 números.', parent=modal); return
                    if auto_txt and len(auto_txt) > 10:
                        messagebox.showerror('Tarjeta', 'Número de autorización: máximo 10 caracteres.', parent=modal); return
                    if target == 'primary':
                        datos_pago.update({'metodo':'tarjeta','tipo':tipo_var.get().strip(),'banco':banco_txt,'ultimos4':ult4_txt,'autorizacion':auto_txt,'foto_tarjeta':foto_t_txt,'foto_dpi':foto_d_txt})
                        vars_m['authorization_no'].set(auto_txt); vars_m['card_last4'].set(ult4_txt); vars_m['support_photo'].set(foto_t_txt); vars_m['dpi_photo'].set(foto_d_txt)
                    else:
                        datos_pago[f'{target}_support'] = {'metodo':'tarjeta','tipo':tipo_var.get().strip(),'banco':banco_txt,'ultimos4':ult4_txt,'autorizacion':auto_txt,'foto_tarjeta':foto_t_txt,'foto_dpi':foto_d_txt}
                    if hasattr(modal, '_header_save_feedback'): modal._header_save_feedback()
                    modal.after(220, modal.destroy)
                footer = tk.Frame(modal, bg=PANEL); footer.pack(fill='x', padx=18, pady=(8, 14))
                tk.Button(footer, text='💾 Guardar datos', command=guardar, bg=ACCENT, fg='white', relief='flat', bd=0, font=('Segoe UI', 11, 'bold'), padx=18, pady=11, width=30).pack(anchor='center', pady=(0, 10))
                actions = tk.Frame(footer, bg=PANEL); actions.pack(anchor='center')
                tk.Button(actions, text='Cancelar', command=modal.destroy, bg='#475569', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=16).pack(side='left', padx=(0, 8))
                tk.Button(actions, text='Quitar', command=lambda:[foto_t.set(''), foto_d.set(''), modal.destroy()], bg='#991b1b', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=16).pack(side='left')
            else:
                modal.title('Pago mixto')
                _attach_modal_header(modal, 'MIXTO')
                tk.Label(modal, text='Divide el monto entre dos métodos de pago', bg=PANEL, fg=MUTED, font=('Arial', 10)).pack(pady=(0, 10))
                body = tk.Frame(modal, bg=PANEL); body.pack(fill='both', expand=True, padx=20, pady=8)
                opts = ['efectivo', 'deposito', 'transferencia', 'tarjeta']
                m1_box, m1_amount = _small_field(body, 'Monto método 1', width=14, placeholder='Ej. 50.00'); m1_box.pack(pady=4)
                method1 = ttk.Combobox(body, values=[_payment_method_label(x) for x in opts], state='readonly', width=20, justify='center'); method1.pack(pady=(0, 10)); method1.set('Efectivo')
                m2_box, m2_amount = _small_field(body, 'Monto método 2', width=14, placeholder='Ej. 25.00'); m2_box.pack(pady=4)
                method2 = ttk.Combobox(body, values=[_payment_method_label(x) for x in opts], state='readonly', width=20, justify='center'); method2.pack(pady=(0, 10)); method2.set('Tarjeta')
                ref_mix_box, ref_mix = _small_field(body, 'Detalle / referencia', width=24, placeholder='Ej. Efectivo + Transferencia'); ref_mix_box.pack(pady=4)
                support_row = tk.Frame(body, bg=PANEL); support_row.pack(pady=(8, 4))
                support1_btn = tk.Button(support_row, text='Soporte método 1', bg='#1d4ed8', fg='white', relief='flat', bd=0, font=('Segoe UI', 9, 'bold'), padx=12, pady=7, cursor='hand2')
                support1_btn.pack(side='left', padx=(0, 8))
                support2_btn = tk.Button(support_row, text='Soporte método 2', bg='#1d4ed8', fg='white', relief='flat', bd=0, font=('Segoe UI', 9, 'bold'), padx=12, pady=7, cursor='hand2')
                support2_btn.pack(side='left')
                support_hint = tk.Label(body, text='Abre soporte cuando uses depósito, transferencia o tarjeta.', bg=PANEL, fg=MUTED, font=('Segoe UI', 8, 'bold'))
                support_hint.pack(pady=(0, 2))
                def _raw_from_combo(combo_value):
                    labels = [_payment_method_label(x) for x in opts]
                    return opts[labels.index(combo_value)]
                def _update_support_buttons(*args):
                    for btn, raw, slot in ((support1_btn, _raw_from_combo(method1.get()), 'mix_1'), (support2_btn, _raw_from_combo(method2.get()), 'mix_2')):
                        requires = raw in ('deposito', 'transferencia', 'tarjeta')
                        saved = bool(datos_pago.get(f'{slot}_support'))
                        btn.configure(state=('normal' if requires else 'disabled'), bg=('#16a34a' if saved else '#1d4ed8'))
                support1_btn.configure(command=lambda: (_open_method_modal(_raw_from_combo(method1.get()), target='mix_1'), _update_support_buttons()))
                support2_btn.configure(command=lambda: (_open_method_modal(_raw_from_combo(method2.get()), target='mix_2'), _update_support_buttons()))
                method1.bind('<<ComboboxSelected>>', lambda e: _update_support_buttons(), add='+')
                method2.bind('<<ComboboxSelected>>', lambda e: _update_support_buttons(), add='+')
                _update_support_buttons()
                def guardar():
                    try:
                        a1 = safe_float(m1_amount.get().replace('Ej. ', ''))
                        a2 = safe_float(m2_amount.get().replace('Ej. ', ''))
                    except Exception:
                        a1 = a2 = 0.0
                    if a1 <= 0 or a2 <= 0:
                        messagebox.showerror('Mixto', 'Debes ingresar ambos montos.', parent=modal); return
                    total_mix = round(a1 + a2, 2)
                    current_amount = round(safe_float(vars_m['amount'].get()), 2)
                    if current_amount > 0 and abs(total_mix - current_amount) > 0.009:
                        messagebox.showerror('Mixto', f'La suma de ambos métodos debe ser Q{current_amount:.2f}.', parent=modal); return
                    raw1 = _raw_from_combo(method1.get())
                    raw2 = _raw_from_combo(method2.get())
                    for raw, slot in ((raw1, 'mix_1'), (raw2, 'mix_2')):
                        if raw in ('deposito', 'transferencia', 'tarjeta') and not datos_pago.get(f'{slot}_support'):
                            messagebox.showerror('Mixto', f'Debes cargar el soporte del {_payment_method_label(raw)} en {slot.replace('_', ' método ')}.', parent=modal); return
                    datos_pago.update({'metodo':'mixto','mix_1_method':raw1,'mix_1_amount':a1,'mix_2_method':raw2,'mix_2_amount':a2,'mix_detail':ref_mix.get().replace('Ej. ', '').strip()})
                    refs = []
                    photos = []
                    for slot in ('mix_1', 'mix_2'):
                        support = datos_pago.get(f'{slot}_support') or {}
                        ref_val = str(support.get('referencia', support.get('autorizacion', ''))).strip()
                        if ref_val: refs.append(f"{slot[-1]}:{ref_val}")
                        photo_val = str(support.get('comprobante', support.get('foto_tarjeta', ''))).strip()
                        if photo_val: photos.append(photo_val)
                    vars_m['reference'].set(ref_mix.get().replace('Ej. ', '').strip() or ' | '.join(refs))
                    vars_m['support_photo'].set(' | '.join(photos))
                    if hasattr(modal, '_header_save_feedback'): modal._header_save_feedback()
                    modal.after(220, modal.destroy)
                footer = tk.Frame(modal, bg=PANEL); footer.pack(fill='x', padx=18, pady=(8, 14))
                tk.Button(footer, text='💾 Guardar datos', command=guardar, bg=ACCENT, fg='white', relief='flat', bd=0, font=('Segoe UI', 11, 'bold'), padx=18, pady=11, width=24).pack(anchor='center', pady=(0, 10))
                actions = tk.Frame(footer, bg=PANEL); actions.pack(anchor='center')
                tk.Button(actions, text='Cancelar', command=modal.destroy, bg='#475569', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=14).pack(side='left', padx=(0, 8))
                tk.Button(actions, text='Quitar', command=lambda:[modal.destroy()], bg='#991b1b', fg='white', relief='flat', bd=0, font=('Segoe UI', 10, 'bold'), padx=16, pady=8, width=14).pack(side='left')
            win.wait_window(modal)
            if metodo_var.get() == m and datos_pago.get('metodo') != m:
                metodo_var.set('efectivo')
                datos_pago.clear(); datos_pago['metodo'] = 'efectivo'
                seleccionar_metodo('efectivo', open_modal=False)

        method_defs = [
            ('Efectivo', 'efectivo', '#15803d', '#38ef7d'),
            ('Depósito', 'deposito', '#a16207', '#fbbf24'),
            ('Transferencia', 'transferencia', '#2563eb', '#60a5fa'),
            ('Tarjeta', 'tarjeta', '#7c3aed', '#c084fc'),
            ('Mixto', 'mixto', '#0f766e', '#2dd4bf'),
        ]
        method_buttons = {}
        for col in range(3):
            btns.grid_columnconfigure(col, weight=1, uniform='pay_methods')
        for row_idx in range(2):
            btns.grid_rowconfigure(row_idx, weight=1)

        def seleccionar_metodo(m, open_modal=True):
            metodo_var.set(m)
            datos_pago.setdefault('metodo', m)
            datos_pago['metodo'] = m
            color_map = {
                'efectivo': '#86efac',
                'deposito': '#fde68a',
                'transferencia': '#93c5fd',
                'tarjeta': '#d8b4fe',
                'mixto': '#99f6e4',
            }
            metodo_info_var.set(f'Método seleccionado: {_payment_method_label(m)}')
            metodo_info.configure(fg=color_map.get(m, '#dbeafe'))
            for value, (btn, fill, border) in method_buttons.items():
                _style_payment_button(btn, fill, border, selected=(value == m))
            if m == 'efectivo':
                _show_cash_wrap()
                return
            _hide_cash_wrap()
            if open_modal:
                _open_method_modal(m)

        for idx, (label, value, fill, border) in enumerate(method_defs):
            row, col = divmod(idx, 3)
            btn = tk.Button(btns, text=label, image=payment_icons.get(value), command=lambda v=value: seleccionar_metodo(v))
            _style_payment_button(btn, fill, border, selected=(value == metodo_var.get()))
            btn.bind('<Enter>', lambda e, b=btn: b.configure(bg=getattr(b, '_hover_bg', b.cget('bg'))), add='+')
            btn.bind('<Leave>', lambda e, b=btn: b.configure(bg=getattr(b, '_normal_bg', b.cget('bg'))), add='+')
            btn.bind('<ButtonPress-1>', lambda e, b=btn: b.configure(bg=getattr(b, '_active_bg', b.cget('bg'))), add='+')
            btn.bind('<ButtonRelease-1>', lambda e, b=btn: b.configure(bg=getattr(b, '_hover_bg', b.cget('bg'))), add='+')
            btn.grid(row=row, column=col, padx=6, pady=6, sticky='nsew')
            method_buttons[value] = (btn, fill, border)

        amount_entry.focus_set()

        def build_receipt_text(receipt_no, amount, payment_method, new_due, new_favor, new_available):
            movement_label = title_map.get(movement_kind, movement_kind)
            lines = [
                'TECNOMEDIA GT BUSINESS SUITE',
                'COMPROBANTE DE MOVIMIENTO DE CLIENTE',
                '',
                f'No. comprobante: {receipt_no}',
                f"Fecha: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}",
                f'Tipo: {movement_label}',
                '',
                f'Cliente: {client_name}',
                f'Código: {client_code}',
                f'Usuario: {current_user_label()}',
                '',
                f'Método: {payment_method}',
                f'Monto: Q{amount:.2f}',
            ]
            ref_txt = vars_m['reference'].get().strip()
            if ref_txt:
                lines.append(f'Referencia: {ref_txt}')
            auto_txt = vars_m['authorization_no'].get().strip()
            if auto_txt:
                lines.append(f'Autorización: {auto_txt}')
            last4_txt = vars_m['card_last4'].get().strip()
            if last4_txt:
                lines.append(f'Últimos 4: {last4_txt}')
            note_txt = notes_var.get().strip()
            if note_txt:
                lines.append(f'Notas: {note_txt}')
            lines.extend(['', f'Saldo a deber: Q{new_due:.2f}', f'Saldo a favor: Q{new_favor:.2f}', f'Saldo disponible: Q{new_available:.2f}', '', '', 'Firma cliente: ________________________'])
            return "\n".join(lines) + "\n"

        def save_and_show_receipt(receipt_no, receipt_text):
            receipt_dir = Path(__file__).resolve().parents[1] / 'data' / 'client_balance_vouchers'
            receipt_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = receipt_dir / f'{receipt_no}.txt'
            receipt_path.write_text(receipt_text, encoding='utf-8')
            preview = tk.Toplevel(self)
            preview.title(f'Ticket {receipt_no}')
            preview.configure(bg=PANEL)
            preview.transient(self.winfo_toplevel())
            try:
                sw = preview.winfo_screenwidth(); sh = preview.winfo_screenheight(); pw, ph = 620, 700
                preview.geometry(f'{pw}x{ph}+{max(0,(sw-pw)//2)}+{max(0,(sh-ph)//2)}')
            except Exception:
                preview.geometry('620x700')
            tk.Label(preview, text='COMPROBANTE DE CLIENTE', bg=PANEL, fg=TEXT, font=('Arial', 16, 'bold')).pack(pady=(12, 6))
            tk.Label(preview, text=receipt_no, bg=PANEL, fg=MUTED, font=('Arial', 10, 'bold')).pack(pady=(0, 8))
            body = tk.Text(preview, bg='white', fg='black', relief='flat', bd=0, font=('Consolas', 11))
            body.pack(fill='both', expand=True, padx=16, pady=(0, 12))
            body.insert('1.0', receipt_text); body.configure(state='disabled')
            footer = tk.Frame(preview, bg=PANEL); footer.pack(fill='x', padx=16, pady=(0, 14))
            def do_print():
                try:
                    if os.name == 'nt':
                        os.startfile(str(receipt_path), 'print')
                        messagebox.showinfo('Impresión', 'Se envió el ticket a impresión.', parent=preview)
                    else:
                        raise RuntimeError('Impresión no soportada en este entorno')
                except Exception as exc:
                    messagebox.showwarning('Impresión', f"No se pudo imprimir automáticamente. El ticket quedó guardado en:\n{receipt_path}\n\nDetalle: {exc}", parent=preview)
            tk.Button(footer, text='Imprimir ticket', command=do_print, bg=ACCENT, fg='#03281e', relief='flat', bd=0, font=('Arial', 11, 'bold'), width=18, padx=12, pady=8).pack(side='left', padx=(0, 8))
            tk.Button(footer, text='Cerrar', command=preview.destroy, bg='#334155', fg=TEXT, relief='flat', bd=0, font=('Arial', 11, 'bold'), width=14, padx=12, pady=8).pack(side='left')
            return receipt_path

        def apply_movement():
            amount = safe_float(vars_m['amount'].get())
            if amount <= 0:
                messagebox.showwarning('Monto inválido', 'Ingresa un monto mayor que cero.', parent=win); return
            metodo = metodo_var.get()
            reference_value = vars_m['reference'].get().strip()
            if metodo == 'efectivo':
                datos_pago['metodo'] = 'efectivo'
            else:
                datos_pago['metodo'] = metodo
                if metodo in ('deposito', 'transferencia') and not vars_m['support_photo'].get().strip():
                    messagebox.showerror('Pago', 'Debes adjuntar el comprobante del pago.', parent=win); return
                if metodo == 'tarjeta':
                    if not vars_m['support_photo'].get().strip() or not vars_m['dpi_photo'].get().strip():
                        messagebox.showerror('Pago', 'Debes adjuntar fotografía de la tarjeta y del DPI.', parent=win); return
                if metodo == 'mixto':
                    mix_total = round(safe_float(datos_pago.get('mix_1_amount')) + safe_float(datos_pago.get('mix_2_amount')), 2)
                    if abs(mix_total - round(amount,2)) > 0.009:
                        messagebox.showerror('Mixto', 'La suma de los dos métodos debe coincidir con el monto.', parent=win); return
                    refs = []
                    photos = []
                    dpi_list = []
                    for slot, raw in (('mix_1', datos_pago.get('mix_1_method')), ('mix_2', datos_pago.get('mix_2_method'))):
                        support = datos_pago.get(f'{slot}_support') or {}
                        if raw in ('deposito', 'transferencia', 'tarjeta') and not support:
                            messagebox.showerror('Mixto', f'Debes completar el soporte de {_payment_method_label(raw)}.', parent=win); return
                        ref_val = str(support.get('referencia', support.get('autorizacion', ''))).strip()
                        if ref_val: refs.append(ref_val)
                        photo_val = str(support.get('comprobante', support.get('foto_tarjeta', ''))).strip()
                        if photo_val: photos.append(photo_val)
                        dpi_val = str(support.get('foto_dpi', '')).strip()
                        if dpi_val: dpi_list.append(dpi_val)
                    if refs and not vars_m['reference'].get().strip():
                        vars_m['reference'].set(' | '.join(refs))
                    if photos:
                        vars_m['support_photo'].set(' | '.join(photos))
                    if dpi_list:
                        vars_m['dpi_photo'].set(' | '.join(dpi_list))
                    if not vars_m['reference'].get().strip() and datos_pago.get('mix_detail'):
                        vars_m['reference'].set(str(datos_pago.get('mix_detail')).strip())
            conn = db_connect(); cur = conn.cursor()
            try:
                cur.execute('SELECT balance_due, balance_favor, balance_available FROM clients WHERE client_code=?', (client_code,))
                row = cur.fetchone() or (0,0,0)
                current_due, current_favor, current_available = map(safe_float, row)
                if movement_kind == 'ABONO_A_DEUDA':
                    if current_due <= 0:
                        messagebox.showwarning('Sin saldo a deber', 'Este cliente no tiene saldo a deber para abonar.', parent=win); return
                    if amount > current_due:
                        messagebox.showwarning('Monto excedido', f'El abono no puede ser mayor al saldo a deber actual (Q {current_due:.2f}).', parent=win); return
                    new_due, new_favor, new_available = round(current_due - amount, 2), current_favor, current_available
                else:
                    new_due, new_favor, new_available = current_due, round(current_favor + amount, 2), round(current_available + amount, 2)
                cur.execute('UPDATE clients SET balance_due=?, balance_favor=?, balance_available=? WHERE client_code=?', (new_due, new_favor, new_available, client_code))
                receipt_no = next_document_correlativo('TICKET', conn=conn)
                payment_method_label = _payment_method_label(str(datos_pago.get('metodo', metodo)).strip())
                if metodo == 'mixto':
                    payment_method_label = f"Mixto ({_payment_method_label(datos_pago.get('mix_1_method'))} + {_payment_method_label(datos_pago.get('mix_2_method'))})"
                    if notes_var.get().strip():
                        notes_var.set(notes_var.get().strip() + ' | ' + f"Q{safe_float(datos_pago.get('mix_1_amount')):.2f} + Q{safe_float(datos_pago.get('mix_2_amount')):.2f}")
                    else:
                        notes_var.set(f"Q{safe_float(datos_pago.get('mix_1_amount')):.2f} + Q{safe_float(datos_pago.get('mix_2_amount')):.2f}")
                cur.execute(
                    'INSERT INTO client_balance_movements (created_at, client_code, client_name, movement_kind, payment_method, amount, reference, authorization_no, card_last4, support_photo, dpi_photo, notes, receipt_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (datetime.now().isoformat(timespec='seconds'), client_code, client_name, movement_kind, payment_method_label, amount, vars_m['reference'].get().strip(), vars_m['authorization_no'].get().strip(), vars_m['card_last4'].get().strip(), vars_m['support_photo'].get().strip(), vars_m['dpi_photo'].get().strip(), notes_var.get().strip(), receipt_no)
                )
                try:
                    movement_desc = title_map.get(movement_kind, movement_kind)
                    cur.execute('INSERT INTO cash_movements (created_at, movement_type, amount, reason, reference_no, user_name) VALUES (?, ?, ?, ?, ?, ?)', (datetime.now().isoformat(timespec='seconds'), 'INGRESO', amount, f'{movement_desc} cliente {client_code} | Método: {payment_method_label}', client_code, current_user_label()))
                except Exception:
                    pass
                conn.commit()
            finally:
                conn.close()
            receipt_text = build_receipt_text(receipt_no, amount, payment_method_label, new_due, new_favor, new_available)
            self.vars['balance_due'].set(f'{new_due:.2f}')
            self.vars['balance_favor'].set(f'{new_favor:.2f}')
            self.vars['balance_available'].set(f'{new_available:.2f}')
            self._refresh_balance_labels(); self._load_rows(); win.destroy(); save_and_show_receipt(receipt_no, receipt_text)
            messagebox.showinfo('Movimiento aplicado', f"El movimiento fue registrado correctamente.\nComprobante: {receipt_no}")

        footer = tk.Frame(win, bg=PANEL); footer.pack(fill='x', padx=18, pady=(22, 16))
        footer_inner = tk.Frame(footer, bg=PANEL); footer_inner.pack(anchor='center')
        tk.Button(footer_inner, text='Cancelar', command=win.destroy, bg='#334155', fg=TEXT, relief='flat', bd=0, font=('Arial', 11, 'bold'), width=16, padx=12, pady=8).pack(side='left', padx=8)
        tk.Button(footer_inner, text='Confirmar movimiento', command=apply_movement, bg=ACCENT, fg='#03281e', relief='flat', bd=0, font=('Arial', 11, 'bold'), width=18, padx=12, pady=8).pack(side='left', padx=8)

    def _load_rows(self):
        self._row_client_codes = {}
        for item in self.tree.get_children():
            self.tree.delete(item)
        term = self.search_var.get().strip().lower()
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT client_code, name, phone, COALESCE(phone2,''), COALESCE(nit,''), allow_credit, balance_due, balance_favor, status, credit_limit FROM clients ORDER BY id DESC LIMIT 300")
        rows = cur.fetchall(); cur.execute("SELECT COUNT(*) FROM clients")
        total = cur.fetchone()[0]; conn.close()
        shown = 0
        active_count = 0
        total_credit_limit = 0.0
        total_due = 0.0
        total_favor = 0.0
        for code, name, phone, phone2, nit, allow_credit, due, favor, status, credit_limit in rows:
            searchable = f"{code} {name} {phone} {phone2} {nit}".lower()
            if term and term not in searchable:
                continue
            item_id = self.tree.insert("", "end", values=(name or "", phone or "", phone2 or "", nit or "", "Sí" if allow_credit else "No", f"Q {safe_float(due):.2f}", f"Q {safe_float(favor):.2f}"))
            self._row_client_codes[item_id] = code
            shown += 1
            if str(status or '').lower() == 'activo':
                active_count += 1
            total_due += safe_float(due)
            total_favor += safe_float(favor)
            if allow_credit:
                total_credit_limit += safe_float(credit_limit)
        self.quick_total.configure(text=f"{shown} / {total} clientes")
        if getattr(self, 'metric_active', None):
            self.metric_active.value_label.configure(text=str(active_count))
        if getattr(self, 'metric_credit', None):
            self.metric_credit.value_label.configure(text=f"Q {total_credit_limit:.2f}")
        if getattr(self, 'metric_due', None):
            self.metric_due.value_label.configure(text=f"Q {total_due:.2f}")
        if getattr(self, 'metric_favor', None):
            self.metric_favor.value_label.configure(text=f"Q {total_favor:.2f}")


class ProvidersView(ttk.Frame):
    COUNTRIES = ["Guatemala", "El Salvador", "Honduras", "México", "Estados Unidos", "Otro"]

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.editing_id = None
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._load_rows())
        self.vars = {
            "provider_code": tk.StringVar(value=self._next_provider_code()),
            "name": tk.StringVar(),
            "nit": tk.StringVar(),
            "contact_name": tk.StringVar(),
            "phone": tk.StringVar(),
            "phone2": tk.StringVar(),
            "email": tk.StringVar(),
            "address": tk.StringVar(),
            "country": tk.StringVar(value="Guatemala"),
            "social_url": tk.StringVar(),
            "status": tk.StringVar(value="Activo"),
        }
        self.notes = None
        self.account_numbers = None
        self.tree = None
        self.quick_total = None
        self.provider_metric_values = {}
        self._build()
        self._load_rows()

    def _build(self):
        self.columnconfigure(0, weight=12)
        self.columnconfigure(1, weight=14)
        self.rowconfigure(0, weight=1)

        left_shell = ttk.Frame(self, style="TFrame")
        left_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left_shell.columnconfigure(0, weight=1)
        left_shell.rowconfigure(0, weight=1)

        left = ttk.Frame(left_shell, style="Card.TFrame", padding=24)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)

        accent_bar = tk.Frame(left, bg="#0f172a", height=3)
        accent_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        for idx, color in enumerate(["#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#22c55e"]):
            accent_bar.columnconfigure(idx, weight=1)
            tk.Frame(accent_bar, bg=color, height=3).grid(row=0, column=idx, sticky="nsew")

        ttk.Label(left, text="FICHA DE PROVEEDOR", style="CardTitle.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(left, text="Directorio comercial listo para compras, inventario y conciliaciones.", style="CardNote.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 18))

        def pfield(parent, row, col, label, widget, pad=(0, 12)):
            ttk.Label(parent, text=label, style="CardTitle.TLabel").grid(row=row, column=col, sticky="w", pady=(0, 6), padx=pad)
            widget.grid(row=row + 1, column=col, sticky="ew", pady=(0, 16), padx=pad)
            return widget

        identity = ttk.Frame(left, style="Card.TFrame")
        identity.grid(row=3, column=0, columnspan=2, sticky="ew")
        for i in range(4):
            identity.columnconfigure(i, weight=1)
        pfield(identity, 0, 0, "Código proveedor", ttk.Entry(identity, textvariable=self.vars["provider_code"]))
        pfield(identity, 0, 1, "Estado", ttk.Combobox(identity, textvariable=self.vars["status"], values=["Activo", "Inactivo"], state="readonly"))
        pfield(identity, 0, 2, "País", ttk.Combobox(identity, textvariable=self.vars["country"], values=self.COUNTRIES, state="readonly"))
        pfield(identity, 0, 3, "Contacto principal", ttk.Entry(identity, textvariable=self.vars["contact_name"]))

        contact = ttk.Frame(left, style="Card.TFrame")
        contact.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        for i in range(4):
            contact.columnconfigure(i, weight=1)
        ttk.Label(contact, text="DATOS PRINCIPALES", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(2, 10))
        pfield(contact, 1, 0, "Nombre del proveedor", ttk.Entry(contact, textvariable=self.vars["name"]))
        pfield(contact, 1, 1, "NIT", ttk.Entry(contact, textvariable=self.vars["nit"]))
        pfield(contact, 1, 2, "Teléfono", ttk.Entry(contact, textvariable=self.vars["phone"]))
        pfield(contact, 1, 3, "Teléfono 2", ttk.Entry(contact, textvariable=self.vars["phone2"]))
        pfield(contact, 3, 0, "Email", ttk.Entry(contact, textvariable=self.vars["email"]))
        pfield(contact, 3, 1, "URL red social", ttk.Entry(contact, textvariable=self.vars["social_url"]))
        pfield(contact, 3, 2, "Dirección", ttk.Entry(contact, textvariable=self.vars["address"]))

        bank_card = ttk.Frame(left, style="Card.TFrame")
        bank_card.grid(row=5, column=0, sticky="nsew", pady=(12, 0), padx=(0, 8))
        bank_card.columnconfigure(0, weight=1)
        ttk.Label(bank_card, text="CUENTAS Y PAGOS", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(bank_card, text="Agrega bancos, números de cuenta o referencias de pago.", style="CardNote.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.account_numbers = tk.Text(bank_card, height=8, bg="#172033", fg="#e5e7eb", insertbackground="white", relief="flat", bd=0, highlightthickness=1, highlightbackground="#334155", highlightcolor="#3b82f6", font=("Segoe UI", 10), padx=12, pady=10)
        self.account_numbers.grid(row=2, column=0, sticky="nsew")

        notes_card = ttk.Frame(left, style="Card.TFrame")
        notes_card.grid(row=5, column=1, sticky="nsew", pady=(12, 0), padx=(8, 0))
        notes_card.columnconfigure(0, weight=1)
        ttk.Label(notes_card, text="NOTAS Y CONDICIONES", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(notes_card, text="Condiciones comerciales, observaciones o acuerdos especiales.", style="CardNote.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.notes = tk.Text(notes_card, height=8, bg="#172033", fg="#e5e7eb", insertbackground="white", relief="flat", bd=0, highlightthickness=1, highlightbackground="#334155", highlightcolor="#8b5cf6", font=("Segoe UI", 10), padx=12, pady=10)
        self.notes.grid(row=2, column=0, sticky="nsew")

        actions = ttk.Frame(left, style="Card.TFrame")
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.btn_provider_new = ttk.Button(actions, text="Nuevo", command=self.reset_form)
        self.btn_provider_new.pack(side="left", padx=(0, 8))
        self.btn_provider_save = ttk.Button(actions, text="Guardar / Actualizar", style="Primary.TButton", command=self.save_provider)
        self.btn_provider_save.pack(side="left", padx=(0, 8))
        self.btn_provider_refresh = ttk.Button(actions, text="Actualizar listado", command=self._load_rows)
        self.btn_provider_refresh.pack(side="left")
        disable_button_if_denied(self.btn_provider_save, 'Proveedores', 'crear', 'guardar proveedor')

        right = ttk.Frame(self, style="TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        stats = ttk.Frame(right, style="Card.TFrame", padding=20)
        stats.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        stats.columnconfigure(0, weight=1)
        ttk.Label(stats, text="RESUMEN PROVEEDORES", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.quick_total = ttk.Label(stats, text="0 / 0 proveedores", style="CardValue.TLabel")
        self.quick_total.grid(row=1, column=0, sticky="w", pady=(10, 2))
        ttk.Label(stats, text="Doble click para editar. Este directorio alimenta inventario y compras.", style="CardNote.TLabel").grid(row=2, column=0, sticky="w")

        metrics = ttk.Frame(stats, style="Card.TFrame")
        metrics.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        for idx in range(4):
            metrics.columnconfigure(idx, weight=1)
        metric_specs = [
            ("Activos", "0", "#4ade80"),
            ("Con contacto", "0", "#38bdf8"),
            ("Con email", "0", "#f59e0b"),
            ("Con cuentas", "0", "#a78bfa"),
        ]
        for idx, (title, default_value, accent) in enumerate(metric_specs):
            card = tk.Frame(metrics, bg="#162235", highlightthickness=1, highlightbackground=accent)
            card.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 8, 0))
            tk.Label(card, text=title, bg="#162235", fg="#cbd5e1", font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(10, 0))
            value = tk.Label(card, text=default_value, bg="#162235", fg=accent, font=("Segoe UI Semibold", 16))
            value.pack(anchor="w", padx=12, pady=(0, 10))
            self.provider_metric_values[title] = value

        search_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        search_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(search_card, text="Buscar proveedor", style="CardTitle.TLabel").pack(anchor="w")
        search_inner = ttk.Frame(search_card, style="Card.TFrame")
        search_inner.pack(fill="x", pady=(8, 0))
        search_inner.columnconfigure(0, weight=1)
        self.provider_search_entry = ttk.Entry(search_inner, textvariable=self.search_var)
        self.provider_search_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(search_inner, text="Buscar", style="Primary.TButton", command=self._load_rows).grid(row=0, column=1, padx=(8, 0))

        list_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        list_card.grid(row=2, column=0, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)
        ttk.Label(list_card, text="Listado de proveedores", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        cols = ("code", "name", "contact", "phone", "phone2", "nit", "country", "status")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings")
        headings = {"code": "Código", "name": "Nombre del proveedor", "contact": "Contacto", "phone": "Teléfono", "phone2": "Tel. 2", "nit": "NIT", "country": "País", "status": "Estado"}
        widths = {"code": 112, "name": 240, "contact": 160, "phone": 120, "phone2": 120, "nit": 120, "country": 112, "status": 90}
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        install_column_manager(list_card, self.tree, 'proveedores_listado', row=0, column=0, padx=(0, 0), pady=(0, 8))
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        scroll = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")

    def _next_provider_code(self):
        conn = db_connect(); cur = conn.cursor(); cur.execute("SELECT id FROM providers ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close(); return f"PRV-{((row[0] + 1) if row else 1):05d}"

    def reset_form(self):
        self.editing_id = None
        self.vars["provider_code"].set(self._next_provider_code())
        self.vars["name"].set("")
        self.vars["nit"].set("")
        self.vars["contact_name"].set("")
        self.vars["phone"].set("")
        self.vars["phone2"].set("")
        self.vars["email"].set("")
        self.vars["address"].set("")
        self.vars["country"].set("Guatemala")
        self.vars["social_url"].set("")
        self.vars["status"].set("Activo")
        self.account_numbers.delete("1.0", tk.END)
        self.notes.delete("1.0", tk.END)

    def save_provider(self):
        needed = 'editar' if self.editing_id else 'crear'
        if not require_permission('Proveedores', needed, self, 'guardar proveedor'):
            return
        name = self.vars["name"].get().strip()
        if not name:
            messagebox.showwarning("Campo requerido", "Debes ingresar el nombre del proveedor.")
            return
        conn = db_connect(); cur = conn.cursor()
        payload = (
            self.vars["provider_code"].get().strip(),
            name,
            self.vars["nit"].get().strip(),
            self.vars["contact_name"].get().strip(),
            self.vars["phone"].get().strip(),
            self.vars["phone2"].get().strip(),
            self.vars["email"].get().strip(),
            self.vars["address"].get().strip(),
            self.vars["country"].get().strip(),
            self.vars["social_url"].get().strip(),
            self.account_numbers.get("1.0", tk.END).strip(),
            self.notes.get("1.0", tk.END).strip(),
            self.vars["status"].get().strip(),
        )
        if self.editing_id:
            cur.execute("""UPDATE providers SET provider_code=?, name=?, nit=?, contact_name=?, phone=?, phone2=?, email=?, address=?, country=?, social_url=?, account_numbers=?, notes=?, status=? WHERE id=?""", (*payload, self.editing_id))
            msg = "Proveedor actualizado correctamente."
        else:
            cur.execute("""INSERT INTO providers (provider_code, name, nit, contact_name, phone, phone2, email, address, country, social_url, account_numbers, notes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (*payload, datetime.now().isoformat(timespec="seconds")))
            msg = "Proveedor guardado correctamente."
        conn.commit(); conn.close()
        messagebox.showinfo("Proveedor", msg)
        self.reset_form(); self._load_rows()

    def _load_rows(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        term = self.search_var.get().strip().lower()
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id, COALESCE(provider_code,''), name, COALESCE(contact_name,''), COALESCE(phone,''), COALESCE(phone2,''), COALESCE(nit,''), COALESCE(country,''), status, COALESCE(email,''), COALESCE(account_numbers,'') FROM providers ORDER BY id DESC LIMIT 300")
        rows = cur.fetchall(); cur.execute("SELECT COUNT(*) FROM providers")
        total = cur.fetchone()[0]; conn.close()
        shown = active = with_contact = with_email = with_accounts = 0
        for row_id, provider_code, name, contact_name, phone, phone2, nit, country, status, email, account_numbers in rows:
            searchable = f"{provider_code} {name} {contact_name} {phone} {phone2} {nit} {country} {status} {email}".lower()
            if term and term not in searchable:
                continue
            self.tree.insert("", "end", iid=str(row_id), values=(provider_code, name, contact_name, phone, phone2, nit, country, status))
            shown += 1
            if (status or '').strip().lower() == 'activo':
                active += 1
            if (contact_name or '').strip() or (phone or '').strip():
                with_contact += 1
            if (email or '').strip():
                with_email += 1
            if (account_numbers or '').strip():
                with_accounts += 1
        self.quick_total.configure(text=f"{shown} / {total} proveedores")
        self.provider_metric_values["Activos"].configure(text=str(active))
        self.provider_metric_values["Con contacto"].configure(text=str(with_contact))
        self.provider_metric_values["Con email"].configure(text=str(with_email))
        self.provider_metric_values["Con cuentas"].configure(text=str(with_accounts))

    def _on_tree_double_click(self, event=None):
        if not require_permission('Proveedores', 'editar', self, 'editar proveedor'):
            return
        sel = self.tree.selection()
        if not sel:
            return
        row_id = sel[0]
        conn = db_connect(); cur = conn.cursor()
        cur.execute("""SELECT id, COALESCE(provider_code,''), name, COALESCE(nit,''), COALESCE(contact_name,''), COALESCE(phone,''), COALESCE(phone2,''), COALESCE(email,''), COALESCE(address,''), COALESCE(country,''), COALESCE(social_url,''), COALESCE(account_numbers,''), COALESCE(notes,''), status FROM providers WHERE id=?""", (row_id,))
        row = cur.fetchone(); conn.close()
        if not row:
            return
        self.editing_id = row[0]
        self.vars["provider_code"].set(row[1] or "")
        self.vars["name"].set(row[2] or "")
        self.vars["nit"].set(row[3] or "")
        self.vars["contact_name"].set(row[4] or "")
        self.vars["phone"].set(row[5] or "")
        self.vars["phone2"].set(row[6] or "")
        self.vars["email"].set(row[7] or "")
        self.vars["address"].set(row[8] or "")
        self.vars["country"].set(row[9] or "Guatemala")
        self.vars["social_url"].set(row[10] or "")
        self.account_numbers.delete("1.0", tk.END)
        self.account_numbers.insert("1.0", row[11] or "")
        self.notes.delete("1.0", tk.END)
        self.notes.insert("1.0", row[12] or "")
        self.vars["status"].set(row[13] or "Activo")


class InventoryView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.photo_path = tk.StringVar(value="")
        self.editing_item_id = None
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._load_rows())
        self.vars = {
            "internal_code": tk.StringVar(value=self._next_internal_code()),
            "provider_code": tk.StringVar(),
            "sku_code": tk.StringVar(),
            "item_type": tk.StringVar(value="Producto"),
            "barcode": tk.StringVar(),
            "name": tk.StringVar(),
            "serial": tk.StringVar(),
            "provider": tk.StringVar(),
            "location": tk.StringVar(),
            "category": tk.StringVar(),
            "brand": tk.StringVar(),
            "cost": tk.StringVar(value="0.00"),
            "price": tk.StringVar(value="0.00"),
            "stock": tk.StringVar(value="0.00"),
            "min_stock": tk.StringVar(value="0.00"),
            "status": tk.StringVar(value="Activo"),
        }
        self.obs = None
        self.tree = None
        self.quick_total = None
        self.inventory_metric_values = []
        self.stock_value_boxes = {}
        self.photo_preview_name = None
        self._build()
        for key in ('cost', 'price', 'stock', 'min_stock'):
            self.vars[key].trace_add('write', lambda *_: self._refresh_stock_value_boxes())
        self._refresh_stock_value_boxes()
        self._load_rows()

    def _category_values(self):
        conn = db_connect(); cur = conn.cursor(); cur.execute("SELECT name FROM inventory_categories WHERE status='Activo' ORDER BY name COLLATE NOCASE")
        vals = [r[0] for r in cur.fetchall()]
        conn.close(); return vals

    def _provider_values(self):
        conn = db_connect(); cur = conn.cursor(); cur.execute("SELECT name FROM providers WHERE status='Activo' ORDER BY name COLLATE NOCASE")
        vals = [r[0] for r in cur.fetchall()]
        conn.close(); return vals

    def _build(self):
        self.columnconfigure(0, weight=7)
        self.columnconfigure(1, weight=6)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Card.TFrame", padding=22)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,12))
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)

        accent = tk.Canvas(left, height=3, bg="#111827", highlightthickness=0, bd=0)
        accent.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,14))
        accent.create_line(0, 1, 220, 1, fill="#22d3ee", width=3)
        accent.create_line(220, 1, 520, 1, fill="#a855f7", width=3)
        accent.create_line(520, 1, 840, 1, fill="#f59e0b", width=3)

        ttk.Label(left, text="Datos del artículo", style="CardTitle.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(left, text="Productos y servicios con mejor orden visual, lectura rápida y foco en datos clave.", style="CardNote.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4,16))

        def ifield(parent, row, col, label, widget, pad=(0,12)):
            ttk.Label(parent, text=label, style="CardTitle.TLabel").grid(row=row, column=col, sticky="w", pady=(0,6), padx=pad)
            widget.grid(row=row+1, column=col, sticky="ew", pady=(0,12), padx=pad)
            return widget

        ident = ttk.Frame(left, style="Card.TFrame")
        ident.grid(row=3, column=0, columnspan=2, sticky="ew")
        for i in range(4):
            ident.columnconfigure(i, weight=1)
        ttk.Label(ident, text="Identificación del artículo", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0,10))
        ifield(ident, 1, 0, "Código interno", ttk.Entry(ident, textvariable=self.vars["internal_code"]))
        ifield(ident, 1, 1, "Código proveedor", ttk.Entry(ident, textvariable=self.vars["provider_code"]))
        ifield(ident, 1, 2, "Código SKU", ttk.Entry(ident, textvariable=self.vars["sku_code"]))
        ifield(ident, 1, 3, "Tipo", ttk.Combobox(ident, textvariable=self.vars["item_type"], values=["Producto", "Servicio"], state="readonly"))
        ifield(ident, 3, 0, "Nombre", ttk.Entry(ident, textvariable=self.vars["name"]))
        ifield(ident, 3, 1, "Serial", ttk.Entry(ident, textvariable=self.vars["serial"]))
        ifield(ident, 3, 2, "Marca", ttk.Entry(ident, textvariable=self.vars["brand"]))
        ifield(ident, 3, 3, "Estado", ttk.Combobox(ident, textvariable=self.vars["status"], values=["Activo", "Inactivo"], state="readonly"))

        commercial = ttk.Frame(left, style="Card.TFrame")
        commercial.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10,0))
        for i in range(4):
            commercial.columnconfigure(i, weight=1)
        ttk.Label(commercial, text="Clasificación y proveedor", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0,10))

        provider_wrap = ttk.Frame(commercial, style="Card.TFrame")
        provider_wrap.columnconfigure(0, weight=1)
        self.provider_combo = ttk.Combobox(provider_wrap, textvariable=self.vars["provider"], values=self._provider_values(), state="readonly")
        self.provider_combo.grid(row=0, column=0, sticky="ew")
        self.btn_inv_provider_add = ttk.Button(provider_wrap, text="+", style="Mini.TButton", width=2, command=self._manage_provider_add)
        self.btn_inv_provider_add.grid(row=0, column=1, padx=(6,4))
        self.btn_inv_provider_edit = ttk.Button(provider_wrap, text="✎", style="Mini.TButton", width=2, command=self._manage_provider_edit)
        self.btn_inv_provider_edit.grid(row=0, column=2)
        disable_button_if_denied(self.btn_inv_provider_add, 'Inventario', 'editar', 'agregar proveedor rápido en inventario')
        disable_button_if_denied(self.btn_inv_provider_edit, 'Inventario', 'editar', 'editar proveedor rápido en inventario')

        category_wrap = ttk.Frame(commercial, style="Card.TFrame")
        category_wrap.columnconfigure(0, weight=1)
        self.category_combo = ttk.Combobox(category_wrap, textvariable=self.vars["category"], values=self._category_values(), state="readonly")
        self.category_combo.grid(row=0, column=0, sticky="ew")
        self.btn_inv_category_add = ttk.Button(category_wrap, text="+", style="Mini.TButton", width=2, command=self._manage_category_add)
        self.btn_inv_category_add.grid(row=0, column=1, padx=(6,4))
        self.btn_inv_category_edit = ttk.Button(category_wrap, text="✎", style="Mini.TButton", width=2, command=self._manage_category_edit)
        self.btn_inv_category_edit.grid(row=0, column=2)
        disable_button_if_denied(self.btn_inv_category_add, 'Inventario', 'editar', 'agregar categoría rápida en inventario')
        disable_button_if_denied(self.btn_inv_category_edit, 'Inventario', 'editar', 'editar categoría rápida en inventario')

        ifield(commercial, 1, 0, "Proveedor", provider_wrap)
        ifield(commercial, 1, 1, "Categoría", category_wrap)
        ifield(commercial, 1, 2, "Ubicación", ttk.Entry(commercial, textvariable=self.vars["location"]))

        ttk.Label(commercial, text="Foto del producto", style="CardTitle.TLabel").grid(row=1, column=3, sticky="w", padx=(0,12), pady=(0,6))
        photo_card = tk.Frame(commercial, bg="#131f33", highlightthickness=1, highlightbackground="#4c1d95")
        photo_card.grid(row=2, column=3, sticky="nsew", padx=(0,12), pady=(0,12))
        tk.Label(photo_card, text="📷", bg="#131f33", fg="#a78bfa", font=("Segoe UI Emoji", 19)).pack(pady=(10,2))
        self.photo_preview_name = tk.Label(photo_card, text="Sin imagen", bg="#131f33", fg="#cbd5e1", font=("Segoe UI", 9), wraplength=140, justify="center")
        self.photo_preview_name.pack(pady=(0,6), padx=8)
        self.btn_inv_photo = ttk.Button(photo_card, text="Agregar foto", style="Primary.TButton", command=self.pick_photo)
        self.btn_inv_photo.pack(fill="x", padx=10, pady=(0,10))
        disable_button_if_denied(self.btn_inv_photo, 'Inventario', 'editar', 'seleccionar foto de producto')

        stock_card = ttk.Frame(left, style="Card.TFrame")
        stock_card.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10,0))
        for i in range(4):
            stock_card.columnconfigure(i, weight=1)
        ttk.Label(stock_card, text="Precios y existencias", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0,10))
        self.stock_value_boxes = {}
        stock_specs = [
            ("cost", "Costo", "#f8fafc", "Q 0.00"),
            ("price", "Precio", "#f8fafc", "Q 0.00"),
            ("stock", "Stock", "#93c5fd", "0"),
            ("min_stock", "Stock mínimo", "#fca5a5", "0"),
        ]
        for idx, (key, title, color, default_text) in enumerate(stock_specs):
            box = tk.Frame(stock_card, bg="#162235", highlightthickness=1, highlightbackground="#24344d")
            box.grid(row=1, column=idx, sticky="nsew", padx=(0 if idx == 0 else 6, 0), pady=(0,8))
            tk.Label(box, text=title, bg="#162235", fg="#cbd5e1", font=("Segoe UI Semibold", 10), anchor="w").pack(fill="x", padx=12, pady=(10,2))
            value = tk.Label(box, text=default_text, bg="#162235", fg=color, font=("Segoe UI Semibold", 17), anchor="w")
            value.pack(fill="x", padx=12, pady=(0,4))
            entry = ttk.Entry(box, textvariable=self.vars[key])
            entry.pack(fill="x", padx=12, pady=(0,10))
            self.stock_value_boxes[key] = value

        obs_card = ttk.Frame(left, style="Card.TFrame")
        obs_card.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10,0))
        obs_card.columnconfigure(0, weight=1)
        ttk.Label(obs_card, text="Observación", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0,8))
        self.obs = tk.Text(obs_card, height=4, bg="#1f2937", fg="#e5e7eb", insertbackground="white", relief="flat")
        self.obs.grid(row=1, column=0, sticky="ew")

        actions = ttk.Frame(left, style="Card.TFrame")
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12,0))
        self.btn_inv_new = ttk.Button(actions, text="Nuevo", command=self.reset_form)
        self.btn_inv_new.pack(side="left", padx=(0,8))
        self.btn_inv_save = ttk.Button(actions, text="Guardar / Actualizar", style="Primary.TButton", command=self.save_item)
        self.btn_inv_save.pack(side="left", padx=(0,8))
        self.btn_inv_refresh = ttk.Button(actions, text="Actualizar listado", command=self._load_rows)
        self.btn_inv_refresh.pack(side="left")
        disable_button_if_denied(self.btn_inv_save, 'Inventario', 'crear', 'guardar artículo de inventario')

        right = ttk.Frame(self, style="TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        stats = ttk.Frame(right, style="Card.TFrame", padding=18)
        stats.grid(row=0, column=0, sticky="ew", pady=(0,10))
        ttk.Label(stats, text="Resumen inventario", style="CardTitle.TLabel").pack(anchor="w")
        self.quick_total = ttk.Label(stats, text="0 / 0 registros", style="CardValue.TLabel")
        self.quick_total.pack(anchor="w", pady=(10,2))
        ttk.Label(stats, text="Búsqueda por nombre, código interno, código proveedor, SKU o proveedor.", style="CardNote.TLabel").pack(anchor="w")

        metric_row = ttk.Frame(stats, style="Card.TFrame")
        metric_row.pack(fill="x", pady=(14,0))
        for i in range(4):
            metric_row.columnconfigure(i, weight=1)
        metric_specs = [
            ("Productos", "0", "#a855f7"),
            ("Valor inventario", "Q 0.00", "#f59e0b"),
            ("Stock total", "0", "#22d3ee"),
            ("Activos", "0", "#10b981"),
        ]
        self.inventory_metric_values = []
        for idx, (title, default, color) in enumerate(metric_specs):
            card = tk.Frame(metric_row, bg="#162235", highlightthickness=1, highlightbackground=color)
            card.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))
            tk.Label(card, text=title, bg="#162235", fg="#cbd5e1", font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(10,0))
            value = tk.Label(card, text=default, bg="#162235", fg=color, font=("Segoe UI Semibold", 16))
            value.pack(anchor="w", padx=12, pady=(0,10))
            self.inventory_metric_values.append(value)

        search_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        search_card.grid(row=1, column=0, sticky="ew", pady=(0,10))
        ttk.Label(search_card, text="Buscar en inventario", style="CardTitle.TLabel").pack(anchor="w")
        search_inner = ttk.Frame(search_card, style="Card.TFrame")
        search_inner.pack(fill="x", pady=(8,0))
        search_inner.columnconfigure(0, weight=1)
        self.inv_search_entry = ttk.Entry(search_inner, textvariable=self.search_var)
        self.inv_search_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(search_inner, text="Buscar", style="Primary.TButton", command=self._load_rows).grid(row=0, column=1, padx=(8,0))

        list_card = ttk.Frame(right, style="Card.TFrame", padding=18)
        list_card.grid(row=2, column=0, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)
        ttk.Label(list_card, text="Listado de inventario", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0,8))
        cols = ("code", "prov_code", "sku", "type", "name", "provider", "price", "stock")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings")
        headings = {"code": "Código", "prov_code": "Cod. proveedor", "sku": "SKU", "type": "Tipo", "name": "Nombre", "provider": "Proveedor", "price": "Precio", "stock": "Stock"}
        widths = {"code": 112, "prov_code": 118, "sku": 100, "type": 88, "name": 220, "provider": 148, "price": 94, "stock": 82}
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        install_column_manager(list_card, self.tree, 'inventario_listado', row=0, column=0, padx=(0, 0), pady=(0, 8))
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        scroll = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")
    def _refresh_stock_value_boxes(self):
        mapping = {
            'cost': f"Q {safe_float(self.vars['cost'].get()):.2f}",
            'price': f"Q {safe_float(self.vars['price'].get()):.2f}",
            'stock': f"{safe_float(self.vars['stock'].get()):.2f}",
            'min_stock': f"{safe_float(self.vars['min_stock'].get()):.2f}",
        }
        for key, label in getattr(self, 'stock_value_boxes', {}).items():
            try:
                label.configure(text=mapping.get(key, '0.00'))
            except Exception:
                pass

    def _refresh_photo_preview(self):
        if self.photo_preview_name is None:
            return
        current = (self.photo_path.get() or '').strip()
        if not current:
            self.photo_preview_name.configure(text='Sin imagen')
            return
        try:
            name = Path(current).name
        except Exception:
            name = current
        self.photo_preview_name.configure(text=name)

    def _next_internal_code(self):
        conn = db_connect(); cur = conn.cursor(); cur.execute("SELECT id FROM inventory_items ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close(); return f"INT-{((row[0] + 1) if row else 1):06d}"

    def _generate_barcode(self):
        return

    def _refresh_option_lists(self):
        self.category_combo.configure(values=self._category_values())
        self.provider_combo.configure(values=self._provider_values())

    def _simple_catalog_editor(self, table, current_name=""):
        current = simpledialog.askstring("Catálogo", "Nombre:", initialvalue=current_name, parent=self)
        if not current:
            return None
        return current.strip()

    def _manage_category_add(self):
        if not require_permission('Inventario', 'editar', self, 'agregar categoría rápida en inventario'):
            return
        name = self._simple_catalog_editor('inventory_categories')
        if not name: return
        conn = db_connect(); cur = conn.cursor(); cur.execute("INSERT OR IGNORE INTO inventory_categories (name, created_at) VALUES (?, ?)", (name, datetime.now().isoformat(timespec='seconds'))); conn.commit(); conn.close(); self._refresh_option_lists(); self.vars['category'].set(name)

    def _manage_category_edit(self):
        if not require_permission('Inventario', 'editar', self, 'editar categoría rápida en inventario'):
            return
        old = self.vars['category'].get().strip()
        if not old:
            messagebox.showwarning("Categoría", "Selecciona o escribe una categoría primero.")
            return
        new = self._simple_catalog_editor('inventory_categories', old)
        if not new: return
        conn = db_connect(); cur = conn.cursor(); cur.execute("UPDATE inventory_categories SET name=? WHERE name=?", (new, old)); cur.execute("UPDATE inventory_items SET category=? WHERE category=?", (new, old)); conn.commit(); conn.close(); self._refresh_option_lists(); self.vars['category'].set(new); self._load_rows()

    def _manage_provider_add(self):
        if not require_permission('Inventario', 'editar', self, 'agregar proveedor rápido en inventario'):
            return
        name = self._simple_catalog_editor('providers')
        if not name: return
        conn = db_connect(); cur = conn.cursor(); cur.execute("INSERT OR IGNORE INTO providers (name, created_at) VALUES (?, ?)", (name, datetime.now().isoformat(timespec='seconds'))); conn.commit(); conn.close(); self._refresh_option_lists(); self.vars['provider'].set(name)

    def _manage_provider_edit(self):
        if not require_permission('Inventario', 'editar', self, 'editar proveedor rápido en inventario'):
            return
        old = self.vars['provider'].get().strip()
        if not old:
            messagebox.showwarning("Proveedor", "Selecciona o escribe un proveedor primero.")
            return
        new = self._simple_catalog_editor('providers', old)
        if not new: return
        conn = db_connect(); cur = conn.cursor(); cur.execute("UPDATE providers SET name=? WHERE name=?", (new, old)); cur.execute("UPDATE inventory_items SET provider=? WHERE provider=?", (new, old)); conn.commit(); conn.close(); self._refresh_option_lists(); self.vars['provider'].set(new); self._load_rows()

    def pick_photo(self):
        if not require_permission('Inventario', 'editar', self, 'seleccionar foto de producto'):
            return
        file_path = filedialog.askopenfilename(title="Seleccionar foto del producto", filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg;*.webp"), ("Todos", "*.*")])
        if file_path:
            self.photo_path.set(file_path)
            self._refresh_photo_preview()

    def reset_form(self):
        self.editing_item_id = None
        for key, var in self.vars.items():
            if key == "internal_code":
                var.set(self._next_internal_code())
            elif key == "item_type":
                var.set("Producto")
            elif key == "status":
                var.set("Activo")
            elif key in {"cost", "price", "stock", "min_stock"}:
                var.set("0.00")
            else:
                var.set("")
        self.photo_path.set("")
        self.obs.delete("1.0", tk.END)
        self._refresh_option_lists()
        self._refresh_stock_value_boxes()
        self._refresh_photo_preview()

    def _on_tree_double_click(self, event=None):
        if not require_permission('Inventario', 'editar', self, 'editar artículo de inventario'):
            return
        sel = self.tree.selection()
        if not sel: return
        code = self.tree.item(sel[0], 'values')[0]
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT id, internal_code, COALESCE(provider_code,''), COALESCE(sku_code,''), item_type, COALESCE(barcode,''), name, COALESCE(serial,''), COALESCE(provider,''), COALESCE(location,''), COALESCE(category,''), COALESCE(brand,''), cost, price, stock, min_stock, COALESCE(observations,''), COALESCE(photo_path,''), status FROM inventory_items WHERE internal_code=?", (code,))
        row = cur.fetchone(); conn.close()
        if not row: return
        (self.editing_item_id, internal_code, provider_code, sku_code, item_type, barcode, name, serial, provider, location, category, brand, cost, price, stock, min_stock, observations, photo_path, status) = row
        self.vars['internal_code'].set(internal_code or '')
        self.vars['provider_code'].set(provider_code or '')
        self.vars['sku_code'].set(sku_code or '')
        self.vars['item_type'].set(item_type or 'Producto')
        self.vars['barcode'].set(barcode or '')
        self.vars['name'].set(name or '')
        self.vars['serial'].set(serial or '')
        self.vars['provider'].set(provider or '')
        self.vars['location'].set(location or '')
        self.vars['category'].set(category or '')
        self.vars['brand'].set(brand or '')
        self.vars['cost'].set(f"{safe_float(cost):.2f}")
        self.vars['price'].set(f"{safe_float(price):.2f}")
        self.vars['stock'].set(f"{safe_float(stock):.2f}")
        self.vars['min_stock'].set(f"{safe_float(min_stock):.2f}")
        self.photo_path.set(photo_path or '')
        self.vars['status'].set(status or 'Activo')
        self.obs.delete('1.0', tk.END); self.obs.insert('1.0', observations or '')
        self._refresh_option_lists()
        self._refresh_stock_value_boxes()
        self._refresh_photo_preview()

    def save_item(self):
        needed = 'editar' if self.editing_item_id else 'crear'
        if not require_permission('Inventario', needed, self, 'guardar artículo de inventario'):
            return
        if not self.vars["name"].get().strip():
            messagebox.showwarning("Campo requerido", "Debes ingresar el nombre del producto o servicio.")
            return
        conn = db_connect(); cur = conn.cursor()
        payload = (
            self.vars["internal_code"].get().strip(),
            self.vars["provider_code"].get().strip(),
            self.vars["sku_code"].get().strip(),
            datetime.now().isoformat(timespec="seconds"),
            self.vars["item_type"].get().strip(),
            self.vars["barcode"].get().strip(),
            self.vars["name"].get().strip(),
            self.vars["serial"].get().strip(),
            self.vars["provider"].get().strip(),
            self.vars["location"].get().strip(),
            self.vars["category"].get().strip(),
            self.vars["brand"].get().strip(),
            safe_float(self.vars["cost"].get()),
            safe_float(self.vars["price"].get()),
            safe_float(self.vars["stock"].get()),
            safe_float(self.vars["min_stock"].get()),
            self.obs.get("1.0", tk.END).strip(),
            self.photo_path.get(),
            self.vars["status"].get().strip(),
        )
        if self.editing_item_id:
            cur.execute("""UPDATE inventory_items SET internal_code=?, provider_code=?, sku_code=?, item_type=?, barcode=?, name=?, serial=?, provider=?, location=?, category=?, brand=?, cost=?, price=?, stock=?, min_stock=?, observations=?, photo_path=?, status=? WHERE id=?""", (payload[0], payload[1], payload[2], payload[4], payload[5], payload[6], payload[7], payload[8], payload[9], payload[10], payload[11], payload[12], payload[13], payload[14], payload[15], payload[16], payload[17], payload[18], self.editing_item_id))
            msg = f"Registro {self.vars['internal_code'].get()} actualizado correctamente."
        else:
            cur.execute("""INSERT INTO inventory_items (internal_code, provider_code, sku_code, created_at, item_type, barcode, name, serial, provider, location, category, brand, cost, price, stock, min_stock, observations, photo_path, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", payload)
            msg = f"Registro {self.vars['internal_code'].get()} guardado correctamente."
        conn.commit(); conn.close()
        self._refresh_option_lists()
        messagebox.showinfo("Guardado", msg)
        self.reset_form(); self._load_rows()

    def _load_rows(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        term = self.search_var.get().strip().lower()
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT internal_code, COALESCE(provider_code,''), COALESCE(sku_code,''), item_type, name, COALESCE(provider,''), price, stock, COALESCE(barcode,''), status, cost FROM inventory_items ORDER BY id DESC LIMIT 300")
        rows = cur.fetchall(); cur.execute("SELECT COUNT(*) FROM inventory_items")
        total = cur.fetchone()[0]; conn.close()
        shown = 0
        total_stock = 0.0
        active_count = 0
        inventory_value = 0.0
        for code, provider_code, sku_code, item_type, name, provider, price, stock, barcode, status, cost in rows:
            searchable = f"{code} {provider_code} {sku_code} {name} {provider} {barcode}".lower()
            if term and term not in searchable:
                continue
            price_f = safe_float(price)
            stock_f = safe_float(stock)
            cost_f = safe_float(cost)
            self.tree.insert("", "end", values=(code, provider_code, sku_code, item_type, name, provider, f"Q {price_f:.2f}", f"{stock_f:.2f}"))
            shown += 1
            total_stock += stock_f
            inventory_value += cost_f * stock_f
            if (status or '').strip().lower() == 'activo':
                active_count += 1
        self.quick_total.configure(text=f"{shown} / {total} registros")
        if getattr(self, 'inventory_metric_values', None) and len(self.inventory_metric_values) >= 4:
            self.inventory_metric_values[0].configure(text=str(shown))
            self.inventory_metric_values[1].configure(text=f"Q {inventory_value:.2f}")
            self.inventory_metric_values[2].configure(text=f"{total_stock:.2f}")
            self.inventory_metric_values[3].configure(text=str(active_count))


def safe_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


if __name__ == "__main__":
    ensure_database()
    login = LoginWindow(authenticate_user=authenticate_user, system_version=SYSTEM_VERSION)
    if not login.valid:
        raise SystemExit
    SESSION_USER = login.username or "admin"
    SESSION_ROLE = login.role or "Administrador"
    SESSION_FULL_NAME = login.full_name or SESSION_USER
    SESSION_FORCE_PASSWORD_CHANGE = bool(login.force_password_change)
    app = App()
    if SESSION_FORCE_PASSWORD_CHANGE:
        changed = prompt_force_password_change(app, SESSION_USER)
        if not changed:
            app.destroy()
            raise SystemExit
    app.show_ready()
    try:
        app.after(120, app._maximize_on_start)
    except Exception:
        pass
    app.mainloop()
