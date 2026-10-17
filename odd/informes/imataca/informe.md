# Imataca: cuarenta años de cobertura y una ventana sobre treinta charlas

**Un estudio de caso sobre cómo se observó una zona del escudo guayanés en las charlas de los congresos de ecología, y qué le pasó al terreno mientras tanto.**

---

## 1. Qué se estudió y por qué

Este informe mira un rectángulo de **165 × 156 km** en el noreste de Bolívar, en la Reserva Forestal de Imataca, definido por cuatro coordenadas:

```
oeste  -61.746314    sur  6.60103
este   -60.246314    norte 8.00103
```

Esa caja tiene 2.576.410 hectáreas (25.764 km²). Se eligió porque, en un análisis preliminar, esa zona contiene **el punto más compartido de todo el catálogo de congresos** y tres lugares específicos de Imataca —el **Campamento El Buey**, la **cuenca del río Botanamo** y la **Estación Experimental Caparo**—: 28 de las 30 charlas que caen adentro comparten una sola coordenada, el centroide de la **Reserva Forestal de Imataca**. No es un error: en la taxonomía curada con la que se revisó el catálogo, la reserva es un *lugar nombrado* y el geocodificador devuelve el mismo punto para todas.

Este es uno de los puntos mejorables de la plataforma: hoy ubica **un punto por estudio**, y se les debería poder asignar multipuntos y polígonos.

**Este informe es un producto derivado: muestra los resúmenes de los congresos de ecología en el contexto de qué sucedía antes y después de esos trabajos.**

## 2. Cómo leer las cifras antes de leerlas

Tres advertencias valen más que cualquier tabla que venga después.

- **La extensión del visor no es la frontera del país.** Las cifras de este informe cubren la extensión del píxel en los COG de origen —**1.086.229,52 km²**, unos **169.600 km² más** que los **916.445 km²** que Venezuela tiene reconocidos internacionalmente—, porque incluye territorio en disputa y **no se aplicó ninguna máscara de fronteras**. La consecuencia es directa: **cualquier cifra de este informe difiere de las cifras oficiales en aproximadamente un 18 %**.
- **Las áreas son geodésicas.** Cada hectárea se calculó como área geodésica sobre la esfera WGS84 con radio authálico **R = 6.371.007,181 m**, fila por fila sobre el ráster. Dos cifras de área solo son comparables si comparten ese método, y estas lo comparten.
- **La caja está observada entera.** En los diez años medidos, el área sin dato de la ventana es **cero**: no hay píxeles no observados dentro de esta caja, así que la proporción de cada clase es directamente la proporción de la caja. Es un dato del estudio, no un supuesto: se verificó año por año.

## 3. Lo que le pasó al terreno

La caja es, sobre todo, bosque. En 1985 el **89,91 %** de su superficie estaba en la clase *Bosque*; en 2024, el **88,05 %**. En el medio pasaron cuarenta años y una pérdida neta de **47.844 hectáreas** de bosque.

| Clase | 1985 | 2024 | Cambio |
|---|---|---|---|
| **1.1 Bosque** | 89,91 % | **88,05 %** | **−1,86 puntos (−47.844 ha)** |
| **3.1 Uso pecuario / Tierras en descanso** | 1,70 % | **2,79 %** | **+1,10 puntos (+28.275 ha)** |
| **4.3 Uso Minero** | 0,04 % | **0,42 %** | **×10 (+9.932 ha)** |
| 2.2 Sabana / Herbazal | 3,60 % | 3,78 % | +0,19 puntos (+4.822 ha) |
| 1.4 Bosque inundable | 4,27 % | 4,25 % | estable (−487 ha) |
| 5.1 Río, lago u océano | 0,36 % | 0,43 % | +0,07 puntos (+1.742 ha) |

El dato más interesante es **la forma de la curva minera**. La clase que el propio codebook llama *Uso Minero* pasó de un 0,04 % en 1985 a un 0,42 % en 2024, y no creció parejo: se mantiene casi plana hasta 2005 (0,08 %), empieza a subir en 2011 (0,12 %) y 2013 (0,16 %), y **se acelera en la última década: 0,28 % en 2019 y 0,42 % en 2024**. Es un cambio medido en la clasificación oficial, dentro de una caja declarada, en la zona del arco minero de Imataca.

El resto de la historia es lento: el uso pecuario gana 1,10 puntos en cuarenta años, la sabana y el herbazal casi no cambian, el bosque inundable es muy estable en su cobertura, y el agua de la caja se mueve apenas 0,07 puntos (1.742 ha).

**Sobre el agua, este informe no afirma nada más allá de eso.** La clase 33 del proyecto crece un 4,42 % en toda la serie, y solo dos escalones están corroborados externamente como embalses reales; aproximadamente el 80 % de esa ganancia es una cola difusa sin causa atribuida. Por eso el agua aparece en la tabla y no aparece en ninguna conclusión.

## 4. Lo que registraron los congresos

En la caja hay **30 charlas** repartidas en **ocho ediciones**:

| Edición | 1999 | 2001 | 2003 | 2005 | 2007 | 2011 | 2013 | 2019 |
|---|---|---|---|---|---|---|---|---|
| Charlas | 2 | 3 | 6 | **9** | 2 | **1** | 2 | 5 |

Este es un subset de las charlas revisadas: se está haciendo una evaluación previa de qué capacidad tendrían los modelos de IA actuales para obtener una ubicación acertada, las especies mencionadas y un ROR de la institución del investigador.

De esas 30 charlas, **24 fueron revisadas por una máquina y 6 por una persona** para este catálogo — y la concentración no está repartida: 2005 es 9 de 9 revisadas por máquina, 2019 es 5 de 5, 2003 es 5 de 6. **Este estudio asume que una charla revisada por máquina está en el mismo nivel que una revisada por una persona**, y lo declara acá en vez de dejarlo al descubierto: quien no comparta esa premisa puede rehacer cualquier cifra de esta sección excluyendo esas charlas, porque el dato está en el catálogo (`human_reviewer`, por estudio). En total en el visor hay **212** charlas revisadas por un humano, pero la meta final es más de 5.000 solo para los congresos de Venezuela: por eso interesa ver el nivel de los modelos para estas tareas y, más que nada, tener un sistema robusto para verificar y corregir errores.

## 5. Dónde se escribió lo que se escribió: las instituciones

**39 pares charla-institución, con 10 instituciones distintas.** El orden es elocuente:

| Pares | Institución |
|---|---|
| **11** | Universidad Nacional Experimental de Guayana |
| 8 | Instituto de Zoología y Ecología Tropical, UCV |
| 6 | Universidad Central de Venezuela |
| 5 | Universidad de Los Andes |
| 4 | Centro de Estudios Integrales del Ambiente, UCV |
| 1 | Universidad de Oriente · Universidad Simón Bolívar · IVIC · Instituto de Ciencias Ambientales y Ecológicas (ULA) · Asociación Civil Fundación Esfera |

La universidad regional de Guayana es una de las más fuertes en aportes sobre la zona, pero con un matiz importante: el **Instituto de Zoología y Ecología Tropical** y el **Centro de Estudios Integrales del Ambiente** son parte de la UCV, lo que coloca a la **Universidad Central de Venezuela como la que más aportó, con 18 pares** (sumando esas tres filas de la tabla). De los 39 pares, **5 vienen de identificadores ROR que el curado marcó como dudosos** —el ROR resuelve a una institución distinta de la que el resumen nombra—, y **4 de esos 5 están dentro de esos 18**; están incluidos por decisión del dueño, cada uno con su nota en la tabla curada.

## 6. Qué se mencionó: las especies

El catálogo extrajo de los resúmenes **42 entradas** de esta caja; **solo 31 son determinaciones a nivel de especie (30 especies distintas), 1 es un género (*Ficus* sp.), 3 son familias y 7 no son nombres de organismos**: entre esos siete hay un reino (*bacterias*), una forma de vida (*árboles*), un grupo funcional (*hongos micorrízicos arbusculares*) y cuatro descripciones del tipo *"especies típicas de las comunidades primarias"* o *"pioneras sin valor de mercado"*, que son fragmentos de prosa que el parseo tomó por nombres. Aunque en la plataforma está toda la información, para este informe se filtraron.

Con eso, la serie limpia queda así:

| Edición | 1999 | 2001 | 2003 | 2005 | 2007 | 2011 | 2013 | 2019 |
|---|---|---|---|---|---|---|---|---|
| Especies distintas registradas | 0 | **13** | 0 | **11** | 0 | **0** | 4 | 3 |

Sin esa curación, el informe habría dicho que 2011 registró tres especies. Las tres eran descripciones: **2011 registró cero**. También aparece una especie contada dos veces —*Harpia harpyja*, el águila harpía, en 2013 y en 2019, escrita de dos maneras distintas— y dos erratas del resumen original (*"clansia racemosa"* y *"psaracolius decumanus"*) que se conservan tal como están, marcadas, en vez de corregirse en silencio.

## 7. Lo que este informe no dice

- **No dice que los congresos causaran los cambios de cobertura.** La serie de cobertura es continua y no depende de las ediciones: los años de congreso son **el marco temporal** en el que se decidió mirar, no el motor del cambio.
- **No mezcla las dos series en una figura.** La cobertura y los registros de congresos van en secciones separadas a propósito: un solo gráfico con "cobertura y charlas" invitaría exactamente a la lectura causal que este estudio rechaza.
- **No afirma nada sobre el agua** más allá de los dos escalones corroborados.
- **No corrige las fuentes en silencio**: las erratas del resumen y los pares dudosos quedan a la vista, con su nota.
- **Un punto no es una charla.** El mapa de esta zona ubica un punto por estudio con coordenada; 28 charlas comparten ese punto, así que **un punto no es un trabajo de campo** en el centroide de la reserva.

## 8. De dónde salen estos números

Cada cifra de este informe se puede rastrear y recalcular:

- **La composición de la caja** se calculó con el mismo endpoint que usa el visor, una vez por año: `GET /api/clip-stats?year=<año>&bbox=-61.746314,6.60103,-60.246314,8.00103`. Las diez respuestas crudas están en la evidencia de este estudio.
- **La procedencia** de la composición: artefacto `composition-summary-venezuela-collection-3.json`, esquema **2**, generado el **2026-09-24**, método de área geodésica con radio authálico 6.371.007,181 m. Cada año tiene su propio ráster de origen, con su `sha256` registrado (los diez están en la evidencia).
- **El catálogo de congresos**: artefacto `catalogo-estudios.json`, esquema **4**, generado el **2026-10-15**.
- **La recomputación**: el pipeline del repositorio (`./run.sh pipeline`) reconstruye los artefactos de datos desde los insumos versionados. Este informe tiene además su propio constructor, `python3 tools/build_informe_imataca.py`, que lee la evidencia del estudio y escribe el artefacto que esta página consume.
- **La consulta**: **2026-10-16**.

## 9. Licencia y cita

Los datos de cobertura que este informe usa son de **MapBiomas Venezuela** y se publican bajo **CC BY 4.0**, con atribución obligatoria y **sin ShareAlike**: se permite el uso comercial y la obra derivada manteniendo la atribución. Este informe los **adapta**.

Cita:

> «MapBiomas – Colección **3** de la Serie **anual** de Mapas de **Cobertura y Uso del Suelo** de Venezuela, consultada el **16 de octubre de 2026** a través del enlace: **https://biomas-cve.marioggil.xyz/**»

El catálogo de congresos y el código del visor **no son datos de MapBiomas** y no están cubiertos por esa licencia; la licencia con la que se van a compartir esos datos **está por definir**.
