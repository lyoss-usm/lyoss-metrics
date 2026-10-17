# Informacion general

Objetivo: Realizar un dashboard que responda preguntas sobre la operacion y gestion de el area de tecnologia de lyoss (organizaion de GH).

Pendiente:
- [ ] Que se va a hacer con los dias de trafico que nunca maduraron
- [ ] Definir politicas de visivilidad del dashboard publico, porque tiene datos de repos privados y logins (nombres de usuario).

Decisiones:
- Las tablas Raw son espejos de la API, osea, tienen 0 campos calculados para total replicacion.
- Los commits extraidos son solo de la rama por defecto.
- Se incluye las estadisticas de trafico para no perder datos en el futuro, porque mantienen una ventana de 14 dias de historial.
- No se va a incluir subscribers_count ya que solo incrementa la complejidad y el overfetching, porque no lo proporciona el listado de repos de la organizacion, sino que el endpoint de repo especifico y hariamos N+1 consultas siempre.
- Para las particiones se usa la fecha UTC del inicio de la ejecucion.
- Los trending repos son aquellos creados desde 7 dias antes de "run_at"
- La representativdad de los top topicos viene dada por el "top_limit" de la consulta.
- Si GraphQL devuelve una respuesta parcial, los datos quedan como error, no aceptamos filas incompletas.
- Al terminar el job inserta una fila a extractions para indicar su correcto termino, de la forma INSERT(<extraction_id>,<run_at>,task="terminate",endpoint="",page_number=0,has_more=false,cursor=null,code=0,message=null,result="succeeded"), la cual sirve unicamente como diagnostico de extracciones.
- No existen reintentos de tareas dentro de la misma extraccion.

Suposiciones:
- Se trabaja con menos de 100 repos, y pasara bastante tiempo hasta llegar siquiera cerca. Esto mantiene el costo de la ingesta alrededor de un 5% de la cuota total por hora de la GH API.

Restricciones:
- La couta para la API REST en /repos y /org es 5000reqs/hora con un token autenticado
- La couta para la API GraphQL es 5000pts/hora con un token autenticado
- La couta para la API REST en /search es 30reqs/minuto con un token autenticado
