# Politicas

## Tablas raw
Unicamente se añade informacion a las tablas raw, no se modifican ni eliminan.

### Estrategias contra duplicacion y expiracion

Estrategias:
- A : Quedarse con las filas que se trae la ultima ejecucion completa de esa tarea de extraccion y descartar lo que no este en ella.
- B : Para cada clave natural, quedarse con la ultima version vista en cualquier ejecucion completa de esa tarea. (prefiriendo las ultimas)
- C : Para cada clave natural y cada dia UTC, quedarse con la ultima ejecucion completa de esa tarea de ese dia.

Una tarea es identificada por extraccion_id + task, se dice completa si cumple las siguientes condiciones:
1. Todas sus filas tienen result = succeeded.
2. Sus page_number son consecutivos empezando desde el 1, sin saltos.
3. La ultima pagina (de mayor page_number) tiene has_more = false.
de otra forma es incompleta sin importar la causa. Los datos de una tarea incompleta no se usan en los marts y message solo sirve para diagnostico.

| Tabla | Clave Natural | Estrategia |
| --- | --- | --- |
| extractions | extraction_id, task, page_number | N/A |
| repos | id | C |
| trending_repos | id, attribute, top_limit | C |
| users | id | A |
| actions | id | B |
| commits | sha, repo_id | A |
| pull_requests | id | A |
| issues | id | A |
| traffic_views | repo_id, timestamp | B |
| traffic_clones | repo_id, timestamp | B |
| traffic_referrers | repo_id, referrer | A |
| traffic_paths | repo_id, path | A |

La PK de cada tabla es la Clave Natural + extraction_id + task + page_number.

### Catalogo de nombres de task

Formato: `<tabla>` o `<tabla>:<discriminador>`. El discriminador usa el id (no el nombre) para que un renombre no cambie la tarea.

| Tabla | task |
| --- | --- |
| repos | repos |
| trending_repos | trending_repos:{attribute}:{top_limit} |
| users | users |
| actions | actions:{repo_id} |
| commits | commits:{repo_id} |
| pull_requests | pull_requests:{repo_id} |
| issues | issues:{repo_id} |
| traffic_views | traffic_views:{repo_id} |
| traffic_clones | traffic_clones:{repo_id} |
| traffic_referrers | traffic_referrers:{repo_id} |
| traffic_paths | traffic_paths:{repo_id} |
| (fila de cierre en extractions) | terminate |

## Visibilidad

- Se publican dos informes: uno publico y otro privado. El privado muestra todos los datos; el publico solo muestra repositorios publicos.
- El filtro usa la visibilidad **actual** del repositorio (la de la ultima version de repos), no la que tenia en cada dia. Consecuencia: si un repo pasa de privado a publico, su historial completo aparece en el informe publico; si pasa de publico a privado, desaparece de el.
- En el informe publico los totales de "todos los repos" incluyen solo repositorios publicos.
- Los logins y la pertenencia a la organizacion no tienen politica especial: ninguna metrica del dashboard los expone.
