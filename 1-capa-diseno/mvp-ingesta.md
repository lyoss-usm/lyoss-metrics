# Spec: MVP de ingesta (raw)

Objetivo: dejar corriendo la ingesta diaria de las 12 tablas raw definidas en `0-capa-datos/` lo antes posible.
Los marts, Looker Studio y el criterio de madurez X quedan fuera de este spec (ver "Fuera de alcance").

Valores de trending del MVP: `attribute = stars`, `top_limit = 100` (task `trending_repos:stars:100`).

Fuentes: `0-capa-datos/borrador-tablas-raw.md`, `0-capa-datos/politicas.md`, `0-capa-datos/general.md`.

---

## 1. Ubicacion y datasets

| Recurso | Valor | Motivo |
| --- | --- | --- |
| Region de todo (BQ, Cloud Run, Scheduler, Artifact Registry, Secret Manager) | `us-central1` | BQ no permite consultas que crucen ubicaciones: raw y marts deben vivir juntos. Region dentro del Free Tier. |
| Dataset raw | `raw` | Unico dataset del MVP. |
| Datasets de marts | (pendiente, misma region) | Se crean cuando exista la logica de marts. |

Reglas del dataset `raw`:
- Sin `default_table_expiration` ni `default_partition_expiration` (verificar explicitamente: un proyecto que fue sandbox hereda 60 dias).
- Tablas creadas por DDL antes del primer despliegue. El recolector nunca crea tablas ni usa autodetect de esquema.

## 2. Tablas raw: particionado y clustering

Aplica a las 12 tablas (incluida `extractions`):

- Particion: por **mes** sobre `run_at` (truncado a MONTH).
- Clustering: `task`.
- `require_partition_filter`: desactivado (la estrategia B lee todo el historial).
- Esquema: exactamente el de `borrador-tablas-raw.md`. Los campos marcados "(puede ser null)" son NULLABLE; el resto REQUIRED salvo los que la API pueda omitir (decidir en capa 2 al escribir el DDL, ante la duda NULLABLE: un REQUIRED violado hace fallar la carga de la pagina entera).

Justificacion: ~124 KB por corrida (~0,04 GB/año). Particiones diarias serian miles de particiones de KB.
Nota: la particion es por fecha de **ingesta** (`run_at`), no por fecha del evento (`commit_date`, `timestamp`).
La poda solo ayuda a consultas que filtran por ejecucion (estrategias A y C sobre la ultima corrida), no a metricas mensuales por fecha del evento.

## 3. extraction_id

- `extraction_id` = `run_at` expresado en **microsegundos desde epoch UTC** (INT64).
- Biyectivo con `run_at` (misma precision que TIMESTAMP de BQ): dos ejecuciones manuales en el mismo segundo no colisionan.
- Orden de "ultima ejecucion" en los marts: `extraction_id DESC` (equivalente a `run_at DESC`).
- `run_at` se toma **una sola vez** al iniciar el proceso y se reutiliza en todas las filas de la corrida.

## 4. Flujo de una corrida

```
inicio: run_at = ahora UTC ; extraction_id = micros(run_at)
token  = token de instalacion de la GH App

1. tarea repos
   - si queda incompleta -> no se ejecutan tareas por repo (paso 3)
2. tareas independientes de repos (se ejecutan siempre): users, trending_repos:{attribute}:{top_limit}
3. por cada repo de la lista obtenida en el paso 1 (nunca desde BQ):
   actions, commits, pull_requests, issues, traffic_views, traffic_clones, traffic_referrers, traffic_paths
4. si repos fue completa -> fila terminate ; codigo de salida 0
   si repos fue incompleta -> sin terminate ; codigo de salida != 0
```

Las tareas que fallan en los pasos 2 y 3 no detienen la corrida (son parciales aceptadas; ver seccion 5).

### Invariante de escritura (por pagina)

> Una fila de `extractions` con `result = succeeded` para la pagina k solo se escribe **despues** de que los datos de la pagina k quedaron cargados en su tabla.

Orden por pagina:

1. Llamar a la API (pagina k).
2. Si la llamada falla (HTTP != 2xx, error GraphQL o respuesta parcial):
   cargar fila k en `extractions` con `result = failed`, `code`, `message`; **terminar la tarea**.
3. Si la pagina trae 0 filas de datos: no hay carga de datos (no es un error).
4. Si trae filas: cargar las filas de datos de la pagina k (WRITE_APPEND).
5. Si la carga de datos falla: **no** escribir la fila k en `extractions`; registrar el error en logs; **terminar la tarea**.
   Efecto: la ultima fila de la tarea queda con `has_more = true` y la regla 3 de completitud la marca incompleta.
6. Si la carga de datos tuvo exito: cargar la fila k en `extractions` con `result = succeeded`.
7. Si `has_more` -> pagina k+1.

Sin reintentos: ni de pagina, ni de tarea, ni de job (`maxRetries = 0`).

Caso borde aceptado: si el paso 4 tiene exito y el paso 6 falla, quedan filas de datos sin su fila de extractions.
La tarea resulta incompleta por la regla 2 o 3 (falta la pagina k) y sus datos se ignoran. No hay perdida silenciosa.

## 5. Casos limite (decididos por el usuario; registrar en `0-capa-datos/politicas.md`)

| Caso | Resultado |
| --- | --- |
| `repos` incompleta | La corrida no ejecuta tareas por repo, no escribe terminate y sale con codigo != 0. |
| Repo vacio (sin rama por defecto) | `commits:{repo_id}` = `succeeded` con 0 filas: una fila en extractions, page_number 1, has_more false. |
| 403 en `traffic_*` | Tarea `failed`, aceptado. Solo diagnostico. |
| Cualquier otra tarea por repo falla | Parcial aceptada; la corrida continua. |

## 6. Estrategia de carga

- **Load jobs** (gratis), desde memoria en formato JSON por lineas. Sin streaming inserts.
- `WRITE_APPEND`, `CREATE_NEVER`, esquema explicito (no autodetect).
- Cuota a vigilar: **1.500 load jobs por tabla y por dia**. Con carga por pagina, la tabla mas cargada es `extractions`
  (una carga por pagina de todas las tareas).
  Hoy: ~118 cargas por corrida (16 repos) -> margen de ~12 corridas/dia.
  Con 100 repos: ~830 cargas por corrida -> **solo 1 corrida/dia** (una ejecucion manual extra superaria la cuota).
  Si se acerca ese limite: pasar a una carga de extractions por tarea, manteniendo el invariante (las filas de la tarea se cargan despues de sus datos).

## 7. Cloud Run Job

| Parametro | Valor | Motivo |
| --- | --- | --- |
| tasks / parallelism | 1 / 1 | Una corrida = un extraction_id. |
| maxRetries | 0 | "No existen reintentos dentro de la misma extraccion". |
| task timeout | 3600 s | El default de 10 min no alcanza: ~240 load jobs secuenciales de 1 a 3 s cada uno. |
| CPU / memoria | 1 vCPU / 512 MiB | Carga por pagina = memoria acotada. |
| Cuenta de servicio | `sa-collector` | Ver seccion 9. |

Free Tier: ~10 min/dia x 30 = ~18.000 vCPU-s/mes, muy por debajo de la cuota gratuita.

Artifact Registry: repositorio en `us-central1`, imagen base slim, politica de limpieza que conserve las 2 ultimas versiones (0,5 GB gratis).

## 8. Cloud Scheduler

- Frecuencia: 1 vez al dia.
- Zona horaria: `Etc/UTC` explicita (las fechas de trafico y el criterio X se comparan en UTC global).
- Hora: **00:30 UTC**. El dia D-1 ya cerro en UTC; que sus vistas esten completas lo decide el criterio X, no la hora.
- Destino: ejecutar el Cloud Run Job, autenticado con `sa-scheduler` (OAuth).
- Reintentos de Scheduler: 0. Una ejecucion perdida se recupera lanzando el job a mano: es una extraccion nueva e inofensiva por las politicas A/B/C.

## 9. IAM

| Cuenta de servicio | Rol | Alcance |
| --- | --- | --- |
| `sa-collector` | `roles/bigquery.jobUser` | proyecto |
| `sa-collector` | `roles/bigquery.dataEditor` | dataset `raw` |
| `sa-collector` | `roles/secretmanager.secretAccessor` | secreto de la clave privada de la GH App |
| `sa-scheduler` | `roles/run.invoker` (o un rol custom con `run.jobs.run`) | el Cloud Run Job |

El despliegue lo hace el usuario con su propia identidad. Ninguna SA tiene roles a nivel de proyecto sobre BQ salvo `jobUser`.

## 10. Autenticacion con GitHub: GitHub App

- Se usa una GH App instalada en la org: no expira como un PAT.
- Secret Manager guarda: la clave privada (PEM), el App ID y el Installation ID (o los ids como variables de entorno no secretas).
- Flujo: JWT firmado con el PEM -> token de instalacion (dura 1 h). Si la corrida pasa de ~50 min, renovarlo.
- Permisos de la App (solo lectura):
  - Repositorio: Metadata, Contents (commits), Issues, Pull requests, Actions, Administration (requerido por `traffic/*`).
  - Organizacion: Members, Custom properties.
- Cuota: las instalaciones tienen 5.000 req/h minimo (igual o mayor que el PAT). El presupuesto del 5% se mantiene.
- Efecto secundario: con Administration (lectura) en todos los repos instalados, el 403 de trafico solo deberia ocurrir en repos excluidos de la instalacion.

## 11. Control de costos

- Budget del proyecto: **1 USD**, alertas al 50/90/100% por correo. Un budget avisa, **no corta** el gasto.
- Load jobs: costo 0. Almacenamiento: <1% del Free Tier.
- `maximum_bytes_billed`: se define junto con los marts (el MVP no ejecuta consultas).

## 12. Estructura del recolector (firmas, sin implementacion)

```
collector/
  main.py          run() -> int                                  # orquesta la seccion 4, devuelve el codigo de salida
  context.py       RunContext(run_at, extraction_id)             # valores fijos de la corrida
  github_auth.py   installation_token(app_id, installation_id, pem) -> str
  github_client.py rest_pages(path, params) -> Iterator[Page]
                   graphql_pages(query, variables) -> Iterator[Page]
                   # Page: filas crudas, has_more, cursor, code, message, result
  tasks.py         una funcion por familia: (ctx, client, writer, [repo]) -> TaskResult
  mapping.py       una funcion por tabla: payload de API -> filas raw (sin campos calculados)
  bq_writer.py     load_rows(table, rows) -> None                # lanza una excepcion si la carga falla
                   load_extraction_row(row) -> None
```

---

## Fuera de alcance (despues del MVP)

Marts (repos_snapshot, trafico, tendencias, actividad) · criterio de madurez X · datasets de marts publico y privado ·
Looker Studio · `maximum_bytes_billed` · alerta automatica de fallo (seccion 13, opcional).

## 13. Monitoreo

MVP: revision manual en Cloud Logging del Cloud Run Job.

Alerta opcional (no bloquea el MVP), en orden de preferencia:

| Opcion | Detecta | No detecta | Costo |
| --- | --- | --- | --- |
| A. Chequeo de frescura con consulta programada de BQ | Scheduler que no disparo, job caido, timeout, `repos` incompleta | Tareas parciales (esperadas) | ~0: una consulta diaria sobre `extractions` (minimo facturable 10 MB, dentro del Free Tier de consultas) |
| B. Alerting policy de Cloud Monitoring sobre ejecuciones fallidas del job | Codigo de salida != 0, timeout | Scheduler que nunca disparo (no hay ejecucion que falle) | Verificar el precio vigente de las alerting policies |
| C. Alerta basada en logs (severidad ERROR del job) | Cualquier error registrado, incluso cargas fallidas por pagina | Scheduler que nunca disparo | Igual que B; ruidosa con los 403 de trafico |

Logica de A (conceptual):
- Se ejecuta a diario a las 02:00 UTC (00:30 + timeout de 1 h + margen).
- Busca en `extractions` una fila `task = 'terminate'` con `run_at` dentro del dia UTC actual.
- Si no existe, la consulta falla a proposito (funcion de error de BQ) y la consulta programada envia un correo de fallo.
- Usa la fila terminate porque solo se escribe si `repos` fue completa (seccion 4): su ausencia cubre todos los modos de fallo graves.
- Identidad: necesita leer `raw` y crear jobs. Verificar a quien llega el correo de fallo si el dueño de la consulta programada es una SA.
