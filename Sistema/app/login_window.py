import tkinter as tk


class LoginWindow:
    def __init__(self, authenticate_user, system_version, title_prefix="TECNOMEDIA LOGIN", width=500, height=430):
        self.authenticate_user = authenticate_user
        self.system_version = system_version
        self.title_prefix = title_prefix
        self.width = width
        self.height = height

        self.root = tk.Tk()
        self.root.title(f"{self.title_prefix} {self.system_version}")
        self.root.geometry(f"{self.width}x{self.height}")
        self.root.resizable(False, False)
        self.root.configure(bg="#0f172a")
        self._center_window()

        wrapper = tk.Frame(self.root, bg="#0f172a")
        wrapper.pack(fill="both", expand=True, padx=42, pady=34)

        tk.Label(
            wrapper,
            text=f"TECNOMEDIA\n{self.system_version}",
            fg="white",
            bg="#0f172a",
            font=("Arial", 22, "bold")
        ).pack(pady=(6, 28))

        form = tk.Frame(wrapper, bg="#0f172a")
        form.pack()

        entry_col_width = 260
        side_col_width = 44
        form.grid_columnconfigure(0, minsize=entry_col_width)
        form.grid_columnconfigure(1, minsize=side_col_width)

        entry_width = 26
        label_font = ("Arial", 11, "bold")
        entry_font = ("Arial", 12)

        tk.Label(form, text="Usuario", fg="white", bg="#0f172a", anchor="center", font=label_font).grid(row=0, column=0, columnspan=2, pady=(0, 8))
        self.user = tk.Entry(form, width=entry_width, justify="left", font=entry_font)
        self.user.grid(row=1, column=0, padx=(0, 10), pady=(0, 16), ipady=7, sticky="ew")
        self.user_spacer = tk.Frame(form, width=side_col_width, height=34, bg="#0f172a", highlightthickness=0, bd=0)
        self.user_spacer.grid(row=1, column=1, pady=(0, 16), sticky="w")
        self.user_spacer.grid_propagate(False)

        tk.Label(form, text="Contraseña", fg="white", bg="#0f172a", anchor="center", font=label_font).grid(row=2, column=0, columnspan=2, pady=(0, 8))
        self.pwd = tk.Entry(form, show="*", width=entry_width, justify="left", font=entry_font)
        self.pwd.grid(row=3, column=0, padx=(0, 10), pady=(0, 8), ipady=7, sticky="ew")
        self.show_pwd = False
        self.toggle_btn = tk.Button(form, text="👁", command=self.toggle_password, width=3, font=("Arial", 10))
        self.toggle_btn.grid(row=3, column=1, pady=(0, 8), sticky="w")

        self.error_label = tk.Label(wrapper, text="", fg="#f87171", bg="#0f172a", font=("Arial", 10, "bold"))
        self.error_label.pack(pady=(10, 8))

        self.btn_login = tk.Button(wrapper, text="Entrar", command=self.login, width=12, font=("Arial", 11, "bold"))
        self.btn_login.pack(pady=(8, 0), ipady=4)

        self.valid = False
        self.username = ""
        self.role = ""
        self.full_name = ""
        self.force_password_change = False

        self.user.bind("<Return>", self._on_enter, add="+")
        self.pwd.bind("<Return>", self._on_enter, add="+")
        self.user.focus_set()

        self.root.mainloop()

    def toggle_password(self):
        self.show_pwd = not self.show_pwd
        self.pwd.configure(show="" if self.show_pwd else "*")
        self.toggle_btn.configure(text="🙈" if self.show_pwd else "👁")

    def _center_window(self):
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = int((screen_w / 2) - (self.width / 2))
        y = int((screen_h / 2) - (self.height / 2))
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _on_enter(self, event=None):
        try:
            self.btn_login.invoke()
        except Exception:
            self.login()
        return "break"

    def login(self):
        username = self.user.get().strip()
        password = self.pwd.get().strip()
        record = self.authenticate_user(username, password)
        if not record:
            self.error_label.config(text="Usuario o contraseña incorrectos")
            self.pwd.focus_set()
            self.pwd.selection_range(0, "end")
            return

        self.valid = True
        self.username = record.get("username", "")
        self.role = record.get("role", "")
        self.full_name = record.get("full_name", "")
        self.force_password_change = bool(record.get("force_password_change"))
        try:
            self.user.unbind("<Return>")
            self.pwd.unbind("<Return>")
        except Exception:
            pass
        self.root.after(10, self.root.destroy)
