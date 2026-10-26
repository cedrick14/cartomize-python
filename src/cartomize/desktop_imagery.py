"""Scene/band selection and optional multispectral production in Qt."""
from dataclasses import asdict
import json
from pathlib import Path

import rasterio
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog, QWidget, QHBoxLayout, QVBoxLayout)

import cartomize as cm
from .desktop import Page, PathField, RASTER_FILTER, VECTOR_FILTER, spin, real


class PreparationPage(Page):
    engine = False
    staged = True

    def __init__(self):
        super().__init__("Prétraitement multispectral",
            "Sélection des scènes et des bandes, mosaïque, assemblage multibande, extraction par masque et composition colorée.")
        self.files = []
        self.source = PathField("directory")
        self.mode = QComboBox()
        self.mode.addItem("Landsat, Sentinel-2 ou manifeste de scènes", "auto")
        self.mode.addItem("Bandes personnalisées : correspondance manuelle", "manual")
        self.form.addRow("Identification des bandes", self.mode)
        self.form.addRow("Répertoire des scènes", self.source)
        select = QPushButton("Sélectionner les bandes…")
        clear = QPushButton("Utiliser le répertoire")
        select.clicked.connect(self.select_files)
        clear.clicked.connect(self.clear_files)
        selection_controls=QWidget();selection_row=QHBoxLayout(selection_controls);selection_row.setContentsMargins(0,0,0,0)
        selection_row.addWidget(select);selection_row.addWidget(clear);self.form.addRow(selection_controls)
        inspect = QPushButton("Analyser les bandes")
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
        note = QLabel("Cocher les bandes à traiter. En mode personnalisé, renseigner le même identifiant de scène pour les bandes d’une acquisition et le même nom spectral entre scènes (red, green, blue, nir…). Vérifier les facteurs de calibration.")
        note.setWordWrap(True)
        self.form.addRow(note)
        self.aoi = PathField(filter=VECTOR_FILTER)
        self.form.addRow("Couche de délimitation", self.aoi)
        self.coverage_threshold = real(100.)
        self.coverage_threshold.setRange(.01, 100.)
        self.coverage_threshold.setDecimals(2)
        self.form.addRow("Couverture utile minimale (%)", self.coverage_threshold)
        self.audit_button = QPushButton("Diagnostiquer la couverture")
        self.audit_button.clicked.connect(self.diagnose_coverage)
        self.apply_audit_button = QPushButton("Appliquer la sélection proposée")
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
        self.coverage_scenes = QTableWidget(0, 4)
        self.coverage_scenes.setHorizontalHeaderLabels(["Scène", "Emprise (%)", "Données (%)", "Utilisable (%)"])
        self.coverage_scenes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.coverage_scenes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.coverage_scenes.setMaximumHeight(165)
        self.coverage_scenes.hide()
        self.form.addRow(self.coverage_scenes)
        self._audit_report = None
        self._next_action = None
        self._audit_generation = 0
        self._pending_audit_generation = None
        self.mosaic = QCheckBox("Mosaïque des scènes")
        self.mosaic.setChecked(True)
        self.multiband = QCheckBox("Assemblage multibande")
        self.multiband.setToolTip('Conserver le GeoTIFF scientifique multibande.')
        self.multiband.setChecked(True)
        self.clip = QCheckBox("Extraction par masque")
        self.colour = QCheckBox("Composition colorée")
        self.colour.setToolTip('Enregistrer la visualisation dans un GeoTIFF séparé des valeurs scientifiques.')
        self.separate = QCheckBox("Extraction des bandes")
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
        self.resolution.setSpecialValueText("Résolution native la plus grossière")
        self.resampling = QComboBox()
        for label,value in [('Plus proche voisin','nearest'),('Bilinéaire','bilinear'),('Cubique','cubic'),('Moyenne','average')]:self.resampling.addItem(label,value)
        self.overlap = QComboBox()
        self.overlap.addItem('Première scène valide','first');self.overlap.addItem('Dernière scène valide','last')
        self.saturation = QCheckBox('Appliquer le masque de saturation disponible');self.saturation.setChecked(True)
        self.clouds = QCheckBox("Appliquer les masques QA/SCL")
        self.clouds.setChecked(True)
        self.dates = QCheckBox("Autoriser les dates différentes ou inconnues")
        self.dates.setToolTip("Autoriser une mosaïque multitemporelle ou des scènes dont la date d’acquisition est inconnue.")
        for label, control in [("Système de coordonnées cible", self.crs), ("Résolution (m)", self.resolution),
                               ("Rééchantillonnage spectral", self.resampling), ("Recouvrement des scènes", self.overlap), ("Saturation", self.saturation), ("Masque de qualité", self.clouds), ("Dates d’acquisition", self.dates)]:
            self.form.addRow(label, control)
        self.output = PathField("directory")
        self.name = QLineEdit("pretraitement")
        self.form.addRow("Répertoire de sortie", self.output)
        self.form.addRow("Nouveau dossier de résultats", self.name)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.form.addRow(self.summary)
        self.layout.addStretch()
        self.assets.itemChanged.connect(self.refresh_bands)
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
        self.assets.setRowCount(0)
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
                        name = src.descriptions[index - 1] or (path.stem if src.count == 1 else f"band_{index}")
                        # Temporary unique keys; duplicates remain visible for manual correction.
                        bands[f"asset_{len(bands)}"] = (name, cm.Band(str(path.resolve()), index=index,
                            scale=src.scales[index - 1], offset=src.offsets[index - 1], unit=src.units[index - 1] or "source units"))
            if not bands:
                raise ValueError("Aucune bande raster trouvée.")
            scenes = [cm.Scene("scene_1", {key: band for key, (_, band) in bands.items()}, sensor="custom")]
            self.clouds.setChecked(False)
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
        names = list(dict.fromkeys(self.assets.item(row, 2).text().strip() for row in range(self.assets.rowCount())
            if self.assets.item(row, 2) and self.assets.cellWidget(row, 0) and self.assets.cellWidget(row, 0).isChecked()))
        for control, default in [(self.rgb_red, "red"), (self.rgb_green, "green"), (self.rgb_blue, "blue")]:
            previous = control.currentData() or default
            control.clear()
            control.addItem("Sélectionner une bande", None)
            for name in names:
                control.addItem(name, name)
            index = control.findData(previous)
            control.setCurrentIndex(max(0, index))

    def refresh_options(self, *_):
        for control in (self.rgb_red, self.rgb_green, self.rgb_blue):
            control.setEnabled(self.colour.isChecked())
        self.summary.setText("Sortie : " + ("scènes assemblées" if self.mosaic.isChecked() else "un dossier par scène") +
            ". Les bandes scientifiques et la composition colorée sont enregistrées dans des fichiers distincts. Le dossier de résultats doit être nouveau.")

    def restore_controls(self):
        for row in range(self.assets.rowCount()):
            self.assets.cellWidget(row, 0).toggled.connect(self.refresh_bands)
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
            'mosaic': "La combinaison des scènes atteint la couverture demandée ; une mosaïque est proposée.",
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
            values = [str(scene['id'])] + [f"{scene.get(key, 0):.2f}".replace('.', ',')
                                          for key in ('footprint_percent', 'present_percent', 'usable_percent')]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.coverage_scenes.setItem(row, column, item)
        self.coverage_scenes.setVisible(bool(record.get('scenes')))
        self.apply_audit_button.setEnabled(bool(record.get('recommended_scene_ids')))

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
        for row in range(self.assets.rowCount()):
            if not self.assets.cellWidget(row, 0).isChecked():
                continue
            scene, name, path, index, scale, offset, date = [self.assets.item(row, col).text().strip() for col in range(1, 8)]
            raw = self.assets.item(row, 3).data(Qt.ItemDataRole.UserRole)
            metadata = {**raw["scene"], "scene_id": scene, "acquired": date or None}
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

    def job(self, options):
        if self._next_action == 'audit':
            return self.audit_job()
        if not self.assets.rowCount():
            self.load_inputs()
        scenes = self.selected_scenes()
        if self.clip.isChecked() and not self.aoi.text():
            raise ValueError("Charger la couche de délimitation pour l’extraction par masque.")
        rgb = tuple(control.currentData() for control in (self.rgb_red, self.rgb_green, self.rgb_blue)) if self.colour.isChecked() else None
        if rgb and None in rgb:
            raise ValueError("Affecter une bande à chacun des trois canaux rouge, vert et bleu.")
        destination = self.result_destination()
        kwargs = dict(aoi=self.aoi.text() if self.clip.isChecked() else None, mosaic=self.mosaic.isChecked(),
            multiband=self.multiband.isChecked(), separate_bands=self.separate.isChecked(), composition=rgb,
            target_crs=self.crs.text().strip() or None, resolution=self.resolution.value() or None,
            mask_clouds=self.clouds.isChecked(), mask_saturation=self.saturation.isChecked(), resampling=self.resampling.currentData(), overlap=self.overlap.currentData(), allow_mixed_dates=self.dates.isChecked())
        return lambda progress, cancel, stage: cm.process_imagery(scenes, destination,
            progress=progress, cancel=cancel, stage=stage, **kwargs).manifest
