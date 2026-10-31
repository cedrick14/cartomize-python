"""Scene/band selection and optional multispectral production in Qt."""
from dataclasses import asdict
import json
from pathlib import Path

import rasterio
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QWidget, QVBoxLayout, QSizePolicy)

import cartomize as cm
from .sensor_profiles import semantic_band_name
from .desktop import Page, PathField, RASTER_FILTER, VECTOR_FILTER, spin, real


class PreparationPage(Page):
    engine = False
    staged = True

    def __init__(self):
        super().__init__("Prétraitement multispectral",
            "Contrôler la couverture, retenir les scènes nécessaires et préparer les images de la zone d’étude.")
        self.findChild(QLabel, "pageTitle").setWordWrap(True)
        self.parameter_card.setTitle("Données et options")
        self.preparation_mode = QComboBox()
        self.preparation_mode.addItem("Automatique : contrôler et préparer", "automatic")
        self.preparation_mode.addItem("Expert : choisir les opérations", "expert")
        self.preparation_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preparation_mode.setMinimumContentsLength(15)
        self.preparation_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preparation_mode.setToolTip("Automatique : diagnostic recalculé à chaque lancement, sélection des scènes et mosaïque selon la couverture. Expert : choix explicite des opérations sans imposer le seuil de couverture.")
        self.form.addRow("Mode de préparation", self.preparation_mode)
        self.files = []
        self.source = PathField("directory")
        self.mode = QComboBox()
        self.mode.addItem("Landsat, Sentinel-2 ou manifeste de scènes", "auto")
        self.mode.addItem("Bandes personnalisées : correspondance manuelle", "manual")
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(15)
        self.mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mode.setToolTip("Reconnaissance des produits Landsat/Sentinel-2 et des manifestes, ou correspondance manuelle de fichiers personnalisés.")
        for index in range(self.mode.count()):
            self.mode.setItemData(index, self.mode.itemText(index), Qt.ItemDataRole.ToolTipRole)
        self.form.addRow("Identification des bandes", self.mode)
        self.form.addRow("Répertoire des scènes", self.source)
        select = QPushButton("Sélectionner\nles bandes…")
        clear = QPushButton("Utiliser le\nrépertoire")
        select.clicked.connect(self.select_files)
        clear.clicked.connect(self.clear_files)
        selection_controls=QWidget();selection_row=QVBoxLayout(selection_controls);selection_row.setContentsMargins(0,0,0,0)
        selection_row.addWidget(select);selection_row.addWidget(clear);self.form.addRow(selection_controls)
        inspect = QPushButton("Analyser\nles bandes")
        inspect.clicked.connect(self.inspect_inputs)
        self.inventory = QLabel("Sélectionner les bandes ou analyser un répertoire.")
        self.inventory.setWordWrap(True)
        self.form.addRow(inspect);self.form.addRow(self.inventory)
        self.assets = QTableWidget(0, 8)
        self.assets.setHorizontalHeaderLabels(["Inclure", "Scène", "Bande spectrale", "Fichier", "Numéro", "Échelle", "Décalage", "Date"])
        self.assets.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.assets.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.assets.setMinimumHeight(170)
        self.assets.setMaximumHeight(250)
        self.form.addRow(self.assets)
        self.add_help("Cocher les bandes à traiter. En mode personnalisé, renseigner le même identifiant de scène pour les bandes d’une acquisition et le même nom spectral entre scènes (red, green, blue, nir…). Vérifier les facteurs de calibration.",
            subject="Identification des bandes",summary="Seules les bandes cochées sont traitées.")
        self.assets.setToolTip("Bandes personnalisées : vérifier les identifiants de scène, les noms spectraux et les facteurs de calibration.")
        self.quality_masks = QTableWidget(0, 4)
        self.quality_masks.setHorizontalHeaderLabels(["Scène", "Qualité", "Type", "Saturation"])
        self.quality_masks.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.quality_masks.verticalHeader().hide()
        self.quality_masks.setToolTip("Sélectionner une scène pour associer ses fichiers de qualité et de saturation. Les chemins complets s’affichent au survol. Le type de masque est choisi dans la troisième colonne.")
        self.quality_masks.setMinimumHeight(90)
        self.quality_masks.setMaximumHeight(155)
        self.form.addRow("Masques associés aux scènes", self.quality_masks)
        mask_controls = QWidget()
        mask_row = QVBoxLayout(mask_controls)
        mask_row.setContentsMargins(0, 0, 0, 0)
        quality_button = QPushButton("Associer\nun masque…")
        saturation_button = QPushButton("Associer la\nsaturation…")
        quality_button.clicked.connect(lambda: self.select_mask(1))
        saturation_button.clicked.connect(lambda: self.select_mask(3))
        mask_row.addWidget(quality_button)
        mask_row.addWidget(saturation_button)
        self.form.addRow(mask_controls)
        self.aoi = PathField(filter=VECTOR_FILTER)
        self.form.addRow("Couche de délimitation", self.aoi)
        self.coverage_threshold = real(100.)
        self.coverage_threshold.setRange(.01, 100.)
        self.coverage_threshold.setDecimals(2)
        self.form.addRow("Couverture utile minimale (%)", self.coverage_threshold)
        self.allow_partial = QCheckBox("Accepter moins\nque le seuil")
        self.allow_partial.setToolTip("Autoriser explicitement une couverture utile insuffisante. Le résultat conserve les lacunes en NoData et porte la mention de couverture partielle ; un résultat sans pixel utile reste refusé.")
        self.form.addRow(self.allow_partial)
        self.catalog_enabled = QCheckBox("Compléter depuis\nun catalogue")
        self.catalog_enabled.setToolTip("Si la couverture est insuffisante, rechercher et télécharger les scènes dans le catalogue STAC indiqué, dans les limites choisies. Sans fichier local, renseigner les bandes à obtenir.")
        self.form.addRow(self.catalog_enabled)
        self.catalog_endpoint = QLineEdit()
        self.catalog_endpoint.setPlaceholderText("Adresse du service STAC")
        self.catalog_collections = QLineEdit()
        self.catalog_collections.setPlaceholderText("Identifiants séparés par des virgules")
        self.catalog_dates = QLineEdit()
        self.catalog_dates.setPlaceholderText("2026-08-01/2026-08-31")
        self.catalog_bands = QLineEdit()
        self.catalog_bands.setPlaceholderText("Exemple : blue,green,red,nir")
        self.catalog_max_items = spin(10, 1, 1000)
        self.catalog_max_mb = spin(1000, 1, 1_000_000)
        self.catalog_timeout = spin(60, 1, 300)
        self._catalog_fields = [self.catalog_endpoint, self.catalog_collections, self.catalog_dates,
                                self.catalog_bands, self.catalog_max_items, self.catalog_max_mb,
                                self.catalog_timeout]
        for label, control in [("Catalogue STAC", self.catalog_endpoint),
                               ("Collections", self.catalog_collections),
                               ("Période de recherche", self.catalog_dates),
                               ("Bandes à obtenir", self.catalog_bands),
                               ("Nombre maximal de scènes", self.catalog_max_items),
                               ("Téléchargement maximal (Mo)", self.catalog_max_mb),
                               ("Délai par requête (s)", self.catalog_timeout)]:
            self.form.addRow(label, control)
        self.audit_button = QPushButton("Diagnostiquer\nla couverture")
        self.audit_button.clicked.connect(self.diagnose_coverage)
        self.apply_audit_button = QPushButton("Appliquer la\nsélection\nproposée")
        self.apply_audit_button.setEnabled(False)
        self.apply_audit_button.clicked.connect(self.apply_audit_proposal)
        audit_controls = QWidget()
        audit_row = QVBoxLayout(audit_controls)
        audit_row.setContentsMargins(0, 0, 0, 0)
        audit_row.addWidget(self.audit_button)
        audit_row.addWidget(self.apply_audit_button)
        self.form.addRow(audit_controls)
        self.coverage_summary = QLabel("Le diagnostic utilise les bandes cochées et la zone d’étude. Choisir le répertoire de sortie avant de le lancer.")
        self.coverage_summary.setWordWrap(True)
        self.coverage_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.form.addRow(self.coverage_summary)
        self.coverage_scenes = QTableWidget(0, 7)
        self.coverage_scenes.setHorizontalHeaderLabels(
            ["Scène", "Emprise (%)", "Données (%)", "Utilisable (%)",
             "Nuages SCL (%)", "Nuages sup. (%)", "Ombres (%)"])
        self.coverage_scenes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.coverage_scenes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.coverage_scenes.setMaximumHeight(165)
        self.coverage_scenes.hide()
        self.form.addRow(self.coverage_scenes)
        self._audit_report = None
        self._next_action = None
        self._audit_generation = 0
        self._pending_audit_generation = None
        self.mosaic = QCheckBox("Mosaïque des\nscènes")
        self.mosaic.setChecked(True)
        self.multiband = QCheckBox("Assemblage\nmultibande")
        self.multiband.setToolTip('Conserver le GeoTIFF scientifique multibande.')
        self.multiband.setChecked(True)
        self.clip = QCheckBox("Extraction\npar masque")
        self.colour = QCheckBox("Composition\ncolorée")
        self.colour.setToolTip('Enregistrer la visualisation dans un GeoTIFF séparé des valeurs scientifiques.')
        self.separate = QCheckBox("Extraction\ndes bandes")
        self.separate.setToolTip('Enregistrer un GeoTIFF distinct par bande.')
        for control in (self.mosaic, self.multiband, self.clip, self.colour, self.separate):
            self.form.addRow(control)
        self.rgb_red = QComboBox()
        self.rgb_green = QComboBox()
        self.rgb_blue = QComboBox()
        for label, control in [("Canal rouge", self.rgb_red), ("Canal vert", self.rgb_green), ("Canal bleu", self.rgb_blue)]:
            self.form.addRow(label, control)
        self.crs = QLineEdit()
        self.crs.setPlaceholderText("Automatique ; exemple : EPSG:32733")
        self.resolution = spin(0, 0, 100000)
        self.resolution.setSpecialValueText("Native")
        self.resolution.setToolTip("Sans résolution explicite, conserver la résolution native la plus grossière des bandes sélectionnées. Une recherche sans images locales exige une résolution choisie.")
        self.resampling = QComboBox()
        for label,value in [('Plus proche voisin','nearest'),('Bilinéaire','bilinear'),('Cubique','cubic'),('Moyenne','average')]:self.resampling.addItem(label,value)
        self.overlap = QComboBox()
        self.overlap.addItem('Première scène valide','first');self.overlap.addItem('Dernière scène valide','last')
        self.atmosphere = QComboBox()
        self.atmosphere.addItem("Automatique : SR prioritaire, DOS1 en secours", "auto")
        self.atmosphere.addItem("Produit Level-2 / SR uniquement", "provider")
        self.atmosphere.addItem("DOS1 local", "dos1")
        self.atmosphere.setToolTip(
            "Stratégie atmosphérique du mode automatique. Le mode Automatique privilégie "
            "un produit de réflectance de surface officiel avant le fallback DOS1."
        )
        self.saturation = QCheckBox('Masquer les\npixels saturés');self.saturation.setChecked(True)
        self.saturation.setToolTip('Appliquer le masque de saturation lorsqu’il est disponible.')
        self.clouds = QCheckBox("Appliquer les\nmasques QA/SCL")
        self.clouds.setChecked(True)
        self.dates = QCheckBox("Autoriser le\nmélange des dates")
        self.dates.setToolTip("Autoriser une mosaïque multitemporelle ou des scènes dont la date d’acquisition est inconnue.")
        for label, control in [("Système de coordonnées cible", self.crs), ("Résolution (m)", self.resolution),
                               ("Rééchantillonnage spectral", self.resampling), ("Recouvrement des scènes", self.overlap),
                               ("Correction atmosphérique", self.atmosphere), ("Saturation", self.saturation),
                               ("Masque de qualité", self.clouds), ("Dates d’acquisition", self.dates)]:
            self.form.addRow(label, control)
        self.output = PathField("directory")
        self.name = QLineEdit("pretraitement")
        self.form.addRow("Répertoire de sortie", self.output)
        self.form.addRow("Nouveau dossier de résultats", self.name)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.form.addRow(self.summary)
        # Native/fallback fonts can be much wider than the current system font.
        # Keep full captions readable vertically instead of forcing the entire
        # parameter page beyond its viewport. Combo choices remain available in
        # the popup and tooltip even for long user-defined spectral names.
        for row in range(self.form.rowCount()):
            item = self.form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is not None and isinstance(item.widget(), QLabel):
                item.widget().setWordWrap(True)
        for choice in (self.rgb_red, self.rgb_green, self.rgb_blue,
                       self.resampling, self.overlap, self.atmosphere):
            choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            choice.setMinimumContentsLength(12)
            choice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            for index in range(choice.count()):
                choice.setItemData(index, choice.itemText(index), Qt.ItemDataRole.ToolTipRole)
            choice.currentTextChanged.connect(choice.setToolTip)
            choice.setToolTip(choice.currentText())
        self.layout.addStretch()
        self.assets.itemChanged.connect(self.refresh_bands)
        self.quality_masks.itemChanged.connect(self.mask_changed)
        self.preparation_mode.currentIndexChanged.connect(self.refresh_options)
        self.preparation_mode.currentIndexChanged.connect(self.invalidate_diagnostic)
        self.atmosphere.currentIndexChanged.connect(self.invalidate_diagnostic)
        self.allow_partial.toggled.connect(self.refresh_options)
        self.catalog_enabled.toggled.connect(self.refresh_options)
        self.catalog_enabled.toggled.connect(self.refresh_bands)
        self.catalog_bands.textChanged.connect(self.refresh_bands)
        for control in self._catalog_fields:
            if isinstance(control, QLineEdit):
                control.textChanged.connect(self.invalidate_diagnostic)
            else:
                control.valueChanged.connect(self.invalidate_diagnostic)
        self.source.edit.textChanged.connect(self.invalidate_inputs)
        self.mode.currentIndexChanged.connect(self.invalidate_inputs)
        self.aoi.edit.textChanged.connect(lambda text: self.clip.setChecked(bool(text.strip())))
        for control in (self.aoi.edit, self.crs):
            control.textChanged.connect(self.invalidate_diagnostic)
        for control in (self.resolution, self.coverage_threshold):
            control.valueChanged.connect(self.invalidate_diagnostic)
        self.resampling.currentIndexChanged.connect(self.invalidate_diagnostic)
        for control in (self.clouds, self.saturation, self.dates):
            control.toggled.connect(self.invalidate_diagnostic)
        for control in (self.mosaic, self.multiband, self.clip, self.colour, self.separate):
            control.toggled.connect(self.refresh_options)
        self.refresh_options()

    def invalidate_inputs(self, *_):
        self.assets.setRowCount(0)
        self.inventory.setText("Analyser les bandes pour actualiser la sélection.")
        self.refresh_bands()

    def select_files(self):
        paths = QFileDialog.getOpenFileNames(self, "Bandes spectrales et masques de qualité",
            filter=RASTER_FILTER + ";;Manifestes de scènes (*.json)")[0]
        if paths:
            self.files = paths
            self.source.setEnabled(False)
            self.inspect_inputs()

    def clear_files(self):
        self.files = []
        self.source.setEnabled(True)
        self.invalidate_inputs()

    def inspect_inputs(self):
        try:
            self.load_inputs()
        except (ValueError, OSError, rasterio.errors.RasterioError) as exc:
            self.inventory.setText(str(exc))

    def load_inputs(self):
        # A failed reload must never leave the previous scene recommendation
        # available for a new (or now empty) band selection.
        self.invalidate_diagnostic()
        self.assets.setRowCount(0)
        self.quality_masks.setRowCount(0)
        sources = list(self.files) if self.files else self.source.text()
        if not sources:
            raise ValueError("Sélectionner les bandes ou le répertoire des scènes.")
        if self.mode.currentData() == "auto":
            scenes = cm.discover_scenes(sources)
        else:
            paths = [Path(p) for p in sources] if isinstance(sources, list) else sorted(
                p for p in Path(sources).rglob("*") if p.suffix.lower() in {".tif", ".tiff", ".jp2", ".img", ".vrt"})
            bands = {}
            for path in paths:
                with rasterio.open(path) as src:
                    for index in src.indexes:
                        raw_name = src.descriptions[index - 1] or (path.stem if src.count == 1 else f"band_{index}")
                        tags = src.tags(index)
                        name = next((semantic_band_name(value) for value in (
                            raw_name, tags.get("semantic_name"), tags.get("common_name"),
                            tags.get("eo:common_name"), tags.get("band_name")
                        ) if value), None) or raw_name
                        # Temporary unique keys; duplicates remain visible for manual correction.
                        bands[f"asset_{len(bands)}"] = (name, cm.Band(str(path.resolve()), index=index,
                            scale=src.scales[index - 1], offset=src.offsets[index - 1], unit=src.units[index - 1] or "source units"))
            if not bands:
                raise ValueError("Aucune bande raster trouvée.")
            scenes = [cm.Scene("scene_1", {key: band for key, (_, band) in bands.items()}, sensor="custom")]
        self.assets.blockSignals(True)
        for scene in scenes:
            metadata = asdict(scene)
            metadata.pop("bands")
            for name, band in scene.bands.items():
                if self.mode.currentData() == "manual":
                    name = bands[name][0]
                row = self.assets.rowCount()
                self.assets.insertRow(row)
                checked = QCheckBox()
                checked.setChecked(True)
                checked.toggled.connect(self.refresh_bands)
                self.assets.setCellWidget(row, 0, checked)
                values = [scene.scene_id, name, str(Path(band.path).resolve()), str(band.index), str(band.scale), str(band.offset), scene.acquired or ""]
                for col, value in enumerate(values, 1):
                    item = QTableWidgetItem(value)
                    if col == 3:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setData(Qt.ItemDataRole.UserRole, dict(scene=metadata, nodata=band.nodata, unit=band.unit))
                    self.assets.setItem(row, col, item)
        self.assets.blockSignals(False)
        self.inventory.setText(f"{len(scenes)} scène(s) ; {self.assets.rowCount()} bande(s). Vérifier la sélection.")
        self.refresh_bands()

    def refresh_bands(self, *_):
        self.invalidate_diagnostic()
        self.refresh_masks()
        names = list(dict.fromkeys(self.assets.item(row, 2).text().strip() for row in range(self.assets.rowCount())
            if self.assets.item(row, 2) and self.assets.cellWidget(row, 0) and self.assets.cellWidget(row, 0).isChecked()))
        if self.catalog_enabled.isChecked() and self.catalog_bands.text().strip():
            names = list(dict.fromkeys(name.strip() for name in self.catalog_bands.text().split(',') if name.strip()))
        for control, default in [(self.rgb_red, "red"), (self.rgb_green, "green"), (self.rgb_blue, "blue")]:
            previous = control.currentData() or default
            control.clear()
            control.addItem("Sélectionner une bande", None)
            for name in names:
                control.addItem(name, name)
            for index in range(control.count()):
                control.setItemData(index, control.itemText(index), Qt.ItemDataRole.ToolTipRole)
            index = control.findData(previous)
            control.setCurrentIndex(max(0, index))

    def mask_parameters(self):
        masks = {}
        for row in range(self.quality_masks.rowCount()):
            scene = self.quality_masks.item(row, 0).text()
            quality = self.quality_masks.item(row, 1).text().strip()
            kind = self.quality_masks.cellWidget(row, 2).currentData()
            saturation = self.quality_masks.item(row, 3).text().strip()
            masks[scene] = dict(quality=quality or None, quality_kind=kind if quality else None,
                                saturation=saturation or None)
        return masks

    def mask_changed(self, item):
        if item is not None and item.toolTip() != item.text():
            self.quality_masks.blockSignals(True)
            item.setToolTip(item.text())
            self.quality_masks.blockSignals(False)
        self.invalidate_diagnostic()

    def refresh_masks(self):
        """Keep each scene's explicit masks when its band selection changes."""
        previous = self.mask_parameters()
        scenes = {}
        for row in range(self.assets.rowCount()):
            name = self.assets.item(row, 1)
            asset = self.assets.item(row, 3)
            if name is None or asset is None or not name.text().strip():
                continue
            scene_id = name.text().strip()
            scenes.setdefault(scene_id, previous.get(scene_id, asset.data(Qt.ItemDataRole.UserRole)['scene']))
        self.quality_masks.blockSignals(True)
        self.quality_masks.setRowCount(0)
        for scene_id, metadata in scenes.items():
            row = self.quality_masks.rowCount()
            self.quality_masks.insertRow(row)
            label = QTableWidgetItem(scene_id)
            label.setToolTip(scene_id)
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.quality_masks.setItem(row, 0, label)
            self.quality_masks.setItem(row, 1, QTableWidgetItem(str(metadata.get('quality') or '')))
            self.quality_masks.item(row, 1).setToolTip(str(metadata.get('quality') or ''))
            choice = QComboBox()
            for text, kind in [("Choisir le type", None), ("Pixels non nuls valides", 'valid_mask'),
                               ("Landsat QA_PIXEL", 'landsat_qa'), ("Sentinel-2 SCL", 'sentinel_scl')]:
                choice.addItem(text, kind)
                choice.setItemData(choice.count() - 1, text, Qt.ItemDataRole.ToolTipRole)
            choice.setCurrentIndex(max(0, choice.findData(metadata.get('quality_kind'))))
            choice.setMinimumContentsLength(6)
            choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            choice.setToolTip(choice.currentText())
            choice.currentTextChanged.connect(choice.setToolTip)
            choice.currentIndexChanged.connect(self.invalidate_diagnostic)
            self.quality_masks.setCellWidget(row, 2, choice)
            self.quality_masks.setItem(row, 3, QTableWidgetItem(str(metadata.get('saturation') or '')))
            self.quality_masks.item(row, 3).setToolTip(str(metadata.get('saturation') or ''))
        self.quality_masks.blockSignals(False)

    def select_mask(self, column):
        row = self.quality_masks.currentRow()
        if row < 0 and self.quality_masks.rowCount() == 1:
            row = 0
        if row < 0:
            self.inventory.setText("Sélectionner une scène dans le tableau des masques.")
            return
        title = "Masque de qualité" if column == 1 else "Masque de saturation Landsat"
        path = QFileDialog.getOpenFileName(self, title, filter=RASTER_FILTER)[0]
        if path:
            self.quality_masks.item(row, column).setText(path)

    def refresh_options(self, *_):
        automatic = self.preparation_mode.currentData() == 'automatic'
        self.mosaic.setEnabled(not automatic)
        self.clip.setEnabled(not automatic)
        self.allow_partial.setEnabled(automatic)
        self.catalog_enabled.setEnabled(automatic)
        self.atmosphere.setEnabled(automatic)
        for control in self._catalog_fields:
            control.setEnabled(automatic and self.catalog_enabled.isChecked())
            control.setVisible(self.catalog_enabled.isChecked())
            self.form.labelForField(control).setVisible(self.catalog_enabled.isChecked())
        for control in (self.rgb_red, self.rgb_green, self.rgb_blue):
            control.setEnabled(self.colour.isChecked())
        if automatic:
            policy = ("Une couverture sous le seuil est explicitement acceptée et sera signalée."
                      if self.allow_partial.isChecked() else "Une couverture sous le seuil arrête la préparation et conserve le diagnostic.")
            self.summary.setText("À chaque lancement : contrôle des données, nouveau diagnostic, choix des scènes, mosaïque si nécessaire et découpage à la zone. " + policy +
                " Les produits scientifiques et la composition colorée restent distincts. Choisir un nouveau dossier de résultats.")
        else:
            self.summary.setText("Mode expert : " + ("scènes assemblées" if self.mosaic.isChecked() else "un dossier par scène") +
                ". Le seuil de couverture n’est pas imposé à la production. Le diagnostic reste disponible séparément. Les bandes scientifiques et la composition colorée sont enregistrées dans des fichiers distincts.")

    def restore_controls(self):
        for row in range(self.assets.rowCount()):
            self.assets.cellWidget(row, 0).toggled.connect(self.refresh_bands)
        for row in range(self.quality_masks.rowCount()):
            choice = self.quality_masks.cellWidget(row, 2)
            choice.currentIndexChanged.connect(self.invalidate_diagnostic)
            choice.setToolTip(choice.currentText())
            choice.currentTextChanged.connect(choice.setToolTip)
        self.refresh_options()
        self.invalidate_diagnostic()

    def invalidate_diagnostic(self, *_):
        """Do not reuse a recommendation after editing its source selection."""
        if not hasattr(self, 'coverage_summary'):
            return
        self._audit_generation = getattr(self, '_audit_generation', 0) + 1
        self._audit_report = None
        self.apply_audit_button.setEnabled(False)
        self.coverage_scenes.setRowCount(0)
        self.coverage_scenes.hide()
        self.coverage_summary.setText("Sélection ou paramètres modifiés : lancer le diagnostic de couverture pour cette configuration.")

    def diagnose_coverage(self):
        """Use the window's normal cancellable worker and result lifecycle."""
        window = self.window()
        if not hasattr(window, 'start') or not hasattr(window, 'thread'):
            self.coverage_summary.setText("Ouvrir cet outil dans la fenêtre Cartomize pour lancer le diagnostic.")
            return
        if window.thread is not None:
            return
        self._next_action = 'audit'
        try:
            window.start()
        finally:
            self._next_action = None

    def audit_job(self):
        if not self.assets.rowCount():
            raise ValueError("Analyser les bandes puis cocher les données à diagnostiquer.")
        scenes = self.selected_scenes()
        if not self.aoi.text():
            raise ValueError("Sélectionner la zone d’étude pour le diagnostic de couverture.")
        destination = self.result_destination()
        candidate = destination.with_name(destination.name + '_diagnostic')
        number = 2
        while candidate.exists():
            candidate = destination.with_name(destination.name + f'_diagnostic_{number:02d}')
            number += 1
        parameters = dict(aoi=self.aoi.text(), target_crs=self.crs.text().strip() or None,
                          resolution=self.resolution.value() or None,
                          resampling=self.resampling.currentData(), mask_clouds=self.clouds.isChecked(),
                          mask_saturation=self.saturation.isChecked(), allow_mixed_dates=self.dates.isChecked(),
                          coverage_threshold=self.coverage_threshold.value())
        self.invalidate_diagnostic()
        self._pending_audit_generation = self._audit_generation
        self.coverage_summary.setText("Diagnostic de couverture en cours. Les fichiers sont conservés dans un dossier de diagnostic distinct.")
        def run(progress, cancel, stage):
            from .imagery_audit import audit_imagery
            stage("Diagnostic des emprises, des données présentes et de la qualité")
            return audit_imagery(scenes, candidate, progress=progress, cancel=cancel, **parameters).manifest
        return run

    def show_result(self, path):
        path = Path(path)
        if path.suffix.lower() != '.json':
            return
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('schema') == 'cartomize.imagery.automatic.v1':
            self.show_automatic_result(path, record)
            return
        if record.get('schema') != 'cartomize.imagery.audit.v1':
            return
        if self._pending_audit_generation != self._audit_generation:
            self.invalidate_diagnostic()
            self.coverage_summary.setText("Le diagnostic terminé correspond à une configuration précédente. Son rapport reste disponible dans les résultats. Relancer le diagnostic pour la sélection actuelle.")
            self._pending_audit_generation = None
            return
        self._pending_audit_generation = None
        self._audit_report = record
        def percent(key):
            return f"{record.get(key, 0):.2f}".replace('.', ',')
        advice = {
            'single_scene': "Une scène atteint la couverture demandée ; la mosaïque n’est pas nécessaire pour ce seuil.",
            'mosaic': ("La combinaison des scènes atteint la couverture demandée ; la mosaïque sera réalisée automatiquement à l’exécution."
                       if self.preparation_mode.currentData() == 'automatic' else
                       "La combinaison des scènes atteint la couverture demandée ; une mosaïque est proposée."),
            'additional_scenes': "La couverture demandée n’est pas atteinte. Compléter les acquisitions pour les secteurs manquants.",
        }.get(record.get('recommended_action'), "Consulter le rapport de couverture.")
        missing = max(0, record.get('aoi_pixels', 0) - record.get('usable_pixels', 0))
        selected = ', '.join(record.get('recommended_scene_ids', [])) or 'Aucune scène utilisable'
        self.coverage_summary.setText(
            f"Emprises : {percent('footprint_percent')} % · Données présentes : {percent('present_percent')} % · "
            f"Pixels utilisables : {percent('usable_percent')} %.\n"
            f"Secteurs sans donnée utilisable : {missing} pixel(s) de la grille du diagnostic.\n"
            f"{advice}\nSélection proposée : {selected}.\n"
            "Les cartes de couverture et de lacunes ainsi que le rapport sont disponibles dans les résultats.")
        self.coverage_scenes.setRowCount(0)
        for scene in record.get('scenes', []):
            row = self.coverage_scenes.rowCount()
            self.coverage_scenes.insertRow(row)
            quality = scene.get('quality_statistics') or {}
            spectral = scene.get('spectral_cloud_statistics') or {}
            values = [str(scene['id'])] + [f"{scene.get(key, 0):.2f}".replace('.', ',')
                                          for key in ('footprint_percent', 'present_percent', 'usable_percent')]
            values.append(
                f"{quality['cloud_percent']:.2f}".replace('.', ',')
                if 'cloud_percent' in quality else '—'
            )
            values.append(
                f"{spectral['cloud_percent']:.2f}".replace('.', ',')
                if 'cloud_percent' in spectral else '—'
            )
            values.append(
                f"{quality['cloud_shadow_percent']:.2f}".replace('.', ',')
                if 'cloud_shadow_percent' in quality else '—'
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.coverage_scenes.setItem(row, column, item)
        self.coverage_scenes.setVisible(bool(record.get('scenes')))
        self.apply_audit_button.setEnabled(bool(record.get('recommended_scene_ids')))

    def show_automatic_result(self, path, record):
        current = self._pending_audit_generation == self._audit_generation
        audit_path = record.get('audit')
        if audit_path:
            self.show_result(audit_path)
        if not current:
            return
        partial = record.get('status') == 'partial'
        label = "Préparation terminée avec couverture partielle" if partial else "Préparation terminée : zone entièrement couverte"
        selected = ', '.join(record.get('selected_scene_ids', [])) or 'Consulter le rapport'
        coverage = (self._audit_report or {}).get('usable_percent', record.get('usable_percent', 0.))
        percentage = f'{coverage:.2f}'.replace('.', ',')
        threshold = f"{record.get('coverage_threshold', self.coverage_threshold.value()):.2f}".replace('.', ',')
        policy = ("Seuil demandé atteint." if record.get('threshold_met') else
                  "Résultat sous le seuil accepté explicitement ; les lacunes restent sans données.")
        decision = (f"Mosaïque automatique de {len(record.get('selected_scene_ids', []))} scènes."
                    if record.get('mosaic') else
                    "Une seule scène retenue ; aucune mosaïque nécessaire.")
        plan = record.get('preprocessing_plan') or {}
        plan_lines = []
        for scene in plan.get('scenes', []):
            statuses = []
            for level in scene.get('levels', []):
                number = level.get('level')
                status = str(level.get('status', '')).replace('_', ' ')
                if number:
                    statuses.append(f"N{number} {status}")
            if statuses:
                plan_lines.append(f"{scene.get('scene_id', 'Scène')} : " + " · ".join(statuses))
        plan_details = ("Plan automatique :\n" + "\n".join(plan_lines) + "\n") if plan_lines else ""
        recovery = record.get('recovery') or []
        recovered = [item for item in recovery if item.get('status') == 'recovered']
        recovery_details = ""
        if recovery:
            recovery_details = (
                f"Récupération automatique : {len(recovered)}/{len(recovery)} acquisition(s) résolue(s).\n"
            )
        grid = record.get('parameters', {})
        grid_details = ""
        if grid.get('crs') and grid.get('resolution_m') is not None:
            authority = rasterio.crs.CRS.from_user_input(grid['crs']).to_authority()
            crs_label = ':'.join(authority) if authority else 'projection personnalisée (voir le rapport)'
            grid_details = f"Grille commune : {crs_label} ; résolution {grid['resolution_m']:g} m.\n"
        self.coverage_summary.setText(f"{label}.\nCouverture utile : {percentage} % ; seuil : {threshold} %.\n"
                                      f"{policy}\n{decision}\n{recovery_details}{plan_details}{grid_details}"
                                      "Découpage à la zone d’étude réalisé.\n"
                                      f"Scènes retenues : {selected}.\n"
                                      "Diagnostic, plan N1–N5, cartes de lacunes et résultats disponibles dans le projet.")
        self.apply_audit_button.setEnabled(False)
        if partial:
            window = self.window()
            if hasattr(window, 'status'):
                window.status.setText("Traitement terminé avec couverture partielle : " + str(path))
                window.workspace.activity.setText("Traitement terminé avec couverture partielle.")

    @Slot(str)
    def show_rejected_coverage(self, path):
        """Keep the selected tool's coverage explanation after a rejected run."""
        self.show_result(path)

    def apply_audit_proposal(self):
        report = self._audit_report
        if not report:
            return
        recommended = set(report.get('recommended_scene_ids', []))
        for row in range(self.assets.rowCount()):
            checkbox = self.assets.cellWidget(row, 0)
            checkbox.blockSignals(True)
            checkbox.setChecked(checkbox.isChecked() and self.assets.item(row, 1).text().strip() in recommended)
            checkbox.blockSignals(False)
        self.mosaic.setChecked(len(recommended) > 1 and bool(report.get('mosaic_recommended', report.get('recommended_action') == 'mosaic')))
        self.refresh_bands()
        self.coverage_summary.setText("Sélection proposée appliquée. Les autres réglages sont conservés. Relancer le diagnostic pour vérifier la sélection actuelle, ou exécuter la préparation.")

    def result_destination(self):
        name = self.name.text().strip()
        if not name or name in {".", ".."} or any(c in name for c in '/\\:*?"<>|'):
            raise ValueError("Renseigner un nom de dossier de résultats sans séparateur de chemin.")
        if not self.output.text():
            raise ValueError("Sélectionner le répertoire de sortie.")
        return Path(self.output.text()) / name

    def selected_scenes(self):
        groups = {}
        masks = self.mask_parameters()
        for row in range(self.assets.rowCount()):
            if not self.assets.cellWidget(row, 0).isChecked():
                continue
            scene, name, path, index, scale, offset, date = [self.assets.item(row, col).text().strip() for col in range(1, 8)]
            raw = self.assets.item(row, 3).data(Qt.ItemDataRole.UserRole)
            metadata = {**raw["scene"], "scene_id": scene, "acquired": date or None}
            metadata.update(masks.get(scene, {}))
            if metadata.get('quality') and not metadata.get('quality_kind'):
                raise ValueError("Choisir le type du masque de qualité pour la scène : " + scene)
            group = groups.setdefault(scene, dict(metadata=metadata, bands={}))
            if group["metadata"] != metadata:
                raise ValueError("Métadonnées différentes pour une même scène : " + scene)
            if name in group["bands"]:
                raise ValueError(f"Bande dupliquée : {scene} / {name}. Corriger la scène ou le nom spectral.")
            group["bands"][name] = cm.Band(path, index=int(index), scale=float(scale), offset=float(offset),
                nodata=raw["nodata"], unit=raw["unit"])
        if not groups:
            raise ValueError("Cocher au moins une bande.")
        return [cm.Scene(bands=value["bands"], **value["metadata"]) for value in groups.values()]

    def catalog_parameters(self):
        if not self.catalog_enabled.isChecked():
            return None
        endpoint = self.catalog_endpoint.text().strip()
        if not endpoint:
            raise ValueError("Renseigner l’adresse du catalogue STAC pour rechercher des scènes.")
        collections = [value.strip() for value in self.catalog_collections.text().split(',') if value.strip()]
        return dict(endpoint=endpoint, collections=collections,
                    datetime_range=self.catalog_dates.text().strip() or None,
                    max_items=self.catalog_max_items.value(),
                    max_bytes=self.catalog_max_mb.value() * 1_000_000,
                    timeout=self.catalog_timeout.value())

    def job(self, options):
        if self._next_action == 'audit':
            return self.audit_job()
        automatic = self.preparation_mode.currentData() == 'automatic'
        catalog = self.catalog_parameters() if automatic else None
        if not self.assets.rowCount() and (self.files or self.source.text()):
            self.load_inputs()
        scenes = self.selected_scenes() if self.assets.rowCount() else []
        if not scenes and catalog is None:
            raise ValueError("Sélectionner les bandes ou le répertoire des scènes.")
        if automatic and not self.aoi.text():
            raise ValueError("Sélectionner la zone d’étude pour le prétraitement automatique.")
        if not automatic and self.clip.isChecked() and not self.aoi.text():
            raise ValueError("Charger la couche de délimitation pour l’extraction par masque.")
        band_order = None
        if catalog is not None:
            band_order = tuple(name.strip() for name in self.catalog_bands.text().split(',') if name.strip()) or None
            if not scenes and not band_order:
                raise ValueError("Renseigner les bandes à obtenir pour une recherche sans images locales (par exemple red,nir).")
            if not scenes and (not self.crs.text().strip() or not self.resolution.value()):
                raise ValueError("Renseigner le système projeté cible et la résolution pour une recherche sans images locales.")
        missing_masks = [scene.scene_id for scene in scenes if scene.quality is None]
        if self.clouds.isChecked() and missing_masks and not (automatic and catalog is not None):
            raise ValueError(
                "Associer un masque de qualité (quality mask QA/SCL) aux scènes : " + ', '.join(missing_masks)
                + ". Configurer un catalogue pour une récupération automatique, "
                  "ou désactiver explicitement le masque en mode expert."
            )
        rgb = tuple(control.currentData() for control in (self.rgb_red, self.rgb_green, self.rgb_blue)) if self.colour.isChecked() else None
        if rgb and None in rgb:
            raise ValueError("Affecter une bande à chacun des trois canaux rouge, vert et bleu.")
        destination = self.result_destination()
        kwargs = dict(aoi=self.aoi.text() if automatic or self.clip.isChecked() else None,
            multiband=self.multiband.isChecked(), separate_bands=self.separate.isChecked(), composition=rgb,
            target_crs=self.crs.text().strip() or None, resolution=self.resolution.value() or None,
            mask_clouds=self.clouds.isChecked(), mask_saturation=self.saturation.isChecked(),
            resampling=self.resampling.currentData(), overlap=self.overlap.currentData(),
            allow_mixed_dates=self.dates.isChecked())
        if not automatic:
            kwargs['mosaic'] = self.mosaic.isChecked()
            return lambda progress, cancel, stage: cm.process_imagery(scenes, destination,
                progress=progress, cancel=cancel, stage=stage, **kwargs).manifest
        kwargs.update(coverage_threshold=self.coverage_threshold.value(), allow_partial=self.allow_partial.isChecked(),
                      catalog=catalog, band_order=band_order,
                      atmospheric_method=self.atmosphere.currentData())
        self.invalidate_diagnostic()
        self._pending_audit_generation = self._audit_generation
        return lambda progress, cancel, stage: cm.preprocess_imagery(scenes, destination,
            progress=progress, cancel=cancel, stage=stage, **kwargs).manifest
