# Guia 24/7: PC + S23 Ultra (sin apagar operacion)

## Objetivo
- Que el sistema funcione aunque la PC este apagada.
- Que S23 y PC vean la misma base de datos en tiempo real.
- Que puedas seguir editando `app.py` y templates desde la PC.

## Arquitectura recomendada
1. Servidor en la nube siempre encendido (Render/Railway/Fly.io/VPS).
2. Esta app Flask corriendo en ese servidor con `gunicorn`.
3. Una sola base de datos central (inicio con SQLite en disco persistente, luego PostgreSQL).
4. S23 y PC se conectan al mismo URL publico.

## Archivos ya preparados en este repo
- `requirements.txt`
- `Procfile`
- `wsgi.py`
- `.env.example`
- `app.py` ahora soporta `DB_PATH` por variable de entorno.

## Opcion A (rapida): Deploy con SQLite y disco persistente
Esta opcion es la mas rapida para arrancar.

1. Crear repo remoto (GitHub) y subir este proyecto.
2. En tu plataforma (ejemplo Render):
   - New Web Service -> conectar repo.
   - Build Command: `pip install -r requirements.txt`
   - Start Command: se toma de `Procfile`.
3. Configurar variables de entorno:
   - `SECRET_KEY`: una clave larga.
   - `DB_PATH`: ruta del disco persistente, por ejemplo `/var/data/database.db`.
4. Activar disco persistente en el servicio (fundamental para SQLite).
5. Entrar al URL generado y validar login, ventas, cocina, gastos e inventario.

## Opcion B (recomendada para crecimiento): PostgreSQL
Cuando quieras escalar y tener mejor concurrencia:
1. Crear PostgreSQL administrado.
2. Migrar tablas/datos de SQLite a Postgres.
3. Adaptar queries (`?` -> `%s`) o usar capa ORM/mapeo.

Nota: tu codigo actual usa `sqlite3` directo; por eso la ruta segura es empezar con Opcion A y luego migrar con calma.

## Como trabajarias en el dia a dia
1. Editas en PC (`app.py`, `templates/*.html`).
2. Haces `git add .`, `git commit -m "..."`, `git push`.
3. El servidor redeploya.
4. En S23 se actualiza la app (si es PWA, a veces requiere refresco).

## Uso con la PC apagada
- El S23 sigue operando normal porque el servidor esta en la nube.
- Todo lo que captures (gastos, inventario, ventas) queda en la BD central.
- Al prender la PC, veras los cambios inmediatamente al abrir el sistema.

## Instalable en S23 y Windows (PWA)
Mas adelante puedes agregar:
1. `manifest.webmanifest`
2. `service-worker.js`
3. Registro del service worker en templates base

Con eso se podra "instalar" en Android/Windows sin rehacer el sistema.

## Backup recomendado
1. Programar backup diario de `database.db` (si sigues con SQLite).
2. Guardar copias en almacenamiento externo.
3. Probar restauracion 1 vez por semana.

## Checklist de salida a produccion
- [ ] `SECRET_KEY` de produccion definida.
- [ ] `DB_PATH` apuntando a disco persistente.
- [ ] Login admin funcional.
- [ ] Flujo completo: venta -> cocina -> cierre -> corte.
- [ ] Gastos/inventario operando desde movil.
- [ ] Backup diario probado.
