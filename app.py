# =========================
# CONFIGURACIÓN GENERAL
# =========================
import os
import csv
import shutil
import sqlite3
from datetime import datetime, date, timedelta
from io import StringIO, BytesIO
from functools import wraps
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, session, send_file, jsonify, g, flash


# =========================
# CONFIGURACIÓN APP
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
TICKETS_FOLDER = os.path.join(BASE_DIR, "static", "tickets")

# Crear carpetas si no existen
for folder in [UPLOAD_FOLDER, TICKETS_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app = Flask(__name__)
app.secret_key = "pos_secreto"

# =========================
# CONFIGURACIÓN NEGOCIO
# =========================
NOMBRE_NEGOCIO = "La Casa Del Chihuahua"

CATEGORIAS = [
    "Quesadilla", "Gordita", "Sopes", "Pambazo",
    "Tostada", "Caldos", "Tacos", "Bebidas", "Postres"
]


COLORES = {
    "Quesadilla": "#ffe0b2",
    "Gordita": "#d7ccc8",
    "Sopes": "#f0f4c3",
    "Pambazo": "#ffcdd2",
    "Tostada": "#e1bee7",
    "Caldos": "#bbdefb",
    "Tacos": "#c8e6c9",
    "Bebidas": "#b3e5fc",
    "Postres": "#f0abfc"
}


# =========================
# DATABASE OPTIMIZADA (Context Manager)
# =========================
def get_db():
    """Obtiene conexión a BD con WAL mode para mejor concurrencia"""
    if 'db' not in g:
        g.db = sqlite3.connect(DB, timeout=30, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL;")
        g.db.execute("PRAGMA foreign_keys=ON;")
    return g.db

def close_db(e=None):
    """Cierra conexión al final de request"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

app.teardown_appcontext(close_db)

def query_db(query, args=(), one=False):
    """Helper para queries simplificados"""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    """Helper para INSERT/UPDATE/DELETE con commit"""
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid

# =========================
# INICIALIZACIÓN BD (CON CORRECCIONES DE ESQUEMA)
# =========================
def init_db():
    """Inicializa BD con todas las tablas necesarias"""
    db = get_db()
    
    # 1. Crear tablas base (sin índices problemáticos primero)
    schema = """
    -- PRODUCTOS
    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        precio REAL,
        categoria TEXT
    );

    -- COMANDAS
    CREATE TABLE IF NOT EXISTS comandas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        estado TEXT,
        tipo TEXT,
        mesa INTEGER,
        alias TEXT
    );

    -- DETALLE COMANDA
    CREATE TABLE IF NOT EXISTS detalle_comanda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comanda_id INTEGER,
        producto_id INTEGER,
        cantidad INTEGER,
        observaciones TEXT,
        entregado_cantidad INTEGER DEFAULT 0,
        FOREIGN KEY (comanda_id) REFERENCES comandas(id) ON DELETE CASCADE,
        FOREIGN KEY (producto_id) REFERENCES productos(id)
    );

    -- VENTAS
    CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        total REAL
    );

    -- DETALLE VENTA
    CREATE TABLE IF NOT EXISTS detalle_venta (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venta_id INTEGER,
        producto_id INTEGER,
        cantidad INTEGER,
        subtotal REAL,
        FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
    );

    -- USUARIOS
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT UNIQUE,
        password TEXT,
        rol TEXT
    );

    -- CONTROL DIARIO
    CREATE TABLE IF NOT EXISTS control_diario (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        ventas REAL DEFAULT 0,
        caja REAL DEFAULT 0,
        gas REAL DEFAULT 0,
        luz REAL DEFAULT 0,
        internet REAL DEFAULT 0,
        gasolina REAL DEFAULT 0,
        agua REAL DEFAULT 0,
        surtido REAL DEFAULT 0,
        credito REAL DEFAULT 0,
        regalo REAL DEFAULT 0
    );

    -- TICKETS (tabla base - sin índices todavía)
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        categoria TEXT,
        monto REAL,
        archivo TEXT,
        nota TEXT,
        tipo_gasto TEXT DEFAULT 'VARIABLE',
        semana_id INTEGER
    );
    
    -- CORTES SEMANALES
    CREATE TABLE IF NOT EXISTS cortes_semana (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_inicio TEXT,
        fecha_fin TEXT,
        ventas REAL,
        gastos REAL,
        utilidad REAL,
        creado_en TEXT
    );
    
    -- CORTES DIARIOS
    CREATE TABLE IF NOT EXISTS cortes_diarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT UNIQUE,
        ventas REAL,
        gastos REAL,
        utilidad REAL,
        creado_en TEXT
    );
    
    -- APARTADOS BASE
    CREATE TABLE IF NOT EXISTS apartados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE,
        presupuesto REAL,
        tipo TEXT DEFAULT 'Fijo'
    );
    
    -- SEMANAS
    CREATE TABLE IF NOT EXISTS semanas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_inicio TEXT UNIQUE,
        fecha_fin TEXT,
        estado TEXT DEFAULT 'ACTIVA',
        acumulado REAL DEFAULT 0
    );

    -- APARTADOS SEMANALES
    CREATE TABLE IF NOT EXISTS apartados_semanales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        semana_id INTEGER,
        categoria TEXT,
        presupuesto REAL,
        gastado REAL DEFAULT 0,
        FOREIGN KEY (semana_id) REFERENCES semanas(id) ON DELETE CASCADE
    );
    """
    
    db.executescript(schema)
    
    # 2. Verificar y agregar columnas faltantes a tablas existentes (migración)
    try:
        # Verificar si tickets tiene semana_id
        db.execute("SELECT semana_id FROM tickets LIMIT 1")
    except sqlite3.OperationalError:
        # La columna no existe, agregarla
        db.execute("ALTER TABLE tickets ADD COLUMN semana_id INTEGER")
        print("Columna semana_id agregada a tickets")
    
    # 3. Crear índices si no existen (ignorar errores si ya existen)
    indices = [
        ("idx_comandas_estado", "CREATE INDEX IF NOT EXISTS idx_comandas_estado ON comandas(estado)"),
        ("idx_detalle_comanda_comanda", "CREATE INDEX IF NOT EXISTS idx_detalle_comanda_comanda ON detalle_comanda(comanda_id)"),
        ("idx_ventas_fecha", "CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)"),
        ("idx_tickets_fecha", "CREATE INDEX IF NOT EXISTS idx_tickets_fecha ON tickets(fecha)"),
        ("idx_tickets_categoria", "CREATE INDEX IF NOT EXISTS idx_tickets_categoria ON tickets(categoria)"),
        ("idx_tickets_semana", "CREATE INDEX IF NOT EXISTS idx_tickets_semana ON tickets(semana_id)"),
        ("idx_apartados_semanales_semana", "CREATE INDEX IF NOT EXISTS idx_apartados_semanales_semana ON apartados_semanales(semana_id)")
    ]
    
    for idx_name, idx_sql in indices:
        try:
            db.execute(idx_sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e).lower():
                print(f"Advertencia al crear índice {idx_name}: {e}")
    
    # 4. Insertar datos iniciales si no existen
    db.execute("INSERT OR IGNORE INTO control_diario (id) VALUES (1)")
    
    db.execute("""
        INSERT OR IGNORE INTO usuarios (usuario, password, rol) 
        VALUES ('admin', 'admin', 'admin')
    """)
    
    # Insertar apartados base si no existen (basado en tu captura)
    apartados_default = [
        ("Gas", 400),
        ("Luz", 50),
        ("Internet", 100),
        ("Gasolina", 100),
        ("Agua", 200),
        ("Surtido", 4000),
        ("Credito", 275),
        ("Derek", 250)
    ]
    
    for nombre, monto in apartados_default:
        db.execute("""
            INSERT OR IGNORE INTO apartados (nombre, presupuesto, tipo) 
            VALUES (?, ?, 'Fijo')
        """, [nombre, monto])
    
    # 5. Crear semana actual si no existe
    hoy = date.today()
    offset = (hoy.weekday() - 4) % 7
    viernes = hoy - timedelta(days=offset)
    
    semana_existe = db.execute("SELECT 1 FROM semanas WHERE fecha_inicio = ?", [viernes.isoformat()]).fetchone()
    if not semana_existe:
        domingo = viernes + timedelta(days=2)
        db.execute("""
            INSERT INTO semanas (fecha_inicio, fecha_fin, estado) 
            VALUES (?, ?, 'ACTIVA')
        """, [viernes.isoformat(), domingo.isoformat()])
    
    db.commit()
    print("Base de datos inicializada correctamente")


# =========================
# FUNCIONES AUXILIARES OPTIMIZADAS
# =========================
def revisar_comanda_completa(comanda_id):
    """Verifica si todos los items fueron entregados y marca como Lista"""
    pendientes = query_db("""
        SELECT COUNT(*) as p FROM detalle_comanda
        WHERE comanda_id=? AND entregado_cantidad < cantidad
    """, [comanda_id], one=True)["p"]
    
    if pendientes == 0:
        execute_db("UPDATE comandas SET estado='Lista' WHERE id=?", [comanda_id])

def rango_semana_actual():
    """Retorna rango viernes a domingo actual"""
    hoy = date.today()
    offset = (hoy.weekday() - 4) % 7  # Viernes es 4
    inicio = hoy - timedelta(days=offset)
    fin = inicio + timedelta(days=2)  # Domingo
    return inicio.isoformat(), fin.isoformat()

def totales_periodo(inicio=None, fin=None):
    """Calcula ventas y gastos por período (optimizado)"""
    if not inicio:
        inicio, fin = rango_semana_actual()
    
    ventas = query_db("""
        SELECT IFNULL(SUM(total),0) as total FROM ventas 
        WHERE fecha BETWEEN ? AND ?
    """, [inicio, fin], one=True)["total"]
    
    gastos = query_db("""
        SELECT IFNULL(SUM(monto),0) as total FROM tickets 
        WHERE fecha BETWEEN ? AND ?
    """, [inicio, fin], one=True)["total"]
    
    return float(ventas), float(gastos), float(ventas) - float(gastos)

def total_ventas_periodo():
    """Ventas desde el último corte semanal o viernes pasado"""
    ultimo = query_db("""
        SELECT fecha_fin FROM cortes_semana 
        ORDER BY fecha_fin DESC LIMIT 1
    """, one=True)
    
    fecha_inicio = ultimo["fecha_fin"] if ultimo else (
        date.today() - timedelta(days=(date.today().weekday() - 4) % 7)
    ).isoformat()
    
    result = query_db("""
        SELECT IFNULL(SUM(total),0) as total FROM ventas WHERE fecha >= ?
    """, [fecha_inicio], one=True)
    return float(result["total"])

# =========================
# FUNCIONES DE SEMANAS Y APARTADOS
# =========================
def get_semana_actual():
    """Obtiene o crea la semana actual"""
    hoy = date.today()
    offset = (hoy.weekday() - 4) % 7
    viernes = hoy - timedelta(days=offset)
    
    semana = query_db("SELECT * FROM semanas WHERE fecha_inicio = ?", [viernes.isoformat()], one=True)
    
    if not semana:
        # Crear nueva semana
        domingo = viernes + timedelta(days=2)
        semana_id = execute_db("""
            INSERT INTO semanas (fecha_inicio, fecha_fin, estado) 
            VALUES (?, ?, 'ACTIVA')
        """, [viernes.isoformat(), domingo.isoformat()])
        
        # Crear registros de apartados para esta semana
        db = get_db()
        db.execute("""
            INSERT INTO apartados_semanales (semana_id, categoria, presupuesto)
            SELECT ?, nombre, presupuesto FROM apartados
        """, [semana_id])
        db.commit()
        
        semana = query_db("SELECT * FROM semanas WHERE id = ?", [semana_id], one=True)
    
    return semana

def get_apartados_semana(semana_id=None):
    """Obtiene apartados con datos de la semana específica"""
    if not semana_id:
        semana = get_semana_actual()
        semana_id = semana["id"]
    
    return query_db("""
        SELECT 
            a.id,
            a.nombre as categoria,
            a.presupuesto,
            COALESCE(ash.gastado, 0) as gastado_semana,
            (a.presupuesto - COALESCE(ash.gastado, 0)) as restante_semana,
            COALESCE((
                SELECT SUM(t.monto) 
                FROM tickets t 
                WHERE t.categoria = a.nombre AND t.semana_id = ?
            ), 0) as gastado_real
        FROM apartados a
        LEFT JOIN apartados_semanales ash ON a.nombre = ash.categoria AND ash.semana_id = ?
        ORDER BY a.nombre
    """, [semana_id, semana_id])

def actualizar_gasto_apartado(semana_id, categoria, monto):
    """Actualiza el gasto acumulado de un apartado en la semana"""
    db = get_db()
    # Verificar si existe el registro
    existe = db.execute("""
        SELECT 1 FROM apartados_semanales 
        WHERE semana_id = ? AND categoria = ?
    """, [semana_id, categoria]).fetchone()
    
    if existe:
        db.execute("""
            UPDATE apartados_semanales 
            SET gastado = gastado + ? 
            WHERE semana_id = ? AND categoria = ?
        """, [monto, semana_id, categoria])
    else:
        # Obtener presupuesto base
        presupuesto = db.execute("""
            SELECT presupuesto FROM apartados WHERE nombre = ?
        """, [categoria]).fetchone()
        presupuesto = presupuesto[0] if presupuesto else 0
        
        db.execute("""
            INSERT INTO apartados_semanales (semana_id, categoria, presupuesto, gastado)
            VALUES (?, ?, ?, ?)
        """, [semana_id, categoria, presupuesto, monto])
    
    db.commit()

# =========================
# DECORADORES
# =========================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

# =========================
# RUTAS (MANTENIENDO API ORIGINAL)
# =========================

@app.route("/")
@login_required
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = query_db("""
            SELECT usuario, rol FROM usuarios 
            WHERE usuario=? AND password=?
        """, [request.form["usuario"], request.form["password"]], one=True)
        
        if user:
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            return redirect("/")
        return render_template("login.html", error="Credenciales incorrectas")
    
    return render_template("login.html")

# ---------- CONTROL (OPTIMIZADO) ----------
@app.route("/control")
@login_required
def control():
    fecha_inicio = request.args.get("inicio")
    fecha_fin = request.args.get("fin")
    
    # Construir filtros dinámicamente
    filtro_ventas = "WHERE 1=1"
    filtro_tickets = "WHERE 1=1"
    params = []
    
    if fecha_inicio and fecha_fin:
        filtro_ventas += " AND fecha BETWEEN ? AND ?"
        filtro_tickets += " AND fecha BETWEEN ? AND ?"
        params = [fecha_inicio, fecha_fin]
    
    # Consultas consolidadas
    ventas_total = query_db(f"""
        SELECT IFNULL(SUM(total),0) as total FROM ventas {filtro_ventas}
    """, params, one=True)["total"]
    
    gastos_total = query_db(f"""
        SELECT IFNULL(SUM(monto),0) as total FROM tickets {filtro_tickets}
    """, params, one=True)["total"]
    
    gastos_fijos = query_db(f"""
        SELECT IFNULL(SUM(monto),0) FROM tickets 
        WHERE tipo_gasto='FIJO' {filtro_tickets.replace('WHERE 1=1', '')}
    """, params, one=True)[0] or 0
    
    gastos_variables = query_db(f"""
        SELECT IFNULL(SUM(monto),0) FROM tickets 
        WHERE tipo_gasto='VARIABLE' {filtro_tickets.replace('WHERE 1=1', '')}
    """, params, one=True)[0] or 0
    
    # Gastos por categoría
    gastos_por_categoria = query_db(f"""
        SELECT categoria, SUM(monto) as total 
        FROM tickets {filtro_tickets}
        GROUP BY categoria ORDER BY total DESC
    """, params)
    
    # Apartados dinámicos con datos de semana actual
    semana_actual = get_semana_actual()
    apartados_db = get_apartados_semana(semana_actual["id"])
    apartados = []
    
    for ap in apartados_db or []:
        gastado_total = query_db("""
            SELECT IFNULL(SUM(monto),0) FROM tickets WHERE categoria=?
        """, [ap["categoria"]], one=True)[0] or 0
        
        apartados.append({
            "nombre": ap["categoria"],
            "presupuesto": ap["presupuesto"],
            "gastado": ap["gastado_semana"],
            "restante": ap["restante_semana"],
            "gastado_total": gastado_total
        })
    
    return render_template("control.html",
        ventas_total=ventas_total,
        gastos_total=gastos_total,
        gastos_fijos=gastos_fijos,
        gastos_variables=gastos_variables,
        utilidad=ventas_total - gastos_total,
        gastos_por_categoria=gastos_por_categoria,
        apartados=apartados,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin
    )
    
@app.route("/historial_cortes")
@login_required
def historial_cortes():
    cortes = query_db("""
        SELECT id, fecha_inicio, fecha_fin, ventas, gastos, utilidad, creado_en
        FROM cortes_semana
        ORDER BY fecha_inicio DESC
    """)
    
    return render_template("historial_cortes.html", cortes=cortes)


# ---------- TICKETS/GASTOS ----------
@app.route("/subir_ticket", methods=["POST"])
@login_required
def subir_ticket():
    categoria = request.form.get("categoria")
    monto = float(request.form.get("monto", 0))
    nota = request.form.get("nota", "")
    tipo_gasto = request.form.get("tipo_gasto", "VARIABLE")
    
    if not categoria or monto <= 0:
        return redirect("/gastos")
    
    # Obtener semana actual automáticamente
    semana = get_semana_actual()
    semana_id = semana["id"] if semana else None
    
    # Manejo de archivo optimizado
    nombre_archivo = None
    if "foto" in request.files:
        foto = request.files["foto"]
        if foto and foto.filename:
            ext = secure_filename(foto.filename).rsplit('.', 1)[-1]
            nombre_archivo = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
            foto.save(os.path.join(TICKETS_FOLDER, nombre_archivo))
    
    execute_db("""
        INSERT INTO tickets (fecha, categoria, monto, archivo, nota, tipo_gasto, semana_id)
        VALUES (?,?,?,?,?,?,?)
    """, [date.today().isoformat(), categoria, monto, nombre_archivo, nota, tipo_gasto, semana_id])
    
    # Actualizar apartado semanal
    if semana_id:
        actualizar_gasto_apartado(semana_id, categoria, monto)
    
    return redirect("/control")

@app.route("/eliminar_ticket/<int:id>", methods=["POST"])
@login_required
def eliminar_ticket(id):
    # Obtener info del ticket antes de eliminar para actualizar apartado
    ticket = query_db("SELECT semana_id, categoria, monto FROM tickets WHERE id=?", [id], one=True)
    
    if ticket and ticket["semana_id"]:
        # Restar del apartado semanal
        db = get_db()
        db.execute("""
            UPDATE apartados_semanales 
            SET gastado = MAX(0, gastado - ?) 
            WHERE semana_id = ? AND categoria = ?
        """, [ticket["monto"], ticket["semana_id"], ticket["categoria"]])
        db.commit()
    
    # Eliminar archivo si existe
    row = query_db("SELECT archivo FROM tickets WHERE id=?", [id], one=True)
    if row and row["archivo"]:
        ruta = os.path.join(TICKETS_FOLDER, row["archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)
    
    execute_db("DELETE FROM tickets WHERE id=?", [id])
    return redirect("/tickets")

@app.route("/tickets")
@login_required
def ver_tickets():
    categoria = request.args.get("categoria", "")
    fecha = request.args.get("fecha", "")
    
    query = "SELECT * FROM tickets WHERE 1=1"
    params = []
    
    if categoria:
        query += " AND categoria=?"
        params.append(categoria)
    if fecha:
        query += " AND fecha=?"
        params.append(fecha)
    
    query += " ORDER BY fecha DESC, id DESC"
    tickets = query_db(query, params)
    
    total = query_db(f"SELECT IFNULL(SUM(monto),0) FROM ({query})", params, one=True)[0]
    categorias = [c[0] for c in query_db("SELECT DISTINCT categoria FROM tickets ORDER BY categoria")]
    
    return render_template("tickets.html", 
        tickets=tickets, categorias=categorias, total=total,
        categoria_sel=categoria, fecha_sel=fecha)

# ---------- PRODUCTOS ----------
@app.route("/productos", methods=["GET", "POST"])
@login_required
def productos():
    if request.method == "POST":
        execute_db("""
            INSERT INTO productos (nombre, precio, categoria) VALUES (?,?,?)
        """, [request.form["nombre"], request.form["precio"], request.form["categoria"]])
        return redirect("/productos")
    
    productos = query_db("SELECT * FROM productos ORDER BY categoria, nombre")
    return render_template("productos.html", 
        productos=productos, categorias=CATEGORIAS, colores=COLORES)

@app.route("/editar_producto/<int:producto_id>", methods=["GET", "POST"])
@login_required
def editar_producto(producto_id):
    if request.method == "POST":
        execute_db("""
            UPDATE productos SET nombre=?, precio=?, categoria=? WHERE id=?
        """, [request.form["nombre"], request.form["precio"], 
              request.form["categoria"], producto_id])
        return redirect("/productos")
    
    producto = query_db("SELECT * FROM productos WHERE id=?", [producto_id], one=True)
    return render_template("editar_producto.html", 
        producto=producto, categorias=CATEGORIAS)

@app.route("/eliminar_producto/<int:producto_id>")
@login_required
def eliminar_producto(producto_id):
    execute_db("DELETE FROM productos WHERE id=?", [producto_id])
    return redirect("/productos")

# ---------- VENTAS Y COMANDAS ----------
@app.route("/ventas")
@login_required
def ventas():
    ventas_db = query_db("""
        SELECT id, fecha, total FROM ventas ORDER BY id DESC
    """)
    
    ventas = []
    for v in ventas_db:
        items = query_db("""
            SELECT p.nombre, dv.cantidad, dv.subtotal
            FROM detalle_venta dv
            JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        """, [v["id"]])
        
        ventas.append({
            "id": v["id"],
            "fecha": v["fecha"],
            "total": float(v["total"]),
            "items": [{"nombre": i["nombre"], "cantidad": i["cantidad"], 
                      "subtotal": float(i["subtotal"])} for i in items]
        })
    
    return render_template("ventas.html", ventas=ventas, nombre_negocio=NOMBRE_NEGOCIO)

@app.route("/eliminar_venta/<int:venta_id>", methods=["POST"])
@login_required
def eliminar_venta(venta_id):
    execute_db("DELETE FROM detalle_venta WHERE venta_id=?", [venta_id])
    execute_db("DELETE FROM ventas WHERE id=?", [venta_id])
    return redirect("/ventas")

@app.route("/venta_rapida", methods=["GET", "POST"])
@login_required
def venta_rapida():
    if request.method == "GET":
        productos = query_db("SELECT * FROM productos ORDER BY categoria, nombre")
        
        # Obtener categorías únicas de la BD
        categorias_raw = query_db("SELECT DISTINCT categoria FROM productos ORDER BY categoria")
        categorias = [c["categoria"] for c in categorias_raw]
        
        # Fallback si no hay productos
        if not categorias:
            categorias = ["Tacos", "Quesadilla", "Gordita", "Sopes", "Pambazo", "Tostada", "Caldos", "Bebidas", "Postres"]
        
        # Extras por categoría
        extras = {
            'Gordita': ['Nopales', 'Q. rallado', 'Cebolla', 'Cilantro', 'C/Todo', 'Frita', 'Al comal'],
            'Pambazo': ['Lechuga', 'Crema', 'Q. rallado', 'C/Todo'],
            'Quesadilla': ['Lechuga', 'Crema', 'Q. rallado', 'C/Todo', 'Frita', 'Al comal'],
            'Sopes': ['Nopales', 'Lechuga', 'Q. rallado', 'Crema', 'C/Todo'],
            'Tacos': ['Cilantro', 'Cebolla', 'C/Todo'],
            'Tostada': ['Lechuga', 'Crema', 'Queso', 'C/Todo', 'Sin frijoles']
        }
        
        return render_template("ventas_rapidas.html", 
                             productos=productos, 
                             categorias=categorias,
                             extras=extras)
    
    # POST
    tipo = request.form.get("tipo", "MESA")
    mesa = request.form.get("mesa") if tipo == "MESA" else None
    alias = request.form.get("alias", "").strip()
    
    comanda_id = execute_db("""
        INSERT INTO comandas (fecha, estado, tipo, mesa, alias)
        VALUES (DATETIME('now'), 'Pendiente', ?, ?, ?)
    """, [tipo, mesa, alias])
    
    # Procesar productos en batch
    productos = query_db("SELECT id FROM productos")
    inserts = []
    
    for p in productos:
        pid = p["id"]
        cantidad_raw = request.form.get(f"prod_{pid}")
        if cantidad_raw and int(cantidad_raw) > 0:
            cantidad = int(cantidad_raw)
            observaciones = request.form.get(f"obs_{pid}", "").strip()
            inserts.append((comanda_id, pid, cantidad, observaciones))
    
    if inserts:
        db = get_db()
        db.executemany("""
            INSERT INTO detalle_comanda 
            (comanda_id, producto_id, cantidad, observaciones, entregado_cantidad)
            VALUES (?, ?, ?, ?, 0)
        """, inserts)
        db.commit()
    
    return redirect("/cocina")


# ---------- COMANDAS ----------
@app.route("/comandas")
@login_required
def comandas():
    comandas_db = query_db("""
        SELECT id, estado, tipo, mesa, alias
        FROM comandas
        WHERE estado IN ('Pendiente','Preparando','Lista')
        ORDER BY id ASC
    """)
    
    mesas = {}
    for c in comandas_db:
        clave = "Para llevar" if c["tipo"] == "LLEVAR" else f"Mesa {c['mesa']}"
        
        detalle_rows = query_db("""
            SELECT p.categoria, p.nombre, d.cantidad, p.precio,
                   (d.cantidad * p.precio) as subtotal, d.observaciones
            FROM detalle_comanda d
            JOIN productos p ON p.id = d.producto_id
            WHERE d.comanda_id = ?
            ORDER BY p.categoria, p.nombre
        """, [c["id"]])
        
        detalle = []
        for d in detalle_rows:
            detalle.append({
                "categoria": d["categoria"],
                "nombre": d["nombre"],
                "cantidad": d["cantidad"],
                "precio": float(d["precio"]),
                "subtotal": float(d["subtotal"]),
                "observaciones": d["observaciones"] if d["observaciones"] else ""
            })
        
        total = sum(d["subtotal"] for d in detalle)
        
        if clave not in mesas:
            mesas[clave] = {"comandas": [], "estado_general": c["estado"]}
        
        mesas[clave]["comandas"].append({
            "id": int(c["id"]),
            "estado": str(c["estado"]),
            "tipo": str(c["tipo"]),
            "mesa": int(c["mesa"]) if c["mesa"] else None,
            "alias": str(c["alias"]) if c["alias"] else "",
            "detalle": detalle, 
            "total": float(total)
        })
        
        estados = [cmd["estado"] for cmd in mesas[clave]["comandas"]]
        if "Pendiente" in estados:
            mesas[clave]["estado_general"] = "Pendiente"
        elif "Preparando" in estados:
            mesas[clave]["estado_general"] = "Preparando"
        else:
            mesas[clave]["estado_general"] = "Lista"
    
    return render_template("comandas.html", 
        mesas=mesas, nombre_negocio=NOMBRE_NEGOCIO)


@app.route("/editar_comanda/<int:comanda_id>", methods=["GET", "POST"])
@login_required
def editar_comanda(comanda_id):
    if request.method == "POST":
        # Actualizar existentes
        detalles = query_db("SELECT id FROM detalle_comanda WHERE comanda_id=?", [comanda_id])
        for d in detalles:
            cant = int(request.form.get(f"cant_{d['id']}", 0))
            obs = request.form.get(f"obs_{d['id']}", "").strip()
            
            if cant <= 0:
                execute_db("DELETE FROM detalle_comanda WHERE id=?", [d["id"]])
            else:
                execute_db("""
                    UPDATE detalle_comanda 
                    SET cantidad=?, observaciones=? 
                    WHERE id=?
                """, [cant, obs, d["id"]])
        
        # Agregar nuevos productos
        productos = query_db("SELECT id FROM productos")
        for p in productos:
            cant = int(request.form.get(f"nuevo_{p['id']}", 0))
            if cant > 0:
                obs = request.form.get(f"obs_nuevo_{p['id']}", "").strip()
                execute_db("""
                    INSERT INTO detalle_comanda 
                    (comanda_id, producto_id, cantidad, observaciones, entregado_cantidad)
                    VALUES (?,?,?,?, 0)
                """, [comanda_id, p["id"], cant, obs])
        
        # Verificar si la comanda quedó vacía
        remaining = query_db("SELECT COUNT(*) as count FROM detalle_comanda WHERE comanda_id=?", 
                           [comanda_id], one=True)
        if remaining["count"] == 0:
            execute_db("DELETE FROM comandas WHERE id=?", [comanda_id])
            return redirect("/comandas")
        
        return redirect("/comandas")
    
    detalle = query_db("""
        SELECT d.id, p.nombre, d.cantidad, d.observaciones, p.categoria
        FROM detalle_comanda d
        JOIN productos p ON d.producto_id = p.id
        WHERE d.comanda_id=?
        ORDER BY p.categoria, p.nombre
    """, [comanda_id])
    
    productos = query_db("SELECT id, nombre, categoria FROM productos ORDER BY categoria, nombre")
    
    return render_template("editar_comanda.html",
        comanda_id=comanda_id, detalle=detalle, productos=productos)


@app.route("/cerrar_comanda/<int:comanda_id>")
@login_required
def cerrar_comanda(comanda_id):
    detalle = query_db("""
        SELECT d.producto_id, d.cantidad, p.precio
        FROM detalle_comanda d
        JOIN productos p ON d.producto_id = p.id
        WHERE d.comanda_id = ?
    """, [comanda_id])
    
    total = sum(d["precio"] * d["cantidad"] for d in detalle)
    
    # Crear venta
    venta_id = execute_db("""
        INSERT INTO ventas (fecha, total) VALUES (DATE('now'), ?)
    """, [total])
    
    # Insertar detalles
    for d in detalle:
        subtotal = d["precio"] * d["cantidad"]
        execute_db("""
            INSERT INTO detalle_venta (venta_id, producto_id, cantidad, subtotal)
            VALUES (?,?,?,?)
        """, [venta_id, d["producto_id"], d["cantidad"], subtotal])
    
    # Actualizar control diario
    execute_db("""
        UPDATE control_diario 
        SET ventas = COALESCE(ventas, 0) + ?
        WHERE id = 1
    """, [total])
    
    # Eliminar comanda
    execute_db("DELETE FROM comandas WHERE id=?", [comanda_id])
    
    return redirect("/corte")

@app.route("/cambiar_estado/<int:comanda_id>")
@login_required
def cambiar_estado(comanda_id):
    estado = query_db("SELECT estado FROM comandas WHERE id=?", 
                     [comanda_id], one=True)["estado"]
    
    nuevo = {"Pendiente": "Preparando", "Preparando": "Lista"}.get(estado, "Lista")
    execute_db("UPDATE comandas SET estado=? WHERE id=?", [nuevo, comanda_id])
    return redirect("/comandas")

@app.route("/comanda_ticket/<int:comanda_id>")
@login_required
def comanda_ticket(comanda_id):
    comanda = query_db("SELECT * FROM comandas WHERE id=?", [comanda_id], one=True)
    if not comanda:
        return "Comanda no encontrada", 404
    
    filas = query_db("""
        SELECT p.categoria, p.nombre, dc.cantidad, dc.observaciones, p.precio
        FROM detalle_comanda dc
        JOIN productos p ON p.id = dc.producto_id
        WHERE dc.comanda_id = ?
        ORDER BY p.categoria, p.nombre
    """, [comanda_id])
    
    detalle = {}
    total = 0
    for f in filas:
        cat = f["categoria"]
        if cat not in detalle:
            detalle[cat] = []
        detalle[cat].append(f)
        total += f["cantidad"] * f["precio"]
    
    return render_template("ticket_comanda.html",
        comanda=comanda, detalle=detalle, total=total)

# ---------- COCINA ----------
@app.route("/cocina")
@login_required
def cocina():
    comandas_db = query_db("""
        SELECT id, estado, COALESCE(mesa,0) as mesa, 
               COALESCE(tipo,'MESA') as tipo, COALESCE(alias,'') as alias
        FROM comandas
        WHERE UPPER(estado) IN ('PENDIENTE','PREPARANDO')
        ORDER BY id ASC
    """)
    
    comandas = []
    for c in comandas_db:
        detalle = query_db("""
            SELECT d.id, p.nombre, p.categoria, d.cantidad, 
                   d.entregado_cantidad, d.observaciones
            FROM detalle_comanda d
            JOIN productos p ON d.producto_id = p.id
            WHERE d.comanda_id = ?
            ORDER BY p.categoria, p.nombre
        """, [c["id"]])
        
        comandas.append({
            "id": c["id"], "estado": c["estado"], "mesa": c["mesa"],
            "tipo": c["tipo"], "alias": c["alias"], "detalle": detalle
        })
    
    return render_template("cocina.html", comandas=comandas)

@app.route("/entregar_uno/<int:detalle_id>")
@login_required
def entregar_uno(detalle_id):
    detalle = query_db("""
        SELECT comanda_id, cantidad, entregado_cantidad 
        FROM detalle_comanda WHERE id=?
    """, [detalle_id], one=True)
    
    if detalle and detalle["entregado_cantidad"] < detalle["cantidad"]:
        execute_db("""
            UPDATE detalle_comanda 
            SET entregado_cantidad = entregado_cantidad + 1
            WHERE id=?
        """, [detalle_id])
        revisar_comanda_completa(detalle["comanda_id"])
    
    return redirect("/cocina")

@app.route("/quitar_uno/<int:detalle_id>")
@login_required
def quitar_uno(detalle_id):
    detalle = query_db("""
        SELECT comanda_id, entregado_cantidad 
        FROM detalle_comanda WHERE id=?
    """, [detalle_id], one=True)
    
    if detalle and detalle["entregado_cantidad"] > 0:
        execute_db("""
            UPDATE detalle_comanda 
            SET entregado_cantidad = entregado_cantidad - 1
            WHERE id=?
        """, [detalle_id])
    
    return redirect("/cocina")

@app.route("/entregar_todo/<int:comanda_id>")
@login_required
def entregar_todo(comanda_id):
    execute_db("""
        UPDATE detalle_comanda SET entregado_cantidad = cantidad WHERE comanda_id = ?
    """, [comanda_id])
    execute_db("UPDATE comandas SET estado = 'Lista' WHERE id = ?", [comanda_id])
    return redirect("/cocina")

@app.route("/toggle_entregado", methods=["POST"])
@login_required
def toggle_entregado():
    detalle_id = request.form.get("detalle_id")
    checked = request.form.get("checked") == "true"
    
    nueva_cant = "cantidad" if checked else "0"
    execute_db(f"""
        UPDATE detalle_comanda SET entregado_cantidad = {nueva_cant} WHERE id = ?
    """, [detalle_id])
    
    if checked:
        comanda = query_db("""
            SELECT comanda_id FROM detalle_comanda WHERE id=?
        """, [detalle_id], one=True)
        if comanda:
            revisar_comanda_completa(comanda["comanda_id"])
    
    return "", 204

# ---------- MESAS ----------
@app.route("/mesas")
@login_required
def mesas():
    comandas_activas = query_db("""
        SELECT id, tipo, mesa, estado FROM comandas WHERE estado != 'Cerrada'
    """)
    
    mesas = []
    for n in range(1, 6):
        comanda = next(
            (c for c in comandas_activas if c["tipo"] == "MESA" and c["mesa"] == n),
            None
        )
        mesas.append({
            "label": f"Mesa {n}", "tipo": "MESA", "mesa": n,
            "comanda": comanda
        })
    
    llevar = next(
        (c for c in comandas_activas if c["tipo"] == "LLEVAR"),
        None
    )
    mesas.append({
        "label": "Para llevar", "tipo": "LLEVAR", "mesa": None,
        "comanda": llevar
    })
    
    return render_template("mesas.html", mesas=mesas)

# ---------- CORTES ----------
@app.route("/corte")
@login_required
def corte():
    hoy = query_db("""
        SELECT COUNT(*) as total_ventas, IFNULL(SUM(total),0) as total_dinero
        FROM ventas WHERE fecha = DATE('now')
    """, one=True)
    
    ranking = query_db("""
        SELECT p.nombre, SUM(dv.cantidad) as total_cantidad,
               SUM(dv.subtotal) as total_dinero
        FROM detalle_venta dv
        JOIN productos p ON dv.producto_id = p.id
        JOIN ventas v ON dv.venta_id = v.id
        WHERE v.fecha = DATE('now')
        GROUP BY p.nombre
        ORDER BY total_cantidad DESC, total_dinero DESC
    """)
    
    return render_template("corte.html",
        total_ventas=hoy["total_ventas"],
        total_dinero=hoy["total_dinero"],
        ranking=ranking)

@app.route("/corte_diario", methods=["POST"])
@login_required
def corte_diario():
    ventas = query_db("""
        SELECT IFNULL(SUM(total),0) FROM ventas 
        WHERE fecha = DATE('now','localtime')
    """, one=True)[0]
    
    gastos = query_db("""
        SELECT IFNULL(SUM(monto),0) FROM tickets 
        WHERE fecha = DATE('now','localtime')
    """, one=True)[0]
    
    execute_db("""
        INSERT OR REPLACE INTO cortes_diarios 
        (fecha, ventas, gastos, utilidad, creado_en)
        VALUES (?, ?, ?, ?, DATETIME('now','localtime'))
    """, [date.today().isoformat(), ventas, gastos, ventas - gastos])
    
    return redirect("/control")

# ---------- GASTOS ADICIONALES ----------
@app.route("/gastos", methods=["GET", "POST"])
@login_required
def gastos():
    semana_actual = get_semana_actual()
    
    if request.method == "POST":
        return guardar_gasto()
    
    gastos = query_db("""
        SELECT t.id, t.fecha, t.categoria, t.monto, t.nota, t.archivo, t.semana_id
        FROM tickets t
        ORDER BY t.fecha DESC, t.id DESC
    """)
    
    # Agregar info de semana a cada gasto
    gastos_con_semana = []
    for g in gastos:
        semana_info = None
        if g["semana_id"]:
            semana_info = query_db("SELECT fecha_inicio FROM semanas WHERE id = ?", 
                                 [g["semana_id"]], one=True)
        
        gastos_con_semana.append({
            "id": g["id"],
            "fecha": g["fecha"],
            "categoria": g["categoria"],
            "monto": g["monto"],
            "nota": g["nota"],
            "archivo": g["archivo"],
            "semana": semana_info["fecha_inicio"] if semana_info else "N/A"
        })
    
    return render_template("gastos.html", 
                         gastos=gastos_con_semana,
                         semana_actual=semana_actual)

def guardar_gasto():
    archivo = None
    if "foto" in request.files:
        foto = request.files["foto"]
        if foto.filename:
            ext = secure_filename(foto.filename).rsplit('.', 1)[-1]
            archivo = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
            foto.save(os.path.join(TICKETS_FOLDER, archivo))
    
    categoria = request.form.get("categoria")
    monto = float(request.form.get("monto", 0))
    
    # Obtener semana actual
    semana = get_semana_actual()
    semana_id = semana["id"] if semana else None
    
    execute_db("""
        INSERT INTO tickets (fecha, categoria, monto, archivo, nota, tipo_gasto, semana_id)
        VALUES (?,?,?,?,?,?,?)
    """, [
        request.form.get("fecha", date.today().isoformat()),
        categoria,
        monto,
        archivo,
        request.form.get("nota",""),
        request.form.get("tipo_gasto", "VARIABLE"),
        semana_id
    ])
    
    # Actualizar apartado semanal
    if semana_id and categoria:
        actualizar_gasto_apartado(semana_id, categoria, monto)
    
    return redirect("/gastos")

@app.route("/gastos/eliminar/<int:id>", methods=["POST"])
@login_required
def eliminar_gasto(id):
    return eliminar_ticket(id)

@app.route("/gastos/editar/<int:id>", methods=["POST"])
@login_required
def editar_gasto(id):
    execute_db("""
        UPDATE tickets 
        SET fecha=?, categoria=?, monto=?, nota=?
        WHERE id=?
    """, [
        request.form.get("fecha"),
        request.form.get("categoria"),
        float(request.form.get("monto", 0)),
        request.form.get("nota", ""),
        id
    ])
    return redirect("/gastos")

# ---------- APARTADOS SEMANALES OPTIMIZADOS ----------
@app.route("/apartados", methods=["GET", "POST"])
@login_required
def apartados():
    semana = get_semana_actual()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "update_presupuesto":
            # Actualizar presupuesto base
            execute_db("""
                UPDATE apartados SET presupuesto = ? WHERE id = ?
            """, [float(request.form.get("monto", 0)), request.form.get("id")])
            
            # Actualizar también en la semana actual si existe
            apartado = query_db("SELECT nombre FROM apartados WHERE id = ?", 
                              [request.form.get("id")], one=True)
            if apartado and semana:
                db = get_db()
                db.execute("""
                    UPDATE apartados_semanales 
                    SET presupuesto = ? 
                    WHERE semana_id = ? AND categoria = ?
                """, [float(request.form.get("monto", 0)), semana["id"], apartado["nombre"]])
                db.commit()
            
        elif action == "cerrar_semana":
            # Calcular saldo total restante de esta semana
            saldo_restante = query_db("""
                SELECT COALESCE(SUM(a.presupuesto - COALESCE(ash.gastado, 0)), 0)
                FROM apartados a
                LEFT JOIN apartados_semanales ash ON a.nombre = ash.categoria AND ash.semana_id = ?
            """, [semana["id"]], one=True)[0]
            
            # Sumar acumulado anterior
            acumulado_total = saldo_restante + (semana["acumulado"] or 0)
            
            # Cerrar semana actual
            execute_db("""
                UPDATE semanas SET estado = 'CERRADA' WHERE id = ?
            """, [semana["id"]])
            
            # Crear nueva semana
            hoy = date.today()
            offset = (hoy.weekday() - 4) % 7
            nuevo_viernes = hoy - timedelta(days=offset) + timedelta(days=7)
            nuevo_domingo = nuevo_viernes + timedelta(days=2)
            
            nueva_semana_id = execute_db("""
                INSERT INTO semanas (fecha_inicio, fecha_fin, acumulado, estado) 
                VALUES (?, ?, ?, 'ACTIVA')
            """, [nuevo_viernes.isoformat(), nuevo_domingo.isoformat(), acumulado_total])
            
            # Crear registros de apartados para nueva semana
            db = get_db()
            db.execute("""
                INSERT INTO apartados_semanales (semana_id, categoria, presupuesto)
                SELECT ?, nombre, presupuesto FROM apartados
            """, [nueva_semana_id])
            db.commit()
            
        return redirect("/apartados")
    
    # Obtener semanas para selector
    semanas = query_db("SELECT * FROM semanas ORDER BY fecha_inicio DESC")
    semana_seleccionada = request.args.get("semana_id", type=int)
    
    if semana_seleccionada:
        semana_actual_datos = query_db("SELECT * FROM semanas WHERE id = ?", 
                                     [semana_seleccionada], one=True)
    else:
        semana_actual_datos = semana
        semana_seleccionada = semana["id"]
    
    apartados_data = get_apartados_semana(semana_seleccionada)
    
    # Calcular totales
    total_presupuesto = sum(a["presupuesto"] for a in apartados_data)
    total_gastado = sum(a["gastado_semana"] for a in apartados_data)
    total_restante = total_presupuesto - total_gastado
    acumulado = semana_actual_datos["acumulado"] if semana_actual_datos else 0
    
    return render_template("apartados.html", 
        apartados=apartados_data,
        semanas=semanas,
        semana_actual=semana_actual_datos,
        semana_seleccionada=semana_seleccionada,
        total_presupuesto=total_presupuesto,
        total_gastado=total_gastado,
        total_restante=total_restante,
        acumulado=acumulado,
        puede_cerrar=semana_actual_datos and semana_actual_datos["estado"] == "ACTIVA"
    )

# ---------- EXPORTAR ----------
@app.route("/exportar_ventas_csv")
@login_required
def exportar_ventas_csv():
    ventas = query_db("""
        SELECT id, fecha, total FROM ventas 
        WHERE fecha = DATE('now') ORDER BY id ASC
    """)
    
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ID Venta", "Fecha", "Total"])
    for v in ventas:
        writer.writerow([v["id"], v["fecha"], v["total"]])
    
    buffer.seek(0)
    return send_file(
        BytesIO(buffer.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="ventas_hoy.csv"
    )

@app.route("/exportar_ranking_csv")
@login_required
def exportar_ranking_csv():
    ranking = query_db("""
        SELECT p.nombre, SUM(dv.cantidad) as cantidad, SUM(dv.subtotal) as total
        FROM detalle_venta dv
        JOIN productos p ON dv.producto_id = p.id
        JOIN ventas v ON dv.venta_id = v.id
        WHERE v.fecha = DATE('now')
        GROUP BY p.nombre ORDER BY cantidad DESC
    """)
    
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Producto", "Cantidad Vendida", "Total Generado"])
    for r in ranking:
        writer.writerow([r["nombre"], r["cantidad"], r["total"]])
    
    buffer.seek(0)
    return send_file(
        BytesIO(buffer.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="ranking_hoy.csv"
    )

# ---------- RESPALDO ----------
@app.route("/respaldar_db")
@login_required
def respaldar_db():
    backup_dir = os.path.join(BASE_DIR, "respaldos")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_name = f"database_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_name)
    
    # Cerrar conexión actual para poder copiar
    close_db()
    shutil.copy(DB, backup_path)
    
    return f"""
    <h2>✅ Respaldo creado</h2>
    <p>{backup_name}</p>
    <a href='/'>⬅ Volver al menú</a>
    """

# ---------- API ----------
@app.route("/api/ultima_comanda")
@login_required
def api_ultima_comanda():
    ultima = query_db("""
        SELECT IFNULL(MAX(id), 0) as ultimo_id 
        FROM comandas 
        WHERE UPPER(estado) IN ('PENDIENTE','PREPARANDO')
    """, one=True)
    return jsonify({"ultimo_id": ultima["ultimo_id"]})
    
@app.route("/api/dashboard_data")
def api_dashboard():
    hoy = date.today().isoformat()
    ayer = (date.today() - timedelta(days=1)).isoformat()
    
    ventas_hoy = query_db("SELECT IFNULL(SUM(total),0) FROM ventas WHERE fecha=?", [hoy], one=True)[0]
    ventas_ayer = query_db("SELECT IFNULL(SUM(total),0) FROM ventas WHERE fecha=?", [ayer], one=True)[0]
    ordenes = query_db("SELECT COUNT(*) FROM comandas WHERE estado IN ('Pendiente','Preparando')", one=True)[0]
    mesas = query_db("SELECT COUNT(DISTINCT mesa) FROM comandas WHERE tipo='MESA' AND estado!='Cerrada'", one=True)[0]
    
    return jsonify({
        "ventas": float(ventas_hoy),
        "ventas_ayer": float(ventas_ayer),
        "ordenes": ordenes,
        "mesas_ocupadas": mesas,
        "cocina": query_db("SELECT COUNT(*) FROM comandas WHERE estado='Preparando'", one=True)[0]
    })
    
@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect("/login")
    
# ---------- ADMINISTRACIÓN DE USUARIOS ----------
@app.route("/admin/usuarios")
@login_required
def admin_usuarios():
    # Verificar que sea admin
    if session.get("rol") != "admin":
        return redirect("/")
    
    usuarios = query_db("SELECT id, usuario, rol FROM usuarios ORDER BY id")
    return render_template("admin_usuarios.html", usuarios=usuarios)

@app.route("/admin/usuarios/crear", methods=["POST"])
@login_required
def admin_usuarios_crear():
    if session.get("rol") != "admin":
        return redirect("/")
    
    usuario = request.form.get("usuario", "").strip()
    password = request.form.get("password", "")
    rol = request.form.get("rol", "mesero")
    
    if not usuario or not password:
        return redirect("/admin/usuarios")
    
    try:
        execute_db("""
            INSERT INTO usuarios (usuario, password, rol) 
            VALUES (?, ?, ?)
        """, [usuario, password, rol])
    except sqlite3.IntegrityError:
        # Usuario ya existe
        pass
    
    return redirect("/admin/usuarios")

@app.route("/admin/usuarios/editar", methods=["POST"])
@login_required
def admin_usuarios_editar():
    if session.get("rol") != "admin":
        return redirect("/")
    
    user_id = request.form.get("user_id")
    nuevo_rol = request.form.get("rol")
    nueva_password = request.form.get("password", "").strip()
    
    if not user_id:
        return redirect("/admin/usuarios")
    
    # Actualizar rol
    if nuevo_rol:
        execute_db("""
            UPDATE usuarios SET rol = ? WHERE id = ?
        """, [nuevo_rol, user_id])
    
    # Actualizar password solo si se proporcionó
    if nueva_password:
        execute_db("""
            UPDATE usuarios SET password = ? WHERE id = ?
        """, [nueva_password, user_id])
    
    return redirect("/admin/usuarios")

@app.route("/admin/usuarios/eliminar", methods=["POST"])
@login_required
def admin_usuarios_eliminar():
    if session.get("rol") != "admin":
        return redirect("/")
    
    user_id = request.form.get("user_id")
    
    if user_id:
        # Evitar que se elimine a sí mismo
        usuario_actual = query_db("SELECT id FROM usuarios WHERE usuario = ?", 
                                 [session["usuario"]], one=True)
        if usuario_actual and str(usuario_actual["id"]) != str(user_id):
            execute_db("DELETE FROM usuarios WHERE id = ?", [user_id])
    
    return redirect("/admin/usuarios")
    

# =========================
# CONFIGURACIÓN INVENTARIO (Añadir al inicio con las demás constantes)
# =========================
UNIDADES_MEDIDA = ["piezas", "kg", "litros", "bolsas", "cajas", "gramos", "ml"]
CATEGORIAS_INSUMO = ["Tortillas/Masa", "Carnes", "Quesos/Crema", "Verduras", 
                     "Bebidas", "Empaque", "Gas/Cocina", "Limpieza", "Otros"]

# =========================
# ACTUALIZAR init_db() - Añadir al final del schema
# =========================
def init_db():
    # ... tu código actual ...
    
    schema_additions = """
    -- INSUMOS/INVENTARIO
    CREATE TABLE IF NOT EXISTS insumos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL,
        categoria TEXT,
        unidad_medida TEXT DEFAULT 'piezas',
        stock_actual REAL DEFAULT 0,
        stock_minimo REAL DEFAULT 10,
        costo_unitario REAL DEFAULT 0,
        proveedor TEXT,
        activo INTEGER DEFAULT 1,
        fecha_actualizacion TEXT
    );
    
    -- MOVIMIENTOS DE INVENTARIO (Entradas, Salidas, Mermas)
    CREATE TABLE IF NOT EXISTS movimientos_inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        insumo_id INTEGER,
        tipo TEXT, -- 'ENTRADA', 'SALIDA', 'MERMA', 'AJUSTE'
        cantidad REAL,
        stock_previo REAL,
        stock_nuevo REAL,
        motivo TEXT,
        usuario TEXT,
        fecha TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (insumo_id) REFERENCES insumos(id)
    );
    
    -- RELACIÓN PRODUCTO-INSUMO (para descontar automáticamente al vender)
    CREATE TABLE IF NOT EXISTS recetas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER,
        insumo_id INTEGER,
        cantidad_uso REAL, -- Cuánto usa de cada insumo
        FOREIGN KEY (producto_id) REFERENCES productos(id),
        FOREIGN KEY (insumo_id) REFERENCES insumos(id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_movimientos_insumo ON movimientos_inventario(insumo_id);
    CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos_inventario(fecha);
    """
    
    db = get_db()
    db.executescript(schema_additions)
    
    # Insumos por defecto para un restaurante de antojitos
    insumos_default = [
        ("Tortilla de Maíz", "Tortillas/Masa", "piezas", 100, 50),
        ("Masa para Gorditas", "Tortillas/Masa", "kg", 20, 5),
        ("Carne de Pastor", "Carnes", "kg", 10, 3),
        ("Carne de Bistec", "Carnes", "kg", 8, 2),
        ("Queso Fresco", "Quesos/Crema", "kg", 5, 1),
        ("Crema", "Quesos/Crema", "litros", 2, 0.5),
        ("Lechuga", "Verduras", "piezas", 10, 3),
        ("Cebolla", "Verduras", "kg", 5, 1),
        ("Cilantro", "Verduras", "manojos", 8, 2),
        ("Refrescos 600ml", "Bebidas", "piezas", 48, 12),
        ("Agua Fresca", "Bebidas", "litros", 20, 5),
        ("Gas LP", "Gas/Cocina", "litros", 100, 20),
    ]
    
    for nombre, cat, unidad, stock, minimo in insumos_default:
        db.execute("""
            INSERT OR IGNORE INTO insumos (nombre, categoria, unidad_medida, stock_actual, stock_minimo, fecha_actualizacion)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, [nombre, cat, unidad, stock, minimo])
    
    db.commit()

# =========================
# RUTAS DE INVENTARIO (Añadir al final antes del if __name__)
# =========================

@app.route("/inventario")
@login_required
def inventario():
    """Vista principal de inventario con asistente de voz"""
    filtro_cat = request.args.get("categoria", "")
    
    query = "SELECT * FROM insumos WHERE activo=1"
    params = []
    if filtro_cat:
        query += " AND categoria=?"
        params.append(filtro_cat)
    query += " ORDER BY categoria, nombre"
    
    # Obtener datos y convertir a diccionarios mutables
    rows = query_db(query, params)
    insumos = []
    for row in rows:
        # Convertir sqlite3.Row a dict para poder modificarlo
        i = dict(row)
        
        # Calcular estado
        if i["stock_minimo"] > 0:
            porcentaje = (i["stock_actual"] / i["stock_minimo"]) * 100
        else:
            porcentaje = 100
            
        i["porcentaje"] = min(porcentaje, 100)
        
        if porcentaje <= 100:
            i["estado"] = "critico"
        elif porcentaje <= 150:
            i["estado"] = "bajo"
        else:
            i["estado"] = "ok"
            
        insumos.append(i)
    
    # Alertas de stock bajo
    alertas = query_db("""
        SELECT nombre, stock_actual, stock_minimo, unidad_medida 
        FROM insumos 
        WHERE activo=1 AND stock_actual <= stock_minimo
        ORDER BY (stock_actual/stock_minimo) ASC
    """)
    
    # Historial reciente (últimos 20 movimientos)
    mov_rows = query_db("""
        SELECT m.*, i.nombre as insumo_nombre, i.unidad_medida
        FROM movimientos_inventario m
        JOIN insumos i ON m.insumo_id = i.id
        ORDER BY m.fecha DESC
        LIMIT 20
    """)
    
    # Convertir movimientos también a dicts si necesitas modificarlos luego
    movimientos = [dict(m) for m in mov_rows] if mov_rows else []
    
    return render_template("inventario.html",
        insumos=insumos,
        alertas=alertas,
        movimientos=movimientos,
        categorias=CATEGORIAS_INSUMO,
        unidades=UNIDADES_MEDIDA,
        filtro_cat=filtro_cat
    )


@app.route("/inventario/movimiento", methods=["POST"])
@login_required
def inventario_movimiento():
    """API para registrar entradas, salidas o mermas"""
    data = request.get_json() or request.form
    
    insumo_id = data.get("insumo_id")
    tipo = data.get("tipo", "ENTRADA").upper()  # ENTRADA, SALIDA, MERMA, AJUSTE
    cantidad = float(data.get("cantidad", 0))
    motivo = data.get("motivo", "")
    usuario = session.get("usuario", "sistema")
    
    if not insumo_id or cantidad <= 0:
        return jsonify({"error": "Datos inválidos"}), 400
    
    db = get_db()
    
    # Obtener stock actual
    insumo = query_db("SELECT stock_actual FROM insumos WHERE id=?", [insumo_id], one=True)
    if not insumo:
        return jsonify({"error": "Insumo no encontrado"}), 404
    
    stock_previo = insumo["stock_actual"]
    
    # Calcular nuevo stock
    if tipo == "ENTRADA":
        stock_nuevo = stock_previo + cantidad
    elif tipo in ["SALIDA", "MERMA"]:
        stock_nuevo = max(0, stock_previo - cantidad)
        if stock_nuevo < 0:
            return jsonify({"error": "Stock insuficiente"}), 400
    else:  # AJUSTE
        stock_nuevo = cantidad
    
    # Actualizar insumo
    db.execute("""
        UPDATE insumos SET stock_actual=?, fecha_actualizacion=datetime('now')
        WHERE id=?
    """, [stock_nuevo, insumo_id])
    
    # Registrar movimiento
    db.execute("""
        INSERT INTO movimientos_inventario 
        (insumo_id, tipo, cantidad, stock_previo, stock_nuevo, motivo, usuario)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [insumo_id, tipo, cantidad, stock_previo, stock_nuevo, motivo, usuario])
    
    db.commit()
    
    # Verificar si quedó bajo de stock para alerta
    insumo_actualizado = query_db("SELECT * FROM insumos WHERE id=?", [insumo_id], one=True)
    es_bajo = insumo_actualizado["stock_actual"] <= insumo_actualizado["stock_minimo"]
    
    return jsonify({
        "success": True,
        "insumo": insumo_actualizado["nombre"],
        "stock_nuevo": stock_nuevo,
        "es_bajo": es_bajo,
        "unidad": insumo_actualizado["unidad_medida"]
    })

@app.route("/inventario/nuevo", methods=["POST"])
@login_required
def inventario_nuevo():
    """Agregar nuevo insumo al sistema"""
    nombre = request.form.get("nombre")
    categoria = request.form.get("categoria")
    unidad = request.form.get("unidad_medida")
    stock = float(request.form.get("stock_inicial", 0))
    minimo = float(request.form.get("stock_minimo", 10))
    
    try:
        execute_db("""
            INSERT INTO insumos (nombre, categoria, unidad_medida, stock_actual, stock_minimo)
            VALUES (?, ?, ?, ?, ?)
        """, [nombre, categoria, unidad, stock, minimo])
        return redirect("/inventario")
    except sqlite3.IntegrityError:
        return "Error: Ese insumo ya existe", 400

@app.route("/api/inventario/consulta")
@login_required
def api_consulta_inventario():
    """API para el asistente de voz - consulta por nombre"""
    q = request.args.get("q", "").lower()
    
    # Búsqueda flexible (contiene)
    insumo = query_db("""
        SELECT nombre, stock_actual, stock_minimo, unidad_medida, categoria
        FROM insumos 
        WHERE LOWER(nombre) LIKE ? AND activo=1
        LIMIT 1
    """, [f"%{q}%"], one=True)
    
    if insumo:
        estado = "bajo" if insumo["stock_actual"] <= insumo["stock_minimo"] else "normal"
        return jsonify({
            "encontrado": True,
            "nombre": insumo["nombre"],
            "cantidad": insumo["stock_actual"],
            "unidad": insumo["unidad_medida"],
            "minimo": insumo["stock_minimo"],
            "estado": estado,
            "mensaje": f"Tenemos {insumo['stock_actual']} {insumo['unidad_medida']} de {insumo['nombre']}. {'¡Stock bajo!' if estado == 'bajo' else 'Stock normal.'}"
        })
    else:
        return jsonify({
            "encontrado": False,
            "mensaje": f"No encontré {q} en el inventario"
        })

@app.route("/api/inventario/alertas")
@login_required
def api_alertas_inventario():
    """Devuelve lista de insumos con stock bajo para el asistente"""
    alertas = query_db("""
        SELECT nombre, stock_actual, stock_minimo, unidad_medida 
        FROM insumos 
        WHERE activo=1 AND stock_actual <= stock_minimo
        ORDER BY (stock_actual/stock_minimo) ASC
    """)
    
    if not alertas:
        return jsonify({"hay_alertas": False, "mensaje": "No hay alertas de inventario. Todo está bien."})
    
    mensaje = "Alertas de stock bajo: "
    for a in alertas[:5]:  # Máximo 5 para no ser muy largo
        mensaje += f"{a['nombre']} ({a['stock_actual']} {a['unidad_medida']}), "
    
    return jsonify({
        "hay_alertas": True,
        "cantidad": len(alertas),
        "mensaje": mensaje.rstrip(", "),
        "detalle": [{"nombre": a["nombre"], "actual": a["stock_actual"], "minimo": a["stock_minimo"]} for a in alertas]
    })

# Función para descontar automáticamente al cerrar comanda (integrar en cerrar_comanda)
def descontar_inventario_por_venta(producto_id, cantidad_vendida):
    """Descuenta automáticamente del inventario basado en recetas"""
    recetas = query_db("SELECT * FROM recetas WHERE producto_id=?", [producto_id])
    
    for receta in recetas:
        insumo = query_db("SELECT * FROM insumos WHERE id=?", [receta["insumo_id"]], one=True)
        if insumo:
            total_a_descontar = receta["cantidad_uso"] * cantidad_vendida
            nuevo_stock = max(0, insumo["stock_actual"] - total_a_descontar)
            
            execute_db("""
                UPDATE insumos SET stock_actual=?, fecha_actualizacion=datetime('now') WHERE id=?
            """, [nuevo_stock, receta["insumo_id"]])
            
            # Registrar movimiento automático
            execute_db("""
                INSERT INTO movimientos_inventario 
                (insumo_id, tipo, cantidad, stock_previo, stock_nuevo, motivo, usuario)
                VALUES (?, 'SALIDA', ?, ?, ?, 'Venta automática', 'sistema')
            """, [receta["insumo_id"], total_a_descontar, insumo["stock_actual"], nuevo_stock])
            
@app.route("/catalogo_insumos")
@login_required
def catalogo_insumos():
    """Vista limpia para gestionar el catálogo de insumos"""
    filtro_cat = request.args.get("categoria", "")
    busqueda = request.args.get("q", "").lower()
    
    # Query base
    query = "SELECT * FROM insumos WHERE activo=1"
    params = []
    
    if filtro_cat:
        query += " AND categoria=?"
        params.append(filtro_cat)
    
    if busqueda:
        query += " AND LOWER(nombre) LIKE ?"
        params.append(f"%{busqueda}%")
    
    query += " ORDER BY categoria, nombre"
    
    rows = query_db(query, params)
    insumos = [dict(r) for r in rows] if rows else []
    
    # Conteo por categoría para filtros
    categorias_count = query_db("""
        SELECT categoria, COUNT(*) as total 
        FROM insumos 
        WHERE activo=1 
        GROUP BY categoria 
        ORDER BY total DESC
    """)
    
    return render_template("catalogo_insumos.html",
        insumos=insumos,
        categorias=categorias_count or [],
        categorias_disponibles=CATEGORIAS_INSUMO,
        unidades=UNIDADES_MEDIDA,
        filtro_cat=filtro_cat,
        busqueda=busqueda,
        total_insumos=len(insumos)
    )

@app.route("/api/insumos/<int:id>", methods=["PUT", "DELETE"])
@login_required
def api_insumo(id):
    """API para editar o desactivar insumos"""
    db = get_db()
    
    if request.method == "PUT":
        data = request.get_json()
        
        # Validar que no exista otro con el mismo nombre (si cambia el nombre)
        if data.get("nombre"):
            existe = query_db("""
                SELECT id FROM insumos 
                WHERE LOWER(nombre)=LOWER(?) AND id!=? AND activo=1
            """, [data["nombre"], id], one=True)
            if existe:
                return jsonify({"error": "Ya existe un insumo con ese nombre"}), 400
        
        # Construir update dinámico
        campos = []
        valores = []
        
        campos_permitidos = ["nombre", "categoria", "unidad_medida", 
                           "stock_minimo", "costo_unitario", "proveedor"]
        
        for campo in campos_permitidos:
            if campo in data:
                campos.append(f"{campo}=?")
                valores.append(data[campo])
        
        if campos:
            valores.append(id)
            query = f"UPDATE insumos SET {', '.join(campos)}, fecha_actualizacion=datetime('now') WHERE id=?"
            db.execute(query, valores)
            db.commit()
            
            return jsonify({"success": True, "message": "Insumo actualizado"})
        
        return jsonify({"error": "No hay datos para actualizar"}), 400
    
    elif request.method == "DELETE":
        # Soft delete (desactivar)
        db.execute("UPDATE insumos SET activo=0 WHERE id=?", [id])
        db.commit()
        return jsonify({"success": True, "message": "Insumo eliminado"})

@app.route("/api/insumos_bulk", methods=["POST"])
@login_required
def crear_insumos_bulk():
    """Crear múltiples insumos rápidamente (para cuando tienes muchos)"""
    data = request.get_json()
    items = data.get("items", [])
    
    creados = 0
    errores = []
    
    db = get_db()
    
    for item in items:
        try:
            db.execute("""
                INSERT INTO insumos (nombre, categoria, unidad_medida, stock_actual, stock_minimo, activo)
                VALUES (?, ?, ?, 0, ?, 1)
            """, [item["nombre"], item["categoria"], item["unidad_medida"], 
                  item.get("stock_minimo", 10)])
            creados += 1
        except sqlite3.IntegrityError:
            errores.append(f"'{item['nombre']}' ya existe")
    
    db.commit()
    return jsonify({"creados": creados, "errores": errores})






# =========================
# INICIALIZACIÓN
# =========================
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )
