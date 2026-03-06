# Matriz de Conectividad - La Casa Del Chihuahua

Fecha de auditoria: 2026-03-05

## 1) Template -> Ruta render -> Endpoints consumidos -> Tablas

| Template | Ruta que renderiza | Endpoints consumidos desde la vista | Tablas involucradas (directo/indirecto) | Estado |
|---|---|---|---|---|
| `templates/index.html` | `/` | `/venta_rapida`, `/comandas`, `/cocina`, `/mesas`, `/corte`, `/ventas`, `/control`, `/gastos`, `/inventario`, `/productos`, `/catalogo_insumos`, `/apartados`, `/historial_cortes`, `/admin/usuarios`, `/respaldar_db`, `/logout`, `GET /api/dashboard_data` | `ventas`, `comandas` (via dashboard API) | Conectado |
| `templates/login.html` | `/login` | `POST /login` (form sin `action`, envía a misma ruta) | `usuarios` | Conectado |
| `templates/control.html` | `/control` | `/apartados`, `/tickets`, `/gastos`, `/historial_cortes`, `/` | `ventas`, `tickets`, `semanas`, `apartados`, `apartados_semanales` | Conectado |
| `templates/historial_cortes.html` | `/historial_cortes` | `/control` | `cortes_semana` | Conectado |
| `templates/tickets.html` | `/tickets` | `/tickets`, `POST /eliminar_ticket/<id>`, `/control` | `tickets`, `apartados_semanales` (en eliminación) | Conectado |
| `templates/productos.html` | `/productos` | `/editar_producto/<id>`, `/eliminar_producto/<id>`, `/` | `productos` | Conectado |
| `templates/editar_producto.html` | `/editar_producto/<id>` | `/productos`, `/ventas`, `/eliminar_producto/<id>`, `GET /api/stats_producto/<id>` | `productos`, `detalle_venta`, `ventas` (stats API) | Conectado |
| `templates/ventas.html` | `/ventas` | `POST /eliminar_venta/<id>`, `/` | `ventas`, `detalle_venta`, `productos` | Conectado |
| `templates/ventas_rapidas.html` | `/venta_rapida` | `POST /venta_rapida` (form sin `action`, envía a misma ruta), `/` | `productos` (GET), `comandas`, `detalle_comanda` (POST) | Conectado |
| `templates/comandas.html` | `/comandas` | `/cambiar_estado/<id>`, `/cerrar_comanda/<id>`, `/editar_comanda/<id>` | `comandas`, `detalle_comanda`, `productos`, `ventas`, `detalle_venta`, `control_diario`, `recetas`, `insumos`, `movimientos_inventario` (al cerrar) | Conectado |
| `templates/editar_comanda.html` | `/editar_comanda/<id>` | `POST /editar_comanda/<id>`, `/comandas` | `detalle_comanda`, `comandas`, `productos` | Conectado |
| `templates/ticket_comanda.html` | `/comanda_ticket/<id>` | (sin enlaces/acciones críticas) | `comandas`, `detalle_comanda`, `productos` | Conectado |
| `templates/cocina.html` | `/cocina` | `/entregar_todo/<id>`, `/`, `/cocina`, `POST /toggle_entregado`, `GET /api/ultima_comanda` | `comandas`, `detalle_comanda`, `productos` | Conectado |
| `templates/mesas.html` | `/mesas` | `/comandas`, `/venta_rapida?mesa=...`, `/venta_rapida?tipo=LLEVAR`, `/` | `comandas` | Conectado |
| `templates/corte.html` | `/corte` | `/exportar_ventas_csv`, `/exportar_ranking_csv`, `/` | `ventas`, `detalle_venta`, `productos` | Conectado |
| `templates/gastos.html` | `/gastos` | `POST /gastos`, `POST /gastos/eliminar/<id>`, `/control` | `tickets`, `semanas`, `apartados_semanales` | Conectado |
| `templates/apartados.html` | `/apartados` | `GET /apartados` (selector semana, form sin `action`), `POST /apartados` (update/cerrar), `/control`, `/` | `apartados`, `semanas`, `apartados_semanales`, `tickets` | Conectado |
| `templates/admin_usuarios.html` | `/admin/usuarios` | `POST /admin/usuarios/crear`, `POST /admin/usuarios/editar`, `POST /admin/usuarios/eliminar`, `/` | `usuarios` | Conectado |
| `templates/inventario.html` | `/inventario` | `POST /inventario/nuevo`, `POST /inventario/movimiento`, `GET /api/inventario/consulta`, `GET /api/inventario/alertas`, `/` | `insumos`, `movimientos_inventario` | Conectado |
| `templates/catalogo_insumos.html` | `/catalogo_insumos` | `/inventario`, `/catalogo_insumos`, `/catalogo_insumos?categoria=...`, `POST /inventario/nuevo`, `PUT/DELETE /api/insumos/<id>` | `insumos` | Conectado |
| `templates/mesa.html` | (ninguna) | `/comandas`, `/venta_rapida?...`, `/` | N/A | Huérfano (no renderizado) |

## 2) Integración de negocio por dominio

- Ventas/comandas/cocina: conectadas de extremo a extremo (`venta_rapida` -> `comandas`/`detalle_comanda` -> `cerrar_comanda` -> `ventas`/`detalle_venta`).
- Inventario: integrado al cierre de comanda mediante `descontar_inventario_por_venta(...)` usando `recetas` y registrando en `movimientos_inventario`.
- Gastos/apartados/semanas: conectados (`/gastos` actualiza `tickets` + `apartados_semanales`; `/apartados` administra presupuestos y cierre semanal).
- Dashboard (`/api/dashboard_data`): conectado a `index.html`.

## 3) Rutas existentes sin uso directo en templates (deuda técnica)

- `POST /subir_ticket` (flujo legacy; la vista actual usa `POST /gastos`).
- `POST /gastos/editar/<id>` (no hay UI actual para editar gasto).
- `POST /api/insumos_bulk` (sin UI actual, útil para carga masiva futura).
- `POST /corte_diario` (sin botón/form en template actual).
- `GET /comanda_ticket/<id>` (existe template, pero no hay enlace en UI actual).

## 4) Conclusión operativa

- No se detectaron endpoints rotos en los templates activos.
- La conectividad principal del POS (ventas, cocina, inventario, gastos, control) está funcional y coherente.
- Hay 1 template huérfano (`mesa.html`) y 5 rutas activas sin consumo directo en UI (candidatas a limpieza o reactivación por feature flag).
