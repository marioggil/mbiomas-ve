<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.40.5-Bratislava" styleCategories="Symbology|Symbology3D|Labeling|Fields|Forms|Actions|Diagrams|GeometryOptions|Relations|Legend">
  <pipe-data-defined-properties>
    <Option type="Map">
      <Option type="QString" name="name" value=""/>
      <Option name="properties"/>
      <Option type="QString" name="type" value="collection"/>
    </Option>
  </pipe-data-defined-properties>
  <pipe>
    <provider>
      <resampling enabled="false" zoomedOutResamplingMethod="nearestNeighbour" zoomedInResamplingMethod="nearestNeighbour" maxOversampling="2"/>
    </provider>
    <rasterrenderer band="1" opacity="1" type="paletted" nodataColor="" alphaBand="-1">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <colorPalette>
        <paletteEntry color="#1f8d49" label="3. Bosque" alpha="255" value="3"/>
        <paletteEntry color="#7dc975" label="4. Sabana arbolada" alpha="255" value="4"/>
        <paletteEntry color="#04381d" label="5. Manglar" alpha="255" value="5"/>
        <paletteEntry color="#026975" label="6. Bosque inundable " alpha="255" value="6"/>
        <paletteEntry color="#7a5900" label="9. Plantación forestal" alpha="255" value="9"/>
        <paletteEntry color="#519799" label="11.Herbazal/Arbustal inundable" alpha="255" value="11"/>
        <paletteEntry color="#b8af4f" label="12. Sabanas/Herbazal" alpha="255" value="12"/>
        <paletteEntry color="#d89f5c" label="13. Otras formaciones naturales no forestales" alpha="255" value="13"/>
        <paletteEntry color="#edde8e" label="15. Uso pecuario/Tierras en descanso" alpha="255" value="15"/>
        <paletteEntry color="#e974ed" label="18. Uso agrícola/Tierras en descanso" alpha="255" value="18"/>
        <paletteEntry color="#ffefc3" label="21. Uso agropecuario/Tierras en descanso" alpha="255" value="21"/>
        <paletteEntry color="#ffa07a" label="23. Playa o duna" alpha="255" value="23"/>
        <paletteEntry color="#d4271e" label="24. Uso urbano" alpha="255" value="24"/>
        <paletteEntry color="#db4d4f" label="25. Otras áreas antrópica sin vegetación" alpha="255" value="25"/>
        <paletteEntry color="#d5d5e5" label="27. No observado" alpha="255" value="27"/>
        <paletteEntry color="#ffaa5f" label="29. Afloramiento rocosos" alpha="255" value="29"/>
        <paletteEntry color="#9c0027" label="30. Uso minero" alpha="255" value="30"/>
        <paletteEntry color="#091077" label="31. Acuicultura" alpha="255" value="31"/>
        <paletteEntry color="#fc8114" label="32. Planicie de marea hipersalina" alpha="255" value="32"/>
        <paletteEntry color="#2532e4" label="33. Río, lago u océano" alpha="255" value="33"/>
        <paletteEntry color="#93dfe6" label="34. Glaciar" alpha="255" value="34"/>
        <paletteEntry color="#ad5100" label="50. Herbazal/Arbustal xerófilo" alpha="255" value="50"/>
        <paletteEntry color="#a89358" label="66. Arbustal" alpha="255" value="66"/>
        <paletteEntry color="#e97a7a" label="68. Otras áreas natural sin vegetación" alpha="255" value="68"/>
        <paletteEntry color="#dfeb62" label="81. Vegetación herbácea y arbustiva andina" alpha="255" value="81"/>
        <paletteEntry color="#6fc179" label="82. Vegetación herbácea y arbustiva andina inundable" alpha="255" value="82"/>
      </colorPalette>
      <colorramp type="randomcolors" name="[source]">
        <Option/>
      </colorramp>
    </rasterrenderer>
    <brightnesscontrast gamma="1" contrast="0" brightness="0"/>
    <huesaturation colorizeGreen="128" colorizeOn="0" colorizeStrength="100" grayscaleMode="0" colorizeRed="255" invertColors="0" colorizeBlue="128" saturation="0"/>
    <rasterresampler maxOversampling="2"/>
    <resamplingStage>resamplingFilter</resamplingStage>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
