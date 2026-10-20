-- Verificacion de UNA extraccion del dataset raw (o raw_test).
--
-- Parametro:  @eid  (INT64)  extraction_id de la extraccion a revisar.
-- Dataset:    las tablas van sin calificar; se resuelven con --dataset_id.
--
-- Poda de particion: extraction_id = micros(run_at) (mvp-ingesta.md, seccion 3), asi que
-- `run_at = TIMESTAMP_MICROS(@eid)` apunta a la unica particion mensual de esa extraccion.
-- Todas las consultas filtran por ese predicado.
--
-- Cada bloque "-- ==== N." es una consulta independiente. Ejecucion de todas: `make verificar EID=<id>`
-- (con DRY=1 solo estima los bytes). A mano, una consulta:
--   bq --project_id=<proyecto> query --use_legacy_sql=false --dataset_id=<dataset> \
--      --parameter=eid:INT64:<id> < <consulta.sql>


-- ==== 1. ¿Existe la fila terminate? (ok debe ser true)
SELECT
  COUNT(*) AS filas_terminate,
  COUNTIF(result = 'succeeded' AND code = 0 AND page_number = 0 AND NOT has_more) AS validas,
  COUNT(*) = 1 AND COUNTIF(result = 'succeeded' AND code = 0 AND page_number = 0 AND NOT has_more) = 1 AS ok
FROM extractions
WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid AND task = 'terminate';


-- ==== 2. Tasks INCOMPLETAS segun politicas.md (vacio = todas completas)
-- Completa = todas succeeded + page_number consecutivos desde 1 + ultima pagina con has_more = false.
WITH por_task AS (
  SELECT
    task,
    COUNT(*) AS paginas,
    COUNT(DISTINCT page_number) AS distintas,
    MIN(page_number) AS primera,
    MAX(page_number) AS ultima,
    COUNTIF(result != 'succeeded') AS fallidas,
    ARRAY_AGG(has_more ORDER BY page_number DESC LIMIT 1)[OFFSET(0)] AS ultima_has_more,
    ARRAY_AGG(IF(result != 'succeeded', STRUCT(page_number, code, message), NULL) IGNORE NULLS
              ORDER BY page_number LIMIT 1)[SAFE_OFFSET(0)] AS primera_falla
  FROM extractions
  WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid AND task != 'terminate'
  GROUP BY task
),
evaluada AS (
  SELECT *,
    (primera = 1 AND ultima = paginas AND distintas = paginas) AS consecutivas,
    NOT ultima_has_more AS ultima_sin_mas
  FROM por_task
)
SELECT
  task, paginas, fallidas, consecutivas, ultima_sin_mas,
  primera_falla.page_number AS pagina_fallida, primera_falla.code AS code, primera_falla.message AS message
FROM evaluada
WHERE NOT (fallidas = 0 AND consecutivas AND ultima_sin_mas)
ORDER BY task;


-- ==== 3. Tasks por familia frente a las esperadas
-- repos, users y trending_repos: 1 cada una. Familias por repo: una task por repo de la tabla repos de
-- ESTA extraccion (si repos quedo incompleta, no hay tareas por repo y el resultado lo refleja).
-- Cuando existan las tareas GraphQL, agregar 'commits', 'pull_requests', 'issues' a la lista por repo.
WITH n AS (
  SELECT COUNT(DISTINCT id) AS repos
  FROM repos
  WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
),
esperado AS (
  SELECT 'repos' AS familia, 1 AS esperadas
  UNION ALL SELECT 'users', 1
  UNION ALL SELECT 'trending_repos', 1
  UNION ALL SELECT f, n.repos
  FROM n, UNNEST(['actions', 'traffic_views', 'traffic_clones', 'traffic_referrers', 'traffic_paths']) AS f
),
real AS (
  SELECT SPLIT(task, ':')[OFFSET(0)] AS familia, COUNT(DISTINCT task) AS tasks
  FROM extractions
  WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid AND task != 'terminate'
  GROUP BY familia
)
SELECT
  COALESCE(e.familia, r.familia) AS familia,
  COALESCE(r.tasks, 0) AS tasks,
  COALESCE(e.esperadas, 0) AS esperadas,
  COALESCE(r.tasks, 0) = COALESCE(e.esperadas, 0) AS ok
FROM esperado e FULL OUTER JOIN real r ON e.familia = r.familia
ORDER BY familia;


-- ==== 4. Filas por tabla de datos
SELECT 'repos' AS tabla, COUNT(*) AS filas FROM repos WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'trending_repos', COUNT(*) FROM trending_repos WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'users', COUNT(*) FROM users WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'actions', COUNT(*) FROM actions WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'commits', COUNT(*) FROM commits WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'pull_requests', COUNT(*) FROM pull_requests WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'issues', COUNT(*) FROM issues WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_views', COUNT(*) FROM traffic_views WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_clones', COUNT(*) FROM traffic_clones WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_referrers', COUNT(*) FROM traffic_referrers WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_paths', COUNT(*) FROM traffic_paths WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
ORDER BY tabla;


-- ==== 5. trending_repos: top_ord (ok = minimo 1, maximo = filas, sin repetidos)
SELECT
  task,
  COUNT(*) AS filas,
  MIN(top_ord) AS min_top_ord,
  MAX(top_ord) AS max_top_ord,
  COUNT(DISTINCT top_ord) AS distintos,
  MIN(top_ord) = 1 AND MAX(top_ord) = COUNT(*) AND COUNT(DISTINCT top_ord) = COUNT(*) AS ok
FROM trending_repos
WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
GROUP BY task;


-- ==== 6. Claves naturales duplicadas dentro de la extraccion (politicas.md; sobrantes debe ser 0)
-- sobrantes = filas - claves distintas.
SELECT 'repos (id)' AS tabla, COUNT(*) AS filas, COUNT(*) - COUNT(DISTINCT id) AS sobrantes
FROM repos WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'trending_repos (id, attribute, top_limit)', COUNT(*),
  COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(STRUCT(id, attribute, top_limit)))
FROM trending_repos WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'users (id)', COUNT(*), COUNT(*) - COUNT(DISTINCT id)
FROM users WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'actions (id)', COUNT(*), COUNT(*) - COUNT(DISTINCT id)
FROM actions WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'commits (sha, repo_id)', COUNT(*),
  COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(STRUCT(sha, repo_id)))
FROM commits WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'pull_requests (id)', COUNT(*), COUNT(*) - COUNT(DISTINCT id)
FROM pull_requests WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'issues (id)', COUNT(*), COUNT(*) - COUNT(DISTINCT id)
FROM issues WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_views (repo_id, timestamp)', COUNT(*),
  COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(STRUCT(repo_id, timestamp)))
FROM traffic_views WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_clones (repo_id, timestamp)', COUNT(*),
  COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(STRUCT(repo_id, timestamp)))
FROM traffic_clones WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_referrers (repo_id, referrer)', COUNT(*),
  COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(STRUCT(repo_id, referrer)))
FROM traffic_referrers WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
UNION ALL SELECT 'traffic_paths (repo_id, path)', COUNT(*),
  COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(STRUCT(repo_id, path)))
FROM traffic_paths WHERE run_at = TIMESTAMP_MICROS(@eid) AND extraction_id = @eid
ORDER BY tabla;
