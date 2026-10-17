# Informacion general

Objetivo: Realizar un dashboard que responda preguntas sobre la operacion y gestion de el area de tecnologia de lyoss (organizaion de GH).

Pendiente:
- [ ] Definir las preguntas del dashboard
- [ ] Definir las PKs de las tablas raw
- [ ] Que pasa si una ejecucion muere a medias
- [ ] Como va a ser el comportamiento de las tablas de trafico con una respuesta 403 de la API
- [ ] Que se va a hacer con los dtias de trafico que nunca maduraron
- [ ] Definir politicas de visivilidad del dashboard publico, porque tiene datos de repos privados y logins (nombres de usuario).

Decisiones:
- Las tablas Raw son espejos de la API, osea, tienen 0 campos calculados para total replicacion.
- Los commits extraidos son solo de la rama por defecto.
- Se incluye las estadisticas de trafico para no perder datos en el futuro, porque mantienen una ventana de 14 dias de historial.
- No se va a incluir subscribers_count ya que solo incrementa la complejidad y el overfetching, porque no lo proporciona el listado de repos de la organizacion, sino que el endpoint de repo especifico y hariamos N+1 consultas siempre.
- Para quitar los duplicados en los marts se elige la ultima version de la ultima ejecucion que este completa, porque las tablas raw solo agregan info, no modifican ni eliminan.
- Para las particiones se usa la fecha UTC del inicio de la ejecucion.

Suposiciones:
- Se trabaja con menos de 100 repos, y pasara bastante tiempo hasta llegar siquiera cerca. Esto mantiene el costo de la ingesta alrededor de un 5% de la cuota total por hora de la GH API.
