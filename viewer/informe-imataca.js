/* viewer/informe-imataca.js
 *
 * The Imataca case study page: one document, one fetch.
 *
 * Every number on this page comes from `GET /api/informe/imataca`, the
 * committed artifact built by `tools/build_informe_imataca.py` from the study's
 * versioned evidence. Nothing is typed into the markup and nothing is
 * recomputed here: this file formats the artifact's numbers, draws the figures
 * as hand-rolled SVG (the repository's rule: no chart library) and paints the
 * study's box on the 2024 tile pyramid with the vendored MapLibre build.
 *
 * The prose is not built here. It lives in informe-imataca.html because it is
 * the published text; the figures, the tables and the map's labels are built
 * from the artifact so a rebuilt artifact moves them and a change in the prose
 * cannot move a number.
 *
 * The page is a report, not a panel: there is no year slider, no selection and
 * no per-year re-render. The artifact is fetched once and drawn once.
 */

(function () {
  "use strict";

  var API_INFORME = "/api/informe/imataca";

  // The viewer's public address. It is the site's own identity, not a study
  // figure: the citation names it and the printed page carries it as text.
  var URL_VIEWER = "https://biomas-cve.marioggil.xyz/";

  var SVG_NS = "http://www.w3.org/2000/svg";

  // ---------------------------------------------------------------------------
  // Small helpers: DOM, Spanish number formatting
  // ---------------------------------------------------------------------------

  function porId(id) {
    return document.getElementById(id);
  }

  function fijarTexto(id, texto) {
    var nodo = porId(id);
    if (nodo) {
      nodo.textContent = texto;
    }
  }

  function crear(tag, clase, texto) {
    var nodo = document.createElement(tag);
    if (clase) {
      nodo.className = clase;
    }
    if (texto !== undefined && texto !== null) {
      nodo.textContent = texto;
    }
    return nodo;
  }

  function crearSvg(tag, atributos) {
    var nodo = document.createElementNS(SVG_NS, tag);
    if (atributos) {
      Object.keys(atributos).forEach(function (clave) {
        nodo.setAttribute(clave, String(atributos[clave]));
      });
    }
    return nodo;
  }

  function vaciar(id) {
    var nodo = porId(id);
    if (nodo) {
      nodo.textContent = "";
    }
    return nodo;
  }

  // Spanish formatting is written by hand instead of delegated to
  // `toLocaleString`: a browser built with reduced ICU data falls back to
  // en-US and would print "47,844" where the report prints "47.844".
  function agrupar(entero) {
    var signo = entero < 0 ? "\u2212" : "";
    var digitos = String(Math.abs(entero));
    var salida = "";
    while (digitos.length > 3) {
      salida = "." + digitos.slice(-3) + salida;
      digitos = digitos.slice(0, -3);
    }
    return signo + digitos + salida;
  }

  // `toFixed` on a value indistinguishable from zero prints "-0,00"; the report
  // says "estable" for that case, so the sign is dropped below half a unit of
  // the last printed decimal. A negative value prints the report's own minus
  // sign (U+2212), the one its section 3 table is written with.
  function decimales(valor, cuantos) {
    var numero = Number(valor);
    var limite = Math.pow(10, -cuantos) / 2;
    if (Math.abs(numero) < limite) {
      numero = 0;
    }
    return numero.toFixed(cuantos).replace(".", ",").replace(/^-/, "\u2212");
  }

  function porcentaje(valor, cuantos) {
    return decimales(valor, cuantos) + " %";
  }

  function porcentajeConSigno(valor, cuantos) {
    var texto = decimales(valor, cuantos);
    return (valor > 0 ? "+" : "") + texto + " puntos";
  }

  function hectareas(valor) {
    var numero = Number(valor);
    var redondeado = Math.round(Math.abs(numero)) * (numero < 0 ? -1 : 1);
    return (numero > 0 ? "+" : "") + agrupar(redondeado) + " ha";
  }

  // The study's coordinates travel with five or six decimals, so they are
  // printed exactly as the artifact carries them -- the same form the report's
  // code block uses, and the same form the viewer's clip tool accepts.
  function coordenada(valor) {
    return String(valor);
  }

  // ---------------------------------------------------------------------------
  // Header, coordinates, footer
  // ---------------------------------------------------------------------------

  function pintarCabecera(datos) {
    fijarTexto(
      "informe-cita-corta",
      "Consulta del " +
        datos.procedencia.consulta_es +
        " · " +
        URL_VIEWER +
        " · cifras servidas desde " +
        API_INFORME
    );
    fijarTexto(
      "informe-pie",
      "Informe de caso · MapBiomas " +
        mayuscula(datos.pais) +
        " · Colección " +
        String(datos.coleccion) +
        " · consulta del " +
        datos.procedencia.consulta_es +
        " · " +
        URL_VIEWER
    );
  }

  function mayuscula(texto) {
    var cadena = String(texto);
    return cadena.charAt(0).toUpperCase() + cadena.slice(1);
  }

  function pintarCaja(datos) {
    var caja = datos.caja;
    // The same two lines the report's code block carries, in the report's own
    // column layout.
    var lineas = [
      "oeste  " + coordenada(caja.oeste) + "    sur   " + coordenada(caja.sur),
      "este   " + coordenada(caja.este) + "    norte " + coordenada(caja.norte),
    ];
    var bloque = vaciar("caja-coordenadas");
    if (bloque) {
      bloque.textContent = lineas.join("\n");
    }

    var lista = vaciar("mapa-coordenadas");
    if (!lista) {
      return;
    }
    [
      ["Oeste", caja.oeste],
      ["Sur", caja.sur],
      ["Este", caja.este],
      ["Norte", caja.norte],
    ].forEach(function (par) {
      var item = crear("li");
      item.appendChild(crear("span", "coordenada-nombre", par[0]));
      item.appendChild(crear("span", "coordenada-valor", coordenada(par[1])));
      lista.appendChild(item);
    });

    fijarTexto(
      "mapa-pie",
      "La caja del estudio sobre las coberturas de " +
        datos.mapa.anio +
        ". " +
        redondear(caja.ancho_km) +
        " × " +
        redondear(caja.alto_km) +
        " km · " +
        agrupar(Math.round(caja.ventana_ha)) +
        " ha (" +
        agrupar(Math.round(caja.ventana_km2)) +
        " km²) · " +
        decimales(caja.observada_pct, 0) +
        " % observada, " +
        decimales(caja.sin_dato_ha, 0) +
        " ha sin dato. Coordenadas en grados decimales, con punto decimal, " +
        "como en el informe. Datos: MapBiomas Venezuela, Colección " +
        datos.coleccion +
        " (CC BY 4.0, adaptado)."
    );
  }

  function redondear(valor) {
    return agrupar(Math.round(Number(valor)));
  }

  // ---------------------------------------------------------------------------
  // Map: the study's box over the 2024 tile pyramid
  // ---------------------------------------------------------------------------

  function pintarMapa(datos) {
    var contenedor = porId("mapa");
    if (!contenedor) {
      return;
    }
    if (typeof window.maplibregl === "undefined") {
      contenedor.appendChild(
        crear(
          "p",
          "mapa-ayuda",
          "No se pudo cargar el visor de mapas local, así que el mapa no está " +
            "disponible en esta visita. Las coordenadas de la caja y el resto " +
            "de las cifras del informe sí se muestran."
        )
      );
      return;
    }

    var caja = datos.caja;
    var oeste = caja.oeste;
    var sur = caja.sur;
    var este = caja.este;
    var norte = caja.norte;
    var plantilla = datos.mapa.plantilla.replace("{year}", String(datos.mapa.anio));

    var mapa = new window.maplibregl.Map({
      container: contenedor,
      // MapLibre needs a style with a source before a source can be added; the
      // only layer is the background colour the viewer's own canvas uses.
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "fondo",
            type: "background",
            paint: { "background-color": "#dde3eb" },
          },
        ],
      },
      center: caja.centro,
      zoom: 8,
      minZoom: datos.mapa.zoom_min,
      maxZoom: datos.mapa.zoom_max,
      attributionControl: false,
    });

    mapa.addControl(
      new window.maplibregl.NavigationControl({ showCompass: false }),
      "top-right"
    );
    // The attribution is not compact: the printed page must carry it, and a
    // collapsed control prints as a button with no text.
    mapa.addControl(
      new window.maplibregl.AttributionControl({
        compact: false,
        customAttribution:
          "Datos: <a href='https://venezuela.mapbiomas.org/terminos-de-uso/' target='_blank' rel='noopener'>MapBiomas Venezuela</a> · Colección " +
          datos.coleccion +
          " · <a href='https://creativecommons.org/licenses/by/4.0/' target='_blank' rel='noopener'>CC BY 4.0</a> · adaptado",
      }),
      "bottom-right"
    );

    // MapLibre measures its canvas once, at construction. The page's figures
    // are added after it, and the print layout resizes the column: without this
    // observer the canvas keeps a stale size and clips the box.
    if (typeof window.ResizeObserver !== "undefined") {
      var observador = new window.ResizeObserver(function () {
        if (typeof mapa.resize === "function" && typeof mapa.loaded === "function" && mapa.loaded()) {
          mapa.resize();
        }
      });
      observador.observe(contenedor);
    }

    mapa.on("load", function () {
      if (typeof mapa.resize === "function") {
        mapa.resize();
      }
      mapa.addSource("cobertura-2024", {
        type: "raster",
        tiles: [plantilla],
        tileSize: 256,
        minzoom: datos.mapa.zoom_min,
        maxzoom: datos.mapa.zoom_max,
      });
      mapa.addLayer({
        id: "cobertura",
        type: "raster",
        source: "cobertura-2024",
        paint: { "raster-opacity": 1, "raster-saturation": 0 },
      });

      mapa.addSource("caja-estudio", {
        type: "geojson",
        data: cajaGeoJson(caja),
      });
      mapa.addLayer({
        id: "caja-relleno",
        type: "fill",
        source: "caja-estudio",
        paint: { "fill-color": "#2563eb", "fill-opacity": 0.14 },
      });
      mapa.addLayer({
        id: "caja-borde",
        type: "line",
        source: "caja-estudio",
        paint: { "line-color": "#2563eb", "line-width": 2 },
      });

      // The box with a margin of context, so the rectangle reads as a chosen
      // area inside a larger region instead of as the edge of the data.
      var margenLon = (este - oeste) * 0.15;
      var margenLat = (norte - sur) * 0.15;
      mapa.fitBounds(
        [
          [oeste - margenLon, sur - margenLat],
          [este + margenLon, norte + margenLat],
        ],
        { padding: 12, animate: false, duration: 0 }
      );

      etiquetasDeEsquinas(mapa, caja);
    });
  }

  function cajaGeoJson(caja) {
    var anillo = [
      [caja.oeste, caja.sur],
      [caja.este, caja.sur],
      [caja.este, caja.norte],
      [caja.oeste, caja.norte],
      [caja.oeste, caja.sur],
    ];
    return {
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [anillo] },
    };
  }

  // The four coordinates, labelled on the rectangle. They are DOM markers, not
  // a `symbol` layer: a symbol layer's text needs a glyphs endpoint, and this
  // repository serves none, so the labels would silently not draw. Each corner
  // carries the two coordinates that meet there and sits INSIDE the rectangle,
  // which keeps it readable at 390 px where outside placement would be clipped.
  function etiquetasDeEsquinas(mapa, caja) {
    var esquinas = [
      {
        lng: caja.oeste,
        lat: caja.norte,
        lineas: ["O " + coordenada(caja.oeste), "N " + coordenada(caja.norte)],
        anchor: "top-left",
        offset: [8, 8],
      },
      {
        lng: caja.este,
        lat: caja.norte,
        lineas: ["E " + coordenada(caja.este), "N " + coordenada(caja.norte)],
        anchor: "top-right",
        offset: [-8, 8],
      },
      {
        lng: caja.oeste,
        lat: caja.sur,
        lineas: ["O " + coordenada(caja.oeste), "S " + coordenada(caja.sur)],
        anchor: "bottom-left",
        offset: [8, -8],
      },
      {
        lng: caja.este,
        lat: caja.sur,
        lineas: ["E " + coordenada(caja.este), "S " + coordenada(caja.sur)],
        anchor: "bottom-right",
        offset: [-8, -8],
      },
    ];
    esquinas.forEach(function (esquina) {
      var placa = crear("div", "mapa-etiqueta");
      esquina.lineas.forEach(function (linea, indice) {
        if (indice > 0) {
          placa.appendChild(document.createElement("br"));
        }
        placa.appendChild(document.createTextNode(linea));
      });
      new window.maplibregl.Marker({
        element: placa,
        anchor: esquina.anchor,
        offset: esquina.offset,
      })
        .setLngLat([esquina.lng, esquina.lat])
        .addTo(mapa);
    });
  }

  // ---------------------------------------------------------------------------
  // Table: the report's section 3
  // ---------------------------------------------------------------------------

  function tabla(encabezados, filas, pie) {
    var tablaNodo = crear("table");
    if (pie) {
      var caption = crear("caption", null, pie);
      tablaNodo.appendChild(caption);
    }
    var thead = crear("thead");
    var filaTitulo = crear("tr");
    encabezados.forEach(function (encabezado) {
      var celda = crear("th", null, encabezado.titulo);
      celda.scope = "col";
      if (encabezado.clase) {
        celda.className = encabezado.clase;
      }
      filaTitulo.appendChild(celda);
    });
    thead.appendChild(filaTitulo);
    tablaNodo.appendChild(thead);

    var tbody = crear("tbody");
    filas.forEach(function (fila) {
      var tr = crear("tr");
      fila.forEach(function (celdaDatos) {
        var celda = crear("td", celdaDatos.clase || null, celdaDatos.texto);
        if (celdaDatos.titulo) {
          celda.title = celdaDatos.titulo;
        }
        tr.appendChild(celda);
      });
      tbody.appendChild(tr);
    });
    tablaNodo.appendChild(tbody);
    return tablaNodo;
  }

  function celda(texto, clase, titulo) {
    return { texto: texto, clase: clase, titulo: titulo };
  }

  function pintarTablaCoberturas(datos) {
    var contenedor = vaciar("tabla-coberturas");
    if (!contenedor) {
      return;
    }
    var anios = datos.coberturas.anios;
    var primero = anios[0];
    var ultimo = anios[anios.length - 1];
    var filas = datos.coberturas.clases
      .filter(function (clase) {
        return clase.en_informe;
      })
      .map(function (clase) {
        return [
          celda(clase.codigo + " " + clase.nombre_es),
          celda(porcentaje(clase.share_1985, 2), "numero"),
          celda(porcentaje(clase.share_2024, 2), "numero"),
          celda(
            porcentajeConSigno(clase.delta_puntos, 2) + " (" + hectareas(clase.delta_ha) + ")",
            "numero"
          ),
        ];
      });
    contenedor.appendChild(
      tabla(
        [
          { titulo: "Clase" },
          { titulo: String(primero), clase: "numero" },
          { titulo: String(ultimo), clase: "numero" },
          { titulo: "Cambio", clase: "numero" },
        ],
        filas,
        "Participación de cada clase en la caja del estudio, en los dos años " +
          "extremos de la serie. Denominador: la ventana medida, " +
          agrupar(Math.round(datos.caja.ventana_ha)) +
          " ha, " +
          decimales(datos.caja.observada_pct, 0) +
          " % observada. Área geodésica WGS84 con radio authálico " +
          agrupar(Math.round(datos.caja.radio_autalico_m)) +
          " m."
      )
    );
  }

  // ---------------------------------------------------------------------------
  // Figure: coverage over the ten years, one panel per class
  // ---------------------------------------------------------------------------

  function techoBonito(valor) {
    if (!(valor > 0)) {
      return 1;
    }
    var exponente = Math.pow(10, Math.floor(Math.log(valor) / Math.LN10));
    var mantisa = valor / exponente;
    var paso = mantisa <= 1 ? 1 : mantisa <= 2 ? 2 : mantisa <= 5 ? 5 : 10;
    return paso * exponente;
  }
  function pintarFiguraCoberturas(datos) {
    var contenedor = vaciar("figura-coberturas-paneles");
    if (!contenedor) {
      return;
    }
    var anios = datos.coberturas.anios;
    var clases = datos.coberturas.clases.filter(function (clase) {
      return clase.en_informe;
    });

    clases.forEach(function (clase) {
      var figura = crear("figure", "panel-clase");
      figura.appendChild(
        crear("figcaption", "panel-clase-titulo", clase.codigo + " " + clase.nombre_es)
      );
      figura.appendChild(panelCobertura(clase, anios, datos.caja.ventana_ha));
      figura.appendChild(
        crear(
          "p",
          "panel-clase-pie",
          String(anios[0]) +
            ": " +
            porcentaje(clase.share_1985, 2) +
            " · " +
            String(anios[anios.length - 1]) +
            ": " +
            porcentaje(clase.share_2024, 2) +
            " · " +
            porcentajeConSigno(clase.delta_puntos, 2) +
            " (" +
            hectareas(clase.delta_ha) +
            ")"
        )
      );
      contenedor.appendChild(figura);
    });

    fijarTexto(
      "figura-coberturas-pie",
      "Evolución de la participación de las seis clases que tabula la sección " +
        "3 del informe, en los " +
        String(anios.length) +
        " años medidos (" +
        String(anios[0]) +
        "–" +
        String(anios[anios.length - 1]) +
        "). Denominador de cada panel: la ventana medida, " +
        agrupar(Math.round(datos.caja.ventana_ha)) +
        " ha, " +
        decimales(datos.caja.observada_pct, 0) +
        " % observada, así que la proporción es la de la caja. Cada panel tiene " +
        "su propia escala vertical, visible en su eje: la forma de cada curva es " +
        "el dato, y una escala común aplanaría las cinco clases pequeñas contra " +
        "el eje. El área se midió como área geodésica sobre la esfera WGS84 con " +
        "radio authálico " +
        agrupar(Math.round(datos.caja.radio_autalico_m)) +
        " m. Las series no se leen como una causa de las charlas: el informe lo " +
        "declara en su sección 5."
    );
  }

  function panelCobertura(clase, anios, ventanaHa) {
    var ancho = 320;
    var alto = 150;
    var izq = 36;
    var der = 56;
    var arriba = 10;
    var abajo = 24;
    var interiorAncho = ancho - izq - der;
    var interiorAlto = alto - arriba - abajo;

    var maximo = Math.max.apply(null, clase.share_pct);
    var techo = techoBonito(maximo * 1.15);
    var x = function (indice) {
      return izq + (indice / (anios.length - 1)) * interiorAncho;
    };
    var y = function (valor) {
      return arriba + interiorAlto - (valor / techo) * interiorAlto;
    };

    var svg = crearSvg("svg", {
      viewBox: "0 0 " + ancho + " " + alto,
      class: "panel-clase-svg",
      role: "img",
    });
    var titulo = crearSvg("title");
    titulo.textContent =
      "Participación de " +
      clase.nombre_es +
      " en la caja, " +
      anios[0] +
      "–" +
      anios[anios.length - 1];
    svg.appendChild(titulo);
    svg.setAttribute(
      "aria-label",
      "Serie de " +
        clase.nombre_es +
        ": " +
        clase.share_pct
          .map(function (valor, indice) {
            return anios[indice] + ", " + porcentaje(valor, 2);
          })
          .join("; ") +
        ". Denominador: la ventana medida de " +
        agrupar(Math.round(ventanaHa)) +
        " ha."
    );

    // Base line and the two scale ticks the panel's own scale needs.
    var base = crearSvg("line", {
      class: "svg-eje-linea",
      x1: izq,
      y1: y(0),
      x2: izq + interiorAncho,
      y2: y(0),
    });
    svg.appendChild(base);
    [0, techo].forEach(function (valor) {
      var etiqueta = crearSvg("text", {
        class: "svg-eje",
        x: izq - 5,
        y: y(valor) + 4,
        "text-anchor": "end",
      });
      etiqueta.textContent = decimales(valor, techo >= 10 ? 0 : 2) + " %";
      svg.appendChild(etiqueta);
    });

    anios.forEach(function (anio, indice) {
      if (indice > 0 && indice < anios.length - 1) {
        svg.appendChild(
          crearSvg("line", {
            class: "svg-eje-linea",
            x1: x(indice),
            y1: y(0),
            x2: x(indice),
            y2: y(0) + 3,
          })
        );
      }
    });
    [0, anios.length - 1].forEach(function (indice, posicion) {
      var etiqueta = crearSvg("text", {
        class: "svg-eje",
        x: x(indice),
        y: alto - 8,
        "text-anchor": posicion === 0 ? "start" : "end",
      });
      etiqueta.textContent = String(anios[indice]);
      svg.appendChild(etiqueta);
    });

    var puntos = clase.share_pct.map(function (valor, indice) {
      return [x(indice), y(valor)];
    });
    var dArea =
      "M " + puntos[0][0] + " " + y(0) + " " +
      puntos
        .map(function (punto) {
          return "L " + punto[0] + " " + punto[1];
        })
        .join(" ") +
      " L " + puntos[puntos.length - 1][0] + " " + y(0) + " Z";
    svg.appendChild(crearSvg("path", { class: "svg-area", d: dArea }));

    var dLinea =
      "M " +
      puntos
        .map(function (punto) {
          return punto[0] + " " + punto[1];
        })
        .join(" L ");
    svg.appendChild(crearSvg("path", { class: "svg-serie", d: dLinea }));

    var ultimo = puntos[puntos.length - 1];
    svg.appendChild(crearSvg("circle", { class: "svg-punto", cx: ultimo[0], cy: ultimo[1], r: 2.5 }));
    var valorFinal = crearSvg("text", {
      class: "svg-valor",
      x: ultimo[0] + 5,
      y: ultimo[1] + 4,
    });
    valorFinal.textContent = porcentaje(clase.share_pct[clase.share_pct.length - 1], 2);
    svg.appendChild(valorFinal);

    return svg;
  }

  // ---------------------------------------------------------------------------
  // Tables: the congress record and the curation
  // ---------------------------------------------------------------------------

  function pintarTablaCongresos(datos) {
    var contenedor = vaciar("tabla-charlas");
    if (!contenedor) {
      return;
    }
    var filas = datos.congresos.ediciones.map(function (edicion) {
      return [
        celda(String(edicion.anio)),
        celda(String(edicion.charlas), "numero"),
        celda(String(edicion.pares_ror), "numero"),
        celda(String(edicion.instituciones), "numero"),
        celda(
          edicion.pares_dudosos > 0 ? String(edicion.pares_dudosos) : "—",
          edicion.pares_dudosos > 0 ? "numero dudoso" : "numero"
        ),
      ];
    });
    filas.push([
      celda("Total", "destacado"),
      celda(String(datos.congresos.charlas), "numero destacado"),
      celda(String(datos.congresos.pares_institucion), "numero destacado"),
      celda(String(datos.congresos.instituciones_distintas), "numero destacado"),
      celda(String(datos.congresos.pares_dudosos), "numero destacado"),
    ]);
    contenedor.appendChild(
      tabla(
        [
          { titulo: "Edición" },
          { titulo: "Charlas", clase: "numero" },
          { titulo: "Pares charla-institución", clase: "numero" },
          { titulo: "Instituciones", clase: "numero" },
          { titulo: "Pares dudosos", clase: "numero" },
        ],
        filas,
        "El registro por edición dentro de la caja. Denominador: las " +
          String(datos.congresos.charlas) +
          " charlas del estudio, repartidas en " +
          String(datos.congresos.ediciones.length) +
          " ediciones. Los pares charla-institución suman " +
          String(datos.congresos.pares_institucion) +
          ", de los cuales " +
          String(datos.congresos.pares_dudosos) +
          " llevan un ROR que el curado marcó dudoso."
      )
    );
  }

  function pintarTablaInstituciones(datos) {
    var contenedor = vaciar("tabla-instituciones");
    if (!contenedor) {
      return;
    }
    var filas = datos.congresos.instituciones.map(function (institucion) {
      return [
        celda(
          institucion.nombre + (institucion.estado === "dudoso" ? " (dudoso)" : ""),
          institucion.estado === "dudoso" ? "dudoso" : null
        ),
        celda(String(institucion.pares), "numero"),
      ];
    });
    contenedor.appendChild(
      tabla(
        [
          { titulo: "Institución" },
          { titulo: "Pares", clase: "numero" },
        ],
        filas,
        "Denominador: los " +
          String(datos.congresos.pares_institucion) +
          " pares charla-institución del estudio, en " +
          String(datos.congresos.instituciones_distintas) +
          " instituciones distintas. “(dudoso)” marca los pares cuyo ROR " +
          "resuelve a una institución distinta de la nombrada en el resumen; " +
          "están incluidos por decisión del dueño."
      )
    );
  }

  function pintarTablaEspecies(datos) {
    var contenedor = vaciar("tabla-especies");
    if (!contenedor) {
      return;
    }
    var filas = datos.congresos.ediciones.map(function (edicion) {
      var quitadas = edicion.especies_sin_curar - edicion.especies_distintas;
      return [
        celda(String(edicion.anio)),
        celda(String(edicion.especies_distintas), "numero"),
        celda(String(edicion.especies_sin_curar), "numero"),
        celda(quitadas > 0 ? "la curación quitó " + String(quitadas) : "—", "nota"),
      ];
    });
    filas.push([
      celda("Total", "destacado"),
      celda(String(datos.especies.determinaciones), "numero destacado"),
      celda(
        String(
          datos.congresos.ediciones.reduce(function (suma, edicion) {
            return suma + edicion.especies_sin_curar;
          }, 0)
        ),
        "numero destacado"
      ),
      celda("", null),
    ]);
    contenedor.appendChild(
      tabla(
        [
          { titulo: "Edición" },
          { titulo: "Especies distintas", clase: "numero" },
          { titulo: "Sin curar", clase: "numero" },
          { titulo: "Efecto de la curación", clase: "nota" },
        ],
        filas,
        "Especies distintas registradas por edición, tras la curación: " +
          String(datos.especies.determinaciones) +
          " determinaciones a nivel de especie en las " +
          String(datos.congresos.ediciones.length) +
          " ediciones, que corresponden a " +
          String(datos.especies.especies_distintas) +
          " especies distintas porque hay " +
          String(datos.especies.repetidas.length) +
          " especie nombrada en más de una edición (" +
          datos.especies.repetidas
            .map(function (repetida) {
              return repetida.taxon + ", en " + repetida.ediciones.join(" y ");
            })
            .join("; ") +
          "). La columna “Sin curar” es lo que el parseo contó antes de la " +
          "curación, sobre las " +
          String(datos.especies.entradas_crudas) +
          " entradas crudas de la caja."
      )
    );
  }

  function pintarTablaCuracion(datos) {
    var contenedor = vaciar("tabla-curacion");
    if (!contenedor) {
      return;
    }
    var nombres = {
      especie: "Determinaciones a nivel de especie",
      "género": "Determinación a nivel de género",
      familia: "Familias",
      "no es un nombre": "No son nombres de organismos",
    };
    var filas = Object.keys(datos.especies.clases).map(function (clave) {
      return [celda(nombres[clave] || clave), celda(String(datos.especies.clases[clave]), "numero")];
    });
    filas.push([
      celda("Entradas crudas", "destacado"),
      celda(String(datos.especies.entradas_crudas), "numero destacado"),
    ]);
    contenedor.appendChild(
      tabla(
        [
          { titulo: "Clase de la curación" },
          { titulo: "Entradas", clase: "numero" },
        ],
        filas,
        "La curación de las " +
          String(datos.especies.entradas_crudas) +
          " entradas que el parseo extrajo en esta caja. Denominador: esas " +
          String(datos.especies.entradas_crudas) +
          " entradas. Las " +
          String(datos.especies.clases.especie) +
          " determinaciones a nivel de especie son " +
          String(datos.especies.especies_distintas) +
          " especies distintas: " +
          datos.especies.repetidas
            .map(function (repetida) {
              return repetida.taxon + " (" + repetida.ediciones.join(" y ") + ")";
            })
            .join(", ") +
          "."
      )
    );
  }

  function pintarTablaCuracionMarcadas(datos) {
    var contenedor = vaciar("tabla-curacion-marcadas");
    if (!contenedor) {
      return;
    }
    var marcadas = datos.especies.entradas.filter(function (entrada) {
      return entrada.nota !== "";
    });
    var filas = marcadas.map(function (entrada) {
      return [
        celda(entrada.crudo),
        celda(entrada.taxon || "—"),
        celda(entrada.clase),
        celda(entrada.nota, "nota"),
      ];
    });
    contenedor.appendChild(
      tabla(
        [
          { titulo: "Forma cruda" },
          { titulo: "Taxón normalizado" },
          { titulo: "Clase" },
          { titulo: "Nota de la curación" },
        ],
        filas,
        "Las " +
          String(marcadas.length) +
          " entradas de las " +
          String(datos.especies.entradas_crudas) +
          " que llevan una nota: erratas del resumen, la especie nombrada dos " +
          "veces, el género, las familias y las que no son nombres de " +
          "organismos. La forma cruda se conserva tal como está y se marca, en " +
          "vez de corregirse en silencio. Denominador: las " +
          String(datos.especies.entradas_crudas) +
          " entradas crudas de la caja."
      )
    );
  }

  // ---------------------------------------------------------------------------
  // Figures: the two congress series
  // ---------------------------------------------------------------------------

  function pintarFiguraBarras(contenedorId, ediciones, valores, opciones) {
    var contenedor = vaciar(contenedorId);
    if (!contenedor) {
      return;
    }
    // The viewBox is the container's own CSS width, so the drawing is rendered
    // at roughly one SVG unit per CSS pixel at any viewport: a fixed viewBox
    // scaled down to 390 px would print its axis labels at 6 px. The CSS width
    // (100 %) then only rescales on a later resize of the window.
    var ancho = Math.round(contenedor.clientWidth) || 640;
    ancho = Math.max(320, Math.min(720, ancho));
    var alto = ancho < 480 ? 260 : 250;
    var izq = 44;
    var der = 16;
    var arriba = 16;
    var abajo = 36;
    var interiorAncho = ancho - izq - der;
    var interiorAlto = alto - arriba - abajo;

    var techo = techoBonito(Math.max.apply(null, valores) * 1.15);
    var paso = interiorAncho / ediciones.length;
    var anchoBarra = Math.min(52, paso * 0.62);
    var y = function (valor) {
      return arriba + interiorAlto - (valor / techo) * interiorAlto;
    };

    var svg = crearSvg("svg", {
      viewBox: "0 0 " + ancho + " " + alto,
      class: "panel-svg",
      role: "img",
      "aria-label": opciones.descripcion,
    });
    var titulo = crearSvg("title");
    titulo.textContent = opciones.titulo;
    svg.appendChild(titulo);

    svg.appendChild(
      crearSvg("line", {
        class: "svg-eje-linea",
        x1: izq,
        y1: y(0),
        x2: izq + interiorAncho,
        y2: y(0),
      })
    );
    // Horizontal grid lines at the scale's ceiling and midpoint, labelled on
    // the left: the bars carry their own value label, the lines carry the scale.
    [techo, techo / 2].forEach(function (valor) {
      svg.appendChild(
        crearSvg("line", {
          class: "svg-eje-linea",
          x1: izq,
          y1: y(valor),
          x2: izq + interiorAncho,
          y2: y(valor),
        })
      );
      var etiqueta = crearSvg("text", {
        class: "svg-eje",
        x: izq - 6,
        y: y(valor) + 4,
        "text-anchor": "end",
      });
      etiqueta.textContent = String(valor);
      svg.appendChild(etiqueta);
    });

    ediciones.forEach(function (edicion, indice) {
      var centro = izq + paso * indice + paso / 2;
      var valor = valores[indice];
      var barra = crearSvg("rect", {
        class: "svg-barra",
        x: centro - anchoBarra / 2,
        y: y(valor),
        width: anchoBarra,
        height: Math.max(0, y(0) - y(valor)),
        rx: 2,
        ry: 2,
      });
      svg.appendChild(barra);

      var valorTexto = crearSvg("text", {
        class: "svg-valor",
        x: centro,
        y: y(valor) - 5,
        "text-anchor": "middle",
      });
      valorTexto.textContent = String(valor);
      svg.appendChild(valorTexto);

      var anioTexto = crearSvg("text", {
        class: "svg-eje",
        x: centro,
        y: alto - 16,
        "text-anchor": "middle",
      });
      anioTexto.textContent = String(edicion.anio);
      svg.appendChild(anioTexto);
    });

    contenedor.appendChild(svg);
  }

  function pintarFiguraCongresos(datos) {
    var ediciones = datos.congresos.ediciones;
    // The edition the curation rescued from a false count: the one the parse
    // gave organisms to and the curation emptied. The prose of section 4 names
    // it (2011), and the figure's caption reaches it from the data instead of
    // assuming it is the last edition.
    var rescatada = ediciones.filter(function (edicion) {
      return edicion.especies_distintas === 0 && edicion.especies_sin_curar > 0;
    });
    pintarFiguraBarras(
      "figura-charlas-svg",
      ediciones,
      ediciones.map(function (edicion) {
        return edicion.charlas;
      }),
      {
        titulo: "Charlas por edición",
        descripcion:
          "Charlas del estudio por edición: " +
          ediciones
            .map(function (edicion) {
              return edicion.anio + ", " + edicion.charlas;
            })
            .join("; ") +
          ".",
      }
    );
    fijarTexto(
      "figura-charlas-pie",
      "Charlas por edición dentro de la caja. Denominador: las " +
        String(datos.congresos.charlas) +
        " charlas del estudio, en " +
        String(ediciones.length) +
        " ediciones del Congreso Venezolano de Ecología (" +
        String(ediciones[0].anio) +
        "–" +
        String(ediciones[ediciones.length - 1].anio) +
        "). Las barras no se leen contra la serie de cobertura: son dos " +
        "registros distintos, y el informe rechaza por nombre el gráfico que " +
        "los mezcla (sección 5)."
    );

    pintarFiguraBarras(
      "figura-especies-svg",
      ediciones,
      ediciones.map(function (edicion) {
        return edicion.especies_distintas;
      }),
      {
        titulo: "Especies distintas por edición",
        descripcion:
          "Especies distintas registradas por edición: " +
          ediciones
            .map(function (edicion) {
              return edicion.anio + ", " + edicion.especies_distintas;
            })
            .join("; ") +
          ".",
      }
    );
    fijarTexto(
      "figura-especies-pie",
      "Especies distintas registradas por edición, después de la curación. " +
        "Denominador: las " +
        String(datos.especies.determinaciones) +
        " determinaciones a nivel de especie de la caja, que son " +
        String(datos.especies.especies_distintas) +
        " especies distintas porque " +
        datos.especies.repetidas
          .map(function (repetida) {
            return repetida.taxon + " aparece en " + repetida.ediciones.join(" y ");
          })
          .join(", ") +
        ". Las " +
        String(datos.especies.entradas_crudas) +
        " entradas crudas incluyen además " +
        String(datos.especies.clases["género"]) +
        " género, " +
        String(datos.especies.clases.familia) +
        " familias y " +
        String(datos.especies.clases["no es un nombre"]) +
        " que no son nombres" +
        (rescatada.length
          ? ": sin esa curación, " +
            rescatada
              .map(function (edicion) {
                return (
                  String(edicion.anio) +
                  " habría contado " +
                  String(edicion.especies_sin_curar) +
                  " especies"
                );
              })
              .join("; ") +
            "."
          : ".") +
        " La tabla de esta sección muestra el conteo sin curar de cada edición."
    );
  }

  // ---------------------------------------------------------------------------
  // Provenance and citation
  // ---------------------------------------------------------------------------

  function pintarProcedencia(datos) {
    var contenedor = vaciar("procedencia-detalle");
    if (!contenedor) {
      return;
    }
    var procedencia = datos.procedencia;
    var filas = [
      [
        celda("Composición de la caja"),
        celda(procedencia.composicion.artefacto),
        celda("esquema " + String(procedencia.composicion.schema_version), "numero"),
        celda(
          procedencia.composicion.generado_es +
            " (" +
            procedencia.composicion.generado_utc +
            ")",
          "nota"
        ),
      ],
      [
        celda("Catálogo de congresos"),
        celda(procedencia.catalogo.artefacto),
        celda("esquema " + String(procedencia.catalogo.schema_version), "numero"),
        celda(
          procedencia.catalogo.generado_es + " (" + procedencia.catalogo.generado_utc + ")",
          "nota"
        ),
      ],
      [
        celda("Respuestas crudas de la caja"),
        celda(procedencia.clip_schema),
        celda(String(datos.coberturas.anios.length) + " años", "numero"),
        celda(datos.coberturas.metodo_area, "nota"),
      ],
      [
        celda("Consulta"),
        celda(procedencia.consulta_utc),
        celda("", "numero"),
        celda(procedencia.consulta_es, "nota"),
      ],
      [
        celda("Recomputación"),
        celda(procedencia.recomputar),
        celda("", "numero"),
        celda("reconstruye los artefactos desde los insumos versionados", "nota"),
      ],
      [
        celda("Radio authálico"),
        celda(agrupar(Math.round(datos.caja.radio_autalico_m)) + " m"),
        celda("WGS84", "numero"),
        celda("el mismo método de área geodésica en las dos series", "nota"),
      ],
    ];
    contenedor.appendChild(
      tabla(
        [
          { titulo: "Qué" },
          { titulo: "Artefacto" },
          { titulo: "Versión" },
          { titulo: "Fecha o método" },
        ],
        filas,
        "Lo que produjo cada cifra de esta página. El informe se sirve desde " +
          API_INFORME +
          ", que devuelve el artefacto de este estudio tal como quedó " +
          "construido; el visor público que se cita es " +
          URL_VIEWER +
          "."
      )
    );

    var digestTabla = tabla(
      [{ titulo: "Año" }, { titulo: "sha256 del ráster de origen" }, { titulo: "Bytes", clase: "numero" }],
      procedencia.cogs.map(function (cog) {
        return [
          celda(String(cog.anio)),
          celda(cog.sha256, "digest", cog.sha256),
          celda(agrupar(cog.bytes), "numero"),
        ];
      }),
      "Un ráster de origen por año medido, con su digest registrado. Denominador: " +
        String(procedencia.cogs.length) +
        " años, uno por cada respuesta cruda de la caja."
    );
    contenedor.appendChild(digestTabla);
  }

  function pintarCita(datos) {
    var contenedor = vaciar("cita");
    if (!contenedor) {
      return;
    }
    var parrafo = crear("p");
    parrafo.appendChild(
      document.createTextNode(
        "«MapBiomas – Colección " +
          String(datos.coleccion) +
          " de la Serie anual de Mapas de Cobertura y Uso del Suelo de " +
          mayuscula(datos.pais) +
          ", consultada el " +
          datos.procedencia.consulta_es +
          " a través del enlace: "
      )
    );
    var enlace = crear("a", null, URL_VIEWER);
    enlace.href = URL_VIEWER;
    parrafo.appendChild(enlace);
    parrafo.appendChild(document.createTextNode("»"));
    contenedor.appendChild(parrafo);
  }

  // ---------------------------------------------------------------------------
  // Entry point
  // ---------------------------------------------------------------------------

  function aviso(mensaje) {
    var nodo = porId("informe-aviso");
    if (nodo) {
      nodo.textContent = mensaje;
      nodo.hidden = false;
    }
  }

  function pintar(datos) {
    pintarCabecera(datos);
    pintarCaja(datos);
    pintarTablaCoberturas(datos);
    pintarFiguraCoberturas(datos);
    pintarTablaCongresos(datos);
    pintarTablaInstituciones(datos);
    pintarTablaEspecies(datos);
    pintarFiguraCongresos(datos);
    pintarTablaCuracion(datos);
    pintarTablaCuracionMarcadas(datos);
    pintarProcedencia(datos);
    pintarCita(datos);
    pintarMapa(datos);
  }

  function iniciar() {
    if (typeof window.fetch !== "function") {
      aviso("Este navegador no puede leer el artefacto del informe (no tiene fetch).");
      return;
    }
    window
      .fetch(API_INFORME, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
      .then(function (respuesta) {
        if (!respuesta.ok) {
          throw new Error("HTTP " + respuesta.status + " al leer " + API_INFORME);
        }
        return respuesta.json();
      })
      .then(function (datos) {
        pintar(datos);
      })
      .catch(function (error) {
        // The prose stays: it is the document. What is missing is every figure,
        // and the page says so in one place instead of leaving empty boxes.
        aviso(
          "No se pudo leer el artefacto del informe (" +
            error.message +
            "), así que las cifras, las tablas, las figuras y el mapa no se " +
            "muestran. El texto del informe sí está completo. Vuelva a cargar " +
            "la página o consulte /api/informe/imataca."
        );
      });
  }

  iniciar();
})();
