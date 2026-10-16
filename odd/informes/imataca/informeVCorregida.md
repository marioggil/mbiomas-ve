# Imataca: cuarenta años de cobertura y una ventana por treinta charlas

**Un estudio de caso sobre cómo fue observada en las charlas de los congresos de ecologia una zona del escudo guayanés, y qué le pasó al terreno mientras tanto.**

---

## 1. Qué se estudió y por qué

Este informe mira un rectángulo de **165 × 156 km** en el noreste de Bolívar, definido por cuatro coordenadas que se encuentra dentro del Reserva Forestal Imataca:

```
oeste  -61.746314    sur  6.60103
este   -60.246314    norte 8.00103
```

Esa caja tiene 2.576.410 hectáreas (25.764 km²), fue seleccionada esa caja por que con analisis preliminares esa zona contiene **una de las zonas mas mencionadas en los congresos y tres regiones especificas de Imataca**: 28 de las 30 charlas que caen adentro comparten una sola coordenada, el centroide de la **Reserva Forestal de Imataca**. Este es uno de los puntos mejorables de la plataforma en este momento a los estudios se le deben poder asignar multipuntos y poligonos.

**Este informe es un producto derivado para mostrar los resumenes de los congresos de ecologia en un contexto de que sucesia antes y despues de esoso trabajos**.


## 2. Lo que le pasó al terreno

La caja es, sobre todo, bosque. En 1985 el **89,91 %** de su superficie estaba en la clase *Bosque*; en 2024, el **88,05 %**. En el medio pasaron cuarenta años y una pérdida neta de **47.844 hectáreas** de bosque.

| Clase | 1985 | 2024 | Cambio |
|---|---|---|---|
| **1.1 Bosque** | 89,91 % | **88,05 %** | **−1,86 puntos (−47.844 ha)** |
| **3.1 Uso pecuario / Tierras en descanso** | 1,70 % | **2,79 %** | **+1,10 puntos (+28.275 ha)** |
| **4.3 Uso Minero** | 0,04 % | **0,42 %** | **×10 (+9.932 ha)** |
| 2.2 Sabana / Herbazal | 3,60 % | 3,78 % | +0,19 puntos (+4.822 ha) |
| 1.4 Bosque inundable | 4,27 % | 4,25 % | estable |
| 5.1 Río, lago u océano | 0,36 % | 0,43 % | +0,07 puntos (+1.742 ha) |

El dato mas interesante es **la forma de la curva minera**. Esta paso de ocupar un 0,04 % en 1985 y un 0,42 % en 2024, sin tener un crecimiento igual en todo el tiempo se mantiene casi plana hasta 2005 (0,08 %), empieza a subir en 2011 (0,12 %) y 2013 (0,16 %), y **se acelera en la última década: 0,28 % en 2019 y 0,42 % en 2024**.

El resto de la historia es lenta donde el uso pecuario gana 1,10 puntos en cuarenta años, la sabana y el herbazal casi ni cambian, el bosque inundable es muy estable en su cobertura, y el agua de la caja se mueve apenas 0,07 puntos (1.742 ha).


## 3. Lo que registraron los congresos

En la caja hay **30 charlas** repartidas en **ocho ediciones**:

| Edición | 1999 | 2001 | 2003 | 2005 | 2007 | 2011 | 2013 | 2019 |
|---|---|---|---|---|---|---|---|---|
| Charlas | 2 | 3 | 6 | **9** | 2 | **1** | 2 | 5 |

Este es un subset de las charlas revisadas, se esta haciendo una evaluacion previa de que capacidad se tendrian con los modelos de ia actuales para obtener una ubicacion acertada, las especies mencionadas y un ror de la institucion del investigador.

De esas 30 charlas, **24 fueron revisadas por una máquina y 6 por una persona** para este catálogo — y la concentración no está repartida: 2005 es 9 de 9 revisadas por máquina, 2019 es 5 de 5, 2003 es 5 de 6. **Este estudio asume que una charla revisada por máquina está en el mismo nivel que una revisada por una persona**. En total en el visor hay 212 charlas revisadas por un humano pero la meta final es mas de 5000 solo para los congresos en venezuela, por eso es interesante ver el nivel de los modelos para hacer estas tareas y mas que todo tener un vistema robusto para poder verificar y corregir errores.

### 4. Dónde se escribió lo que se escribió: las instituciones

**39 pares charla-institución, con 10 instituciones distintas.** El orden es elocuente:

| Pares | Institución |
|---|---|
| **11** | Universidad Nacional Experimental de Guayana |
| 8 | Instituto de Zoología y Ecología Tropical, UCV |
| 6 | Universidad Central de Venezuela |
| 5 | Universidad de Los Andes |
| 4 | Centro de Estudios Integrales del Ambiente, UCV |
| 1 | Universidad de Oriente · Universidad Simón Bolívar · IVIC · Instituto de Ciencias Ambientales y Ecológicas (ULA) · Asociación Civil Fundación Esfera |

La universidad regional de Guayana es una de las mas fuertes en aportes sobre la zona pero viendo en detalle . Pero esto es con un matiz muy importante, el **Instituto de Zoología y Ecología Tropical** y **Centro de Estudios Integrales del Ambiente** son parte de la UCV lo cual coloca a la UCV como el que mas aportes hizo con 18.

### 5. Qué se mencionó: las especies

El catálogo extrajo de los resúmenes **42 entradas** de esta caja; **solo 31 son determinaciones a nivel de especie (30 especies distintas), 1 es un género (*Ficus* sp.), 3 son familias y 7 no son nombres de organismos**: entre esos siete hay un reino (*bacterias*), una forma de vida (*árboles*), un grupo funcional (*hongos micorrízicos arbusculares*) y cuatro descripciones del tipo *"especies típicas de las comunidades primarias"* o *"pioneras sin valor de mercado"*, que son fragmentos de prosa que el parseo tomó por nombres. Aunque en la plataforma esta toda la informacion, para este informe se filtraron.

Con eso, la serie limpia queda así:

| Edición | 1999 | 2001 | 2003 | 2005 | 2007 | 2011 | 2013 | 2019 |
|---|---|---|---|---|---|---|---|---|
| Especies distintas registradas | 0 | **13** | 0 | **11** | 0 | **0** | 4 | 3 |


## 6. Licencia y cita

Los datos de cobertura que este informe usa son de **MapBiomas Venezuela** y se publican bajo **CC BY 4.0**, con atribución obligatoria y **sin ShareAlike**: se permite el uso comercial y la obra derivada manteniendo la atribución. Este informe los **adapta**.

Cita:

> «MapBiomas – Colección **3** de la Serie **anual** de Mapas de **Cobertura y Uso del Suelo** de Venezuela, consultada el **16 de octubre de 2026** a través del enlace: **https://biomas-cve.marioggil.xyz/**»

El catálogo de congresos y el código del visor **no son datos de MapBiomas** y no están cubiertos por esa licencia, sinceramente como todavia es una idea muy verde se esta pensando que licencias para compartir los datos
