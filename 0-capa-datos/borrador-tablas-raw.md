# Tablas de BigQuery

## Tablas raw

### Tabla "extractions"

INTEGER extraction_id : id de la ejecucion de recoleccion
TIMESTAMP run_at : Fecha y hora UTC en la que se ejecuto la recolecicon
STRING result : resultado de la ejecucion complete,partial,error

### Tabla "repos"

> Se obtiene listando los repos disponibles en GET /orgs/{org}/repos

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER id : id del repositorio
STRING name : nombre del repositorio
STRING full_name : nombre completo con owner incluido
STRING visibility : visibilidad explicita public,private,internal
(puede ser null) STRING description : descripcion del repo
BOOLEAN fork : true si es un fork
BOOLEAN archived : true si el repo esta en modo solo lectura
BOOLEAN disabled : true si el repo esta deshabilitado
BOOLEAN is_template : true si el repo es una plantilla

INTEGER stargazers_count : numero de estrellas del repo
INTEGER subscribers_count : numero de usuarios siguiendo el repo
INTEGER forks_count : numero de forks hecho al repo
INTEGER open_issues_count : issues y prs abiertas del repo
INTEGER size : tamaño en KB del repo

TIMESTAMP created_at : Fecha y hora de creacion
TIMESTAMP updated_at : Fecha y hora de la ultima actualizacion de metadatos o codigo
TIMESTAMP pushed_at : Fecha y hora del ultimo push enviado a cualquier rama

BOOLEAN has_issues : tiene issues habilitadas
BOOLEAN has_projects : tiene projects habilitados
BOOLEAN has_wiki : tiene wiki habilitada
BOOLEAN has_pages : tiene github pages activado
BOOLEAN has_discussions : tiene discusiones habilitadas
BOOLEAN allow_forking : se permite realizar forks al repo

(puede ser null) STRING language : Lenguaje principal detectado
ARRAY<STRINGS> topics : Lista de tags asignados al repo
STRING default_branch : nombre de la rama por defecto
(puede ser null) STRING license_key (license.key) : Identificador corto de la licencia

BOOLEAN custom_active (custom_properties.active) : El proyecto esta marcado como activo a la fecha
BOOLEAN custom_help (custom_properties.help) : El proyecto esta marcado como que necesita apoyo/ayuda
STRING custom_display (custom_properties.display) : Nick del repositorio para vistas publicas

> Los campos "custom_active" y "custom_help" son strings de booleanos en la respuesta de la API

### Tabla "users"

> Obtenido desde GET /orgs/{org}/members

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER id : id del usuario
STRING login : nombre del usuario
STRING type : tipos de miembro de la organizacion

### Tabla "actions"

> Obtenido desde GET /repos/{owner}/{repo}/actions/runs

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER id : id de la ejecucion del workflow de GH Actions
INTEGER repo_id (repository.id) : id del repositorio donde ocurrio el workflow
STRING name : nombre del workflow
STRING status : estado de la ejecucion
(puede ser null) STRING conclusion : resultado de la ejecucion success,failure,cancelled
TIMESTAMP created_at : inicio de la action
TIMESTAMP updated_at : cuando termino o actualizo su estado por ultima vez

### Tabla "commits"

> Obtenido desde GraphQl

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

STRING sha : hash que identifica al commit
(desde el request) INTEGER repo_id : id del repositorio al que pertenece
(puede ser null) STRING user_login (author.user.login) : nombre del autor
TIMESTAMP commit_date (author.user.date) : Fecha y hora en que se hizo el commit

### Tabla "pull_requests"

> Obtenido desde Graph

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER id : id de la PR
INTEGER number : numero correlativo de la PR en el repo
(desde el request) INTEGER repo_id : id del repositorio donde se abrio la PR
STRING user_login (author.login) : nombre de quien abrio la PR
STRING state : estado de la PR open,closed
TIMESTAMP created_at : fecha de creacion de la PR
(puede ser null) TIMESTAMP merged_at : fecha en que se integro el codigo relacionado
(puede ser null) TIMESTAMP closed_at : fecha en que se cerro la PR con o sin merge

### Tabla "issues"

> Obtenido desde GET /repos/{owner}/{repo}/issues

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER id : id de la issue
INTEGER number : numero correlativo de la issue en el repo
(desde el request) INTEGER repo_id : id del repositorio al que pertenece
STRING user_login (author.login) : nombre de quien abrio la issue
STRING state : estado de la issue open,closed
TIMESTAMP created_at : fecha en la que se abrio la issue
(puede ser null) TIMESTAMP closed_at : fecha en la que se cerro la issue

### Tabla "traffic_views"

> Obtenido desde GET /repos/{owner}/{repo}/traffic/views

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER repo_id : id del repositorio
TIMESTAMP timestamp (views[].timestamp) : Fecha del bloque de vistas UTC
INTEGER count (views[].count) : Cantidad total de vistas en ese dia
INTEGER uniques (views[].uniques) : Cantidad de visitantes unicos en ese dia

### Tabla "traffic_clones"

> Obtenido desde GET /repos/{owner}/{repo}/traffic/clones

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER repo_id : id del repositorio
TIMESTAMP timestamp (clones[].timestamp) : Fecha del bloque de clones UTC
INTEGER count (clones[].count) : Cantidad de clonaciones en ese dia
INTEGER uniques (clones[].uniques) : Cantidad de usuarios unicos que clonaron

### Tabla "traffic_referrers"

> Obtenido desde GET /repos/{owner}/{repo}/traffic/popular/referrers

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER repo_id : id del repositorio
STRING referrer : Dominio que origino la visita
INTEGER count : Vistas totales desde esa fuente
INTEGER uniques : Visitantes unicos desde esa fuente

### Tabla "traffic_paths"

> Obtenido desde GET get/repos/{owner}/{repo}/traffic/popular/paths

INTEGER extraction_id : id de la ejecucion de la recoleccion del dato

INTEGER repo_id : id del repositorio
STRING path : ruta dentro del repositorio
STRING title : titulo de la pagina o archivo
INTEGER count : vistas totales a esa ruta
INTEGER uniques : visitantes unicos a esa ruta
