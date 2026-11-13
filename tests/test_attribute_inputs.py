import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout

from main import (
    SS_ATTR_SPIN,
    SS_DIALOG,
    SS_WIDGET,
    PlayerDetailDialog,
    _AttrSpinBox,
)


class AttributeInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def test_values_fit_inside_styled_inputs(self):
        dialog = QDialog()
        dialog.setStyleSheet(SS_WIDGET + SS_DIALOG + SS_ATTR_SPIN)
        layout = QVBoxLayout(dialog)
        for maximum, width in ((20, 34), (200, 52)):
            spin = _AttrSpinBox(0, maximum, maximum, width)
            if maximum == 20:
                PlayerDetailDialog._style_attr_spin(spin, maximum)
            else:
                spin.setObjectName("abilitySpin")
            layout.addWidget(spin)
        dialog.show()
        self.app.processEvents()
        try:
            for spin in dialog.findChildren(_AttrSpinBox):
                with self.subTest(maximum=spin.maximum()):
                    for value in (0, spin.maximum()):
                        spin.setValue(value)
                        edit = spin.lineEdit()
                        metrics = edit.fontMetrics()
                        self.assertGreaterEqual(
                            edit.contentsRect().width(),
                            metrics.horizontalAdvance(edit.text()) + 4,
                        )
                        self.assertGreaterEqual(
                            edit.contentsRect().height(), metrics.height()
                        )
        finally:
            dialog.close()
