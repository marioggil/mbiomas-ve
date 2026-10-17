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

## 2. Lo que le pasó al terreno

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

## 3. Lo que registraron los congresos

En la caja hay **30 charlas** repartidas en **ocho ediciones**:

| Edición | 1999 | 2001 | 2003 | 2005 | 2007 | 2011 | 2013 | 2019 |
|---|---|---|---|---|---|---|---|---|
| Charlas | 2 | 3 | 6 | **9** | 2 | **1** | 2 | 5 |

Este es un subset de las charlas revisadas: se está haciendo una evaluación previa de qué capacidad tendrían los modelos de IA actuales para obtener una ubicación acertada, las especies mencionadas y un ROR de la institución del investigador.

De esas 30 charlas, **24 fueron revisadas por una máquina y 6 por una persona** para este catálogo — y la concentración no está repartida: 2005 es 9 de 9 revisadas por máquina, 2019 es 5 de 5, 2003 es 5 de 6. **Este estudio asume que una charla revisada por máquina está en el mismo nivel que una revisada por una persona**. En total en el visor hay **212** charlas revisadas por un humano, pero la meta final es más de 5.000 solo para los congresos de Venezuela: por eso interesa ver el nivel de los modelos para estas tareas y, más que nada, tener un sistema robusto para verificar y corregir errores.

## 4. Dónde se escribió lo que se escribió: las instituciones

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

## 5. Qué se mencionó: las especies

El catálogo extrajo de los resúmenes **42 entradas** de esta caja; **solo 31 son determinaciones a nivel de especie (30 especies distintas), 1 es un género (*Ficus* sp.), 3 son familias y 7 no son nombres de organismos**: entre esos siete hay un reino (*bacterias*), una forma de vida (*árboles*), un grupo funcional (*hongos micorrízicos arbusculares*) y cuatro descripciones del tipo *"especies típicas de las comunidades primarias"* o *"pioneras sin valor de mercado"*, que son fragmentos de prosa que el parseo tomó por nombres. Aunque en la plataforma está toda la información, para este informe se filtraron.

Con eso, la serie limpia queda así:

| Edición | 1999 | 2001 | 2003 | 2005 | 2007 | 2011 | 2013 | 2019 |
|---|---|---|---|---|---|---|---|---|
| Especies distintas registradas | 0 | **13** | 0 | **11** | 0 | **0** | 4 | 3 |

## 6. Planes de futuro con la plataforma

Lo que sigue, en orden:

1. **Permitir el consumo de los datos para su análisis.** El catálogo de congresos y el código del visor no están cubiertos por la licencia de MapBiomas y su licencia está por definir: ese es el primer paso para que cualquiera pueda descargar, citar y analizar lo que hay acá.
2. **Procesar todos los congresos de ecología de Venezuela con una metodología más automatizada.** Hoy el visor tiene 255 charlas (212 revisadas por una persona y 43 por una máquina) y la meta es más de 5.000 solo para los congresos venezolanos: eso no se alcanza revisando charla por charla, así que el trabajo es que la extracción —ubicación, especies mencionadas y ROR de la institución del investigador— corra de forma más automática y que la revisión humana se concentre en verificar y corregir. En el mismo paso entra la precisión de esa ubicación: hoy es un punto por estudio, y se le debería poder asignar multipuntos y polígonos.
3. **Ampliar la cobertura a otros congresos de la región**, con la misma metodología y el mismo esquema de datos, para que las series sean comparables entre países.
4. **Sumar fuentes de datos y formas de obtenerlos desde acá**: además de los resúmenes de congresos, otras fuentes que registren observaciones sobre un lugar, y más caminos para cargarlas y consultarlas desde la plataforma.

## 7. Licencia y cita

Los datos de cobertura que este informe usa son de **MapBiomas Venezuela** y se publican bajo **CC BY 4.0**, con atribución obligatoria y **sin ShareAlike**: se permite el uso comercial y la obra derivada manteniendo la atribución. Este informe los **adapta**.

Cita:

> «MapBiomas – Colección **3** de la Serie **anual** de Mapas de **Cobertura y Uso del Suelo** de Venezuela, consultada el **16 de octubre de 2026** a través del enlace: **https://biomas-cve.marioggil.xyz/**»

El catálogo de congresos y el código del visor **no son datos de MapBiomas** y no están cubiertos por esa licencia; la licencia con la que se van a compartir esos datos **está por definir**.
