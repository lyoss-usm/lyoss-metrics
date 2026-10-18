# Dashboard

## Preguntas que responde el dashboard

- ¿Nuestros repositorios reciben visualizaciones? ¿Con que distribucion en el tiempo?
    - Visitas por dia en todos los repos y por repo
    - Visitas en el ultimo mes categorizada por umbrales de todos los repos y por repo (<=10: bajo, <=50: medio, >50 alto)
- ¿Que distribucion tienen las licencias de nuestros repositorios?
    - Cantidad de repos por licencia incluyendo sin licencia
- ¿Desde donde proviene nuestro trafico?
    - Cantidad de visitas de los ultimos 14 dias por origen
- ¿Nuestros repositorios ocupan los topicos en tendencia de los ultimos 7 dias?
    - Porcentaje de los top 20 topicos (del top obtenido con "top_limit" del dia) en tendencia que estan presentes en al menos uno de nuestros repos. (si se obtienen menos de 20 topicos, el mart debe avisar en vez de calcular el porcentaje con menos de 20)
    - Top repositorios de la organizacion con mayor numero de topicos en trending
    - Lista de topicos prominentes hoy en la ventana (7 dias) sin presencia en los repos de la organizacion categorizados por lenguaje principal
- ¿Se estan trabajando activamente nuestros repositorios?
    - Cantidad de commits, issues y pull requests abiertas/cerradas por semana o mes, de todos los repos y por repo
    - Porcentaje de pull requests integradas vs cerradas sin integracion vs actualmente abiertas
    - Promedio de duracion en dias que pasan abiertas las pull requests y/o las issues
    - Cantidad de workflows ejecutados por dia
    - Porcentaje de workflows terminados en succeeded vs failure o cancelled
    - Ranking de repositorios sin pushes, commits o pull requests en el ultimo mes
    - Categorizacion de repositorios segun su ultimo cambio (pushed_at): < 7d, < 30d, < 90d, +90d
- ¿Que tanto usamos de las features que nos proporciona GH como organizacion?
    - Porcentaje de repos que tienen habilitado Issues, Projects, Wiki, Pages, Discussions y Forking
    - Cantidad total de minutos que se demoran los workflows completados (no es la couta, ademas para repos publicos no hay limite), mide la duracion total que incluye tiempo en la cola, no es de computo

### Detalles

- Las metricas que incluyen un periodo mayor al de la antiguedad de los datos, simplemente muestran las metricas con los datos que existan, osea, si se piden datos por mes y solo se tiene la de 1 dia, el 1 dia cuenta como todo el mes.
- Para el caso de metricas de "crecimiento" que necesitan mas de 1 ejecucion (las ejecuciones son por dia), se debe anunciar que la metrica no se puede calcular al no tener almenos datos sobre 2 dias. (se debe indicar que la metrica de cambio aplica para los n-1 dias incluidos)
- Es responsabilidad del mart indicar que periodos estan incompletos o son no calculables.
- Las visitas son totales no por unicos
- Los marts se deben guiar unicamente por tareas no por extracciones para obtener datos.
- Los marts son responsables de marcar a los datos como provisional (inmaduro) o normal (maduro).

## Tablas "mart"

Los marts no son append-only: se reconstruyen en cada actualizacion diaria a partir de las tablas raw. Cada mart se publica en dos destinos: el privado (todos los repos) y el publico (solo repos con visibilidad actual public), por lo que no llevan columna de visibilidad.

### Tabla "repos_snapshot" (familia: foto de repos)

> Granularidad: una fila por repositorio, con su estado en la ultima ejecucion completa de la tarea `repos`. No guarda historial. Como `repos` es una unica tarea que lista toda la organizacion, todas las filas provienen de la misma extraccion; un repo eliminado o transferido desaparece al dejar de estar en esa foto.
>
> Responde: distribucion de licencias, % de features habilitadas, categorizacion por `pushed_at` (la categoria se calcula en el dashboard contra la fecha de la consulta, el mart solo entrega `pushed_at`).

| Tipo de dato | Campo | Descripción |
| --- | --- | --- |
| INTEGER | repo_id | id del repositorio (repos.id) |
| STRING | name | nombre actual del repositorio |
| STRING | display_name | nick para vistas publicas (repos.custom_display, obligatorio en todos los repos) |
| BOOLEAN | fork | true si es un fork |
| BOOLEAN | archived | true si el repo esta en modo solo lectura |
| BOOLEAN | disabled | true si el repo esta deshabilitado |
| BOOLEAN | is_template | true si el repo es una plantilla |
| STRING | license | repos.license_key, o "sin licencia" si es null |
| BOOLEAN | has_issues | tiene issues habilitadas |
| BOOLEAN | has_projects | tiene projects habilitados |
| BOOLEAN | has_wiki | tiene wiki habilitada |
| BOOLEAN | has_pages | tiene github pages activado |
| BOOLEAN | has_discussions | tiene discusiones habilitadas |
| BOOLEAN | allow_forking | se permite realizar forks al repo |
| TIMESTAMP | pushed_at | fecha y hora del ultimo push; si es null se reemplaza por created_at |
| DATE | snapshot_date | fecha UTC de run_at de la extraccion de la que proviene la fila |
| BOOLEAN | fresh | true si snapshot_date es la fecha UTC de la ultima extraccion que escribio filas en alguna tabla raw de datos (completa o no); false si la fila viene de una ejecucion anterior |

Decisiones:
- No hay limite de antiguedad: una foto vieja sigue mostrandose con fresh = false mientras no haya una mas nueva.
- No se contempla el caso de que el cronjob o los marts dejen de ejecutarse: en ese escenario los datos pueden figurar como frescos sin serlo.
- `name` y `display_name` se entregan ambos; el consumidor elige cual mostrar.
- El lenguaje principal y los topicos de nuestros repos viven en otro mart (familia trending).

- "La ultima extraccion" se determina por los `run_at` de las filas de las tablas raw de datos (cualquier tarea, completa o incompleta), sin consultar `extractions`. Una extraccion que no escribio ninguna fila se considera como si no hubiera ocurrido.
