# modulo seguro de auditoria (preparado)
USUARIO_ACTUAL = "ADMIN"

def registrar_evento(tipo, descripcion):
    with open("auditoria.log", "a", encoding="utf-8") as f:
        f.write(f"{tipo} | {USUARIO_ACTUAL} | {descripcion}\n")
