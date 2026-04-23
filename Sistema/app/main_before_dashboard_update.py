import os
import sqlite3
import json
import textwrap
import subprocess
import sys
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

APP_NAME = "TECNOMEDIA GT Business Suite"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(BASE_DIR, "app")
ASSETS_DIR = os.path.join(APP_DIR, "assets")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "tecnomedia_gt_business_suite.sqlite3")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_tecnomedia_gt.png")


RESETTABLE_TABLES = [
    "sale_items",
    "sales",
    "cash_movements",
    "cash_sessions",
    "stock_movements",
    "technical_ticket_parts",
    "technical_tickets",
    "clients",
    "inventory_items",
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
                json.dump({"voucher": 1, "factura": 1}, fh, ensure_ascii=False, indent=2)
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
    conn.commit()
    conn.close()



def db_connect():
    return sqlite3.connect(DB_PATH)


def sales_pos_dir():
    path = os.path.join(DATA_DIR, "sales_pos")
    os.makedirs(path, exist_ok=True)
    return path


def load_sales_jsonl():
    rows = []
    path = os.path.join(sales_pos_dir(), "ventas.jsonl")
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


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

    fallback = []
    for row in load_sales_jsonl():
        fallback.append({
            "fecha": row.get("fecha", ""),
            "usuario": row.get("usuario", ""),
            "cliente": row.get("cliente", ""),
            "subtotal_val": safe_float(row.get("subtotal")),
            "descuento_val": safe_float(row.get("descuento")),
            "total_val": safe_float(row.get("total")),
            "metodo": (row.get("pago") or {}).get("metodo", ""),
            "tipo_documento": row.get("tipo_documento", ""),
            "correlativo": row.get("correlativo", ""),
            "estado": row.get("estado", "ACTIVA"),
        })
    return fallback


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
        self.title(APP_NAME)
        self.geometry("1440x880")
        self.minsize(1220, 760)
        try:
            self.state("zoomed")
        except Exception:
            pass
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
        self.show_module("Dashboard")

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
        self.style.configure("TButton", font=("Segoe UI", 10), padding=8)
        self.style.configure("Primary.TButton", background=accent, foreground="white")
        self.style.map("Primary.TButton", background=[("active", "#2563eb")])
        self.style.configure("Nav.TButton", background="#08111f", foreground="#e2e8f0", borderwidth=0, anchor="center", padding=(12, 10), font=("Segoe UI Semibold", 14))
        self.style.map("Nav.TButton", background=[("active", "#0f2547")], foreground=[("active", "white")])
        self.style.configure("SelectedNav.TButton", background="#11336e", foreground="white", borderwidth=0, anchor="center", padding=(12, 10), font=("Segoe UI Semibold", 14))
        self.style.map("SelectedNav.TButton", background=[("active", "#11336e")], foreground=[("active", "white")])
        self.style.configure("TEntry", fieldbackground=input_bg, foreground=fg)
        self.style.configure("TCombobox", fieldbackground=input_bg, foreground=fg)
        self.style.configure("Treeview", background=input_bg, fieldbackground=input_bg, foreground=fg, rowheight=26, borderwidth=0)
        self.style.configure("Treeview.Heading", background="#182235", foreground="#f8fafc", font=("Segoe UI Semibold", 10))
        self.style.map("Treeview", background=[("selected", "#1d4ed8")])
        self.option_add("*TCombobox*Listbox.background", input_bg)
        self.option_add("*TCombobox*Listbox.foreground", fg)

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

        self.nav_buttons = {}
        nav = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        nav.pack(fill="both", expand=True, padx=14, pady=(8, 8))
        for mod in MODULES:
            btn = ttk.Button(nav, text=mod, style="Nav.TButton", command=lambda m=mod: self.show_module(m))
            btn.pack(fill="x", pady=4)
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
        ttk.Label(right, text="Usuario: Administrador", style="SubHeader.TLabel").pack(anchor="e", pady=(4,0))

    def clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def show_module(self, module_name):
        self.selected_module.set(module_name)
        self.page_title.configure(text=module_name)
        subtitle_map = {
            "Dashboard": "Resumen general del negocio.",
            "Área Técnica": "Gestión de tickets, diagnósticos, anticipos y seguimiento.",
            "Clientes": "Registro comercial, crédito, descuentos y saldos por cliente.",
            "Inventario": "Productos y servicios con código interno, foto, stock y precios.",
            "Caja": "Apertura, movimientos y cierre de caja enlazados con ventas.",
            "Reportes": "Resumen comercial alimentado por ventas reales e inventario.",
            "Cibercafé y Consolas": "Control de PCs y consolas con tiempos, estados y cobro por uso.",
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
        elif module_name == "Clientes":
            ClientsView(self.content).grid(sticky="nsew")
        elif module_name == "Inventario":
            InventoryView(self.content).grid(sticky="nsew")
        elif module_name == "Caja":
            CashView(self.content).grid(sticky="nsew")
        elif module_name == "Reportes":
            ReportsView(self.content).grid(sticky="nsew")
        elif module_name == "Configuración":
            SettingsView(self.content, refresh_callback=lambda: self.show_module("Dashboard")).grid(sticky="nsew")
        else:
            PlaceholderView(self.content, module_name).grid(sticky="nsew")


class DashboardView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.columnconfigure((0,1,2,3), weight=1)
        self.rowconfigure(1, weight=1)

        stats = self._load_stats()
        cards = [
            ("Ventas hoy", stats["today_sales"], "Ventas activas registradas en el día"),
            ("Ingreso hoy", f"Q {stats['today_amount']:.2f}", "Total vendido hoy según el POS"),
            ("Inventario", stats["items"], "Productos y servicios registrados"),
            ("Stock bajo", stats["low_stock"], "Ítems por debajo del mínimo"),
        ]
        for i, (title, value, note) in enumerate(cards):
            card = ttk.Frame(self, style="Card.TFrame", padding=18)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i==0 else 8, 0), pady=(0, 12))
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text=str(value), style="CardValue.TLabel").pack(anchor="w", pady=(10, 6))
            ttk.Label(card, text=note, style="CardNote.TLabel", wraplength=220).pack(anchor="w")

        body = ttk.Frame(self, style="TFrame")
        body.grid(row=1, column=0, columnspan=4, sticky="nsew")
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Card.TFrame", padding=20)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        ttk.Label(left, text="Resumen operativo real", style="CardTitle.TLabel").pack(anchor="w")
        msg = (
            "El sistema ya está leyendo clientes, inventario, tickets y ahora también ventas reales desde la base local. "
            "El siguiente salto natural es seguir fortaleciendo caja y reportes sin tocar el diseño principal."
        )
        ttk.Label(left, text=textwrap.fill(msg, 96), style="CardNote.TLabel", wraplength=760).pack(anchor="w", pady=(12,18))

        metrics = [
            f"Clientes activos: {stats['clients']}",
            f"Tickets técnicos: {stats['tickets']}",
            f"Ventas activas acumuladas: {stats['sales_count']}",
            f"Monto acumulado vendido: Q {stats['sales_amount']:.2f}",
        ]
        for m in metrics:
            ttk.Label(left, text=f"• {m}", style="CardTitle.TLabel", wraplength=760).pack(anchor="w", pady=3)

        recent_card = ttk.Frame(left, style="Card.TFrame", padding=14)
        recent_card.pack(fill="both", expand=True, pady=(18, 0))
        ttk.Label(recent_card, text="Ventas recientes", style="CardTitle.TLabel").pack(anchor="w")
        cols = ("fecha", "cliente", "metodo", "total")
        tree = ttk.Treeview(recent_card, columns=cols, show="headings", height=8)
        headers = {"fecha": "Fecha", "cliente": "Cliente", "metodo": "Método", "total": "Total"}
        widths = {"fecha": 150, "cliente": 220, "metodo": 110, "total": 100}
        for col in cols:
            tree.heading(col, text=headers[col])
            tree.column(col, width=widths[col], anchor="w")
        tree.pack(fill="both", expand=True, pady=(10, 0))
        for row in stats["recent_sales"]:
            tree.insert("", "end", values=(row.get("fecha",""), row.get("cliente","Consumidor Final"), row.get("metodo",""), f"Q {safe_float(row.get('total_val')):.2f}"))

        right = ttk.Frame(body, style="Card.TFrame", padding=20)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Estado de integración", style="CardTitle.TLabel").pack(anchor="w")
        bullets = [
            "POS conectado a ventas en SQLite",
            "Descuento automático de stock por venta",
            "Caja preparada para apertura y cierre",
            "Reportes leyendo ventas reales",
            "Área técnica, clientes e inventario en la misma base",
        ]
        for b in bullets:
            ttk.Label(right, text=f"• {b}", style="CardTitle.TLabel", wraplength=300).pack(anchor="w", pady=6)

    def _load_stats(self):
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM technical_tickets")
        tickets = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM clients WHERE status='Activo'")
        clients = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM inventory_items")
        items = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM inventory_items WHERE item_type='Producto' AND stock <= min_stock")
        low_stock = cur.fetchone()[0]
        conn.close()
        s = sales_summary()
        return {
            "tickets": tickets,
            "clients": clients,
            "items": items,
            "low_stock": low_stock,
            "sales_count": s["count"],
            "sales_amount": s["amount"],
            "today_sales": s["today_count"],
            "today_amount": s["today_amount"],
            "recent_sales": s["recent"],
        }


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
            SalesHubView.POS_PROCESS = subprocess.Popen([sys.executable, target], cwd=base_dir)
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
        ttk.Button(controls, text="Abrir caja", style="Primary.TButton", command=self.open_session).pack(side="left", padx=(0,8))
        ttk.Button(controls, text="Cerrar caja", command=self.close_session).pack(side="left", padx=(0,8))
        ttk.Button(controls, text="Actualizar", command=self.refresh).pack(side="left")

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
        self.tree.grid(row=5, column=0, sticky="nsew")

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
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self, style="TFrame")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,10))
        ttk.Button(top, text="Actualizar reportes", command=self.refresh).pack(side="left")

        self.kpis = []
        for i in range(4):
            card = ttk.Frame(self, style="Card.TFrame", padding=16)
            card.grid(row=1, column=i % 2, sticky="nsew", padx=(0,10) if i % 2 == 0 else (0,0), pady=(0,10))
        # rebuilt in refresh into dedicated containers

        self.summary_left = ttk.Frame(self, style="Card.TFrame", padding=18)
        self.summary_left.grid(row=2, column=0, sticky="nsew", padx=(0,10))
        self.summary_right = ttk.Frame(self, style="Card.TFrame", padding=18)
        self.summary_right.grid(row=2, column=1, sticky="nsew")

        ttk.Label(self.summary_left, text="Productos más vendidos", style="CardTitle.TLabel").pack(anchor="w")
        cols = ("producto", "cantidad", "monto")
        self.products_tree = ttk.Treeview(self.summary_left, columns=cols, show="headings", height=12)
        for col, width, title in [("producto", 240, "Producto"), ("cantidad", 90, "Cantidad"), ("monto", 100, "Monto")]:
            self.products_tree.heading(col, text=title)
            self.products_tree.column(col, width=width, anchor="w")
        self.products_tree.pack(fill="both", expand=True, pady=(10,0))

        ttk.Label(self.summary_right, text="Ventas por método de pago", style="CardTitle.TLabel").pack(anchor="w")
        cols2 = ("metodo", "ventas", "monto")
        self.methods_tree = ttk.Treeview(self.summary_right, columns=cols2, show="headings", height=12)
        for col, width, title in [("metodo", 150, "Método"), ("ventas", 90, "Ventas"), ("monto", 110, "Monto")]:
            self.methods_tree.heading(col, text=title)
            self.methods_tree.column(col, width=width, anchor="w")
        self.methods_tree.pack(fill="both", expand=True, pady=(10,0))

        self.lbl_report_head = ttk.Label(self, text="", style="CardTitle.TLabel")
        self.lbl_report_head.grid(row=3, column=0, columnspan=2, sticky="w", pady=(12,0))

    def refresh(self):
        stats = sales_summary()
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
        finally:
            conn.close()

        for child in self.summary_left.winfo_children()[1:]:
            pass
        for item in self.products_tree.get_children():
            self.products_tree.delete(item)
        for item in self.methods_tree.get_children():
            self.methods_tree.delete(item)
        for name, qty, amount_row in product_rows:
            self.products_tree.insert("", "end", values=(name, f"{safe_float(qty):.2f}", f"Q {safe_float(amount_row):.2f}"))
        for method, ventas, amount_row in method_rows:
            self.methods_tree.insert("", "end", values=(method or 'sin método', int(ventas or 0), f"Q {safe_float(amount_row):.2f}"))

        top_user = user_rows[0][0] if user_rows else 'ADMIN'
        self.lbl_report_head.configure(text=f"Ventas activas: {count or 0} | Total vendido: Q {safe_float(amount):.2f} | Descuento otorgado: Q {total_discount:.2f} | Usuario líder: {top_user}")


class SettingsView(ttk.Frame):
    def __init__(self, parent, refresh_callback=None):
        super().__init__(parent, style="TFrame", padding=10)
        self.refresh_callback = refresh_callback

        wrap = ttk.Frame(self, style="TFrame")
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=1)

        general = ttk.Frame(wrap, style="Card.TFrame", padding=24)
        general.grid(row=0, column=0, sticky="ew")
        ttk.Label(general, text="Configuración", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            general,
            text=(
                "Módulo activado para tareas de mantenimiento y preparación del sistema. "
                "El botón inferior es temporal y sirve para dejar la base totalmente limpia antes de seguir trabajando sobre una sola fuente de datos."
            ),
            style="CardTitle.TLabel",
            wraplength=980,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

        danger = ttk.Frame(wrap, style="Card.TFrame", padding=24)
        danger.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        ttk.Label(danger, text="Reseteo total temporal", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            danger,
            text=(
                "Borra ventas, historial, reportes derivados, clientes, inventario, caja, tickets técnicos, movimientos y archivos auxiliares. "
                "También reinicia correlativos y limpia JSON/JSONL para que el sistema quede absolutamente en cero."
            ),
            style="CardTitle.TLabel",
            wraplength=980,
            justify="left",
        ).pack(anchor="w", pady=(12, 14))

        warn = tk.Label(
            danger,
            text="ADVERTENCIA: esta acción es irreversible y está pensada solo para esta etapa de limpieza.",
            bg="#111827",
            fg="#fca5a5",
            font=("Segoe UI Semibold", 11),
            anchor="w",
            justify="left",
        )
        warn.pack(fill="x", pady=(0, 14))

        tk.Button(
            danger,
            text="BORRAR ABSOLUTAMENTE TODOS LOS REGISTROS",
            command=self._reset_everything,
            bg="#dc2626",
            fg="white",
            activebackground="#b91c1c",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=("Segoe UI Semibold", 13),
            cursor="hand2",
            padx=14,
            pady=14,
        ).pack(anchor="w")

    def _reset_everything(self):
        confirm_1 = messagebox.askyesno(
            "Confirmación",
            "Se borrarán todos los registros del sistema y se reiniciarán correlativos. ¿Deseas continuar?",
        )
        if not confirm_1:
            return
        confirm_2 = messagebox.askyesno(
            "Confirmación final",
            "Esta limpieza dejará ventas, reportes, clientes, inventario, caja y tickets en cero. Esta acción no se puede deshacer. ¿Confirmas el borrado total?",
        )
        if not confirm_2:
            return
        try:
            reset_all_business_data()
            messagebox.showinfo(
                "Proceso completado",
                "El sistema quedó limpio y reiniciado en cero. Ya puedes seguir trabajando sobre una sola base de datos.",
            )
            if self.refresh_callback:
                self.refresh_callback()
        except Exception as exc:
            messagebox.showerror("Error", f"No fue posible completar la limpieza total.\n\nDetalle: {exc}")
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
        ttk.Button(actions, text="Nuevo", command=self.reset_form).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Guardar", style="Primary.TButton", command=self.save_ticket).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Anular", command=self.not_implemented).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Reporte PDF", command=self.not_implemented).pack(side="left")

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
        ttk.Button(parts_card, text="Agregar repuesto", command=self.add_part_to_ticket).grid(row=1, column=2, sticky="ew", pady=(10,8))
        self.parts_listbox = tk.Listbox(parts_card, height=6, bg="#1f2937", fg="#e5e7eb", relief="flat", highlightthickness=0)
        self.parts_listbox.grid(row=2, column=0, columnspan=3, sticky="ew")
        ttk.Button(parts_card, text="Quitar seleccionado", command=self.remove_selected_part).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8,0))

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

    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.vars = {
            "client_code": tk.StringVar(value=self._next_client_code()),
            "name": tk.StringVar(),
            "nit": tk.StringVar(),
            "phone": tk.StringVar(),
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
        self._build()
        self._load_rows()

    def _build(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Card.TFrame", padding=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        for c in range(4):
            left.columnconfigure(c, weight=1)

        ttk.Label(left, text="Código cliente", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0,6))
        ttk.Entry(left, textvariable=self.vars["client_code"], state="readonly").grid(row=1, column=0, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(left, text="Estado", style="CardTitle.TLabel").grid(row=0, column=1, sticky="w", pady=(0,6))
        ttk.Combobox(left, textvariable=self.vars["status"], values=["Activo", "Inactivo"], state="readonly").grid(row=1, column=1, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(left, text="Permitir crédito", style="CardTitle.TLabel").grid(row=0, column=2, sticky="w", pady=(0,6))
        ttk.Checkbutton(left, variable=self.vars["allow_credit"], text="Habilitado").grid(row=1, column=2, sticky="w", pady=(0,10))

        fields = [
            ("Nombre", "name"), ("NIT", "nit"), ("Teléfono", "phone"), ("Email", "email"),
            ("Dirección", "address"), ("Dirección de envío", "shipping_address"), ("Departamento", "department"), ("URL red social", "social_url"),
            ("Descuento (%)", "discount"), ("Saldo a favor", "balance_favor"), ("Saldo disponible", "balance_available"), ("Saldo a deber", "balance_due"),
            ("Límite crédito", "credit_limit"),
        ]
        positions = [(2,0),(2,1),(2,2),(2,3),(4,0),(4,1),(4,2),(4,3),(6,0),(6,1),(6,2),(6,3),(8,0)]
        for (label, key), (r, c) in zip(fields, positions):
            ttk.Label(left, text=label, style="CardTitle.TLabel").grid(row=r, column=c, sticky="w", pady=(0,6))
            if key == "department":
                ttk.Combobox(left, textvariable=self.vars[key], values=self.DEPARTMENTS, state="readonly").grid(row=r+1, column=c, sticky="ew", padx=(0,8), pady=(0,10))
            else:
                ttk.Entry(left, textvariable=self.vars[key]).grid(row=r+1, column=c, sticky="ew", padx=(0,8), pady=(0,10))

        ttk.Label(left, text="Observaciones", style="CardTitle.TLabel").grid(row=10, column=0, columnspan=4, sticky="w", pady=(0,6))
        self.notes = tk.Text(left, height=4, bg="#1f2937", fg="#e5e7eb", insertbackground="white", relief="flat")
        self.notes.grid(row=11, column=0, columnspan=4, sticky="ew", pady=(0,10))

        actions = ttk.Frame(left, style="Card.TFrame")
        actions.grid(row=12, column=0, columnspan=4, sticky="ew", pady=(8,0))
        ttk.Button(actions, text="Nuevo", command=self.reset_form).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Guardar", style="Primary.TButton", command=self.save_client).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Actualizar listado", command=self._load_rows).pack(side="left")

        right = ttk.Frame(self, style="TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        stats = ttk.Frame(right, style="Card.TFrame", padding=16)
        stats.grid(row=0, column=0, sticky="ew", pady=(0,10))
        ttk.Label(stats, text="Resumen clientes", style="CardTitle.TLabel").pack(anchor="w")
        self.quick_total = ttk.Label(stats, text="0 clientes", style="CardValue.TLabel")
        self.quick_total.pack(anchor="w", pady=(10,0))
        ttk.Label(stats, text="Con crédito y saldos controlados", style="CardNote.TLabel").pack(anchor="w")

        list_card = ttk.Frame(right, style="Card.TFrame", padding=16)
        list_card.grid(row=1, column=0, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(0, weight=1)
        cols = ("code", "name", "phone", "credit", "due")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings")
        headings = {"code": "Código", "name": "Nombre", "phone": "Teléfono", "credit": "Crédito", "due": "Saldo a deber"}
        widths = {"code": 90, "name": 200, "phone": 110, "credit": 80, "due": 100}
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")

    def _next_client_code(self):
        conn = db_connect(); cur = conn.cursor(); cur.execute("SELECT id FROM clients ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close(); return f"CLI-{((row[0] + 1) if row else 1):05d}"

    def reset_form(self):
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

    def save_client(self):
        if not self.vars["name"].get().strip():
            messagebox.showwarning("Campo requerido", "Debes ingresar el nombre del cliente.")
            return
        conn = db_connect(); cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clients (
                client_code, created_at, name, nit, phone, email, address, shipping_address,
                department, social_url, discount, allow_credit, credit_limit,
                balance_favor, balance_available, balance_due, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.vars["client_code"].get(), datetime.now().isoformat(timespec="seconds"), self.vars["name"].get().strip(),
                self.vars["nit"].get().strip(), self.vars["phone"].get().strip(), self.vars["email"].get().strip(),
                self.vars["address"].get().strip(), self.vars["shipping_address"].get().strip(), self.vars["department"].get().strip(),
                self.vars["social_url"].get().strip(), safe_float(self.vars["discount"].get()), 1 if self.vars["allow_credit"].get() else 0,
                safe_float(self.vars["credit_limit"].get()), safe_float(self.vars["balance_favor"].get()), safe_float(self.vars["balance_available"].get()),
                safe_float(self.vars["balance_due"].get()), self.vars["status"].get().strip(), self.notes.get("1.0", tk.END).strip(),
            ),
        )
        conn.commit(); conn.close()
        messagebox.showinfo("Guardado", f"Cliente {self.vars['client_code'].get()} guardado correctamente.")
        self.reset_form(); self._load_rows()

    def _load_rows(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT client_code, name, phone, allow_credit, balance_due FROM clients ORDER BY id DESC LIMIT 100")
        rows = cur.fetchall(); cur.execute("SELECT COUNT(*) FROM clients")
        total = cur.fetchone()[0]; conn.close()
        for code, name, phone, allow_credit, due in rows:
            self.tree.insert("", "end", values=(code, name, phone or "", "Sí" if allow_credit else "No", f"Q {due:.2f}"))
        self.quick_total.configure(text=f"{total} clientes")


class InventoryView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="TFrame")
        self.photo_path = tk.StringVar(value="")
        self.vars = {
            "internal_code": tk.StringVar(value=self._next_internal_code()),
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
        self._build()
        self._load_rows()

    def _build(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Card.TFrame", padding=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        for c in range(4):
            left.columnconfigure(c, weight=1)

        ttk.Label(left, text="Código interno", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0,6))
        ttk.Entry(left, textvariable=self.vars["internal_code"]).grid(row=1, column=0, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(left, text="Tipo", style="CardTitle.TLabel").grid(row=0, column=1, sticky="w", pady=(0,6))
        ttk.Combobox(left, textvariable=self.vars["item_type"], values=["Producto", "Servicio"], state="readonly").grid(row=1, column=1, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Label(left, text="Estado", style="CardTitle.TLabel").grid(row=0, column=2, sticky="w", pady=(0,6))
        ttk.Combobox(left, textvariable=self.vars["status"], values=["Activo", "Inactivo"], state="readonly").grid(row=1, column=2, sticky="ew", padx=(0,8), pady=(0,10))

        fields = [
            ("Código de barras", "barcode"), ("Nombre", "name"), ("Serial", "serial"), ("Proveedor", "provider"),
            ("Ubicación", "location"), ("Categoría", "category"), ("Marca", "brand"), ("Costo", "cost"),
            ("Precio", "price"), ("Stock", "stock"), ("Stock mínimo", "min_stock"),
        ]
        positions = [(2,0),(2,1),(2,2),(2,3),(4,0),(4,1),(4,2),(6,0),(6,1),(6,2),(6,3)]
        for (label, key), (r, c) in zip(fields, positions):
            ttk.Label(left, text=label, style="CardTitle.TLabel").grid(row=r, column=c, sticky="w", pady=(0,6))
            ttk.Entry(left, textvariable=self.vars[key]).grid(row=r+1, column=c, sticky="ew", padx=(0,8), pady=(0,10))

        ttk.Label(left, text="Foto del producto", style="CardTitle.TLabel").grid(row=8, column=0, sticky="w", pady=(0,6))
        ttk.Entry(left, textvariable=self.photo_path, state="readonly").grid(row=9, column=0, columnspan=2, sticky="ew", padx=(0,8), pady=(0,10))
        ttk.Button(left, text="Seleccionar foto", command=self.pick_photo).grid(row=9, column=2, sticky="w", pady=(0,10))
        ttk.Button(left, text="Generar/Imprimir código interno", command=self.not_implemented).grid(row=9, column=3, sticky="ew", pady=(0,10))

        ttk.Label(left, text="Observación", style="CardTitle.TLabel").grid(row=10, column=0, columnspan=4, sticky="w", pady=(0,6))
        self.obs = tk.Text(left, height=4, bg="#1f2937", fg="#e5e7eb", insertbackground="white", relief="flat")
        self.obs.grid(row=11, column=0, columnspan=4, sticky="ew", pady=(0,10))

        actions = ttk.Frame(left, style="Card.TFrame")
        actions.grid(row=12, column=0, columnspan=4, sticky="ew", pady=(8,0))
        ttk.Button(actions, text="Nuevo", command=self.reset_form).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Guardar", style="Primary.TButton", command=self.save_item).pack(side="left", padx=(0,8))
        ttk.Button(actions, text="Actualizar listado", command=self._load_rows).pack(side="left")

        right = ttk.Frame(self, style="TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        stats = ttk.Frame(right, style="Card.TFrame", padding=16)
        stats.grid(row=0, column=0, sticky="ew", pady=(0,10))
        ttk.Label(stats, text="Resumen inventario", style="CardTitle.TLabel").pack(anchor="w")
        self.quick_total = ttk.Label(stats, text="0 registros", style="CardValue.TLabel")
        self.quick_total.pack(anchor="w", pady=(10,0))
        ttk.Label(stats, text="Productos y servicios en esta base", style="CardNote.TLabel").pack(anchor="w")

        list_card = ttk.Frame(right, style="Card.TFrame", padding=16)
        list_card.grid(row=1, column=0, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(0, weight=1)
        cols = ("code", "type", "name", "price", "stock")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings")
        headings = {"code": "Código", "type": "Tipo", "name": "Nombre", "price": "Precio", "stock": "Stock"}
        widths = {"code": 110, "type": 80, "name": 220, "price": 90, "stock": 90}
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")

    def _next_internal_code(self):
        conn = db_connect(); cur = conn.cursor(); cur.execute("SELECT id FROM inventory_items ORDER BY id DESC LIMIT 1")
        row = cur.fetchone(); conn.close(); return f"INT-{((row[0] + 1) if row else 1):06d}"

    def pick_photo(self):
        file_path = filedialog.askopenfilename(title="Seleccionar foto del producto", filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg;*.webp"), ("Todos", "*.*")])
        if file_path:
            self.photo_path.set(file_path)

    def reset_form(self):
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

    def not_implemented(self):
        messagebox.showinfo("Próxima versión", "La impresión de código interno quedó prevista para una siguiente versión estable.")

    def save_item(self):
        if not self.vars["name"].get().strip():
            messagebox.showwarning("Campo requerido", "Debes ingresar el nombre del producto o servicio.")
            return
        conn = db_connect(); cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO inventory_items (
                internal_code, created_at, item_type, barcode, name, serial, provider,
                location, category, brand, cost, price, stock, min_stock, observations,
                photo_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.vars["internal_code"].get().strip(), datetime.now().isoformat(timespec="seconds"), self.vars["item_type"].get().strip(),
                self.vars["barcode"].get().strip(), self.vars["name"].get().strip(), self.vars["serial"].get().strip(), self.vars["provider"].get().strip(),
                self.vars["location"].get().strip(), self.vars["category"].get().strip(), self.vars["brand"].get().strip(), safe_float(self.vars["cost"].get()),
                safe_float(self.vars["price"].get()), safe_float(self.vars["stock"].get()), safe_float(self.vars["min_stock"].get()),
                self.obs.get("1.0", tk.END).strip(), self.photo_path.get(), self.vars["status"].get().strip(),
            ),
        )
        conn.commit(); conn.close()
        messagebox.showinfo("Guardado", f"Registro {self.vars['internal_code'].get()} guardado correctamente.")
        self.reset_form(); self._load_rows()

    def _load_rows(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT internal_code, item_type, name, price, stock FROM inventory_items ORDER BY id DESC LIMIT 100")
        rows = cur.fetchall(); cur.execute("SELECT COUNT(*) FROM inventory_items")
        total = cur.fetchone()[0]; conn.close()
        for code, item_type, name, price, stock in rows:
            self.tree.insert("", "end", values=(code, item_type, name, f"Q {price:.2f}", f"{stock:.2f}"))
        self.quick_total.configure(text=f"{total} registros")


def safe_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


if __name__ == "__main__":
    ensure_database()
    app = App()
    app.mainloop()
