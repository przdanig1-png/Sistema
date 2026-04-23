
import tkinter as tk
import os
import base64
import json
import sqlite3
import getpass
from datetime import datetime, timedelta
from tkinter import ttk, messagebox, filedialog, simpledialog
try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

BG = "#071633"
PANEL = "#0b1f44"
CARD = "#16386b"
CARD_HOVER = "#1f4b8b"
TEXT = "#ffffff"
MUTED = "#b9c7e6"
ACCENT = "#20c997"
DANGER = "#ef4444"
FIELD = "#102750"
BORDER = "#244f89"

PRODUCTOS = []

CLIENTES = []

SESSION_USER = os.environ.get('TECNOMEDIA_SESSION_USER', os.environ.get('USERNAME') or getpass.getuser() or 'ADMIN')

def _db_path():
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'tecnomedia_gt_business_suite.sqlite3'))

def _user_has_permission(username, module, action='ver'):
    if not username:
        return False
    try:
        conn = sqlite3.connect(_db_path())
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(role, 'Vendedor') FROM system_users WHERE username=?", (username,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False
        role_name = row[0] or 'Vendedor'
        cur.execute("""
            SELECT p.module, p.action
            FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE r.name=?
        """, (role_name,))
        perms = {(m,a) for m,a in cur.fetchall()}
        cur.execute("""
            SELECT p.module, p.action, up.allowed
            FROM user_permissions up
            JOIN system_users su ON su.id = up.user_id
            JOIN permissions p ON p.id = up.permission_id
            WHERE su.username=?
        """, (username,))
        for m,a,allowed in cur.fetchall():
            if int(allowed or 0):
                perms.add((m,a))
            else:
                perms.discard((m,a))
        conn.close()
        return (module, action) in perms
    except Exception:
        return True

def _require_permission(module, action='ver', feature_name=None, parent=None, notify=True):
    allowed = _user_has_permission(SESSION_USER, module, action)
    if (not allowed) and notify:
        try:
            messagebox.showwarning('Permisos', f"No tienes permisos para {feature_name or (module + ' / ' + action)}.", parent=parent)
        except Exception:
            messagebox.showwarning('Permisos', f"No tienes permisos para {feature_name or (module + ' / ' + action)}.")
    return allowed

def _disable_button_if_denied(button, module, action='ver', feature_name=None):
    try:
        if not _require_permission(module, action, feature_name=feature_name, parent=button.winfo_toplevel(), notify=False):
            button.configure(state='disabled')
    except Exception:
        pass
    return button

def _safe_float(value):
    try:
        if isinstance(value, str):
            value = value.replace('Q', '').replace(',', '').strip()
        return float(value or 0)
    except Exception:
        return 0.0

def _mix_hex(color_a, color_b, factor=0.5):
    try:
        a = color_a.lstrip('#')
        b = color_b.lstrip('#')
        ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
        br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        r = round(ar * (1 - factor) + br * factor)
        g = round(ag * (1 - factor) + bg * factor)
        b = round(ab * (1 - factor) + bb * factor)
        return f'#{r:02x}{g:02x}{b:02x}'
    except Exception:
        return color_a


class POSApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TECNOMEDIA GT - POS Cliente Pro")
        try:
            self.state("zoomed")
        except Exception:
            self.geometry("1450x880")
        self.configure(bg=BG)
        self._payment_icons = self._load_payment_icons()

        self.carrito = []
        self._ensure_sqlite_schema()
        self.products_catalog = self._load_products_catalog()
        self.filtered_products = self.products_catalog[:]
        self.clients_catalog = []
        self._refresh_clients_catalog()
        self.cliente_actual = None
        self.logged_user = SESSION_USER
        self.employee_var = tk.StringVar(value=self.logged_user or "ADMIN")
        self.employee_name_selected = self.logged_user or "ADMIN"
        self.employees_catalog = []
        self.employee_combo = None

        self.columnconfigure(0, weight=4)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        self._build_left()
        self._build_right()
        self.render_products()
        self.refresh_clients()
        self.refresh_cart()

    

    def _load_payment_icons(self):
        icons = {}
        icon_dir = os.path.join(os.path.dirname(__file__), "assets", "payment")
        keys = ["efectivo", "credito", "saldo_favor", "deposito", "transferencia", "tarjeta"]
        for key in keys:
            path = os.path.join(icon_dir, f"{key}.png")
            if os.path.exists(path):
                try:
                    icons[key] = tk.PhotoImage(file=path)
                except Exception:
                    icons[key] = None
            else:
                icons[key] = None
        return icons

    
    def _soften_color(self, hex_color, factor=0.22):
        try:
            value = hex_color.lstrip("#")
            r = int(value[0:2], 16)
            g = int(value[2:4], 16)
            b = int(value[4:6], 16)
            r = int(r * factor + 7 * (1 - factor))
            g = int(g * factor + 22 * (1 - factor))
            b = int(b * factor + 51 * (1 - factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#102750"

    def _style_payment_button(self, btn, fill, border, selected=False):
        base_bg = _mix_hex(fill, "#0b1f44", 0.24) if not selected else _mix_hex(fill, "#ffffff", 0.07)
        hover_bg = _mix_hex(fill, "#ffffff", 0.24) if not selected else _mix_hex(fill, "#ffffff", 0.16)
        active_bg = _mix_hex(fill, "#000000", 0.18)
        edge = _mix_hex(border, "#ffffff", 0.56) if selected else _mix_hex(border, "#ffffff", 0.14)
        btn.configure(
            bg=base_bg,
            fg="#ffffff",
            activebackground=active_bg,
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=4 if selected else 1,
            highlightbackground=edge,
            highlightcolor=edge,
            padx=10,
            pady=11,
            cursor="hand2",
            compound="left",
            anchor="center",
            font=("Segoe UI Semibold", 10, "bold") if selected else ("Segoe UI Semibold", 10),
            width=1,
            wraplength=150,
        )
        btn._normal_bg = base_bg
        btn._hover_bg = hover_bg
        btn._active_bg = active_bg
        btn._edge = edge


    def _ensure_single_window(self, attr_name, title=None, width=None, height=None):
        existing = getattr(self, attr_name, None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                try:
                    existing.attributes("-topmost", True)
                    existing.after(500, lambda: existing.attributes("-topmost", False))
                except Exception:
                    pass
                return existing, False
        except Exception:
            pass

        win = tk.Toplevel(self)
        if title:
            win.title(title)
        if width and height:
            try:
                self._center_window(win, width, height)
            except Exception:
                win.geometry(f"{width}x{height}")
        setattr(self, attr_name, win)

        def _cleanup():
            try:
                setattr(self, attr_name, None)
            except Exception:
                pass
            try:
                self.lift()
                self.focus_force()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _cleanup)
        return win, True

    def _bring_window_front(self, win):
        try:
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                win.focus_force()
                try:
                    win.attributes("-topmost", True)
                    win.after(500, lambda: win.attributes("-topmost", False))
                except Exception:
                    pass
        except Exception:
            pass

    def _build_left(self):
        left = tk.Frame(self, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        tk.Label(left, text="VENTAS", bg=BG, fg=TEXT, font=("Arial", 24, "bold")).grid(row=0, column=0, sticky="w")

        search_wrap = tk.Frame(left, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        search_wrap.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        search_wrap.columnconfigure(0, weight=1)

        self.search_product_var = tk.StringVar()
        self.search_product_var.trace_add("write", self.on_search_products)

        product_entry = tk.Entry(
            search_wrap, textvariable=self.search_product_var,
            font=("Arial", 14), bg=PANEL, fg=TEXT,
            insertbackground=TEXT, relief="flat"
        )
        product_entry.grid(row=0, column=0, sticky="ew", padx=12, pady=12)

        outer = tk.Frame(left, bg=BG)
        outer.grid(row=2, column=0, sticky="nsew")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scroll.set)

        self.products_container = tk.Frame(self.canvas, bg=BG)
        self.products_window = self.canvas.create_window((0, 0), window=self.products_container, anchor="nw")

        self.products_container.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)


    def _build_right(self):
        right = tk.Frame(self, bg=PANEL, width=500)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        right.grid_propagate(False)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        employee_box = tk.Frame(right, bg="#102750", highlightthickness=1, highlightbackground=BORDER)
        employee_box.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        employee_box.columnconfigure(0, weight=1)
        employee_box.columnconfigure(1, weight=0)

        tk.Label(employee_box, text="USUARIO / VENDEDOR", bg="#102750", fg=TEXT, font=("Arial", 16, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        self.btn_reload_employees = tk.Button(
            employee_box, text="Recargar", command=self._refresh_employees_catalog,
            bg="#0ea5e9", fg=TEXT, font=("Arial", 10, "bold"),
            relief="flat", bd=0, padx=10, pady=5
        )
        self.btn_reload_employees.grid(row=0, column=1, sticky="e", padx=10)

        self.employee_combo = ttk.Combobox(employee_box, textvariable=self.employee_var, state="readonly", font=("Arial", 11))
        self.employee_combo.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 8), ipady=4)
        self.employee_combo.bind("<<ComboboxSelected>>", self.on_employee_selected)
        self._refresh_employees_catalog()

        self.lbl_employee_info = tk.Label(
            employee_box,
            text="Las ventas se registrarán automáticamente con el usuario logueado.",
            bg="#102750", fg=MUTED, font=("Arial", 10)
        )
        self.lbl_employee_info.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 4))

        self.lbl_employee_commission = tk.Label(
            employee_box,
            text="Comisión estimada venta actual: Q0.00",
            bg="#102750", fg="#93c5fd", font=("Arial", 10, "bold")
        )
        self.lbl_employee_commission.grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12))

        client_box = tk.Frame(right, bg="#102750", highlightthickness=1, highlightbackground=BORDER)
        client_box.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        client_box.columnconfigure(0, weight=1)
        client_box.columnconfigure(1, weight=1)

        tk.Label(client_box, text="CLIENTE", bg="#102750", fg=TEXT, font=("Arial", 18, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        self.btn_new_client = tk.Button(
            client_box, text="Nuevo cliente", command=self._nuevo_cliente_popup,
            bg="#16a34a", fg=TEXT, font=("Arial", 10, "bold"),
            relief="flat", bd=0, padx=10, pady=5
        )
        self.btn_new_client.grid(row=0, column=1, sticky="e", padx=10)
        _disable_button_if_denied(self.btn_new_client, 'Clientes', 'crear', 'crear cliente desde POS')

        self.search_client_var = tk.StringVar()
        self.search_client_var.trace_add("write", self.on_search_clients)

        client_search_wrap = tk.Frame(
            client_box,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BORDER,
            bd=0
        )
        client_search_wrap.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 8), columnspan=2)
        client_search_wrap.columnconfigure(0, weight=1)

        self.client_entry = tk.Entry(
            client_search_wrap,
            textvariable=self.search_client_var,
            font=("Arial", 14),
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0
        )
        self.client_entry.grid(row=0, column=0, sticky="ew", padx=10, pady=10, ipady=4)

        self.client_list = tk.Listbox(
            client_box, height=4, bg=FIELD, fg=TEXT, selectbackground="#305d9c",
            relief="flat", highlightthickness=0, font=("Arial", 11)
        )
        self.client_list.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10), columnspan=2)
        self.client_list.bind("<<ListboxSelect>>", self.select_client)

        self.lbl_nombre = tk.Label(client_box, text="Nombre: ---", bg="#102750", fg=TEXT, font=("Arial", 11, "bold"))
        self.lbl_nombre.grid(row=3, column=0, sticky="w", padx=12, pady=2, columnspan=2)

        self.lbl_nit = tk.Label(client_box, text="NIT: ---", bg="#102750", fg=MUTED, font=("Arial", 10))
        self.lbl_nit.grid(row=4, column=0, sticky="w", padx=12, pady=2)

        self.lbl_tel = tk.Label(client_box, text="Teléfono: ---", bg="#102750", fg=MUTED, font=("Arial", 10))
        self.lbl_tel.grid(row=4, column=1, sticky="e", padx=12, pady=2)

        self.lbl_credito = tk.Label(client_box, text="Crédito: ---", bg="#102750", fg=MUTED, font=("Arial", 10))
        self.lbl_credito.grid(row=5, column=0, sticky="w", padx=12, pady=2)

        self.lbl_desc = tk.Label(client_box, text="Descuento: 0%", bg="#102750", fg=MUTED, font=("Arial", 10))
        self.lbl_desc.grid(row=5, column=1, sticky="e", padx=12, pady=2)

        self.lbl_dir = tk.Label(client_box, text="Dirección: ---", bg="#102750", fg=MUTED, font=("Arial", 10))
        self.lbl_dir.grid(row=6, column=0, sticky="w", padx=12, pady=(2, 2), columnspan=2)

        self.lbl_saldo = tk.Label(client_box, text="Saldo a deber: Q0.00 | Saldo a favor: Q0.00", bg="#102750", fg=MUTED, font=("Arial", 10))
        self.lbl_saldo.grid(row=7, column=0, sticky="w", padx=12, pady=(2, 12), columnspan=2)

        top_actions = tk.Frame(right, bg=PANEL)
        top_actions.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 6))
        tk.Label(top_actions, text="CARRITO", bg=PANEL, fg=TEXT, font=("Arial", 20, "bold")).pack(side="left")
        self.btn_history = tk.Button(
            top_actions, text="Historial de ventas", command=self.open_sales_history,
            bg="#2563eb", fg=TEXT, activebackground="#1d4ed8", activeforeground=TEXT,
            font=("Arial", 10, "bold"), relief="flat", bd=0, padx=12, pady=8
        )
        self.btn_history.pack(side="right")
        self.btn_reports = tk.Button(
            top_actions, text="Reportes", command=self.open_reports,
            bg="#0ea5e9", fg=TEXT, activebackground="#0284c7", activeforeground=TEXT,
            font=("Arial", 10, "bold"), relief="flat", bd=0, padx=12, pady=8
        )
        self.btn_reports.pack(side="right", padx=(0, 8))
        _disable_button_if_denied(self.btn_history, 'Ventas', 'ver', 'historial de ventas')
        _disable_button_if_denied(self.btn_reports, 'Reportes', 'ver', 'reportes de ventas')

        cart_wrap = tk.Frame(right, bg="#102750")
        cart_wrap.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 10))
        cart_wrap.rowconfigure(0, weight=1)
        cart_wrap.columnconfigure(0, weight=1)

        columns = ("producto", "cantidad", "precio", "subtotal")
        self.tree = ttk.Treeview(cart_wrap, columns=columns, show="headings", height=10)
        self.tree.heading("producto", text="Producto")
        self.tree.heading("cantidad", text="Cant.")
        self.tree.heading("precio", text="Precio")
        self.tree.heading("subtotal", text="Subtotal")
        self.tree.column("producto", width=180, anchor="w")
        self.tree.column("cantidad", width=60, anchor="center")
        self.tree.column("precio", width=85, anchor="e")
        self.tree.column("subtotal", width=95, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", background="#102750", fieldbackground="#102750", foreground=TEXT, rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background="#17396d", foreground=TEXT, relief="flat")
        style.map("Treeview", background=[("selected", "#305d9c")])

        edit = tk.Frame(right, bg=PANEL)
        edit.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 8))
        edit.columnconfigure(1, weight=1)
        edit.columnconfigure(2, weight=1)

        tk.Label(edit, text="Cantidad:", bg=PANEL, fg=MUTED, font=("Arial", 12)).grid(row=0, column=0, sticky="w")
        self.qty_var = tk.StringVar(value="1")
        self.qty_entry = tk.Entry(edit, textvariable=self.qty_var, font=("Arial", 12), width=8, justify="center")
        self.qty_entry.grid(row=0, column=1, sticky="w", padx=(8, 16))
        self.qty_entry.bind("<Return>", self.apply_qty)
        self.qty_entry.bind("<KeyRelease>", self.apply_qty)

        tk.Button(
            edit, text="+1", command=self.add_one,
            bg="#334155", fg=TEXT, activebackground="#475569", activeforeground=TEXT,
            font=("Arial", 11, "bold"), relief="flat", bd=0, pady=4
        ).grid(row=0, column=2, sticky="ew")

        totals = tk.Frame(right, bg=PANEL)
        totals.grid(row=5, column=0, sticky="ew", padx=18)
        totals.columnconfigure(1, weight=1)

        tk.Label(totals, text="Subtotal:", bg=PANEL, fg=MUTED, font=("Arial", 12)).grid(row=0, column=0, sticky="w")
        self.lbl_subtotal = tk.Label(totals, text="Q0.00", bg=PANEL, fg=TEXT, font=("Arial", 12, "bold"))
        self.lbl_subtotal.grid(row=0, column=1, sticky="e")

        tk.Label(totals, text="Descuento:", bg=PANEL, fg=MUTED, font=("Arial", 12)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.lbl_discount_amt = tk.Label(totals, text="Q0.00", bg=PANEL, fg="#f59e0b", font=("Arial", 12, "bold"))
        self.lbl_discount_amt.grid(row=1, column=1, sticky="e", pady=(4, 0))

        tk.Label(totals, text="Total:", bg=PANEL, fg=TEXT, font=("Arial", 16, "bold")).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.lbl_total = tk.Label(totals, text="Q0.00", bg=PANEL, fg=ACCENT, font=("Arial", 22, "bold"))
        self.lbl_total.grid(row=2, column=1, sticky="e", pady=(8, 0))

        btns = tk.Frame(right, bg=PANEL)
        btns.grid(row=6, column=0, sticky="ew", padx=18, pady=(12, 18))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        btns.columnconfigure(2, weight=1)

        self.btn_remove = tk.Button(btns, text="Eliminar", command=self.remove_selected,
                  bg="#7f1d1d", fg=TEXT, font=("Arial", 12, "bold"),
                  relief="flat", bd=0, pady=10)
        self.btn_remove.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.btn_clear = tk.Button(btns, text="Vaciar", command=self.clear_cart,
                  bg="#334155", fg=TEXT, font=("Arial", 12, "bold"),
                  relief="flat", bd=0, pady=10)
        self.btn_clear.grid(row=0, column=1, sticky="ew", padx=4)
        self.btn_charge = tk.Button(btns, text="Cobrar", command=self.cobrar,
                  bg=ACCENT, fg="#042032", font=("Arial", 12, "bold"),
                  relief="flat", bd=0, pady=10)
        self.btn_charge.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        _disable_button_if_denied(self.btn_remove, 'Ventas', 'editar', 'editar carrito de venta')
        _disable_button_if_denied(self.btn_clear, 'Ventas', 'editar', 'vaciar carrito')
        _disable_button_if_denied(self.btn_charge, 'Ventas', 'crear', 'cobrar venta')

    def refresh_clients(self):
        self.client_list.delete(0, tk.END)
        for c in self.filtered_clients:
            self.client_list.insert(tk.END, f'{c["nombre"]} | NIT: {c["nit"]}')

    def select_client(self, event=None):
        sel = self.client_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.cliente_actual = self.filtered_clients[idx]
        c = self.cliente_actual

        self.lbl_nombre.config(text=f'Nombre: {c["nombre"]}')
        self.lbl_nit.config(text=f'NIT: {c["nit"]}')
        self.lbl_tel.config(text=f'Teléfono: {c["telefono"]}')
        self.lbl_credito.config(text=f'Crédito: {"Sí" if c["credito"] else "No"}')
        self.lbl_desc.config(text=f'Descuento: {c["descuento"]}%')
        self.lbl_saldo.config(text=f'Saldo a deber: Q{c["saldo_deber"]:.2f} | Saldo a favor: Q{c["saldo_favor"]:.2f}')
        self.refresh_cart()


    def on_search_products(self, *_):
        query = (self.search_product_var.get() or "").strip().lower()
        if not query:
            self.filtered_products = self.products_catalog[:]
            self.render_products()
            return

        filtered = []
        for product in self.products_catalog:
            if isinstance(product, dict):
                haystack = " ".join([
                    str(product.get("nombre", "")),
                    str(product.get("codigo", "")),
                    str(product.get("barcode", "")),
                    str(product.get("sku", "")),
                    str(product.get("codigo_proveedor", "")),
                    str(product.get("tipo", "")),
                ]).lower()
            else:
                try:
                    haystack = " ".join(str(x) for x in product).lower()
                except Exception:
                    haystack = ""
            if query in haystack:
                filtered.append(product)

        self.filtered_products = filtered
        self.render_products()


    def _on_canvas_configure(self, event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass


    def _on_left_inner_configure(self, event=None):
        try:
            if hasattr(self, "canvas"):
                self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass


    def on_search_clients(self, *_):
        query = (self.search_client_var.get() or "").strip().lower()
        if not query:
            self.filtered_clients = self.clients_catalog[:]
            self.refresh_clients()
            return

        filtered = []
        for client in self.clients_catalog:
            if isinstance(client, dict):
                haystack = " ".join([
                    str(client.get("nombre", "")),
                    str(client.get("nit", "")),
                    str(client.get("telefono", "")),
                    str(client.get("direccion", "")),
                ]).lower()
            else:
                try:
                    haystack = " ".join(str(x) for x in client).lower()
                except Exception:
                    haystack = ""
            if query in haystack:
                filtered.append(client)

        self.filtered_clients = filtered
        self.refresh_clients()

    def render_clients(self):
        self.refresh_clients()

    def render_products(self):
        for w in self.products_container.winfo_children():
            w.destroy()

        columns = 3
        for c in range(columns):
            self.products_container.columnconfigure(c, weight=1, uniform="prod")

        for idx, product in enumerate(self.filtered_products):
            if isinstance(product, dict):
                name = product.get("nombre", "Producto")
                price = _safe_float(product.get("precio"))
                stock = _safe_float(product.get("stock"))
                item_type = product.get("tipo", "Producto")
                origin = product.get("origen", "local")
            else:
                try:
                    name, price = product[:2]
                except Exception:
                    continue
                stock = 0.0
                item_type = "Producto"
                origin = "local"
                product = {
                    "codigo": "",
                    "tipo": item_type,
                    "nombre": name,
                    "precio": _safe_float(price),
                    "stock": stock,
                    "origen": origin,
                }

            r, c = divmod(idx, columns)
            card = tk.Frame(self.products_container, bg=CARD, highlightthickness=1, highlightbackground="#2a5ea5")
            card.grid(row=r, column=c, sticky="nsew", padx=8, pady=4)

            stock_text = ""
            if item_type == "Producto":
                stock_text = f"\nStock: {stock:.2f}" if origin == "sqlite" else "\nStock: --"
            subtitle = f"{item_type}{stock_text}"

            btn = tk.Button(
                card,
                text=f"{name}\nQ{price:.2f}\n{subtitle}",
                bg=CARD, fg=TEXT, activebackground=CARD_HOVER, activeforeground=TEXT,
                relief="flat", bd=0, font=("Arial", 15, "bold"),
                command=lambda p=product: self.add_product(p),
                cursor="hand2", justify="center", wraplength=180,
                padx=18, pady=24
            )
            btn.pack(fill="both", expand=True)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=CARD_HOVER))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=CARD))
    def add_product(self, product):
        if not isinstance(product, dict):
            try:
                name, price = product[:2]
            except Exception:
                messagebox.showerror("Producto", "No se pudo interpretar el producto seleccionado.")
                return
            product = {
                "codigo": "",
                "tipo": "Producto",
                "nombre": name,
                "precio": _safe_float(price),
                "stock": 0.0,
                "origen": "local",
            }
        nombre = product["nombre"]
        precio = _safe_float(product.get("precio"))
        stock = _safe_float(product.get("stock"))
        item_type = product.get("tipo", "Producto")
        if item_type == "Producto" and product.get("origen") == "sqlite" and stock <= 0:
            messagebox.showwarning("Inventario", f"{nombre} no tiene existencias disponibles.")
            return
        for idx, item in enumerate(self.carrito):
            if item["nombre"] == nombre:
                nueva_cantidad = item["cantidad"] + 1
                if item_type == "Producto" and product.get("origen") == "sqlite" and nueva_cantidad > stock:
                    messagebox.showwarning("Inventario", f"No puedes vender más de {stock:.2f} unidades de {nombre}.")
                    return
                item["cantidad"] = nueva_cantidad
                self.qty_var.set(str(item["cantidad"]))
                self.refresh_cart(select_index=idx)
                return

        self.carrito.append({
            "nombre": nombre,
            "precio": precio,
            "cantidad": 1,
            "codigo": product.get("codigo", ""),
            "tipo": item_type,
            "stock_disponible": stock,
            "origen": product.get("origen", "local"),
        })
        self.qty_var.set("1")
        self.refresh_cart(select_index=len(self.carrito)-1)


    def clear_cart(self):
        if not _require_permission('Ventas', 'editar', 'vaciar carrito', self):
            return
        self.carrito = []
        self.qty_var.set("1")
        self.refresh_cart()


    def _current_cart_total_value(self):
        try:
            total_txt = self.lbl_total.cget("text") if hasattr(self, "lbl_total") else ""
            total_val = _safe_float(total_txt)
            if total_val > 0:
                return round(total_val, 2)
        except Exception:
            pass
        try:
            return round(sum(_safe_float(item.get("precio")) * _safe_float(item.get("cantidad")) for item in (self.carrito or [])), 2)
        except Exception:
            return 0.0

    def cobrar(self):
        if not _require_permission('Ventas', 'crear', 'cobrar venta', self):
            return
        total_actual = self._current_cart_total_value()
        if total_actual <= 0:
            messagebox.showwarning('Venta', 'No puedes cobrar una venta en Q0.00. Agrega productos válidos antes de continuar.')
            return
        return self.go_pay()

    def refresh_cart(self, select_index=None):
        for item in self.tree.get_children():
            self.tree.delete(item)

        subtotal = 0.0
        for idx, item in enumerate(self.carrito):
            line_total = item["precio"] * item["cantidad"]
            subtotal += line_total
            self.tree.insert("", "end", iid=str(idx), values=(
                item["nombre"],
                item["cantidad"],
                f"Q{item['precio']:.2f}",
                f"Q{line_total:.2f}",
            ))

        discount_pct = self.cliente_actual["descuento"] if self.cliente_actual else 0
        discount_amt = subtotal * (discount_pct / 100.0)
        total = subtotal - discount_amt

        self.lbl_subtotal.config(text=f"Q{subtotal:.2f}")
        self.lbl_discount_amt.config(text=f"Q{discount_amt:.2f}")
        self.lbl_total.config(text=f"Q{total:.2f}")

        if select_index is not None and 0 <= select_index < len(self.carrito):
            iid = str(select_index)
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        try:
            self._refresh_employee_info()
        except Exception:
            pass

    def get_selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def on_tree_select(self, event=None):
        idx = self.get_selected_index()
        if idx is None:
            self.qty_var.set("1")
            return
        self.qty_var.set(str(self.carrito[idx]["cantidad"]))


    def apply_qty(self, event=None):
        idx = self.get_selected_index()
        if idx is None:
            return

        texto = self.qty_var.get().strip()
        if texto == "":
            return

        try:
            nueva = int(texto)
            if nueva <= 0:
                raise ValueError
        except ValueError:
            if event is None or getattr(event, "keysym", "") == "Return":
                messagebox.showerror("Cantidad", "Ingresa una cantidad válida mayor a 0.")
            return

        item = self.carrito[idx]
        limite = _safe_float(item.get("stock_disponible"))
        if item.get("tipo") == "Producto" and item.get("origen") == "sqlite" and nueva > limite:
            messagebox.showwarning("Inventario", f"No puedes vender más de {limite:.2f} unidades de {item['nombre']}.")
            return
        self.carrito[idx]["cantidad"] = nueva
        self.refresh_cart(select_index=idx)

    def add_one(self):
        idx = self.get_selected_index()
        if idx is None:
            return
        item = self.carrito[idx]
        limite = _safe_float(item.get("stock_disponible"))
        if item.get("tipo") == "Producto" and item.get("origen") == "sqlite" and item["cantidad"] + 1 > limite:
            messagebox.showwarning("Inventario", f"No puedes vender más de {limite:.2f} unidades de {item['nombre']}.")
            return
        self.carrito[idx]["cantidad"] += 1
        self.qty_var.set(str(self.carrito[idx]["cantidad"]))
        self.refresh_cart(select_index=idx)

    def remove_selected(self):
        if not _require_permission('Ventas', 'editar', 'editar carrito de venta', self):
            return
        idx = self.get_selected_index()
        if idx is None:
            return
        self.carrito.pop(idx)
        self.qty_var.set("1")
        next_idx = min(idx, len(self.carrito)-1) if self.carrito else None
        self.refresh_cart(select_index=next_idx)


    def _center_window(self, window, width=760, height=660):
        window.update_idletasks()
        sw = window.winfo_screenwidth()
        sh = window.winfo_screenheight()
        x = max((sw - width) // 2, 0)
        y = max((sh - height) // 2, 0)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _pick_image(self, target_var, label_widget=None, on_change=None):
        path = filedialog.askopenfilename(
            title="Seleccionar imagen",
            filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("Todos", "*.*")]
        )
        if path:
            target_var.set(path)
            if label_widget is not None:
                try:
                    label_widget.config(text=os.path.basename(path))
                except Exception:
                    pass
            if callable(on_change):
                try:
                    on_change(path)
                except Exception:
                    pass

    def _window_state_path(self):
        return os.path.join(self._base_dir(), "data", "ui_window_state.json")

    def _load_window_states(self):
        try:
            with open(self._window_state_path(), 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_window_states(self, data):
        try:
            os.makedirs(os.path.dirname(self._window_state_path()), exist_ok=True)
            with open(self._window_state_path(), 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _get_window_state(self, key):
        return self._load_window_states().get(key, {})

    def _persist_window_state(self, key, window):
        try:
            window.update_idletasks()
            geo = window.geometry()
            size, _, pos = geo.partition('+')
            w, h = size.split('x', 1)
            x, _, y = pos.partition('+')
            states = self._load_window_states()
            states[key] = {
                'width': max(int(w), 420),
                'height': max(int(h), 320),
                'x': int(x or 0),
                'y': int(y or 0),
            }
            self._save_window_states(states)
        except Exception:
            pass

    def _apply_saved_geometry(self, window, key, default_width, default_height):
        state = self._get_window_state(key)
        try:
            width = int(state.get('width', default_width))
            height = int(state.get('height', default_height))
            x = int(state.get('x', -1))
            y = int(state.get('y', -1))
        except Exception:
            width, height, x, y = default_width, default_height, -1, -1
        if x >= 0 and y >= 0:
            window.geometry(f"{max(width, 420)}x{max(height, 320)}+{x}+{y}")
        else:
            self._center_window(window, max(width, 420), max(height, 320))

    def _make_toggle_switch(self, parent, *, initial=False, command=None):
        holder = tk.Frame(parent, bg=PANEL, highlightthickness=0, bd=0)
        canvas = tk.Canvas(holder, width=52, height=28, bg=PANEL, bd=0, highlightthickness=0)
        canvas.pack()
        state = {'value': bool(initial)}

        def redraw():
            canvas.delete('all')
            on = state['value']
            track = '#22c55e' if on else '#334155'
            border = '#86efac' if on else '#64748b'
            knob = '#ffffff'
            canvas.create_round_rect = lambda x1, y1, x2, y2, r=14, **kw: canvas.create_polygon(
                x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2,
                x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1,
                smooth=True, splinesteps=36, **kw)
            canvas.create_round_rect(2, 3, 50, 25, r=12, fill=track, outline=border, width=1)
            knob_x = 37 if on else 15
            glow = '#bbf7d0' if on else '#cbd5e1'
            canvas.create_oval(knob_x-10, 4, knob_x+10, 24, fill=knob, outline=glow, width=1)

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

    def _attach_resizable_switch(self, modal, key, default_width, default_height, title_text):
        self._apply_saved_geometry(modal, key, default_width, default_height)
        modal.minsize(500 if key != 'tarjeta' else 760, 520 if key != 'tarjeta' else 620)
        modal.resizable(False, False)
        state = {'free': False, 'toast_job': None, 'hint_job': None}

        topbar = tk.Frame(modal, bg=PANEL)
        topbar.pack(fill='x', padx=16, pady=(10, 4))
        title_lbl = tk.Label(topbar, text=title_text, bg=PANEL, fg=TEXT, font=('Arial', 18, 'bold'))
        title_lbl.pack(side='left')
        right = tk.Frame(topbar, bg=PANEL)
        right.pack(side='right')
        hint_lbl = tk.Label(right, text='', bg=PANEL, fg='#86efac', font=('Segoe UI', 8, 'bold'))
        hint_lbl.pack(side='right', padx=(8, 0))
        tk.Label(right, text='Tamaño libre', bg=PANEL, fg=MUTED, font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))

        def clear_hint():
            hint_lbl.configure(text='')
            state['hint_job'] = None

        def show_saved_feedback():
            try:
                if state.get('hint_job'):
                    modal.after_cancel(state['hint_job'])
            except Exception:
                pass
            hint_lbl.configure(text='Guardado')
            state['hint_job'] = modal.after(1400, clear_hint)
            try:
                switch.pulse_saved()
            except Exception:
                pass
            existing = getattr(modal, '_save_toast', None)
            if existing is not None:
                try:
                    existing.destroy()
                except Exception:
                    pass
            toast = tk.Frame(modal, bg='#0f172a', highlightthickness=1, highlightbackground='#22c55e', bd=0)
            toast.place(relx=1.0, rely=1.0, x=-18, y=-18, anchor='se')
            tk.Label(toast, text='✔ Tamaño y posición guardados', bg='#0f172a', fg='#dcfce7', font=('Segoe UI', 9, 'bold')).pack(padx=12, pady=8)
            modal._save_toast = toast
            try:
                if state.get('toast_job'):
                    modal.after_cancel(state['toast_job'])
            except Exception:
                pass
            def _remove_toast():
                try:
                    toast.destroy()
                except Exception:
                    pass
                if getattr(modal, '_save_toast', None) is toast:
                    modal._save_toast = None
                state['toast_job'] = None
            state['toast_job'] = modal.after(1800, _remove_toast)

        def on_toggle(is_on):
            state['free'] = bool(is_on)
            try:
                modal.resizable(state['free'], state['free'])
            except Exception:
                pass
            if not state['free']:
                self._persist_window_state(key, modal)
                show_saved_feedback()
            else:
                clear_hint()
        switch = self._make_toggle_switch(right, initial=False, command=on_toggle)
        switch.pack(side='left')

        modal.bind('<Configure>', lambda e: (not state['free']) and self._persist_window_state(key, modal), add='+')
        modal.protocol('WM_DELETE_WINDOW', lambda: ((not state['free']) and self._persist_window_state(key, modal), modal.destroy()))
        return topbar

    def _small_field(self, parent, label_text, width=26, placeholder=""):
        wrap = tk.Frame(parent, bg=PANEL)
        tk.Label(wrap, text=label_text, bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="center", pady=(2, 6), padx=8)
        inner = tk.Frame(wrap, bg="#f8fafc", highlightthickness=1, highlightbackground="#d6deef")
        inner.pack(anchor="center", padx=8, pady=(0, 2))
        entry = tk.Entry(inner, width=width, justify="left", relief="flat", bd=0, font=("Segoe UI", 10), bg="#f8fafc", fg="#0f172a", insertbackground="#0f172a")
        entry.pack(anchor="center", padx=12, pady=7, ipady=1)
        if placeholder:
            entry.insert(0, placeholder)
            entry.configure(fg="#64748b")
            def _clear_placeholder(event=None):
                if entry.get().strip() == placeholder and entry.cget("fg") == "#64748b":
                    entry.delete(0, "end")
                    entry.configure(fg="#0f172a")
            def _restore_placeholder(event=None):
                if not entry.get().strip():
                    entry.delete(0, "end")
                    entry.insert(0, placeholder)
                    entry.configure(fg="#64748b")
            entry.bind("<FocusIn>", _clear_placeholder)
            entry.bind("<FocusOut>", _restore_placeholder)
        return wrap, entry


    def _small_file(self, parent, label_text):
        wrap = tk.Frame(parent, bg=PANEL)
        tk.Label(wrap, text=label_text, bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="center", pady=(2, 6), padx=8)
        var = tk.StringVar(value="")

        card = tk.Frame(wrap, bg="#0b1f3a", highlightthickness=1, highlightbackground="#233f67")
        card.pack(anchor="center", padx=10, pady=(0, 8))

        status_row = tk.Frame(card, bg="#0b1f3a")
        status_row.pack(fill="x", padx=10, pady=(10, 6))
        status_chip = tk.Label(status_row, text="Sin fotografía", bg="#173768", fg="#dbe7ff",
                               font=("Segoe UI", 8, "bold"), padx=10, pady=4)
        status_chip.pack(side="left")
        remove_btn = tk.Button(status_row, text="🗑", bg="#7f1d1d", fg="#ffffff", relief="flat", bd=0,
                               font=("Segoe UI Emoji", 10), padx=8, pady=3, cursor="hand2")
        remove_btn.pack(side="right")

        pick_area = tk.Frame(card, bg="#10294d", highlightthickness=2, highlightbackground="#4a658d",
                             width=248, height=188, cursor="hand2")
        pick_area.pack_propagate(False)
        pick_area.pack(anchor="center", padx=10, pady=(0, 10))

        preview_wrap = tk.Frame(pick_area, bg="#10294d")
        preview_wrap.place(relx=0.5, rely=0.42, anchor="center")
        preview_lbl = tk.Label(preview_wrap, bg="#10294d")
        preview_lbl.pack(pady=(0, 8))
        icon_lbl = tk.Label(preview_wrap, text="📷", bg="#10294d", fg="#dbe7ff", font=("Segoe UI Emoji", 24))
        icon_lbl.pack()
        shown = tk.Label(preview_wrap, text="Haz clic para adjuntar la fotografía", bg="#10294d", fg=TEXT,
                         width=24, wraplength=196, justify="center", font=("Segoe UI", 10, "bold"))
        shown.pack(padx=12, pady=(8, 2))
        hint_lbl = tk.Label(preview_wrap, text="Formatos permitidos: PNG, JPG, WEBP o BMP", bg="#10294d", fg="#8fb7ff",
                            wraplength=198, justify="center", font=("Segoe UI", 8))
        hint_lbl.pack(padx=12, pady=(0, 0))

        footer_bar = tk.Frame(pick_area, bg="#0d223f", height=34)
        footer_bar.pack(side="bottom", fill="x")
        footer_bar.pack_propagate(False)
        ready_lbl = tk.Label(footer_bar, text="○ Sin fotografía", bg="#0d223f", fg="#c7d7f7", font=("Segoe UI", 8, "bold"))
        ready_lbl.pack(side="left", padx=10, pady=7)
        change_btn = tk.Button(footer_bar, text="Adjuntar fotografía", bg="#2563eb", fg=TEXT, relief="flat", bd=0,
                               font=("Segoe UI", 9, "bold"), padx=12, pady=5, cursor="hand2")
        change_btn.pack(side="right", padx=8, pady=4)
        pick_area._preview_ref = None

        def _set_area_style(mode="normal"):
            if mode == "hover":
                card_bg = "#0d2444"
                area_bg = "#14345f"
                border_bg = "#7dd3fc"
                chip_bg = "#1d4ed8"
            elif mode == "loaded":
                card_bg = "#0b1f3a"
                area_bg = "#10294d"
                border_bg = "#60a5fa"
                chip_bg = "#166534"
            else:
                card_bg = "#0b1f3a"
                area_bg = "#10294d"
                border_bg = "#4a658d"
                chip_bg = "#173768"
            card.configure(bg=card_bg, highlightbackground="#233f67")
            status_row.configure(bg=card_bg)
            status_chip.configure(bg=chip_bg)
            pick_area.configure(bg=area_bg, highlightbackground=border_bg)
            preview_wrap.configure(bg=area_bg)
            preview_lbl.configure(bg=area_bg)
            icon_lbl.configure(bg=area_bg)
            shown.configure(bg=area_bg)
            hint_lbl.configure(bg=area_bg)

        def _apply(path=""):
            path = str(path or "").strip()
            if path and os.path.exists(path):
                var.set(path)
                status_chip.configure(text="Fotografía cargada", fg="#dcfce7")
                ready_lbl.configure(text="✔ Fotografía lista", fg="#dcfce7")
                shown.configure(text=os.path.basename(path), fg="#ffffff")
                hint_lbl.configure(text="Haz clic en cambiar fotografía para reemplazarla", fg="#a5d8ff")
                change_btn.configure(text="Cambiar fotografía")
                _set_area_style("loaded")
                img_ref = None
                if Image is not None and ImageTk is not None:
                    try:
                        img = Image.open(path).convert("RGBA")
                        img.thumbnail((152, 88))
                        img_ref = ImageTk.PhotoImage(img)
                    except Exception:
                        img_ref = None
                pick_area._preview_ref = img_ref
                if img_ref is not None:
                    preview_lbl.configure(image=img_ref, text="")
                    if icon_lbl.winfo_manager():
                        icon_lbl.pack_forget()
                else:
                    preview_lbl.configure(image="", text="")
                    if not icon_lbl.winfo_manager():
                        icon_lbl.pack()
            else:
                var.set("")
                status_chip.configure(text="Sin fotografía", fg="#dbe7ff")
                ready_lbl.configure(text="○ Sin fotografía", fg="#c7d7f7")
                shown.configure(text="Haz clic para adjuntar la fotografía", fg=TEXT)
                hint_lbl.configure(text="Formatos permitidos: PNG, JPG, WEBP o BMP", fg="#8fb7ff")
                change_btn.configure(text="Adjuntar fotografía")
                _set_area_style("normal")
                pick_area._preview_ref = None
                preview_lbl.configure(image="", text="")
                if not icon_lbl.winfo_manager():
                    icon_lbl.pack()

        def _open_picker(event=None):
            self._pick_image(var, shown, _apply)

        def _hover_on(event=None):
            _set_area_style("loaded" if var.get().strip() else "hover")

        def _hover_off(event=None):
            _set_area_style("loaded" if var.get().strip() else "normal")

        for widget in (pick_area, preview_wrap, preview_lbl, icon_lbl, shown, hint_lbl, footer_bar, ready_lbl):
            widget.bind("<Button-1>", _open_picker, add="+")
            widget.bind("<Enter>", _hover_on, add="+")
            widget.bind("<Leave>", _hover_off, add="+")

        change_btn.configure(command=_open_picker)
        remove_btn.configure(command=lambda: _apply(""))
        return wrap, var


    def _base_dir(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _db_path(self):
        return os.path.join(self._base_dir(), "data", "tecnomedia_gt_business_suite.sqlite3")

    def _db_connect(self):
        os.makedirs(os.path.dirname(self._db_path()), exist_ok=True)
        return sqlite3.connect(self._db_path())

    def _ensure_sqlite_schema(self):
        conn = self._db_connect()
        cur = conn.cursor()
        cur.execute("""
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
        """)
        cur.execute("""
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
        """)
        cur.execute("""
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
        """)
        cur.execute("""
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
        """)
        cur.execute("""
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('correlativo_voucher', '1')")
        cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('correlativo_factura', '1')")
        cur.execute("CREATE TABLE IF NOT EXISTS inventory_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'Activo', created_at TEXT NOT NULL)")
        cur.execute("CREATE TABLE IF NOT EXISTS providers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, phone TEXT, email TEXT, notes TEXT, status TEXT DEFAULT 'Activo', created_at TEXT NOT NULL)")
        cur.execute("CREATE TABLE IF NOT EXISTS client_balance_movements (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, client_code TEXT, client_name TEXT, movement_kind TEXT, payment_method TEXT, amount REAL DEFAULT 0, reference TEXT, authorization_no TEXT, card_last4 TEXT, support_photo TEXT, dpi_photo TEXT, notes TEXT)")

        def _ensure_column(table, column, decl):
            cur.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in cur.fetchall()}
            if column not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

        _ensure_column('clients', 'phone2', 'TEXT')
        _ensure_column('clients', 'dpi', 'TEXT')
        _ensure_column('inventory_items', 'provider_code', 'TEXT')
        _ensure_column('inventory_items', 'sku_code', 'TEXT')
        conn.commit()
        conn.close()

    def _load_products_catalog(self):
        products = []
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT internal_code, COALESCE(provider_code,''), COALESCE(sku_code,''), COALESCE(barcode,''), item_type, name, price, stock
                FROM inventory_items
                WHERE status='Activo'
                ORDER BY name COLLATE NOCASE
                """
            )
            rows = cur.fetchall()
            conn.close()
            for internal_code, provider_code, sku_code, barcode, item_type, name, price, stock in rows:
                products.append({
                    'codigo': internal_code or '',
                    'tipo': item_type or 'Producto',
                    'codigo_proveedor': provider_code or '',
                    'sku': sku_code or '',
                    'barcode': barcode or '',
                    'nombre': name,
                    'precio': _safe_float(price),
                    'stock': _safe_float(stock),
                    'origen': 'sqlite',
                })
        except Exception:
            products = []

        if products:
            return products

        return []

    def _load_clients_from_sqlite(self):
        loaded = []
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT name, nit, phone, address, allow_credit, discount, balance_due, balance_favor
                FROM clients
                WHERE status='Activo'
                ORDER BY name COLLATE NOCASE
                """
            )
            rows = cur.fetchall()
            conn.close()
            for name, nit, phone, address, allow_credit, discount, balance_due, balance_favor in rows:
                loaded.append({
                    'nombre': name or '',
                    'nit': nit or 'CF',
                    'telefono': phone or '',
                    'direccion': address or '',
                    'credito': bool(allow_credit),
                    'descuento': _safe_float(discount),
                    'saldo_deber': _safe_float(balance_due),
                    'saldo_favor': _safe_float(balance_favor),
                    'origen': 'sqlite',
                })
        except Exception:
            pass
        return loaded

    def _sync_new_client_to_sqlite(self, cliente):
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            nombre = (cliente.get('nombre') or '').strip()
            if not nombre:
                conn.close()
                return
            cur.execute("SELECT id FROM clients WHERE lower(name)=lower(?) LIMIT 1", (nombre,))
            if cur.fetchone():
                conn.close()
                return
            cur.execute("SELECT id FROM clients ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            code = f"CLI-{((row[0] + 1) if row else 1):06d}"
            cur.execute(
                """
                INSERT INTO clients (
                    client_code, created_at, name, nit, phone, address, discount, allow_credit,
                    balance_favor, balance_available, balance_due, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Activo', ?)
                """,
                (
                    code,
                    datetime.now().isoformat(timespec='seconds'),
                    nombre,
                    cliente.get('nit') or 'CF',
                    cliente.get('telefono') or '',
                    cliente.get('direccion') or '',
                    _safe_float(cliente.get('descuento')),
                    1 if cliente.get('credito') else 0,
                    _safe_float(cliente.get('saldo_favor')),
                    max(0.0, _safe_float(cliente.get('saldo_favor')) - _safe_float(cliente.get('saldo_deber'))),
                    _safe_float(cliente.get('saldo_deber')),
                    'Creado desde POS',
                )
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _refresh_clients_catalog(self):
        self.clients_catalog = self._load_clients_from_sqlite()
        self.filtered_clients = self.clients_catalog[:]

    def _load_employees_from_sqlite(self):
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT employee_code, full_name, commission_rate, position, status
                FROM employees
                WHERE COALESCE(status, 'Activo') = 'Activo'
                ORDER BY full_name COLLATE NOCASE
                """
            )
            rows = cur.fetchall()
            conn.close()
            return [
                {
                    "employee_code": row[0] or "",
                    "full_name": row[1] or "",
                    "commission_rate": _safe_float(row[2]),
                    "position": row[3] or "",
                    "status": row[4] or "Activo",
                }
                for row in rows
            ]
        except Exception:
            return []


    def _ensure_logged_user_employee(self):
        user = (self.logged_user or "ADMIN").strip() or "ADMIN"
        # Match by employee_code or full_name
        for emp in self.employees_catalog:
            if (emp.get("employee_code","").strip().lower() == user.lower()) or (emp.get("full_name","").strip().lower() == user.lower()):
                return emp

        # Auto-create safe employee record if not found
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            code_base = re.sub(r"[^A-Z0-9]", "", user.upper())[:12] or "AUTOUSER"
            employee_code = f"USR-{code_base}"
            suffix = 1
            while True:
                cur.execute("SELECT id FROM employees WHERE employee_code=?", (employee_code,))
                if not cur.fetchone():
                    break
                suffix += 1
                employee_code = f"USR-{code_base[:8]}{suffix}"
            cur.execute("""
                INSERT INTO employees (
                    employee_code, created_at, full_name, dpi, phone, address, position, hire_date,
                    status, base_salary, pay_frequency, commission_rate, notes
                ) VALUES (?, ?, ?, '', '', '', 'Vendedor', ?, 'Activo', 0, 'Mensual', 0, ?)
            """, (
                employee_code,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user,
                datetime.now().strftime("%Y-%m-%d"),
                "Creado automáticamente desde POS por usuario logueado"
            ))
            conn.commit()
            conn.close()
        except Exception:
            return {"employee_code": user, "full_name": user, "position": "Vendedor", "commission_rate": 0}

        self.employees_catalog = self._load_employees_from_sqlite()
        for emp in self.employees_catalog:
            if (emp.get("employee_code","").strip().lower() == employee_code.lower()):
                return emp
        return {"employee_code": user, "full_name": user, "position": "Vendedor", "commission_rate": 0}

    def _current_employee_record(self):
        user = (self.logged_user or "ADMIN").strip() or "ADMIN"
        for emp in self.employees_catalog:
            if (emp.get("employee_code","").strip().lower() == user.lower()) or (emp.get("full_name","").strip().lower() == user.lower()):
                return emp
        return None

    def _current_cart_total(self):
        total = 0.0
        for item in self.carrito:
            try:
                total += _safe_float(item.get("precio")) * _safe_float(item.get("cantidad", 1))
            except Exception:
                pass
        discount_pct = self.cliente_actual["descuento"] if self.cliente_actual else 0
        try:
            total -= total * (_safe_float(discount_pct) / 100.0)
        except Exception:
            pass
        return max(total, 0.0)

    def _refresh_employee_info(self):
        emp = self._current_employee_record()
        if emp:
            self.employee_name_selected = emp.get("full_name") or (self.logged_user or "ADMIN")
            rate = _safe_float(emp.get("commission_rate"))
            position = emp.get("position") or "Sin cargo"
            info_text = f"Usuario/Vendedor: {self.employee_name_selected} | Cargo: {position} | Comisión: {rate:.2f}%"
            estimated = self._current_cart_total() * (rate / 100.0)
        else:
            self.employee_name_selected = self.logged_user or "ADMIN"
            info_text = f"Usuario/Vendedor: {self.employee_name_selected}"
            estimated = 0.0

        if hasattr(self, "lbl_employee_info"):
            try:
                self.lbl_employee_info.config(text=info_text)
            except Exception:
                pass
        if hasattr(self, "lbl_employee_commission"):
            try:
                self.lbl_employee_commission.config(text=f"Comisión estimada venta actual: Q{estimated:.2f}")
            except Exception:
                pass

    def _refresh_employees_catalog(self):
        self.employees_catalog = self._load_employees_from_sqlite()
        emp = self._ensure_logged_user_employee()
        values = [f"{emp.get('employee_code','USR')} | {emp.get('full_name', self.logged_user or 'ADMIN')}"]
        self.employee_var.set(values[0])
        self.employee_name_selected = emp.get("full_name") or (self.logged_user or "ADMIN")
        if self.employee_combo is not None:
            try:
                self.employee_combo["values"] = values
                self.employee_combo.state(["disabled"])
            except Exception:
                pass
        self._refresh_employee_info()

    def on_employee_selected(self, event=None):
        self._refresh_employees_catalog()


    def _data_dir(self):
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sales_pos")
        os.makedirs(base, exist_ok=True)
        return base

    def _save_sale_record(self, record):
        return

    def _save_audit_record(self, text):
        audit_path = os.path.join(self._data_dir(), "auditoria.log")
        with open(audit_path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    def _get_setting(self, key, default=""):
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            cur.execute("SELECT value FROM app_settings WHERE key=?", (key,))
            row = cur.fetchone()
            conn.close()
            return row[0] if row and row[0] is not None else default
        except Exception:
            return default

    def _set_setting(self, key, value):
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _next_correlativo(self, kind):
        setting_key = 'correlativo_voucher' if kind == 'voucher' else 'correlativo_factura'
        prefix = 'T' if kind == 'voucher' else 'F'
        conn = self._db_connect()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, '1')", (setting_key,))
        cur.execute("SELECT value FROM app_settings WHERE key=?", (setting_key,))
        row = cur.fetchone()
        try:
            current = int((row[0] if row else '1') or '1')
        except Exception:
            current = 1
        correlativo = f"{prefix}-{current:06d}"
        cur.execute("UPDATE app_settings SET value=? WHERE key=?", (str(current + 1), setting_key))
        conn.commit()
        conn.close()
        return correlativo

    
    
    
    def _get_active_cash_session_id(self):
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            cur.execute("SELECT id FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    def _validate_cart_stock(self):
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            for item in self.carrito:
                if item.get('tipo') != 'Producto' or item.get('origen') != 'sqlite' or not item.get('codigo'):
                    continue
                cur.execute("SELECT stock FROM inventory_items WHERE internal_code=? LIMIT 1", (item['codigo'],))
                row = cur.fetchone()
                current_stock = _safe_float(row[0] if row else 0)
                if item['cantidad'] > current_stock:
                    conn.close()
                    messagebox.showwarning('Inventario', f"Stock insuficiente para {item['nombre']}. Disponible: {current_stock:.2f}")
                    return False
            conn.close()
            return True
        except Exception:
            return True

    def _persist_sale_to_sqlite(self, registro):
        conn = self._db_connect()
        cur = conn.cursor()
        subtotal_val = _safe_float(registro.get('subtotal'))
        descuento_val = _safe_float(registro.get('descuento'))
        total_val = _safe_float(registro.get('total'))
        payment_method = (registro.get('pago') or {}).get('metodo', '')
        cur.execute(
            """
            INSERT INTO sales (
                created_at, user_name, customer_name, customer_nit, subtotal, discount_amount, total,
                payment_method, document_type, correlativo, status, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                registro.get('fecha') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                registro.get('usuario') or 'ADMIN',
                (registro.get('cliente_detalle') or {}).get('nombre') or registro.get('cliente') or '',
                (registro.get('cliente_detalle') or {}).get('nit') or '',
                subtotal_val,
                descuento_val,
                total_val,
                payment_method,
                registro.get('tipo_documento') or 'guardar',
                registro.get('correlativo') or '',
                registro.get('estado') or 'ACTIVA',
                json.dumps(registro, ensure_ascii=False),
            )
        )
        sale_id = cur.lastrowid

        for item in registro.get('items', []):
            qty = _safe_float(item.get('cantidad'))
            unit_price = _safe_float(item.get('precio'))
            line_total = qty * unit_price
            cur.execute(
                """
                INSERT INTO sale_items (sale_id, item_name, qty, unit_price, line_total, source_item_code, item_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sale_id, item.get('nombre',''), qty, unit_price, line_total, item.get('codigo',''), item.get('tipo','Producto'))
            )

            if item.get('tipo') == 'Producto' and item.get('origen') == 'sqlite' and item.get('codigo'):
                cur.execute(
                    "UPDATE inventory_items SET stock = COALESCE(stock, 0) - ? WHERE internal_code=?",
                    (qty, item.get('codigo'))
                )
                cur.execute(
                    """
                    INSERT INTO stock_movements (created_at, item_code, item_name, movement_type, qty, reference, notes)
                    VALUES (?, ?, ?, 'SALIDA_VENTA', ?, ?, ?)
                    """,
                    (registro.get('fecha'), item.get('codigo',''), item.get('nombre',''), qty, registro.get('correlativo') or '', f"Venta {payment_method}")
                )

        cliente = registro.get('cliente_detalle') or {}
        if cliente.get('nombre'):
            client_name = cliente.get('nombre','')
            if payment_method == 'credito':
                cur.execute(
                    """
                    UPDATE clients
                    SET balance_due = COALESCE(balance_due, 0) + ?,
                        balance_available = CASE
                            WHEN COALESCE(credit_limit, 0) - (COALESCE(balance_due, 0) + ?) < 0 THEN 0
                            ELSE COALESCE(credit_limit, 0) - (COALESCE(balance_due, 0) + ?)
                        END
                    WHERE lower(name)=lower(?)
                    """,
                    (total_val, total_val, total_val, client_name)
                )
                cur.execute(
                    """
                    INSERT INTO client_balance_movements (
                        created_at, client_code, client_name, movement_kind, payment_method, amount,
                        reference, authorization_no, card_last4, support_photo, dpi_photo, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', '', '', ?)
                    """,
                    (
                        registro.get('fecha'),
                        cliente.get('codigo',''),
                        client_name,
                        'CARGO_CREDITO_VENTA',
                        payment_method,
                        total_val,
                        registro.get('correlativo') or '',
                        f"Venta POS a crédito ({(registro.get('pago') or {}).get('credit_days', 0)} días)",
                    )
                )
            elif payment_method == 'saldo_favor':
                cur.execute(
                    """
                    UPDATE clients
                    SET balance_favor = CASE
                            WHEN COALESCE(balance_favor, 0) - ? < 0 THEN 0
                            ELSE COALESCE(balance_favor, 0) - ?
                        END,
                        balance_available = CASE
                            WHEN (CASE WHEN COALESCE(balance_favor, 0) - ? < 0 THEN 0 ELSE COALESCE(balance_favor, 0) - ? END) - COALESCE(balance_due, 0) < 0 THEN 0
                            ELSE (CASE WHEN COALESCE(balance_favor, 0) - ? < 0 THEN 0 ELSE COALESCE(balance_favor, 0) - ? END) - COALESCE(balance_due, 0)
                        END
                    WHERE lower(name)=lower(?)
                    """,
                    (total_val, total_val, total_val, total_val, total_val, total_val, client_name)
                )
                cur.execute(
                    """
                    INSERT INTO client_balance_movements (
                        created_at, client_code, client_name, movement_kind, payment_method, amount,
                        reference, authorization_no, card_last4, support_photo, dpi_photo, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', '', '', ?)
                    """,
                    (
                        registro.get('fecha'),
                        cliente.get('codigo',''),
                        client_name,
                        'USO_SALDO_FAVOR_VENTA',
                        payment_method,
                        total_val,
                        registro.get('correlativo') or '',
                        'Aplicación de saldo a favor en venta POS',
                    )
                )
            else:
                active_session = self._get_active_cash_session_id()
                if active_session and total_val > 0:
                    cur.execute(
                        """
                        INSERT INTO cash_movements (session_id, created_at, movement_type, payment_method, amount, reference, notes, sale_correlativo)
                        VALUES (?, ?, 'INGRESO_VENTA', ?, ?, ?, ?, ?)
                        """,
                        (active_session, registro.get('fecha'), payment_method, total_val, registro.get('correlativo') or '', f"Venta a {registro.get('cliente','Consumidor Final')}", registro.get('correlativo') or '')
                    )

        conn.commit()
        conn.close()

    def _load_sales_records_with_sqlite(self):
        return self._load_sales_records()

    def _cancel_sale_in_sqlite(self, registro):
        correlativo = str(registro.get('correlativo') or '').strip()
        sale_sqlite_id = registro.get('_sale_sqlite_id')
        if not sale_sqlite_id and not correlativo:
            return {'ok': False, 'reason': 'missing_reference'}
        conn = self._db_connect()
        cur = conn.cursor()
        if sale_sqlite_id:
            cur.execute("SELECT id, status, payment_method, total, customer_name, payload_json FROM sales WHERE id=? LIMIT 1", (sale_sqlite_id,))
        else:
            cur.execute("SELECT id, status, payment_method, total, customer_name, payload_json FROM sales WHERE correlativo=? ORDER BY id DESC LIMIT 1", (correlativo,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {'ok': False, 'reason': 'not_found'}
        sale_id, status, payment_method, total, customer_name, payload_json = row
        if str(status).upper() == 'ANULADA':
            conn.close()
            return {'ok': False, 'reason': 'already_cancelled'}

        now_txt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        motivo = str(registro.get('anulada_motivo') or '').strip()
        anulada_por = str(registro.get('anulada_por') or self.logged_user or SESSION_USER or 'ADMIN').strip() or 'ADMIN'

        db_record = {}
        if payload_json:
            try:
                db_record = json.loads(payload_json) or {}
            except Exception:
                db_record = {}
        if not isinstance(db_record, dict):
            db_record = {}
        db_record.update(registro or {})
        db_record['estado'] = 'ANULADA'
        db_record['anulada_por'] = anulada_por
        db_record['anulada_fecha'] = registro.get('anulada_fecha') or now_txt
        db_record['anulada_motivo'] = motivo

        cur.execute("UPDATE sales SET status='ANULADA', payload_json=? WHERE id=?", (json.dumps(db_record, ensure_ascii=False), sale_id))

        for item in db_record.get('items', []):
            qty = _safe_float(item.get('cantidad'))
            if qty <= 0:
                continue
            if item.get('tipo') == 'Producto' and item.get('origen') == 'sqlite' and item.get('codigo'):
                cur.execute(
                    "UPDATE inventory_items SET stock = COALESCE(stock, 0) + ? WHERE internal_code=?",
                    (qty, item.get('codigo'))
                )
                cur.execute(
                    """
                    INSERT INTO stock_movements (created_at, item_code, item_name, movement_type, qty, reference, notes)
                    VALUES (?, ?, ?, 'ENTRADA_ANULACION', ?, ?, ?)
                    """,
                    (
                        now_txt,
                        item.get('codigo',''),
                        item.get('nombre',''),
                        qty,
                        correlativo,
                        f"Reverso por anulación de venta{(': ' + motivo) if motivo else ''}",
                    )
                )

        pm = str(payment_method or db_record.get('pago', {}).get('metodo', '')).lower()
        total_val = _safe_float(total or db_record.get('total'))
        cliente = db_record.get('cliente_detalle') if isinstance(db_record.get('cliente_detalle'), dict) else {}
        client_code = cliente.get('codigo', '')
        customer_name = customer_name or cliente.get('nombre', '') or db_record.get('cliente', '')
        if pm == 'credito' and customer_name:
            cur.execute(
                """
                UPDATE clients
                SET balance_due = CASE
                        WHEN COALESCE(balance_due, 0) - ? < 0 THEN 0
                        ELSE COALESCE(balance_due, 0) - ?
                    END,
                    balance_available = CASE
                        WHEN COALESCE(credit_limit, 0) - (CASE
                            WHEN COALESCE(balance_due, 0) - ? < 0 THEN 0
                            ELSE COALESCE(balance_due, 0) - ?
                        END) < 0 THEN 0
                        ELSE COALESCE(credit_limit, 0) - (CASE
                            WHEN COALESCE(balance_due, 0) - ? < 0 THEN 0
                            ELSE COALESCE(balance_due, 0) - ?
                        END)
                    END
                WHERE lower(name)=lower(?)
                """,
                (total_val, total_val, total_val, total_val, total_val, total_val, customer_name)
            )
            cur.execute(
                """
                INSERT INTO client_balance_movements (
                    created_at, client_code, client_name, movement_kind, payment_method, amount,
                    reference, authorization_no, card_last4, support_photo, dpi_photo, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', '', '', ?)
                """,
                (now_txt, client_code, customer_name, 'REVERSO_CREDITO_VENTA_ANULADA', pm, total_val, correlativo, f'Anulación de venta a crédito{(": " + motivo) if motivo else ""}')
            )
        elif pm == 'saldo_favor' and customer_name:
            cur.execute(
                """
                UPDATE clients
                SET balance_favor = COALESCE(balance_favor, 0) + ?,
                    balance_available = CASE
                        WHEN (COALESCE(balance_favor, 0) + ?) - COALESCE(balance_due, 0) < 0 THEN 0
                        ELSE (COALESCE(balance_favor, 0) + ?) - COALESCE(balance_due, 0)
                    END
                WHERE lower(name)=lower(?)
                """,
                (total_val, total_val, total_val, customer_name)
            )
            cur.execute(
                """
                INSERT INTO client_balance_movements (
                    created_at, client_code, client_name, movement_kind, payment_method, amount,
                    reference, authorization_no, card_last4, support_photo, dpi_photo, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', '', '', ?)
                """,
                (now_txt, client_code, customer_name, 'REVERSO_USO_SALDO_FAVOR_VENTA_ANULADA', pm, total_val, correlativo, f'Reintegro por anulación de venta{(": " + motivo) if motivo else ""}')
            )
        else:
            mov = None
            if correlativo:
                cur.execute("SELECT id FROM cash_movements WHERE sale_correlativo=? ORDER BY id DESC LIMIT 1", (correlativo,))
                mov = cur.fetchone()
            if mov and total_val > 0:
                cur.execute(
                    """
                    INSERT INTO cash_movements (session_id, created_at, movement_type, payment_method, amount, reference, notes, sale_correlativo)
                    SELECT session_id, ?, 'SALIDA_ANULACION', payment_method, ?, ?, ?, sale_correlativo
                    FROM cash_movements WHERE id=?
                    """,
                    (
                        now_txt,
                        total_val,
                        correlativo,
                        f"Reverso por anulación de venta{(': ' + motivo) if motivo else ''}",
                        mov[0],
                    )
                )

        conn.commit()
        conn.close()
        return {'ok': True, 'sale_id': sale_id}

    def _render_document_window(self, kind, correlativo, registro):
        titulo = "Ticket" if kind == "voucher" else "Factura"
        attr_name = "_document_window"
        existing = getattr(self, attr_name, None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.destroy()
        except Exception:
            pass
        win = tk.Toplevel(self)
        setattr(self, attr_name, win)
        win.title(f"{titulo} {correlativo}")
        win.configure(bg=PANEL)
        try:
            self._center_window(win, 900 if kind == "factura" else 700, 860 if kind == "factura" else 820)
        except Exception:
            win.geometry("900x860" if kind == "factura" else "700x820")

        win.transient(self)
        win.grab_set()
        try:
            win.lift()
            win.focus_force()
            win.attributes("-topmost", True)
            win.after(900, lambda: win.attributes("-topmost", False))
        except Exception:
            pass

        outer = tk.Frame(win, bg=PANEL)
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        paper = tk.Frame(outer, bg="white", highlightthickness=1, highlightbackground="#222222")
        paper.pack(fill="both", expand=True)

        fecha = registro.get("fecha", "")
        usuario = registro.get("usuario", "")
        pago = registro.get("pago", {}) or {}
        cliente_detalle = registro.get("cliente_detalle", {}) if isinstance(registro.get("cliente_detalle", {}), dict) else {}
        cliente_nombre = registro.get("cliente", "")
        cliente_nit = cliente_detalle.get("nit", "CF") or "CF"
        cliente_dir = cliente_detalle.get("direccion", "CIUDAD") or "CIUDAD"

        # logo
        logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo_tecnomedia_gt.png")
        logo_photo = None
        try:
            logo_photo = tk.PhotoImage(file=logo_path)
            w = max(logo_photo.width(), 1)
            target = 180 if kind == "factura" else 140
            factor = max((w // target), 1)
            if factor > 1:
                logo_photo = logo_photo.subsample(factor, factor)
            win.logo_photo = logo_photo
        except Exception:
            logo_photo = None

        header = tk.Frame(paper, bg="white")
        header.pack(fill="x", padx=24, pady=(20, 12))

        if kind == "factura":
            header.columnconfigure(1, weight=1)
            logo_box = tk.Frame(header, bg="white")
            logo_box.grid(row=0, column=0, sticky="nw", padx=(0, 16))
            if logo_photo:
                tk.Label(logo_box, image=logo_photo, bg="white").pack(anchor="w")
            else:
                tk.Label(logo_box, text="TECNOMEDIA GT", bg="white", fg="black", font=("Arial", 16, "bold")).pack(anchor="w")

            info = tk.Frame(header, bg="white")
            info.grid(row=0, column=1, sticky="ne")
            tk.Label(info, text="TECNOMEDIA GT", bg="white", fg="black", font=("Arial", 20, "bold")).pack(anchor="e")
            tk.Label(info, text="15 CALLE 8 AVENIDA PUERTO BARRIOS, IZABAL", bg="white", fg="black", font=("Arial", 10)).pack(anchor="e")
            tk.Label(info, text="TEL: 31380850 / 54780043", bg="white", fg="black", font=("Arial", 10)).pack(anchor="e")
            tk.Label(info, text="NIT: 4509238-9", bg="white", fg="black", font=("Arial", 10, "bold")).pack(anchor="e")
            tk.Label(info, text=f"FACTURA No. {correlativo}", bg="white", fg="black", font=("Arial", 14, "bold")).pack(anchor="e", pady=(8, 0))
        else:
            if logo_photo:
                tk.Label(header, image=logo_photo, bg="white").pack()
            tk.Label(header, text="TECNOMEDIA GT", bg="white", fg="black", font=("Arial", 18, "bold")).pack()
            tk.Label(header, text="15 CALLE 8 AVENIDA PUERTO BARRIOS, IZABAL", bg="white", fg="black", font=("Arial", 10)).pack()
            tk.Label(header, text="TEL: 31380850 / 54780043", bg="white", fg="black", font=("Arial", 10)).pack()
            tk.Label(header, text="NIT: 4509238-9", bg="white", fg="black", font=("Arial", 10, "bold")).pack()
            tk.Label(header, text=f"TICKET No. {correlativo}", bg="white", fg="black", font=("Arial", 14, "bold")).pack(pady=(8, 0))

        meta = tk.Frame(paper, bg="white")
        meta.pack(fill="x", padx=24, pady=(0, 10))
        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)

        def meta_row(r, l1, v1, l2="", v2=""):
            tk.Label(meta, text=l1, bg="white", fg="black", font=("Arial", 10, "bold")).grid(row=r, column=0, sticky="w")
            tk.Label(meta, text=v1, bg="white", fg="black", font=("Arial", 10)).grid(row=r, column=1, sticky="w", padx=(6, 18))
            if l2:
                tk.Label(meta, text=l2, bg="white", fg="black", font=("Arial", 10, "bold")).grid(row=r, column=2, sticky="w")
                tk.Label(meta, text=v2, bg="white", fg="black", font=("Arial", 10)).grid(row=r, column=3, sticky="w", padx=(6, 0))

        meta_row(0, "Fecha:", fecha, "Vendedor:", usuario)
        meta_row(1, "Cliente:", cliente_nombre, "NIT:", cliente_nit)
        meta_row(2, "Dirección:", cliente_dir, "Pago:", str(pago.get("metodo", "")).upper())

        sep = tk.Frame(paper, bg="#d1d5db", height=1)
        sep.pack(fill="x", padx=24, pady=(0, 10))

        table = tk.Frame(paper, bg="white")
        table.pack(fill="both", expand=True, padx=24, pady=(0, 10))
        table.columnconfigure(1, weight=1)

        headers = [("CANT", 0, "w"), ("DESCRIPCIÓN", 1, "w"), ("PRECIO", 2, "e"), ("TOTAL", 3, "e")]
        for text, col, anc in headers:
            tk.Label(table, text=text, bg="white", fg="black", font=("Arial", 10, "bold")).grid(row=0, column=col, sticky=anc, pady=(0, 6), padx=(0, 8))

        items = registro.get("items", [])
        row = 1
        for it in items:
            nombre = str(it.get("nombre", it.get("producto", "")))
            cant = int(it.get("cantidad", 1) or 1)
            precio = float(it.get("precio", 0) or 0)
            line_total = precio * cant

            # wrap long descriptions into chunks
            chunks = [nombre[i:i+38] for i in range(0, len(nombre), 38)] or [""]
            tk.Label(table, text=str(cant), bg="white", fg="black", font=("Arial", 10)).grid(row=row, column=0, sticky="w", padx=(0, 8))
            tk.Label(table, text=chunks[0], bg="white", fg="black", font=("Arial", 10), anchor="w", justify="left").grid(row=row, column=1, sticky="w")
            tk.Label(table, text=f"Q{precio:.2f}", bg="white", fg="black", font=("Arial", 10), anchor="e").grid(row=row, column=2, sticky="e", padx=(8, 8))
            tk.Label(table, text=f"Q{line_total:.2f}", bg="white", fg="black", font=("Arial", 10), anchor="e").grid(row=row, column=3, sticky="e")
            row += 1
            for extra in chunks[1:]:
                tk.Label(table, text=extra, bg="white", fg="black", font=("Arial", 10), anchor="w", justify="left").grid(row=row, column=1, sticky="w")
                row += 1

        subtotal_txt = registro.get("subtotal", "Q0.00")
        descuento_txt = registro.get("descuento", "Q0.00")
        total_txt = registro.get("total", "Q0.00")

        sep2 = tk.Frame(paper, bg="#d1d5db", height=1)
        sep2.pack(fill="x", padx=24, pady=(4, 10))

        totals = tk.Frame(paper, bg="white")
        totals.pack(fill="x", padx=24, pady=(0, 10))
        totals.columnconfigure(0, weight=1)

        def total_row(label, value, size=11, bold=False, color="black"):
            fr = tk.Frame(totals, bg="white")
            fr.pack(fill="x", pady=2)
            tk.Label(fr, text=label, bg="white", fg="black", font=("Arial", size, "bold" if bold else "normal")).pack(side="left")
            tk.Label(fr, text=value, bg="white", fg=color, font=("Arial", size, "bold" if bold else "normal")).pack(side="right")

        total_row("SUBTOTAL", subtotal_txt)
        total_row("DESCUENTO", descuento_txt)
        total_row("TOTAL", total_txt, size=15, bold=True, color="#0f766e")
        if cliente_detalle:
            payment_balance_mode = str(pago.get('metodo', '') or '').strip().lower()
            before_due = _safe_float(pago.get('balance_due_before', cliente_detalle.get('saldo_deber', 0)))
            after_due = _safe_float(pago.get('balance_due_after', before_due))
            before_favor = _safe_float(pago.get('balance_favor_before', cliente_detalle.get('saldo_favor', 0)))
            after_favor = _safe_float(pago.get('balance_favor_after', before_favor))
            if payment_balance_mode == 'credito':
                total_row("SALDO DEBER ANTES", f"Q{before_due:.2f}")
                total_row("SALDO DEBER ACTUAL", f"Q{after_due:.2f}")
                if pago.get('credit_days'):
                    total_row("CRÉDITO A", f"{int(_safe_float(pago.get('credit_days')))} días")
                if pago.get('due_date'):
                    total_row("VENCE", str(pago.get('due_date')))
            elif payment_balance_mode == 'saldo_favor':
                total_row("SALDO A FAVOR ANTES", f"Q{before_favor:.2f}")
                total_row("SALDO A FAVOR ACTUAL", f"Q{after_favor:.2f}")

        bottom_note = tk.Frame(paper, bg="white")
        bottom_note.pack(fill="x", padx=24, pady=(6, 18))
        tk.Label(bottom_note, text=f"Impresa el: {fecha}", bg="white", fg="black", font=("Arial", 9)).pack()
        tk.Label(bottom_note, text="Gracias por su compra", bg="white", fg="black", font=("Arial", 10, "bold")).pack(pady=(4, 0))

        def imprimir():
            try:
                data_dir = self._data_dir()
                docs_dir = os.path.join(data_dir, "documentos")
                os.makedirs(docs_dir, exist_ok=True)

                # inline logo as base64
                logo_b64 = ""
                try:
                    with open(logo_path, "rb") as fh:
                        logo_b64 = base64.b64encode(fh.read()).decode("ascii")
                except Exception:
                    logo_b64 = ""

                item_rows = ""
                for it in items:
                    nombre = str(it.get("nombre", it.get("producto", "")))
                    cant = int(it.get("cantidad", 1) or 1)
                    precio = float(it.get("precio", 0) or 0)
                    line_total = precio * cant
                    item_rows += f"<tr><td>{cant}</td><td>{nombre}</td><td style='text-align:right'>Q{precio:.2f}</td><td style='text-align:right'>Q{line_total:.2f}</td></tr>"

                logo_html = f"<img src='data:image/png;base64,{logo_b64}' style='max-width:{220 if kind=='factura' else 160}px; display:block; margin:0 auto 10px auto;' />" if logo_b64 else ""
                title_html = "FACTURA" if kind == "factura" else "TICKET"

                html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>{title_html} {correlativo}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color: #000; }}
.paper {{ max-width: {900 if kind=='factura' else 720}px; margin: 0 auto; border: 1px solid #bbb; padding: 24px; }}
.header {{ text-align: {'left' if kind=='factura' else 'center'}; }}
.header-right {{ text-align:right; }}
.row {{ display:flex; justify-content:space-between; gap:20px; }}
table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
th, td {{ padding:8px 6px; border-bottom:1px solid #ddd; font-size:13px; }}
th {{ text-align:left; }}
.total {{ font-size:20px; font-weight:bold; color:#0f766e; }}
.small {{ font-size:12px; color:#333; }}
</style></head><body>
<div class='paper'>
{logo_html}
<div class='header'>
<h2 style='margin:0'>TECNOMEDIA GT</h2>
<div class='small'>15 CALLE 8 AVENIDA PUERTO BARRIOS, IZABAL</div>
<div class='small'>TEL: 31380850 / 54780043</div>
<div class='small'><b>NIT: 4509238-9</b></div>
<h3 style='margin-top:12px'>{title_html} No. {correlativo}</h3>
</div>
<div class='row'><div><b>Fecha:</b> {fecha}</div><div><b>Vendedor:</b> {usuario}</div></div>
<div class='row'><div><b>Cliente:</b> {cliente_nombre}</div><div><b>NIT:</b> {cliente_nit}</div></div>
<div class='row'><div><b>Dirección:</b> {cliente_dir}</div><div><b>Pago:</b> {str(pago.get('metodo','')).upper()}</div></div>
<table>
<thead><tr><th style='width:10%'>CANT</th><th>DESCRIPCIÓN</th><th style='width:18%; text-align:right'>PRECIO</th><th style='width:18%; text-align:right'>TOTAL</th></tr></thead>
<tbody>{item_rows}</tbody>
</table>
<div style='margin-top:16px'>
<div class='row'><div><b>SUBTOTAL</b></div><div>{subtotal_txt}</div></div>
<div class='row'><div><b>DESCUENTO</b></div><div>{descuento_txt}</div></div>
<div class='row total'><div>TOTAL</div><div>{total_txt}</div></div>
{f"<div class='row'><div><b>SALDO DEBER ANTES</b></div><div>Q{_safe_float(pago.get('balance_due_before', cliente_detalle.get('saldo_deber', 0))):.2f}</div></div>" if str(pago.get('metodo', '') or '').strip().lower() == 'credito' else ''}
{f"<div class='row'><div><b>SALDO DEBER ACTUAL</b></div><div>Q{_safe_float(pago.get('balance_due_after', pago.get('balance_due_before', cliente_detalle.get('saldo_deber', 0)))):.2f}</div></div>" if str(pago.get('metodo', '') or '').strip().lower() == 'credito' else ''}
{f"<div class='row'><div><b>SALDO A FAVOR ANTES</b></div><div>Q{_safe_float(pago.get('balance_favor_before', cliente_detalle.get('saldo_favor', 0))):.2f}</div></div>" if str(pago.get('metodo', '') or '').strip().lower() == 'saldo_favor' else ''}
{f"<div class='row'><div><b>SALDO A FAVOR ACTUAL</b></div><div>Q{_safe_float(pago.get('balance_favor_after', pago.get('balance_favor_before', cliente_detalle.get('saldo_favor', 0)))):.2f}</div></div>" if str(pago.get('metodo', '') or '').strip().lower() == 'saldo_favor' else ''}
{f"<div class='row'><div><b>CRÉDITO A</b></div><div>{int(_safe_float(pago.get('credit_days')))} días</div></div>" if str(pago.get('metodo', '') or '').strip().lower() == 'credito' and pago.get('credit_days') else ''}
{f"<div class='row'><div><b>VENCE</b></div><div>{pago.get('due_date')}</div></div>" if str(pago.get('metodo', '') or '').strip().lower() == 'credito' and pago.get('due_date') else ''}
</div>
<div style='text-align:center; margin-top:18px' class='small'>Impresa el: {fecha}<br>Gracias por su compra</div>
</div></body></html>"""

                filepath = os.path.join(docs_dir, f"{correlativo}.html")
                with open(filepath, "w", encoding="utf-8") as fh:
                    fh.write(html)

                try:
                    os.startfile(filepath, "print")
                    self._save_audit_record(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ADMIN | IMPRESION | corr={correlativo}")
                except Exception:
                    os.startfile(filepath)
                    messagebox.showinfo("Impresión", f"No se pudo enviar directo a imprimir. Se abrió el documento:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Impresión", f"No se pudo preparar la impresión: {e}")

        def _close_doc():
            try:
                setattr(self, "_document_window", None)
            except Exception:
                pass
            parent = getattr(self, "_history_window", None)
            if parent is None or not getattr(parent, "winfo_exists", lambda: False)():
                parent = getattr(self, "_pago_window", None)
            self._bring_window_front(parent)
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _close_doc)

        footer = tk.Frame(outer, bg=PANEL)
        footer.pack(fill="x", pady=(8, 0))
        inner = tk.Frame(footer, bg=PANEL)
        inner.pack(anchor="center")
        tk.Button(inner, text="Imprimir", command=imprimir, bg="#2563eb", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 11, "bold"), padx=14, pady=8).pack(side="left", padx=6)
        tk.Button(inner, text="Cerrar", command=_close_doc, bg="#334155", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 11, "bold"), padx=14, pady=8).pack(side="left", padx=6)


    def _merge_audit_into_sales(self, sales):
        existing_keys = set()
        for rec in sales:
            cliente = rec.get("cliente", "")
            if isinstance(cliente, dict):
                cliente = cliente.get("nombre", "")
            key = (
                str(rec.get("fecha", "")),
                str(cliente),
                str(rec.get("pago", {}).get("metodo", rec.get("metodo", ""))),
                str(rec.get("total", "")),
                str(rec.get("correlativo", "")),
            )
            existing_keys.add(key)

        audit_path = os.path.join(self._data_dir(), "auditoria.log")
        if not os.path.exists(audit_path):
            return sales

        # agregar ventas faltantes desde auditoria.log
        try:
            with open(audit_path, "r", encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or "| VENTA |" not in line:
                        continue
                    try:
                        parts = [p.strip() for p in line.split("|")]
                        fecha = parts[0]
                        usuario = parts[1] if len(parts) > 1 else "ADMIN"
                        cliente = ""
                        metodo = ""
                        total = "Q0.00"
                        corr = ""
                        for p in parts[3:]:
                            if p.startswith("cliente="):
                                cliente = p.split("=", 1)[1].strip()
                            elif p.startswith("metodo="):
                                metodo = p.split("=", 1)[1].strip()
                            elif p.startswith("total="):
                                total = p.split("=", 1)[1].strip()
                            elif p.startswith("corr="):
                                corr = p.split("=", 1)[1].strip()

                        key = (fecha, cliente, metodo, total, corr)
                        if key in existing_keys:
                            continue

                        tipo_documento = "guardar"
                        if corr.startswith("V-"):
                            tipo_documento = "voucher"
                        elif corr.startswith("F-"):
                            tipo_documento = "factura"

                        sales.append({
                            "fecha": fecha,
                            "usuario": usuario,
                            "cliente": cliente,
                            "cliente_detalle": {"nombre": cliente, "nit": "", "telefono": "", "direccion": ""},
                            "items": [],
                            "subtotal": total,
                            "descuento": "Q0.00",
                            "total": total,
                            "estado": "ACTIVA",
                            "pago": {"metodo": metodo},
                            "tipo_documento": tipo_documento,
                            "correlativo": corr
                        })
                        existing_keys.add(key)
                    except Exception:
                        pass
        except Exception:
            pass

        # aplicar anulaciones registradas en auditoría
        try:
            with open(audit_path, "r", encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or "| ANULACION |" not in line:
                        continue
                    try:
                        parts = [p.strip() for p in line.split("|")]
                        corr = ""
                        cliente = ""
                        for p in parts[3:]:
                            if p.startswith("corr="):
                                corr = p.split("=", 1)[1].strip()
                            elif p.startswith("cliente="):
                                cliente = p.split("=", 1)[1].strip()

                        for rec in reversed(sales):
                            rec_cliente = rec.get("cliente", "")
                            if isinstance(rec_cliente, dict):
                                rec_cliente = rec_cliente.get("nombre", "")
                            if (corr and rec.get("correlativo", "") == corr) or (not corr and cliente and rec_cliente == cliente):
                                rec["estado"] = "ANULADA"
                                break
                    except Exception:
                        pass
        except Exception:
            pass

        sales.sort(key=lambda rec: str(rec.get("fecha", "")))
        return sales

    def _payment_method_label(self, metodo, pago=None):
        pago = pago or {}
        metodo = str(metodo or '').strip().lower()
        if metodo == 'credito':
            dias = pago.get('credit_days')
            try:
                dias_num = int(str(dias).strip())
            except Exception:
                dias_num = 0
            return f"Crédito ({dias_num} días)" if dias_num > 0 else 'Crédito'
        mapping = {
            'efectivo': 'Efectivo',
            'saldo_favor': 'Saldo a favor',
            'deposito': 'Depósito',
            'transferencia': 'Transferencia',
            'tarjeta': 'Tarjeta',
            'credito': 'Crédito',
        }
        return mapping.get(metodo, metodo.replace('_', ' ').title() if metodo else '')

    def _build_payment_detail_lines(self, sale):
        pago = sale.get('pago', {}) or {}
        metodo = str(pago.get('metodo', sale.get('metodo', ''))).strip().lower()
        lines = [f"Método: {self._payment_method_label(metodo, pago)}"]
        if metodo == 'efectivo':
            recibido = _safe_float(pago.get('monto_recibido'))
            vuelto = _safe_float(pago.get('vuelto'))
            if recibido > 0:
                lines.append(f"Recibido: Q{recibido:.2f}")
            lines.append(f"Vuelto: Q{vuelto:.2f}")
        elif metodo in ('deposito', 'transferencia'):
            banco = str(pago.get('banco', '')).strip()
            ref = str(pago.get('boleta', pago.get('referencia', ''))).strip()
            if banco:
                lines.append(f"Banco: {banco}")
            if ref:
                label = 'Boleta' if metodo == 'deposito' else 'Referencia'
                lines.append(f"{label}: {ref}")
            if pago.get('foto'):
                lines.append('Comprobante: adjunto')
        elif metodo == 'tarjeta':
            tipo = str(pago.get('tipo', '')).strip()
            banco = str(pago.get('banco', '')).strip()
            ult4 = str(pago.get('ultimos4', '')).strip()
            auto = str(pago.get('autorizacion', '')).strip()
            if tipo:
                lines.append(f"Tipo: {tipo}")
            if banco:
                lines.append(f"Banco: {banco}")
            if ult4:
                lines.append(f"Terminación: ****{ult4}")
            if auto:
                lines.append(f"Autorización: {auto}")
            if pago.get('foto_tarjeta') or pago.get('foto_dpi'):
                lines.append('Soportes: adjuntos')
        elif metodo == 'saldo_favor':
            before = _safe_float(pago.get('balance_favor_before'))
            after = _safe_float(pago.get('balance_favor_after'))
            if before or after:
                lines.append(f"Saldo antes: Q{before:.2f}")
                lines.append(f"Saldo después: Q{after:.2f}")
        elif metodo == 'credito':
            before = _safe_float(pago.get('balance_due_before'))
            after = _safe_float(pago.get('balance_due_after'))
            if before or after:
                lines.append(f"Saldo antes: Q{before:.2f}")
                lines.append(f"Saldo después: Q{after:.2f}")
        return lines

    def _load_sales_records(self):
        sales = []
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, created_at, user_name, customer_name, customer_nit, subtotal, discount_amount, total,
                       payment_method, document_type, correlativo, status, payload_json
                FROM sales
                ORDER BY id DESC
                """
            )
            rows = cur.fetchall()
            conn.close()
            for row in rows:
                sale_id, created_at, user_name, customer_name, customer_nit, subtotal, discount_amount, total, payment_method, document_type, correlativo, status, payload_json = row
                rec = {}
                if payload_json:
                    try:
                        rec = json.loads(payload_json) or {}
                    except Exception:
                        rec = {}
                if not isinstance(rec, dict):
                    rec = {}
                cliente_data = rec.get('cliente_detalle') if isinstance(rec.get('cliente_detalle'), dict) else {}
                if not cliente_data and isinstance(rec.get('cliente'), dict):
                    cliente_data = dict(rec.get('cliente') or {})
                if customer_name and not cliente_data.get('nombre'):
                    cliente_data['nombre'] = customer_name
                if customer_nit and not cliente_data.get('nit'):
                    cliente_data['nit'] = customer_nit
                rec['fecha'] = rec.get('fecha') or created_at or ''
                rec['usuario'] = rec.get('usuario') or user_name or 'ADMIN'
                rec['cliente_detalle'] = cliente_data
                if not rec.get('cliente'):
                    rec['cliente'] = cliente_data.get('nombre', customer_name or '')
                rec['subtotal'] = rec.get('subtotal') or f"Q{_safe_float(subtotal):.2f}"
                rec['descuento'] = rec.get('descuento') or f"Q{_safe_float(discount_amount):.2f}"
                total_txt = rec.get('total')
                if not total_txt:
                    total_txt = f"Q{_safe_float(total):.2f}"
                rec['total'] = total_txt
                pago = rec.get('pago') if isinstance(rec.get('pago'), dict) else {}
                if payment_method and not pago.get('metodo'):
                    pago['metodo'] = payment_method
                rec['pago'] = pago
                rec['metodo'] = payment_method or pago.get('metodo', '')
                rec['tipo_documento'] = rec.get('tipo_documento') or document_type or 'guardar'
                rec['correlativo'] = rec.get('correlativo') or correlativo or ''
                rec['estado'] = (status or rec.get('estado') or 'ACTIVA').upper()
                rec['_sale_sqlite_id'] = sale_id
                sales.append(rec)
        except Exception:
            sales = []
        sales.sort(key=lambda rec: str(rec.get("fecha", "")), reverse=True)
        return sales

    def _rewrite_sales_records(self, sales):
        data_dir = self._data_dir()
        try:
            jsonl_path = os.path.join(data_dir, 'ventas.jsonl')
            with open(jsonl_path, 'w', encoding='utf-8') as fh:
                for rec in sales or []:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def open_sales_history(self):
        if not _require_permission('Ventas', 'ver', 'historial de ventas', self):
            return
        win, created = self._ensure_single_window("_history_window", "Historial de ventas", 1120, 720)
        if not created:
            return
        win.configure(bg=PANEL)

        win.minsize(980, 640)
        win.rowconfigure(2, weight=1)
        win.columnconfigure(0, weight=1)

        header = tk.Frame(win, bg=PANEL)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        header.columnconfigure(0, weight=1)

        tk.Label(header, text="HISTORIAL DE VENTAS", bg=PANEL, fg=TEXT,
                 font=("Arial", 20, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="Colores por método: verde=efectivo, naranja=crédito, amarillo=depósito, azul=transferencia, morado=tarjeta",
                 bg=PANEL, fg=MUTED, font=("Arial", 9)).grid(row=1, column=0, sticky="w", pady=(2,0))

        filters = tk.Frame(win, bg=PANEL)
        filters.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        filters.columnconfigure(1, weight=1)

        tk.Label(filters, text="Buscar:", bg=PANEL, fg=MUTED, font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w")
        search_var = tk.StringVar()
        search_entry = tk.Entry(filters, textvariable=search_var, font=("Arial", 12), width=28)
        search_entry.grid(row=0, column=1, sticky="w", padx=(8, 16), ipady=4)

        tk.Label(filters, text="Método:", bg=PANEL, fg=MUTED, font=("Arial", 11, "bold")).grid(row=0, column=2, sticky="w")
        method_var = tk.StringVar(value="Todos")
        method_combo = ttk.Combobox(filters, textvariable=method_var, state="readonly",
                                    values=["Todos", "efectivo", "credito", "saldo_favor", "deposito", "transferencia", "tarjeta"],
                                    width=16)
        method_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))

        content = tk.Frame(win, bg=PANEL)
        content.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))
        content.rowconfigure(0, weight=3)
        content.rowconfigure(1, weight=2)
        content.columnconfigure(0, weight=1)

        table_wrap = tk.Frame(content, bg=PANEL)
        table_wrap.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        cols = ("fecha", "usuario", "cliente", "metodo", "correlativo", "estado", "total")
        tree = ttk.Treeview(table_wrap, columns=cols, show="headings")
        for col, txt, width, anchor in [
            ("fecha", "Fecha", 150, "center"),
            ("usuario", "Usuario", 90, "center"),
            ("cliente", "Cliente", 170, "w"),
            ("metodo", "Método", 100, "center"),
            ("correlativo", "Correlativo", 120, "center"),
            ("estado", "Estado", 90, "center"),
            ("total", "Total", 100, "e"),
        ]:
            tree.heading(col, text=txt)
            tree.column(col, width=width, anchor=anchor)
        tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)

        tree.tag_configure("efectivo", background="#0f3d2e", foreground="#ffffff")
        tree.tag_configure("credito", background="#5b3a00", foreground="#ffffff")
        tree.tag_configure("saldo_favor", background="#0f766e", foreground="#ffffff")
        tree.tag_configure("deposito", background="#4b3f00", foreground="#ffffff")
        tree.tag_configure("transferencia", background="#0f2f57", foreground="#ffffff")
        tree.tag_configure("tarjeta", background="#3b1f5f", foreground="#ffffff")
        tree.tag_configure("otros", background="#102750", foreground="#ffffff")
        tree.tag_configure("anulada", background="#5f1f1f", foreground="#ffffff")

        bottom = tk.Frame(content, bg=PANEL)
        bottom.grid(row=1, column=0, sticky="nsew")
        bottom.rowconfigure(0, weight=1)
        bottom.columnconfigure(0, weight=1)

        details = tk.Frame(bottom, bg="#102750", highlightthickness=1, highlightbackground=BORDER)
        details.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        details.rowconfigure(1, weight=1)
        details.columnconfigure(0, weight=1)
        details.columnconfigure(1, weight=1)

        tk.Label(details, text="DETALLE DE VENTA", bg="#102750", fg=TEXT,
                 font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4), columnspan=2)

        
        # SCROLLABLE DETAIL AREA
        canvas = tk.Canvas(details, bg="#102750", highlightthickness=0)
        canvas.grid(row=1, column=0, columnspan=2, sticky="nsew")

        scroll_y = ttk.Scrollbar(details, orient="vertical", command=canvas.yview)
        scroll_y.grid(row=1, column=2, sticky="ns")

        canvas.configure(yscrollcommand=scroll_y.set)

        inner = tk.Frame(canvas, bg="#102750")
        canvas.create_window((0,0), window=inner, anchor="nw")

        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)

        detail_left = tk.Text(inner, height=10, bg="#102750", fg=TEXT, relief="flat",
                              font=("Consolas", 10), wrap="word")
        detail_left.grid(row=0, column=0, sticky="nsew", padx=(12,6), pady=(0,12))

        detail_right = tk.Text(inner, height=10, bg="#102750", fg=TEXT, relief="flat",
                               font=("Consolas", 10), wrap="word")
        detail_right.grid(row=0, column=1, sticky="nsew", padx=(6,12), pady=(0,12))

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>", _on_configure)

        detail_left.config(state="disabled")
        detail_right.config(state="disabled")


        actions = tk.Frame(bottom, bg=PANEL, width=190)
        actions.grid(row=0, column=1, sticky="ne")
        actions.grid_propagate(False)

        sales_data = []

        def load_sales():
            sales_data.clear()
            try:
                sales_data.extend(self._load_sales_records_with_sqlite())
            except Exception:
                pass

        def fill_table(*args):
            for item in tree.get_children():
                tree.delete(item)

            q = search_var.get().strip().lower()
            m = method_var.get().strip().lower()

            for idx, sale in enumerate(sales_data):
                raw_cliente = sale.get("cliente", "")
                if isinstance(raw_cliente, dict):
                    cliente = raw_cliente.get("nombre", "")
                else:
                    cliente = str(raw_cliente)

                metodo = str(sale.get("pago", {}).get("metodo", sale.get("metodo", ""))).lower()
                metodo_view = self._payment_method_label(metodo, sale.get("pago", {}))
                fecha = str(sale.get("fecha", ""))
                usuario = str(sale.get("usuario", ""))
                total_raw = sale.get("total", "")
                if isinstance(total_raw, str) and total_raw.startswith("Q"):
                    total = total_raw
                else:
                    try:
                        total = f"Q{float(total_raw):.2f}"
                    except Exception:
                        total = str(total_raw)

                text_blob = f"{fecha} {usuario} {cliente} {metodo} {metodo_view} {total}".lower()
                if q and q not in text_blob:
                    continue
                if m != "todos" and metodo != m:
                    continue

                estado = sale.get("estado", "ACTIVA")
                color_tag = "anulada" if estado == "ANULADA" else (metodo if metodo in ("efectivo", "credito", "saldo_favor", "deposito", "transferencia", "tarjeta") else "otros")
                tree.insert("", "end", iid=str(idx), values=(fecha, usuario, cliente, metodo_view, sale.get("correlativo",""), estado, total), tags=(color_tag,))

        def show_detail(event=None):
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            sale = sales_data[idx]

            left_lines = []
            left_lines.append(f"Fecha: {sale.get('fecha','')}")
            left_lines.append(f"Usuario: {sale.get('usuario','')}")
            cli = sale.get("cliente", "")
            if isinstance(cli, dict):
                left_lines.append(f"Cliente: {cli.get('nombre','')}")
                left_lines.append(f"NIT: {cli.get('nit','')}")
                left_lines.append(f"Teléfono: {cli.get('telefono','')}")
            else:
                left_lines.append(f"Cliente: {cli}")
            left_lines.append(f"Subtotal: {sale.get('subtotal','')}")
            left_lines.append(f"Descuento: {sale.get('descuento','')}")
            left_lines.append(f"Total: {sale.get('total','')}")
            left_lines.append(f"Correlativo: {sale.get('correlativo','')}")
            left_lines.append(f"Estado: {sale.get('estado','ACTIVA')}")

            right_lines = []
            right_lines.append("Pago:")
            right_lines.extend(f"  - {line}" for line in self._build_payment_detail_lines(sale))
            right_lines.append("")
            right_lines.append("Items:")
            for it in sale.get("items", []):
                try:
                    nombre = it.get("nombre", it.get("producto", ""))
                    right_lines.append(f"  - {nombre}")
                    right_lines.append(f"    cant={it.get('cantidad','')} | precio=Q{it.get('precio','')}")
                except Exception:
                    right_lines.append(f"  - {it}")

            detail_left.config(state="normal")
            detail_left.delete("1.0", "end")
            detail_left.insert("1.0", chr(10).join(left_lines))
            detail_left.config(state="disabled")

            detail_right.config(state="normal")
            detail_right.delete("1.0", "end")
            detail_right.insert("1.0", chr(10).join(right_lines))
            detail_right.config(state="disabled")

        def anular_venta():
            if not _require_permission('Ventas', 'anular', 'anular venta', win):
                return
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Historial", "Selecciona una venta para anular.")
                return
            idx = int(sel[0])
            if idx >= len(sales_data):
                return
            sale = sales_data[idx]
            if sale.get("estado") == "ANULADA":
                messagebox.showinfo("Historial", "La venta ya está anulada.")
                return
            motivo = simpledialog.askstring("Anular venta", "Motivo de anulación:", parent=win)
            if motivo is None:
                return
            motivo = motivo.strip()
            if not motivo:
                messagebox.showwarning("Historial", "Debes indicar un motivo para anular la venta.")
                return
            if not messagebox.askyesno("Anular venta", "¿Seguro que deseas anular esta venta? Esta acción revertirá inventario, caja y saldos del cliente cuando aplique."):
                return

            sale["estado"] = "ANULADA"
            sale["anulada_por"] = self.logged_user or SESSION_USER or "ADMIN"
            sale["anulada_fecha"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sale["anulada_motivo"] = motivo
            result = self._cancel_sale_in_sqlite(sale)
            if not result or not result.get('ok'):
                reason = (result or {}).get('reason')
                if reason == 'already_cancelled':
                    messagebox.showinfo("Historial", "La venta ya estaba anulada.")
                else:
                    messagebox.showerror("Historial", "No se pudo anular la venta seleccionada.")
                return
            self._save_audit_record(
                f"{sale['anulada_fecha']} | {sale['anulada_por']} | ANULACION | cliente={sale.get('cliente','')} | corr={sale.get('correlativo','')} | motivo={motivo}"
            )
            load_sales()
            fill_table()
            messagebox.showinfo("Historial", "Venta anulada correctamente. Inventario, caja y saldos fueron ajustados cuando aplicaba.")

        def reimprimir_venta():
            if not _require_permission('Ventas', 'imprimir', 'reimprimir venta', win):
                return
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Historial", "Selecciona una venta para reimprimir.")
                return
            idx = int(sel[0])
            sale = sales_data[idx]
            corr = sale.get("correlativo", "")
            tipo_doc = sale.get("tipo_documento", "")
            if not corr or tipo_doc not in ("voucher", "factura"):
                messagebox.showinfo("Historial", "Esta venta no tiene ticket/factura para reimprimir.")
                return
            self._render_document_window(tipo_doc, corr, sale)

        btn_reprint = tk.Button(actions, text="Reimprimir", command=reimprimir_venta, bg="#2563eb", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 10, "bold"), width=16, padx=12, pady=8)
        btn_reprint.pack(anchor="e", pady=(0, 8))
        btn_void = tk.Button(actions, text="Anular venta", command=anular_venta, bg="#dc2626", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 10, "bold"), width=16, padx=12, pady=8)
        btn_void.pack(anchor="e")
        _disable_button_if_denied(btn_reprint, 'Ventas', 'imprimir', 'reimprimir venta')
        _disable_button_if_denied(btn_void, 'Ventas', 'anular', 'anular venta')

        search_var.trace_add("write", fill_table)
        method_combo.bind("<<ComboboxSelected>>", fill_table)
        tree.bind("<<TreeviewSelect>>", show_detail)

        load_sales()
        fill_table()

    def go_pay(self):
        try:
            total_texto = str(self.lbl_total.cget("text") or "0")
            total_check = float(total_texto.replace("Q", "").replace(",", "").strip() or "0")
        except Exception:
            total_check = 0.0
        if not self.carrito or total_check <= 0:
            messagebox.showwarning("Venta inválida", "No hay productos en la venta.")
            return
        if not self.cliente_actual:
            messagebox.showwarning("Cliente", "Debes seleccionar un cliente para continuar.")
            return

        total_texto = self.lbl_total.cget("text")
        try:
            total = float(total_texto.replace("Q", "").replace(",", ""))
        except Exception:
            total = 0.0

        ventana, created = self._ensure_single_window("_pago_window", "Pago", 760, 620)
        if not created:
            return
        ventana.configure(bg=PANEL)
        ventana.transient(self)
        ventana.grab_set()

        tk.Label(ventana, text="PAGO DE VENTA", bg=PANEL, fg=TEXT, font=("Arial", 20, "bold")).pack(pady=(16, 4))
        tk.Label(ventana, text=f"Cliente: {self.cliente_actual['nombre']}", bg=PANEL, fg=TEXT, font=("Arial", 12, "bold")).pack()
        tk.Label(ventana, text="Usuario: ADMIN", bg=PANEL, fg=MUTED, font=("Arial", 11)).pack(pady=(0, 6))

        tk.Label(ventana, text="TOTAL", bg=PANEL, fg=TEXT, font=("Arial", 16, "bold")).pack(pady=(8, 0))
        total_lbl = tk.Label(ventana, text=f"Q{total:.2f}", bg=PANEL, fg=ACCENT, font=("Arial", 28, "bold"))
        total_lbl.pack()

        tk.Label(ventana, text="VUELTO / DIFERENCIA", bg=PANEL, fg=TEXT, font=("Arial", 14, "bold")).pack(pady=(8, 0))
        vuelto_var = tk.StringVar(value="Q0.00")
        vuelto_lbl = tk.Label(ventana, textvariable=vuelto_var, bg=PANEL, fg="#facc15", font=("Arial", 24, "bold"))
        vuelto_lbl.pack()
        estado_var = tk.StringVar(value="Ingresa el monto recibido")
        tk.Label(ventana, textvariable=estado_var, bg=PANEL, fg=MUTED, font=("Arial", 11)).pack(pady=(0, 10))

        metodo_var = tk.StringVar(value="efectivo")
        datos_pago = {"metodo":"efectivo"}

        selector = tk.Frame(ventana, bg=PANEL)
        selector.pack(fill="x", padx=34, pady=(6, 10))
        tk.Label(selector, text="Método de pago", bg=PANEL, fg=TEXT, font=("Arial", 12, "bold")).pack()
        btns = tk.Frame(selector, bg=PANEL)
        btns.pack(fill="x", pady=8)
        metodo_info_var = tk.StringVar(value="Método seleccionado: Efectivo")
        metodo_info = tk.Label(selector, textvariable=metodo_info_var, bg="#102750", fg="#86efac", font=("Segoe UI", 9, "bold"), padx=12, pady=7)
        metodo_info.pack(pady=(0, 2))

        efectivo_slot = tk.Frame(ventana, bg=PANEL)
        efectivo_slot.pack(pady=(0, 6))
        efectivo_wrap = tk.Frame(efectivo_slot, bg=PANEL)
        tk.Label(efectivo_wrap, text="Efectivo recibido", bg=PANEL, fg=MUTED, font=("Arial", 11, "bold")).pack()
        recibido_entry = tk.Entry(efectivo_wrap, width=18, justify="center", font=("Arial", 13), relief="flat", bd=0)
        recibido_entry.pack(pady=(6, 0), ipady=6)

        dynamic_area = tk.Frame(ventana, bg=PANEL)
        dynamic_area.pack(fill="both", expand=False, padx=24, pady=(0, 6))
        def _show_efectivo_wrap():
            try:
                if not efectivo_slot.winfo_ismapped():
                    efectivo_slot.pack(pady=(0, 6), before=dynamic_area)
                if not efectivo_wrap.winfo_ismapped():
                    efectivo_wrap.pack()
            except Exception:
                try:
                    efectivo_slot.pack(pady=(0, 6), before=dynamic_area)
                except Exception:
                    pass
                try:
                    efectivo_wrap.pack()
                except Exception:
                    pass

        def _hide_efectivo_wrap():
            try:
                if efectivo_wrap.winfo_ismapped():
                    efectivo_wrap.pack_forget()
                if efectivo_slot.winfo_ismapped():
                    efectivo_slot.pack_forget()
            except Exception:
                try:
                    efectivo_wrap.pack_forget()
                except Exception:
                    pass
                try:
                    efectivo_slot.pack_forget()
                except Exception:
                    pass

        def actualizar_vuelto(event=None):
            txt = recibido_entry.get().strip()
            if txt == "":
                vuelto_var.set("Q0.00")
                vuelto_lbl.config(fg="#facc15")
                estado_var.set("Ingresa el monto recibido")
                return
            try:
                pago = float(txt)
                diff = pago - total
                datos_pago["monto_recibido"] = pago
                if diff >= 0:
                    vuelto_var.set(f"Q{diff:.2f}")
                    vuelto_lbl.config(fg="#22c55e")
                    estado_var.set("Pago suficiente")
                else:
                    vuelto_var.set(f"Q{abs(diff):.2f}")
                    vuelto_lbl.config(fg="#ef4444")
                    estado_var.set("Faltan fondos")
            except Exception:
                vuelto_var.set("Q0.00")
                vuelto_lbl.config(fg="#facc15")
                estado_var.set("Monto inválido")
        recibido_entry.bind("<KeyRelease>", actualizar_vuelto)

        def seleccionar_metodo(m):
            metodo_var.set(m)
            datos_pago.clear()
            datos_pago["metodo"] = m
            try:
                color_map = {
                    "efectivo": "#86efac",
                    "credito": "#fdba74",
                    "saldo_favor": "#5eead4",
                    "deposito": "#fde68a",
                    "transferencia": "#93c5fd",
                    "tarjeta": "#d8b4fe",
                }
                metodo_info_var.set(f"Método seleccionado: {self._payment_method_label(m, {'credit_days': 0})}")
                metodo_info.configure(fg=color_map.get(m, "#dbeafe"))
            except Exception:
                pass
            try:
                for _value, (_btn, _fill, _border) in method_buttons.items():
                    self._style_payment_button(_btn, _fill, _border, selected=(_value == m))
            except Exception:
                pass
            saldo_deber_actual = _safe_float((self.cliente_actual or {}).get("saldo_deber", 0))
            saldo_favor_actual = _safe_float((self.cliente_actual or {}).get("saldo_favor", 0))
            if m == "efectivo":
                datos_pago.update({
                    "balance_due_before": saldo_deber_actual,
                    "balance_due_after": saldo_deber_actual,
                    "balance_favor_before": saldo_favor_actual,
                    "balance_favor_after": saldo_favor_actual,
                })
                _show_efectivo_wrap()
                return
            _hide_efectivo_wrap()

            if m == "credito":
                if not self.cliente_actual.get("credito", False):
                    messagebox.showerror("Crédito", "Este cliente no tiene crédito habilitado.")
                    metodo_var.set("efectivo")
                    datos_pago["metodo"] = "efectivo"
                    _show_efectivo_wrap()
                    return
                credit_win = tk.Toplevel(ventana)
                credit_win.title("Crédito")
                credit_win.configure(bg=PANEL)
                self._center_window(credit_win, 420, 250)
                credit_win.transient(ventana)
                credit_win.grab_set()
                tk.Label(credit_win, text="CRÉDITO", bg=PANEL, fg=TEXT, font=("Arial", 18, "bold")).pack(pady=(16, 4))
                tk.Label(credit_win, text="Selecciona a cuántos días deseas enviar el crédito", bg=PANEL, fg=MUTED, font=("Arial", 10)).pack(pady=(0, 10))
                dias_var = tk.StringVar(value="30")
                dias_combo = ttk.Combobox(credit_win, textvariable=dias_var, values=["8", "15", "30", "45", "60", "90"], state="readonly", width=12, justify="center")
                dias_combo.pack(pady=(0, 10), ipady=4)
                vence_var = tk.StringVar(value="")
                def _refresh_due(*_):
                    try:
                        dias = int(float(dias_var.get() or 0))
                    except Exception:
                        dias = 0
                    due = (datetime.now() + timedelta(days=dias)).strftime('%d/%m/%Y') if dias > 0 else ''
                    vence_var.set(f"Vence: {due}" if due else "")
                dias_combo.bind("<<ComboboxSelected>>", _refresh_due)
                _refresh_due()
                tk.Label(credit_win, textvariable=vence_var, bg=PANEL, fg="#93c5fd", font=("Arial", 11, "bold")).pack(pady=(0, 10))
                actions = tk.Frame(credit_win, bg=PANEL)
                actions.pack(pady=(4, 12))
                def guardar_credito():
                    try:
                        dias = int(float(dias_var.get() or 0))
                    except Exception:
                        messagebox.showerror("Crédito", "Selecciona una cantidad de días válida.", parent=credit_win)
                        return
                    due = (datetime.now() + timedelta(days=dias)).strftime('%d/%m/%Y') if dias > 0 else ''
                    datos_pago.update({
                        "metodo": "credito",
                        "credito_autorizado": True,
                        "credit_days": dias,
                        "due_date": due,
                        "balance_due_before": saldo_deber_actual,
                        "balance_due_after": saldo_deber_actual + total,
                        "balance_favor_before": saldo_favor_actual,
                        "balance_favor_after": saldo_favor_actual,
                    })
                    credit_win.destroy()
                tk.Button(actions, text="Cancelar", command=lambda:(metodo_var.set('efectivo'), datos_pago.update({'metodo':'efectivo'}), _show_efectivo_wrap(), credit_win.destroy()), bg="#334155", fg=TEXT, relief="flat", bd=0, font=("Arial",10,"bold"), padx=12, pady=8).pack(side="left", padx=6)
                tk.Button(actions, text="Confirmar crédito", command=guardar_credito, bg="#c2410c", fg=TEXT, relief="flat", bd=0, font=("Arial",10,"bold"), padx=12, pady=8).pack(side="left", padx=6)
                return

            if m == "saldo_favor":
                if saldo_favor_actual <= 0:
                    messagebox.showerror("Saldo a favor", "Este cliente no tiene saldo a favor disponible.")
                    metodo_var.set("efectivo")
                    datos_pago["metodo"] = "efectivo"
                    _show_efectivo_wrap()
                    return
                if saldo_favor_actual < total:
                    messagebox.showerror("Saldo a favor", f"El saldo a favor del cliente es insuficiente. Disponible: Q{saldo_favor_actual:.2f}")
                    metodo_var.set("efectivo")
                    datos_pago["metodo"] = "efectivo"
                    _show_efectivo_wrap()
                    return
                datos_pago.update({
                    "metodo": "saldo_favor",
                    "credito_autorizado": False,
                    "balance_due_before": saldo_deber_actual,
                    "balance_due_after": saldo_deber_actual,
                    "balance_favor_before": saldo_favor_actual,
                    "balance_favor_after": max(0.0, saldo_favor_actual - total),
                })
                messagebox.showinfo("Saldo a favor", f"Se aplicará Q{total:.2f} del saldo a favor del cliente.")
                return

            modal = tk.Toplevel(ventana)
            modal.configure(bg=PANEL)
            modal.transient(ventana)
            modal.grab_set()

            if m == "deposito":
                modal.title("Datos de depósito")
                self._attach_resizable_switch(modal, "deposito", 600, 720, "DEPÓSITO")
                tk.Label(modal, text="Completa los datos del depósito y adjunta la fotografía del comprobante para validar el pago", bg=PANEL, fg=MUTED, font=("Arial", 10)).pack(pady=(0, 8))
                banco_box, banco = self._small_field(modal, "Banco", width=20, placeholder="Ej. Banco Industrial")
                banco_box.pack(pady=2)
                boleta_box, boleta = self._small_field(modal, "Número de boleta o referencia", width=20, placeholder="Ej. DEP45821")
                boleta_box.pack(pady=2)
                comp_box, comp = self._small_file(modal, "Fotografía del comprobante")
                comp_box.pack(pady=(0, 2))
                def guardar():
                    banco_txt = banco.get().strip()
                    boleta_txt = boleta.get().strip()
                    comp_txt = comp.get().strip()

                    if banco_txt and len(banco_txt) > 25:
                        messagebox.showerror("Depósito", "Banco: máximo 25 caracteres.")
                        return
                    if boleta_txt and len(boleta_txt) > 10:
                        messagebox.showerror("Depósito", "Boleta o referencia: máximo 10 caracteres.")
                        return

                    datos_pago.update({
                        "metodo":"deposito",
                        "banco": banco_txt,
                        "boleta": boleta_txt,
                        "comprobante": comp_txt
                    })
                    modal.destroy()
                footer = tk.Frame(modal, bg=PANEL)
                footer.pack(fill="x", padx=18, pady=(10, 14))
                tk.Button(footer, text="💾 Guardar datos", command=guardar, bg=ACCENT, fg="white",
                          relief="flat", bd=0, font=("Segoe UI", 11, "bold"), padx=18, pady=11, width=26).pack(anchor="center", pady=(0, 10))
                actions = tk.Frame(footer, bg=PANEL)
                actions.pack(anchor="center")
                tk.Button(actions, text="Cancelar", command=modal.destroy, bg="#475569", fg="white", relief="flat", bd=0,
                          font=("Segoe UI", 10, "bold"), padx=16, pady=8, width=14).pack(side="left", padx=(0, 8))
                tk.Button(actions, text="Quitar", command=lambda: [comp.set(""), modal.destroy()], bg="#991b1b", fg="white", relief="flat", bd=0,
                          font=("Segoe UI", 10, "bold"), padx=16, pady=8, width=14).pack(side="left")

            elif m == "transferencia":
                modal.title("Datos de transferencia")
                self._attach_resizable_switch(modal, "transferencia", 600, 740, "TRANSFERENCIA")
                tk.Label(modal, text="Completa banco, referencia, depositante y adjunta la fotografía del comprobante para validar el pago", bg=PANEL, fg=MUTED, font=("Arial", 10)).pack(pady=(0, 8))
                banco_box, banco = self._small_field(modal, "Banco", width=20, placeholder="Ej. Banco Industrial")
                banco_box.pack(pady=2)
                ref_box, ref = self._small_field(modal, "Referencia", width=20, placeholder="Ej. TRF875421")
                ref_box.pack(pady=2)
                dep_box, dep = self._small_field(modal, "Nombre del depositante", width=20, placeholder="Ej. Juan Pérez")
                dep_box.pack(pady=2)
                comp_box, comp = self._small_file(modal, "Fotografía del comprobante")
                comp_box.pack(pady=(0, 2))
                def guardar():
                    banco_txt = banco.get().strip()
                    ref_txt = ref.get().strip()
                    dep_txt = dep.get().strip()
                    comp_txt = comp.get().strip()

                    if banco_txt and len(banco_txt) > 25:
                        messagebox.showerror("Transferencia", "Banco: máximo 25 caracteres.")
                        return
                    if ref_txt and len(ref_txt) > 10:
                        messagebox.showerror("Transferencia", "Referencia: máximo 10 caracteres.")
                        return

                    datos_pago.update({
                        "metodo":"transferencia",
                        "banco": banco_txt,
                        "referencia": ref_txt,
                        "depositante": dep_txt,
                        "comprobante": comp_txt
                    })
                    modal.destroy()
                footer = tk.Frame(modal, bg=PANEL)
                footer.pack(fill="x", padx=18, pady=(10, 14))
                tk.Button(footer, text="💾 Guardar datos", command=guardar, bg=ACCENT, fg="white",
                          relief="flat", bd=0, font=("Segoe UI", 11, "bold"), padx=18, pady=11, width=26).pack(anchor="center", pady=(0, 10))
                actions = tk.Frame(footer, bg=PANEL)
                actions.pack(anchor="center")
                tk.Button(actions, text="Cancelar", command=modal.destroy, bg="#475569", fg="white", relief="flat", bd=0,
                          font=("Segoe UI", 10, "bold"), padx=16, pady=8, width=14).pack(side="left", padx=(0, 8))
                tk.Button(actions, text="Quitar", command=lambda: [comp.set(""), modal.destroy()], bg="#991b1b", fg="white", relief="flat", bd=0,
                          font=("Segoe UI", 10, "bold"), padx=16, pady=8, width=14).pack(side="left")

            elif m == "tarjeta":
                modal.title("Datos de tarjeta")
                self._attach_resizable_switch(modal, "tarjeta", 820, 780, "TARJETA")
                tk.Label(modal, text="Completa los datos y adjunta fotografía de la tarjeta y del DPI para respaldo de la operación", bg=PANEL, fg=MUTED, font=("Arial", 10)).pack(pady=(0, 6))

                body = tk.Frame(modal, bg=PANEL)
                body.pack(fill="both", expand=True, padx=18, pady=6)
                body.columnconfigure(0, weight=1)
                body.columnconfigure(1, weight=1)

                def field_box(parent, title, width=28):
                    box = tk.Frame(parent, bg="#102750")
                    tk.Label(box, text=title, bg="#102750", fg=MUTED, font=("Arial", 11, "bold")).pack(anchor="center", pady=(8, 4), padx=10)
                    entry = tk.Entry(box, width=width, justify="center", relief="flat", bd=0, font=("Arial", 12))
                    entry.pack(anchor="center", padx=10, pady=(0, 10), ipady=6)
                    return box, entry

                def file_box(parent, title):
                    box = tk.Frame(parent, bg="#102750")
                    tk.Label(box, text=title, bg="#102750", fg=MUTED, font=("Arial", 11, "bold")).pack(anchor="center", pady=(8, 4), padx=10)
                    path_var = tk.StringVar(value="")
                    shown = tk.Label(box, text="Sin archivo seleccionado", bg="#16386b", fg=TEXT, width=26, height=2, wraplength=200, justify="center")
                    shown.pack(anchor="center", padx=10, pady=(0, 8))
                    tk.Button(box, text="Adjuntar", bg="#2563eb", fg=TEXT, relief="flat", bd=0,
                              font=("Arial", 11, "bold"), padx=18, pady=8,
                              command=lambda: self._pick_image(path_var, shown)).pack(anchor="center", pady=(0, 6))
                    return box, path_var

                # fila 1
                tipo_box = tk.Frame(body, bg=PANEL)
                tipo_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=4)
                tk.Label(tipo_box, text="Tipo", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="center", pady=(2, 6), padx=10)
                tipo_var = tk.StringVar(value="Débito")
                tipo_buttons = tk.Frame(tipo_box, bg=PANEL)
                tipo_buttons.pack(anchor="center")
                btn_debito = tk.Button(tipo_buttons, text="Débito", bg="#2563eb", fg="white", relief="flat", bd=0, font=("Segoe UI", 10, "bold"), width=10, pady=7)
                btn_credito = tk.Button(tipo_buttons, text="Crédito", bg="#1e3a5f", fg="white", relief="flat", bd=0, font=("Segoe UI", 10, "bold"), width=10, pady=7)
                btn_debito.pack(side="left", padx=(0, 6))
                btn_credito.pack(side="left")
                def _set_tipo(value):
                    tipo_var.set(value)
                    btn_debito.configure(bg="#2563eb" if value == "Débito" else "#1e3a5f")
                    btn_credito.configure(bg="#2563eb" if value == "Crédito" else "#1e3a5f")
                btn_debito.configure(command=lambda: _set_tipo("Débito"))
                btn_credito.configure(command=lambda: _set_tipo("Crédito"))

                banco_box, banco = self._small_field(body, "Banco emisor", width=18, placeholder="Ej. Banco Industrial")
                banco_box.grid(row=0, column=1, sticky="nsew", padx=8, pady=4)

                # fila 2
                ult4_box, ult4 = self._small_field(body, "Últimos 4 dígitos", width=12, placeholder="Ej. 1234")
                ult4_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

                auto_box, auto = self._small_field(body, "Número de autorización", width=14, placeholder="Ej. 987654")
                auto_box.grid(row=1, column=1, sticky="nsew", padx=8, pady=4)

                # fila 3
                foto_t_box, foto_t = self._small_file(body, "Fotografía de la tarjeta")
                foto_t_box.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)

                foto_d_box, foto_d = self._small_file(body, "Fotografía del DPI")
                foto_d_box.grid(row=2, column=1, sticky="nsew", padx=8, pady=4)

                def guardar():
                    banco_txt = banco.get().strip()
                    ult4_txt = ult4.get().strip()
                    auto_txt = auto.get().strip()

                    foto_t_txt = foto_t.get().strip()
                    foto_d_txt = foto_d.get().strip()

                    if banco_txt and len(banco_txt) > 25:
                        messagebox.showerror("Tarjeta", "Banco emisor: máximo 25 caracteres.")
                        return
                    if ult4_txt and (len(ult4_txt) != 4 or not ult4_txt.isdigit()):
                        messagebox.showerror("Tarjeta", "Últimos 4 dígitos: deben ser exactamente 4 números.")
                        return
                    if auto_txt and len(auto_txt) > 10:
                        messagebox.showerror("Tarjeta", "Número de autorización: máximo 10 caracteres.")
                        return

                    datos_pago.update({
                        "metodo":"tarjeta",
                        "tipo": tipo_var.get().strip(),
                        "banco": banco_txt,
                        "ultimos4": ult4_txt,
                        "autorizacion": auto_txt,
                        "foto_tarjeta": foto_t_txt,
                        "foto_dpi": foto_d_txt
                    })
                    modal.destroy()

                footer = tk.Frame(modal, bg=PANEL)
                footer.pack(fill="x", padx=18, pady=(8, 14))
                tk.Button(footer, text="💾 Guardar datos", command=guardar, bg=ACCENT, fg="white",
                          relief="flat", bd=0, font=("Segoe UI", 11, "bold"), padx=18, pady=11, width=30).pack(anchor="center", pady=(0, 10))
                actions = tk.Frame(footer, bg=PANEL)
                actions.pack(anchor="center")
                tk.Button(actions, text="Cancelar", command=modal.destroy, bg="#475569", fg="white", relief="flat", bd=0,
                          font=("Segoe UI", 10, "bold"), padx=16, pady=8, width=16).pack(side="left", padx=(0, 8))
                tk.Button(actions, text="Quitar", command=lambda: [foto_t.set(""), foto_d.set(""), modal.destroy()], bg="#991b1b", fg="white", relief="flat", bd=0,
                          font=("Segoe UI", 10, "bold"), padx=16, pady=8, width=16).pack(side="left")

        
        method_defs = [
            ("Efectivo", "efectivo", "#15803d", "#38ef7d"),
            ("Crédito", "credito", "#c2410c", "#fb923c"),
            ("Saldo a favor", "saldo_favor", "#0f766e", "#2dd4bf"),
            ("Depósito", "deposito", "#a16207", "#fbbf24"),
            ("Transferencia", "transferencia", "#2563eb", "#60a5fa"),
            ("Tarjeta", "tarjeta", "#7c3aed", "#c084fc"),
        ]
        btns.configure(bg=PANEL)
        for col in range(3):
            try:
                btns.grid_columnconfigure(col, weight=1, uniform="pay_methods")
            except Exception:
                pass
        method_buttons = {}
        for col in range(3):
            btns.grid_columnconfigure(col, weight=1, uniform="pay_methods")
        for row_idx in range(2):
            btns.grid_rowconfigure(row_idx, weight=1)
        for col in range(3):
            btns.grid_columnconfigure(col, weight=1, uniform="pay_methods")
        for row_idx in range(2):
            btns.grid_rowconfigure(row_idx, weight=1)
        for idx, (label, value, fill, border) in enumerate(method_defs):
            row, col = divmod(idx, 3)
            btn = tk.Button(
                btns,
                text=label,
                image=self._payment_icons.get(value),
                command=lambda v=value: seleccionar_metodo(v),
            )
            self._style_payment_button(btn, fill, border, selected=(value == metodo_var.get()))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=getattr(b, "_hover_bg", b.cget("bg"))), add="+")
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=getattr(b, "_normal_bg", b.cget("bg"))), add="+")
            btn.bind("<ButtonPress-1>", lambda e, b=btn: b.configure(bg=getattr(b, "_active_bg", b.cget("bg"))), add="+")
            btn.bind("<ButtonRelease-1>", lambda e, b=btn: b.configure(bg=getattr(b, "_hover_bg", b.cget("bg"))), add="+")
            btn.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            method_buttons[value] = (btn, fill, border)


        def confirmar_venta():
            # BLOQUEO ANTIVENTA VACIA
            try:
                if not self.carrito or float(total) <= 0:
                    messagebox.showwarning("Venta inválida", "No hay productos en la venta.")
                    return
            except Exception:
                messagebox.showwarning("Venta inválida", "No hay productos en la venta.")
                return

            metodo = metodo_var.get()
            if metodo == "efectivo":
                txt = recibido_entry.get().strip()
                try:
                    pago = float(txt)
                except Exception:
                    messagebox.showerror("Pago", "Ingresa un monto válido en efectivo.")
                    return
                if pago < total:
                    messagebox.showerror("Pago", "El efectivo recibido es menor que el total.")
                    return
                datos_pago["metodo"] = "efectivo"
                datos_pago["monto_recibido"] = pago
                datos_pago["vuelto"] = round(pago-total, 2)
            else:
                datos_pago["metodo"] = metodo
                if "balance_due_before" not in datos_pago:
                    saldo_deber_actual = _safe_float((self.cliente_actual or {}).get("saldo_deber", 0))
                    saldo_favor_actual = _safe_float((self.cliente_actual or {}).get("saldo_favor", 0))
                    datos_pago.update({
                        "balance_due_before": saldo_deber_actual,
                        "balance_due_after": saldo_deber_actual,
                        "balance_favor_before": saldo_favor_actual,
                        "balance_favor_after": saldo_favor_actual,
                    })
                banco_txt = str(datos_pago.get("banco", "")).strip()
                ref_txt = str(datos_pago.get("referencia", datos_pago.get("boleta", datos_pago.get("autorizacion", "")))).strip()
                ult4_txt = str(datos_pago.get("ultimos4", "")).strip()
                if banco_txt and len(banco_txt) > 25:
                    messagebox.showerror("Validación", "Banco: máximo 25 caracteres.")
                    return
                if ref_txt and len(ref_txt) > 10:
                    messagebox.showerror("Validación", "Referencia / boleta / autorización: máximo 10 caracteres.")
                    return
                if ult4_txt and (len(ult4_txt) != 4 or not ult4_txt.isdigit()):
                    messagebox.showerror("Validación", "Últimos 4 dígitos: deben ser exactamente 4 números.")
                    return

            ask = tk.Toplevel(ventana)
            ask.title("Finalizar venta")
            ask.configure(bg=PANEL)
            try:
                self._center_window(ask, 380, 220)
            except Exception:
                ask.geometry("380x220")
            ask.transient(ventana)
            ask.grab_set()

            decision = {"kind": "guardar"}

            tk.Label(ask, text="¿Cómo deseas finalizar la venta?", bg=PANEL, fg=TEXT,
                     font=("Arial", 14, "bold")).pack(pady=(18, 12))

            btns2 = tk.Frame(ask, bg=PANEL)
            btns2.pack(pady=8)
            tk.Button(btns2, text="Guardar", command=lambda:(decision.update({"kind":"guardar"}), ask.destroy()),
                      bg="#334155", fg=TEXT, relief="flat", bd=0, font=("Arial",11,"bold"), padx=12, pady=8).pack(side="left", padx=6)
            tk.Button(btns2, text="Ticket", command=lambda:(decision.update({"kind":"voucher"}), ask.destroy()),
                      bg="#2563eb", fg=TEXT, relief="flat", bd=0, font=("Arial",11,"bold"), padx=12, pady=8).pack(side="left", padx=6)
            tk.Button(btns2, text="Factura", command=lambda:(decision.update({"kind":"factura"}), ask.destroy()),
                      bg="#7c3aed", fg=TEXT, relief="flat", bd=0, font=("Arial",11,"bold"), padx=12, pady=8).pack(side="left", padx=6)

            ventana.wait_window(ask)

            if not self._validate_cart_stock():
                return

            try:
                registro = {
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "usuario": self.employee_name_selected or self.logged_user or "ADMIN",
                    "cliente": self.cliente_actual.get("nombre", "") if isinstance(self.cliente_actual, dict) else str(self.cliente_actual),
                    "cliente_detalle": self.cliente_actual,
                    "items": self.carrito,
                    "subtotal": self.lbl_subtotal.cget("text") if hasattr(self, "lbl_subtotal") else "",
                    "descuento": self.lbl_discount_amt.cget("text") if hasattr(self, "lbl_discount_amt") else "",
                    "total": self.lbl_total.cget("text") if hasattr(self, "lbl_total") else f"Q{total:.2f}",
                    "estado": "ACTIVA",
                    "pago": dict(datos_pago),
                    "tipo_documento": decision["kind"]
                }

                if decision["kind"] in ("voucher", "factura"):
                    registro["correlativo"] = self._next_correlativo(decision["kind"])
                else:
                    registro["correlativo"] = ""

                self._save_sale_record(registro)
                self._persist_sale_to_sqlite(registro)
                self.products_catalog = self._load_products_catalog()
                self.filtered_products = self.products_catalog[:]
                self.render_products()
                self._save_audit_record(
                    f"{registro['fecha']} | ADMIN | VENTA | cliente={registro['cliente']} | metodo={registro['pago'].get('metodo','')} | total={registro['total']} | corr={registro.get('correlativo','')}"
                )
            except Exception as e:
                messagebox.showerror("Guardado", f"No se pudo guardar la venta: {e}")
                return

            if decision["kind"] in ("voucher", "factura"):
                self._render_document_window(decision["kind"], registro["correlativo"], registro)

            messagebox.showinfo("Venta", "Venta guardada correctamente.")
            try:
                self.carrito = []
                self.qty_var.set("1")
                self.refresh_cart()
            except Exception:
                pass
            ventana.destroy()

        footer = tk.Frame(ventana, bg=PANEL)
        footer.pack(fill="x", padx=18, pady=16)

        footer_inner = tk.Frame(footer, bg=PANEL)
        footer_inner.pack(anchor="center")

        tk.Button(footer_inner, text="Cancelar", command=ventana.destroy, bg="#334155", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 11, "bold"), width=16, padx=12, pady=8).pack(side="left", padx=8)
        tk.Button(footer_inner, text="Confirmar venta", command=confirmar_venta, bg=ACCENT, fg="#03281e",
                  relief="flat", bd=0, font=("Arial", 11, "bold"), width=16, padx=12, pady=8).pack(side="left", padx=8)


    def _nuevo_cliente_popup(self):
        if not _require_permission('Clientes', 'crear', 'crear cliente desde POS', self):
            return
        win, created = self._ensure_single_window("_nuevo_cliente_window", "Nuevo cliente", 480, 420)
        if not created:
            return
        win.configure(bg=PANEL)

        tk.Label(win, text="NUEVO CLIENTE", bg=PANEL, fg=TEXT, font=("Arial", 16, "bold")).pack(pady=(14, 10))

        form = tk.Frame(win, bg=PANEL)
        form.pack(fill="both", expand=True, padx=20, pady=10)

        tk.Label(form, text="Nombre", bg=PANEL, fg=MUTED, font=("Arial", 11, "bold")).pack(anchor="w")
        nombre = tk.Entry(form, font=("Arial", 12))
        nombre.pack(fill="x", ipady=5, pady=(4, 10))

        tk.Label(form, text="NIT", bg=PANEL, fg=MUTED, font=("Arial", 11, "bold")).pack(anchor="w")
        nit = tk.Entry(form, font=("Arial", 12))
        nit.pack(fill="x", ipady=5, pady=(4, 10))

        tk.Label(form, text="Teléfono", bg=PANEL, fg=MUTED, font=("Arial", 11, "bold")).pack(anchor="w")
        tel = tk.Entry(form, font=("Arial", 12))
        tel.pack(fill="x", ipady=5, pady=(4, 10))

        tk.Label(form, text="Dirección", bg=PANEL, fg=MUTED, font=("Arial", 11, "bold")).pack(anchor="w")
        direccion = tk.Entry(form, font=("Arial", 12))
        direccion.pack(fill="x", ipady=5, pady=(4, 12))

        def guardar():
            try:
                nuevo = {
                    "nombre": nombre.get().strip(),
                    "nit": nit.get().strip(),
                    "telefono": tel.get().strip(),
                    "direccion": direccion.get().strip(),
                    "credito": False,
                    "descuento": 0,
                    "saldo_deber": 0,
                    "saldo_favor": 0,
                }

                self._sync_new_client_to_sqlite(nuevo)
                self._refresh_clients_catalog()
                self.cliente_actual = next(
                    (c for c in self.clients_catalog if c.get("nombre", "").strip().lower() == nuevo["nombre"].strip().lower()),
                    nuevo,
                )

                try:
                    if hasattr(self, "search_client_var"):
                        self.search_client_var.set(nuevo["nombre"])
                    if hasattr(self, "on_search_clients"):
                        self.on_search_clients()

                    if hasattr(self, "client_list"):
                        for i in range(self.client_list.size()):
                            txt = self.client_list.get(i)
                            if nuevo["nombre"].lower() in txt.lower():
                                self.client_list.selection_clear(0, "end")
                                self.client_list.selection_set(i)
                                self.client_list.activate(i)
                                break

                    if hasattr(self, "lbl_name"):
                        self.lbl_name.config(text=f"Nombre: {self.cliente_actual.get('nombre','---')}")
                    if hasattr(self, "lbl_nit"):
                        self.lbl_nit.config(text=f"NIT: {self.cliente_actual.get('nit','---')}")
                    if hasattr(self, "lbl_phone"):
                        self.lbl_phone.config(text=f"Teléfono: {self.cliente_actual.get('telefono','---')}")
                    if hasattr(self, "lbl_desc"):
                        self.lbl_desc.config(text=f"Descuento: {self.cliente_actual.get('descuento',0)}%")
                    if hasattr(self, "lbl_credit"):
                        self.lbl_credit.config(text=f"Crédito: {'Sí' if self.cliente_actual.get('credito', False) else 'No'}")
                    if hasattr(self, "lbl_saldo"):
                        self.lbl_saldo.config(text=f"Saldo a deber: Q{float(self.cliente_actual.get('saldo_deber',0) or 0):.2f} | Saldo a favor: Q{float(self.cliente_actual.get('saldo_favor',0) or 0):.2f}")
                    if hasattr(self, "lbl_dir"):
                        self.lbl_dir.config(text=f"Dirección: {self.cliente_actual.get('direccion','---')}")
                except Exception:
                    pass

                messagebox.showinfo("Cliente", "Cliente guardado y seleccionado correctamente.")
                win.destroy()
            except Exception as e:
                messagebox.showerror("Cliente", f"No se pudo guardar el cliente: {e}")

        footer = tk.Frame(win, bg=PANEL)
        footer.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(footer, text="Cancelar", command=win.destroy, bg="#334155", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 11, "bold"), padx=14, pady=8).pack(side="left")
        tk.Button(footer, text="Guardar", command=guardar, bg="#22c55e", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 11, "bold"), padx=14, pady=8).pack(side="right")



    def open_reports(self):
        if not _require_permission('Reportes', 'ver', 'reportes de ventas', self):
            return
        win, created = self._ensure_single_window("_reports_window", "Reportes", 700, 560)
        if not created:
            return
        win.configure(bg=PANEL)
        win.minsize(620, 460)

        header = tk.Frame(win, bg=PANEL)
        header.pack(fill="x", padx=16, pady=(16, 10))
        tk.Label(header, text="REPORTES", bg=PANEL, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w")
        tk.Label(header, text="Resumen general de ventas guardadas", bg=PANEL, fg=MUTED, font=("Arial", 10)).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        ventas = self._load_sales_records() if hasattr(self, "_load_sales_records") else []

        total_ventas = len(ventas)
        total_vendido = 0.0
        activas = 0
        anuladas = 0
        por_metodo = {}

        for v in ventas:
            try:
                monto = float(str(v.get("total", "0")).replace("Q", "").replace(",", "").strip() or 0)
            except Exception:
                monto = 0.0

            estado = str(v.get("estado", "ACTIVA")).upper()
            if estado == "ANULADA":
                anuladas += 1
            else:
                activas += 1
                total_vendido += monto

            metodo = str(v.get("pago", {}).get("metodo", "otros")).lower().strip() or "otros"
            por_metodo.setdefault(metodo, {"cantidad": 0, "monto": 0.0})
            por_metodo[metodo]["cantidad"] += 1
            if estado != "ANULADA":
                por_metodo[metodo]["monto"] += monto

        card1 = tk.Frame(body, bg="#102750", highlightthickness=1, highlightbackground=BORDER)
        card1.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        tk.Label(card1, text="RESUMEN", bg="#102750", fg=TEXT, font=("Arial", 14, "bold")).pack(anchor="w", padx=14, pady=(12, 8))
        for line, color in [
            (f"Ventas registradas: {total_ventas}", TEXT),
            (f"Ventas activas: {activas}", "#22c55e"),
            (f"Ventas anuladas: {anuladas}", "#ef4444"),
            (f"Total vendido: Q{total_vendido:.2f}", ACCENT),
        ]:
            tk.Label(card1, text=line, bg="#102750", fg=color, font=("Arial", 12, "bold" if "Total vendido" in line else "normal")).pack(anchor="w", padx=14, pady=4)

        card2 = tk.Frame(body, bg="#102750", highlightthickness=1, highlightbackground=BORDER)
        card2.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        tk.Label(card2, text="POR MÉTODO DE PAGO", bg="#102750", fg=TEXT, font=("Arial", 14, "bold")).pack(anchor="w", padx=14, pady=(12, 8))

        color_map = {
            "efectivo": "#22c55e",
            "credito": "#f97316",
            "deposito": "#eab308",
            "transferencia": "#3b82f6",
            "tarjeta": "#8b5cf6",
            "otros": TEXT,
        }

        methods_wrap = tk.Frame(card2, bg="#102750")
        methods_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        if not por_metodo:
            tk.Label(methods_wrap, text="Sin ventas todavía.", bg="#102750", fg=MUTED, font=("Arial", 11)).pack(anchor="w")
        else:
            for metodo in sorted(por_metodo.keys()):
                info = por_metodo[metodo]
                row = tk.Frame(methods_wrap, bg="#102750")
                row.pack(fill="x", pady=4)
                tk.Label(row, text=metodo.upper(), bg="#102750", fg=color_map.get(metodo, TEXT), font=("Arial", 11, "bold")).pack(side="left")
                tk.Label(row, text=f"{info['cantidad']} ventas", bg="#102750", fg=MUTED, font=("Arial", 11)).pack(side="left", padx=12)
                tk.Label(row, text=f"Q{info['monto']:.2f}", bg="#102750", fg=TEXT, font=("Arial", 11, "bold")).pack(side="right")

        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=16, pady=(0, 16))
        tk.Button(foot, text="Cerrar", command=win.destroy, bg="#334155", fg=TEXT,
                  relief="flat", bd=0, font=("Arial", 11, "bold"), padx=14, pady=8).pack(anchor="e")

if __name__ == "__main__":
    app = POSApp()
    app.mainloop()


# === UI_HOVER_FIX_APPLIED ===
def _ui_hover_effect(widget, base):
    def _shade(hex_color, f):
        hex_color = hex_color.lstrip("#")
        r,g,b = int(hex_color[:2],16), int(hex_color[2:4],16), int(hex_color[4:],16)
        r,g,b = min(255,int(r*f)), min(255,int(g*f)), min(255,int(b*f))
        return f"#{r:02x}{g:02x}{b:02x}"

    hover = _shade(base,1.12)
    active = _shade(base,0.9)

    def enter(e): widget.config(bg=hover)
    def leave(e): widget.config(bg=base)
    def click(e): widget.config(bg=active)

    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)
    widget.bind("<ButtonPress-1>", click)
    widget.bind("<ButtonRelease-1>", enter)
