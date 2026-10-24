"""SAQ sunset artwork behind the receiver, with opaque data displays."""
from PySide6 import QtCore, QtGui, QtWidgets
from .resources import asset_path


class ReceiverCheckBox(QtWidgets.QCheckBox):
    """Native checkbox interaction with an always-visible square indicator."""
    def paintEvent(self, event):
        super().paintEvent(event)
        option=QtWidgets.QStyleOptionButton();self.initStyleOption(option)
        rect=self.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator,option,self)
        painter=QtGui.QPainter(self);painter.setRenderHint(QtGui.QPainter.Antialiasing)
        border='#65cfe3' if self.hasFocus() else '#99abbc'
        painter.setPen(QtGui.QPen(QtGui.QColor(border),1.5))
        painter.setBrush(QtGui.QColor('#ffffff' if self.isEnabled() else '#dce2e8'))
        box=QtCore.QRectF(rect).adjusted(.8,.8,-.8,-.8)
        painter.drawRoundedRect(box,1.5,1.5)
        if self.isChecked():
            painter.setPen(QtGui.QPen(QtGui.QColor('#162d43' if self.isEnabled() else '#83909c'),
                                     2.5,QtCore.Qt.SolidLine,QtCore.Qt.RoundCap,QtCore.Qt.RoundJoin))
            x,y,w,h=box.x(),box.y(),box.width(),box.height()
            painter.drawPolyline(QtGui.QPolygonF([
                QtCore.QPointF(x+w*.20,y+h*.51),QtCore.QPointF(x+w*.43,y+h*.75),
                QtCore.QPointF(x+w*.82,y+h*.27)]))


class ReceiverBackground(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.artwork=QtGui.QPixmap(str(asset_path('saq_sunset.png')))
        self._scaled=QtGui.QPixmap()
        self.art_layout=None
        self.art_gap=None
        self.setStyleSheet('''
            QLabel, QCheckBox { color: #fff5e5; background: transparent; }
            QCheckBox { spacing: 7px; min-height: 24px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            QFrame#controlBand, QFrame#heroBand {
                background-color: rgba(8, 22, 41, 184);
                border: 1px solid rgba(216, 218, 228, 64);
                border-radius: 5px;
            }
            QLabel#sectionTitle {
                background-color: rgba(8, 22, 41, 190);
                padding: 3px 7px;
                border-radius: 3px;
            }
            QPlainTextEdit {
                background-color: #ffffff; color: #17232e;
                border: 1px solid #8ba0b3; border-radius: 2px;
                selection-background-color: #c0d7f0;
            }
            QPushButton {
                color: #142637; background-color: #f4f0e8;
                border: 1px solid #8ba0b3; border-radius: 4px;
                padding: 5px 9px;
            }
            QPushButton:hover { background-color: #fff8e8; border-color: #edbc78; }
            QPushButton:pressed { background-color: #d8dbe2; }
        ''')

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not self.artwork.isNull():
            self._scaled=self.artwork.scaled(self.size(),QtCore.Qt.KeepAspectRatioByExpanding,
                                             QtCore.Qt.SmoothTransformation)
        if self.art_gap is not None:
            # Keep the data column usable on smaller screens. A larger window
            # reveals the tallest antenna beside the opaque plots and decoder.
            width=min(260,max(0,self.width()-880))
            self.art_gap.changeSize(width,0,QtWidgets.QSizePolicy.Fixed,QtWidgets.QSizePolicy.Minimum)
            self.art_layout.invalidate()

    def paintEvent(self,event):
        painter=QtGui.QPainter(self)
        painter.fillRect(self.rect(),QtGui.QColor('#142b48'))
        if not self._scaled.isNull():
            x=(self.width()-self._scaled.width())//2
            y=(self.height()-self._scaled.height())//2
            painter.drawPixmap(x,y,self._scaled)
            painter.fillRect(self.rect(),QtGui.QColor(5,14,30,38))


def control_band(layout, hero=False):
    frame=QtWidgets.QFrame()
    frame.setObjectName('heroBand' if hero else 'controlBand')
    layout.setContentsMargins(10,7,10,7)
    frame.setLayout(layout)
    if hero:frame.setMinimumHeight(72)
    return frame


def section_title(text):
    label=QtWidgets.QLabel(text)
    label.setObjectName('sectionTitle')
    return label
