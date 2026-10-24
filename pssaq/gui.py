"""PSSAQ user interface and 48 kHz audio streams."""
from __future__ import annotations
import datetime, queue, threading, wave, os, sys, subprocess, shutil, zipfile, tempfile
from pathlib import Path
from collections import deque
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from .dsp import SAQProcessor, MorseDecoder, spectrum, RATE, CARRIER, TUNE_MIN, TUNE_MAX
from .storage import folders, load_settings, save_settings, Recorder, Transcript, base_dir
from . import __version__
from .resources import asset_path, license_path
from .audio_feedback import output_chime
from .noise_reduction import MonitorNoiseReducer
from .theme import ReceiverBackground, ReceiverCheckBox, control_band, section_title
from .window_icon import application_icon
from .updater import validate_archive, prepare_update, launch_update
from .i18n import Language, LANGUAGES
from html import escape

try:
    import sounddevice as sd
    AUDIO_IMPORT_ERROR = ''
except (ImportError, OSError) as exc:
    sd = None
    AUDIO_IMPORT_ERROR = str(exc)

def widget_bindings(parent,exclude=()):
    """Capture static source strings once so language switches are reversible."""
    bindings=[]
    for obj in parent.findChildren(QtCore.QObject):
        if obj in exclude:continue
        if isinstance(obj,(QtWidgets.QLabel,QtWidgets.QAbstractButton,QtGui.QAction)):
            bindings.append((obj.setText,obj.text()))
        if isinstance(obj,QtWidgets.QWidget) and obj.toolTip():
            bindings.append((obj.setToolTip,obj.toolTip()))
        if isinstance(obj,QtWidgets.QComboBox):
            for index in range(obj.count()):
                bindings.append((lambda text,obj=obj,index=index:obj.setItemText(index,text),obj.itemText(index)))
    return bindings


def translate_widgets(parent,language):
    for setter,source in widget_bindings(parent):setter(language.text(source))


class Plot(QtWidgets.QWidget):
    frequencyChanged=QtCore.Signal(float)
    frequencyCommitted=QtCore.Signal(float)

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind=kind;self.carrier=CARRIER;self.bandwidth=220;self._dragging=False
        self.setMinimumHeight(140)
        self.data=np.array([]);self.freq=np.array([])
        if kind=='fft':
            self.setCursor(QtCore.Qt.SizeHorCursor)
            self.setFocusPolicy(QtCore.Qt.StrongFocus)

    def set_data(self, data, freq=None):
        self.data=np.asarray(data)
        if freq is not None:self.freq=np.asarray(freq)
        self.update()

    def frequency_x(self, frequency):
        return (frequency-TUNE_MIN)/(TUNE_MAX-TUNE_MIN)*max(1,self.width()-1)

    def set_frequency(self, frequency, notify=False):
        frequency=float(np.clip(round(frequency),TUNE_MIN,TUNE_MAX))
        if frequency==self.carrier:return
        self.carrier=frequency;self.update()
        if notify:self.frequencyChanged.emit(frequency)

    def _tune_at(self, x):
        self.set_frequency(TUNE_MIN+float(x)/max(1,self.width()-1)*(TUNE_MAX-TUNE_MIN),notify=True)

    def mousePressEvent(self, event):
        if self.kind=='fft' and event.button()==QtCore.Qt.LeftButton:
            self.setFocus(QtCore.Qt.MouseFocusReason);self._dragging=True
            self._tune_at(event.position().x());event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.kind=='fft' and self._dragging:
            self._tune_at(event.position().x());event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.kind=='fft' and event.button()==QtCore.Qt.LeftButton and self._dragging:
            self._tune_at(event.position().x());self._dragging=False
            self.frequencyCommitted.emit(self.carrier);event.accept();return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.kind=='fft' and event.button()==QtCore.Qt.LeftButton:
            self._dragging=False;self.set_frequency(CARRIER,notify=True)
            self.frequencyCommitted.emit(self.carrier);event.accept();return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if self.kind=='fft' and event.key() in (QtCore.Qt.Key_Left,QtCore.Qt.Key_Right,QtCore.Qt.Key_Home):
            step=10 if event.modifiers() & QtCore.Qt.ShiftModifier else 1
            if event.key()==QtCore.Qt.Key_Home:value=CARRIER
            else:value=self.carrier+(-step if event.key()==QtCore.Qt.Key_Left else step)
            self.set_frequency(value,notify=True);self.frequencyCommitted.emit(self.carrier)
            event.accept();return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p=QtGui.QPainter(self);p.setRenderHint(QtGui.QPainter.Antialiasing,False)
        r=self.rect();p.fillRect(r,QtGui.QColor('#0e1e2d'))
        if self.kind=='fft':
            left=self.frequency_x(self.carrier-self.bandwidth/2)
            right=self.frequency_x(self.carrier+self.bandwidth/2)
            p.fillRect(QtCore.QRectF(left,0,right-left,r.height()),QtGui.QColor(86,200,219,24))
        p.setPen(QtGui.QColor('#354a5c'))
        for i in range(1,5):
            y=r.height()*i/5;p.drawLine(0,int(y),r.width(),int(y))
        for i in range(1,9):
            x=r.width()*i/9;p.drawLine(int(x),0,int(x),r.height())
        if len(self.data)>=2:
            values=self.data
            if self.kind=='fft':
                select=(self.freq>=TUNE_MIN)&(self.freq<=TUNE_MAX) if len(self.freq)==len(values) else np.zeros(len(values),dtype=bool)
                values=np.clip((values[select]+120)/120,0,1)
                freqs=self.freq[select] if len(self.freq)==len(select) else np.array([])
            else:
                values=np.clip(values/max(float(np.max(values)),1e-6),0,1)
            if len(values)>=2:
                ix=np.linspace(0,len(values)-1,min(r.width(),len(values)),dtype=int)
                xs=[self.frequency_x(freqs[k]) for k in ix] if self.kind=='fft' else np.linspace(0,r.width()-1,len(ix))
                pts=[QtCore.QPointF(float(x),float((1-values[k])*(r.height()-12)+6)) for x,k in zip(xs,ix)]
                p.setPen(QtGui.QPen(QtGui.QColor('#56c8db' if self.kind=='wave' else '#7aacfa'),1.3))
                p.drawPolyline(QtGui.QPolygonF(pts))
        # Draw the tuning marker even before any audio arrives, above the trace.
        if self.kind=='fft':
            x=self.frequency_x(self.carrier)
            p.setPen(QtGui.QPen(QtGui.QColor('#e7b456'),1.5,QtCore.Qt.DashLine))
            p.drawLine(QtCore.QPointF(x,0),QtCore.QPointF(x,r.height()))
            text=f'{self.carrier/1000:.3f} kHz'
            text_width=p.fontMetrics().horizontalAdvance(text)+10
            label_x=max(0,min(x+7,r.width()-text_width))
            p.fillRect(QtCore.QRectF(label_x,3,text_width,19),QtGui.QColor('#172b3d'))
            p.setPen(QtGui.QColor('#f4c66c'));p.drawText(QtCore.QPointF(label_x+5,17),text)
            if self.hasFocus():
                p.setPen(QtGui.QPen(QtGui.QColor('#65cfe3'),1,QtCore.Qt.DotLine))
                p.drawRect(r.adjusted(1,1,-2,-2))

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.i18n=parent.i18n if parent is not None else Language(code=cfg.get('language','ja'))
        self.setWindowTitle(self.i18n.text('Audio IN / OUT 設定'));self.resize(560,280)
        layout=QtWidgets.QFormLayout(self)
        self.inputs=QtWidgets.QComboBox();self.outputs=QtWidgets.QComboBox()
        self.inputs.addItem('入力デバイスなし',None);self.outputs.addItem('出力デバイスなし',None)
        if sd:
            hostapis=sd.query_hostapis()
            for n,d in enumerate(sd.query_devices()):
                api=hostapis[d['hostapi']]['name']
                label=f'{n}: {d["name"]} [{api}]'
                if d['max_input_channels']>0:self.inputs.addItem(label,n)
                if d['max_output_channels']>0:self.outputs.addItem(label,n)
        for combo,key in ((self.inputs,'input'),(self.outputs,'output')):
            idx=combo.findData(cfg.get(key));combo.setCurrentIndex(max(0,idx))
        self.channel=QtWidgets.QComboBox();self.channel.addItems(['1 (モノラル/左)','2 (右)']);self.channel.setCurrentIndex(int(cfg.get('channel',0)))
        self.tone=QtWidgets.QSpinBox();self.tone.setRange(400,1000);self.tone.setSingleStep(50);self.tone.setSuffix(' Hz');self.tone.setValue(cfg.get('tone',700))
        layout.addRow('Audio IN:',self.inputs);layout.addRow('入力チャンネル:',self.channel)
        layout.addRow('Audio OUT:',self.outputs);layout.addRow('CWトーン:',self.tone)
        layout.addRow('録音/処理サンプルレート:',QtWidgets.QLabel('48,000 Hz（固定）'))
        bb=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept);bb.rejected.connect(self.reject);layout.addRow(bb)
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText('キャンセル')
        translate_widgets(self,self.i18n)
    def values(self):
        return {'input':self.inputs.currentData(),'output':self.outputs.currentData(),'channel':self.channel.currentIndex(),'tone':self.tone.value()}

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, root=None, auto_start=True):
        super().__init__();self.setWindowTitle(f'PSSAQ {__version__} — SAQ 17.200 kHz Receiver');self.resize(1120,800)
        self.setWindowIcon(application_icon())
        self.root=folders(root);self.cfg=load_settings(self.root)
        if not self.cfg.get('mute_default_off_applied',False):
            self.cfg.update(mute=False,mute_default_off_applied=True)
            save_settings(self.cfg,self.root)
        self.i18n=Language(self.root,self.cfg.get('language','ja'))
        self._status_key='準備中';self._status_values={};self._last_db=None;self._clipped=False
        self.q=queue.Queue(maxsize=200)
        self.outq=queue.Queue(maxsize=100)
        self.testq=queue.Queue(maxsize=1)
        self._test_left=np.array([],dtype=np.float32)
        self._chime=output_chime()
        width=self.cfg.get('bandwidth',220)
        if width not in (50,100,220,500,1000):width=220
        self.proc=SAQProcessor(tone=self.cfg.get('tone',700),bandwidth=width/2)
        try:self.proc.set_carrier(self.cfg.get('carrier',CARRIER))
        except (ValueError,TypeError,OverflowError):self.proc.set_carrier(CARRIER)
        self.cfg['carrier']=self.proc.carrier
        self.nr_proc=MonitorNoiseReducer(self.cfg.get('nr',0))
        self.decoder=MorseDecoder();self.transcript=Transcript(self.root);self.recorder=None
        self.input_stream=None;self.output_stream=None;self.live=False
        self.samples=deque(maxlen=8192);self.envelopes=deque(maxlen=8000)
        self.last_audio=np.zeros(1024,dtype=np.float32);self.dropped=0
        self.muted_out=self.cfg.get('mute',False);self.out_gain=self.cfg.get('volume',50)/100
        self.preview_timer=QtCore.QTimer(self);self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(160);self.preview_timer.timeout.connect(self.play_output_test)
        self._build()
        self.language_menu=QtWidgets.QMenu('Language',self)
        self.menuBar().insertMenu(self.help_menu.menuAction(),self.language_menu)
        self.language_group=QtGui.QActionGroup(self)
        self.language_group.setExclusive(True)
        self.language_actions={}
        for code,name in LANGUAGES.items():
            action=self.language_menu.addAction(name);action.setCheckable(True)
            action.setData(code);self.language_group.addAction(action)
            action.triggered.connect(lambda checked=False,code=code:self.change_language(code))
            self.language_actions[code]=action
        self._bindings=widget_bindings(self,exclude={self.status,self.level,self.rec,self.gaintext,self.speedtext,self.volume_text,self.frequency_label,self.wave_title})
        self.retranslate()
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)
        if auto_start:QtCore.QTimer.singleShot(150,self.start_audio)

    def _build(self):
        fm=self.menuBar().addMenu('ファイル')
        fm.addAction('録音ファイルを開く',self.open_wav)
        fm.addAction('recdataフォルダーを開く',lambda:self.open_dir(self.root/'recdata'))
        fm.addSeparator();fm.addAction('終了',self.close)
        sm=self.menuBar().addMenu('設定');sm.addAction('Audio IN / Audio OUT 設定',self.audio_settings)
        hm=self.menuBar().addMenu('ヘルプ');self.help_menu=hm;hm.addAction('バージョンアップ（ZIP指定）',self.update_zip);hm.addSeparator();hm.addAction('PSSAQについて',self.about)
        central=ReceiverBackground();self.setCentralWidget(central)
        outer=QtWidgets.QVBoxLayout(central);outer.setContentsMargins(14,12,14,12);outer.setSpacing(10)
        top=QtWidgets.QHBoxLayout();outer.addWidget(control_band(top,hero=True))
        self.frequency_label=QtWidgets.QLabel();self.frequency_label.setStyleSheet('font-size:19px;font-weight:bold');top.addWidget(self.frequency_label)
        top.addStretch();self.status=QtWidgets.QLabel('準備中');top.addWidget(self.status)
        body=QtWidgets.QHBoxLayout();outer.addLayout(body,1)
        v=QtWidgets.QVBoxLayout();v.setSpacing(7);body.addLayout(v,1)
        central.art_gap=QtWidgets.QSpacerItem(240,0,QtWidgets.QSizePolicy.Fixed,QtWidgets.QSizePolicy.Minimum)
        central.art_layout=body;body.addItem(central.art_gap)
        self.wave_title=section_title('');v.addWidget(self.wave_title)
        self.wave=Plot('wave');v.addWidget(self.wave,1)
        v.addWidget(section_title('FFTスペクトラム 16.5–17.9 kHz'))
        self.fft=Plot('fft');self.fft.bandwidth=self.proc.bandwidth*2
        self.fft.set_frequency(self.proc.carrier)
        self.fft.setToolTip('クリック／ドラッグで受信周波数を変更。左右キーで1 Hz、Shift併用で10 Hz。ダブルクリック／Homeで17.200 kHzに戻します。')
        self.fft.frequencyChanged.connect(self.tune_frequency)
        self.fft.frequencyCommitted.connect(self.save_frequency)
        v.addWidget(self.fft,1)
        h=QtWidgets.QHBoxLayout();v.addWidget(control_band(h))
        h.addWidget(QtWidgets.QLabel('入力調整（DSP）'))
        self.gain=QtWidgets.QSlider(QtCore.Qt.Horizontal);self.gain.setRange(0,200);self.gain.setValue(self.cfg.get('gain',100));h.addWidget(self.gain)
        self.gaintext=QtWidgets.QLabel('100%');h.addWidget(self.gaintext)
        self.level=QtWidgets.QLabel('入力 −∞ dBFS');h.addWidget(self.level)
        h2=QtWidgets.QHBoxLayout();v.addWidget(control_band(h2))
        self.auto=ReceiverCheckBox('CW速度 自動調整');self.auto.setChecked(self.cfg.get('auto',True));h2.addWidget(self.auto)
        self.speed=QtWidgets.QSlider(QtCore.Qt.Horizontal);self.speed.setRange(5,40);self.speed.setValue(self.cfg.get('wpm',12));h2.addWidget(self.speed)
        self.speedtext=QtWidgets.QLabel(f'{self.speed.value()} WPM');h2.addWidget(self.speedtext)
        self.auto.toggled.connect(lambda on:self.speed.setEnabled(not on));self.speed.setEnabled(not self.auto.isChecked())
        self.speed.valueChanged.connect(lambda n:self.speedtext.setText(f'{n} WPM'))
        v.addWidget(section_title('CWデコード（推定・誤判定あり）'))
        self.decoded=QtWidgets.QPlainTextEdit();self.decoded.setReadOnly(True);self.decoded.setMaximumBlockCount(4000);v.addWidget(self.decoded,1)
        bottom=QtWidgets.QHBoxLayout();v.addWidget(control_band(bottom))
        self.mute=ReceiverCheckBox('Audio OUT ミュート');self.mute.setChecked(self.cfg.get('mute',False));bottom.addWidget(self.mute)
        self.mute.setToolTip('受信モニター音を消音します。出力確認音はミュート中も鳴ります。')
        bottom.addWidget(QtWidgets.QLabel('OUT音量'))
        self.volume=QtWidgets.QSlider(QtCore.Qt.Horizontal);self.volume.setRange(0,100);self.volume.setValue(self.cfg.get('volume',50));bottom.addWidget(self.volume)
        self.volume.setToolTip('音量を変更すると、選択したAudio OUTから確認音が鳴ります。')
        self.volume_text=QtWidgets.QLabel(f'{self.volume.value()}%');bottom.addWidget(self.volume_text)
        self.mute.toggled.connect(lambda value:setattr(self,'muted_out',value))
        self.volume.valueChanged.connect(self.output_volume_changed)
        self.volume.sliderReleased.connect(self.play_output_test)
        self.output_test=QtWidgets.QPushButton('出力テスト');self.output_test.clicked.connect(self.play_output_test);bottom.addWidget(self.output_test)
        self.rec=QtWidgets.QPushButton('● REC');self.rec.clicked.connect(self.toggle_record);bottom.addWidget(self.rec)
        self.realtime=QtWidgets.QPushButton('音声再接続');self.realtime.clicked.connect(self.start_audio);bottom.addWidget(self.realtime)
        self.gain.valueChanged.connect(lambda n:self.gaintext.setText(f'{n}%'))
        self.gaintext.setText(f'{self.gain.value()}%')

        filters=QtWidgets.QHBoxLayout();v.addWidget(control_band(filters))
        filters.addWidget(QtWidgets.QLabel('受信フィルター'));filters.addStretch()
        filters.addWidget(QtWidgets.QLabel('BW'))
        self.bandwidth=QtWidgets.QComboBox()
        for width in (50,100,220,500,1000):self.bandwidth.addItem(f'{width} Hz',width)
        self.bandwidth.setCurrentIndex(self.bandwidth.findData(int(self.proc.bandwidth*2)))
        self.bandwidth.setToolTip('選択した受信周波数を中心とする帯域幅（全幅）。受信音とデコードに適用します。')
        filters.addWidget(self.bandwidth)
        filters.addSpacing(12);filters.addWidget(QtWidgets.QLabel('NR'))
        self.nr=QtWidgets.QComboBox()
        self.nr.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        for level,label in enumerate(('OFF','弱','中','強')):self.nr.addItem(label,level)
        self.nr.setCurrentIndex(self.nr_proc.level)
        self.nr.setToolTip('簡易ノイズ低減（モニター音のみ）。弱い信号ではOFFとも聞き比べてください。録音は原音を保存します。')
        filters.addWidget(self.nr)
        self.bandwidth.currentIndexChanged.connect(self.filters_changed)
        self.nr.currentIndexChanged.connect(self.filters_changed)

    def refresh_tuning_labels(self):
        frequency=self.proc.carrier/1000
        self.setWindowTitle(f'PSSAQ {__version__} — SAQ {frequency:.3f} kHz Receiver')
        self.frequency_label.setText(f'{frequency:.3f} kHz  /  CW  /  48 kHz PCM')
        self.wave_title.setText(self.tr_text('{frequency:.3f} kHz 包絡線 / 時間変化',frequency=frequency))

    def tune_frequency(self,frequency):
        previous=self.proc.carrier;self.proc.set_carrier(frequency)
        self.cfg['carrier']=self.proc.carrier
        self.fft.set_frequency(self.proc.carrier)
        self.refresh_tuning_labels()
        if previous!=self.proc.carrier:
            self.decoder.reset();self.nr_proc.reset()
            self.envelopes.clear();self.wave.set_data([])
            while True:
                try:self.outq.get_nowait()
                except queue.Empty:break

    def save_frequency(self,frequency):
        self.tune_frequency(frequency)
        save_settings(self.cfg,self.root)

    def filters_changed(self):
        width=self.bandwidth.currentData();level=self.nr.currentData()
        if width != self.proc.bandwidth*2:
            self.proc.set_bandwidth(width)
            self.decoder.reset()
            self.nr_proc.reset()
        self.nr_proc.set_level(level)
        self.fft.bandwidth=width;self.fft.update()
        self.cfg.update(bandwidth=width,nr=level)
        save_settings(self.cfg,self.root)

    def tr_text(self,source,**values):
        return self.i18n.text(source,**values)

    def set_status(self,source,**values):
        self._status_key=source;self._status_values=values
        self.status.setText(self.tr_text(source,**values))

    def refresh_level(self):
        if self._last_db is None:
            self.level.setText(self.tr_text('入力 −∞ dBFS'))
        else:
            self.level.setText(self.tr_text('入力 {db:.1f} dBFS',db=self._last_db)+('  CLIP!' if self._clipped else ''))

    def retranslate(self):
        for setter,source in self._bindings:setter(self.tr_text(source))
        self.set_status(self._status_key,**self._status_values)
        self.refresh_level()
        self.refresh_tuning_labels()
        self.rec.setText('■ STOP' if self.recorder else '● REC')
        for code,action in self.language_actions.items():action.setChecked(code==self.i18n.code)
        self.statusBar().clearMessage()

    def change_language(self,code):
        self.i18n.select(code);self.cfg['language']=self.i18n.code
        self.retranslate()
        save_settings(self.cfg,self.root)

    def warning(self,title,text):
        box=QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning,self.tr_text(title),text,
                                 QtWidgets.QMessageBox.Ok,self)
        box.exec()

    def question(self,title,text):
        box=QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question,self.tr_text(title),self.tr_text(text),
                                 QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No,self)
        box.button(QtWidgets.QMessageBox.Yes).setText(self.tr_text('はい'))
        box.button(QtWidgets.QMessageBox.No).setText(self.tr_text('いいえ'))
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        return box.exec()

    def input_cb(self,indata,frames,time_info,status):
        if status:self.dropped+=1
        try:self.q.put_nowait(indata[:,min(self.cfg.get('channel',0),indata.shape[1]-1)].copy())
        except queue.Full:self.dropped+=1

    def output_cb(self,outdata,frames,time_info,status):
        result=np.zeros(frames,dtype=np.float32)
        i=0
        while i<frames:
            if not hasattr(self,'outleft') or not len(self.outleft):
                try:self.outleft=self.outq.get_nowait()
                except queue.Empty:break
            take=min(frames-i,len(self.outleft))
            result[i:i+take]=self.outleft[:take]
            self.outleft=self.outleft[take:]
            i+=take
        if self.muted_out:result[:]=0
        else:result*=self.out_gain
        # The check sound uses this exact device/stream and volume. It bypasses
        # RX mute and replaces RX briefly; it never enters the recording queue.
        try:self._test_left=self.testq.get_nowait()
        except queue.Empty:pass
        take=min(frames,len(self._test_left))
        if take:
            result[:take]=self._test_left[:take]*self.out_gain
            self._test_left=self._test_left[take:]
        outdata[:]=result[:,None]

    def output_volume_changed(self,value):
        self.out_gain=value/100
        self.volume_text.setText(f'{value}%')
        self.preview_timer.start()

    def _ensure_output(self):
        if self.cfg.get('output') is None:
            raise RuntimeError(self.tr_text('Audio OUTが未選択です。設定からスピーカーを選んでください。'))
        if sd is None:
            raise RuntimeError(self.tr_text('Audioライブラリを読み込めません: ')+AUDIO_IMPORT_ERROR)
        if self.output_stream is not None and self.output_stream.active:return
        if self.output_stream is not None:
            self.output_stream.close();self.output_stream=None
        info=sd.query_devices(self.cfg['output'],'output')
        channels=min(2,int(info['max_output_channels']))
        if channels<1:raise RuntimeError(self.tr_text('選択したデバイスに音声出力がありません。'))
        stream=sd.OutputStream(device=self.cfg['output'],samplerate=RATE,channels=channels,
                               blocksize=2048,dtype='float32',callback=self.output_cb)
        try:stream.start()
        except Exception:
            stream.close();raise
        self.output_stream=stream

    def play_output_test(self):
        self.preview_timer.stop()
        if self.volume.value()==0:
            self.statusBar().showMessage(self.tr_text('OUT音量 0%（消音）'),4000);return
        try:
            self._ensure_output()
        except Exception as exc:
            self.statusBar().showMessage(self.tr_text('出力テスト不可: ')+str(exc),10000);return
        while True:
            try:self.testq.get_nowait()
            except queue.Empty:break
        self.testq.put_nowait(self._chime)
        self.statusBar().showMessage(self.tr_text('出力確認音 / OUT {volume}%（受信ミュート中も鳴ります）',volume=self.volume.value()),3000)

    def stop_audio(self):
        self.preview_timer.stop()
        self.nr_proc.reset()
        for stream in (self.input_stream,self.output_stream):
            if stream:
                try:stream.stop();stream.close()
                except Exception:pass
        self.input_stream=self.output_stream=None;self.live=False
        self.outleft=np.array([],dtype=np.float32)
        self._test_left=np.array([],dtype=np.float32)
        while not self.testq.empty():
            try:self.testq.get_nowait()
            except queue.Empty:break
        while not self.outq.empty():
            try:self.outq.get_nowait()
            except queue.Empty:break

    def start_audio(self):
        self.stop_audio()
        if not sd:
            self.set_status('Audioライブラリを読み込めません')
            self.status.setToolTip(AUDIO_IMPORT_ERROR);return
        try:
            inp=self.cfg.get('input')
            if inp is None:
                # Prefer the OS default recording device.
                inp=sd.default.device[0]
            if inp is None or inp < 0:raise RuntimeError(self.tr_text('音声入力デバイスを設定してください'))
            channels=max(1,self.cfg.get('channel',0)+1)
            self.input_stream=sd.InputStream(device=inp,samplerate=RATE,channels=channels,blocksize=2048,dtype='float32',callback=self.input_cb)
            self.input_stream.start();self.live=True
            if self.cfg.get('output') is not None:
                self._ensure_output()
            self.set_status('RX / 48 kHz')
        except Exception as exc:
            self.stop_audio();self.set_status('Audio接続エラー')
            self.warning('Audioデバイス',str(exc)+self.tr_text('\n設定からデバイスを選び直してください。'))

    def tick(self):
        drained=0;emitted=''
        while drained<32:
            try:block=self.q.get_nowait()
            except queue.Empty:break
            drained+=1
            if self.recorder:self.recorder.write(block)  # pre-gain, unmodified capture
            self.samples.extend(block)
            raw,env,monitor=self.proc.process(block,self.gain.value()/100)
            self.envelopes.extend(env[::24])
            part=self.decoder.feed(env, len(env)/RATE)
            if part:emitted+=part
            try:self.outq.put_nowait(self.nr_proc.process(monitor))
            except queue.Full:
                try:self.outq.get_nowait()
                except queue.Empty:pass
            mx=max(np.max(np.abs(block)),1e-10)
            db=20*np.log10(mx)
            self._last_db=float(db);self._clipped=mx>.98
            self.refresh_level()
        if emitted:
            self.decoded.moveCursor(QtGui.QTextCursor.End)
            self.decoded.insertPlainText(emitted)
            self.transcript.append(emitted)
        self.decoder.settings(self.speed.value(),self.auto.isChecked())
        self.proc.set_tone(self.cfg.get('tone',700))
        if self.envelopes:self.wave.set_data(np.asarray(self.envelopes))
        if len(self.samples)>512:
            f,d=spectrum(np.asarray(self.samples),RATE)
            self.fft.set_data(d,f)
        if self.dropped:
            self.set_status('RX / audio overrun {count}',count=self.dropped)

    def toggle_record(self):
        if self.recorder:
            self.recorder.close();self.recorder=None;self.rec.setText('● REC')
        else:
            try:self.recorder=Recorder(self.root);self.rec.setText('■ STOP')
            except OSError as e:self.warning('録音',str(e))

    def audio_settings(self):
        try:dlg=SettingsDialog(self.cfg,self)
        except Exception as e:self.warning('デバイス一覧',str(e));return
        if dlg.exec()==QtWidgets.QDialog.Accepted:
            self.cfg.update(dlg.values());self.proc.set_tone(self.cfg.get('tone',700));save_settings(self.cfg,self.root);self.start_audio()

    def open_wav(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,self.tr_text('WAV読み込み'),str(self.root/'recdata'),'WAV (*.wav)')
        if not path:return
        try:
            with wave.open(path,'rb') as w:
                channels=w.getnchannels();rate=w.getframerate();width=w.getsampwidth()
                if width!=2 or rate!=RATE:raise ValueError(self.tr_text('48 kHz / 16 bit PCM WAVに対応しています'))
                data=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').reshape(-1,channels)[:,0].astype(np.float32)/32768
            # Offline replay in chunks, with decoder reset and saved separately into daily master file.
            d=SAQProcessor(carrier=self.proc.carrier,tone=self.cfg.get('tone',700),bandwidth=self.bandwidth.currentData()/2);m=MorseDecoder(self.speed.value(),self.auto.isChecked())
            decoded=[]
            for i in range(0,len(data),2048):
                part=data[i:i+2048];_,env,_=d.process(part,self.gain.value()/100)
                s=m.feed(env,len(part)/RATE)
                if s:decoded.append(s)
            text=''.join(decoded)
            heading=self.tr_text('[WAV再解析: {name}]',name=Path(path).name)
            self.decoded.appendPlainText('\n'+heading+'\n'+text+'\n')
            self.transcript.append('\n'+heading+'\n'+text+'\n')
        except Exception as e:self.warning('WAV読み込み',str(e))

    def open_dir(self,path):
        if os.name=='nt':os.startfile(str(path))
        elif sys.platform=='darwin':subprocess.Popen(['open',str(path)])
        else:subprocess.Popen(['xdg-open',str(path)])

    def update_zip(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,self.tr_text('更新ZIPを選択'),str(self.root),'ZIP (*.zip)')
        if not path:return
        try:
            if not getattr(sys,'frozen',False) or os.name!='nt':
                raise ValueError(self.tr_text('ZIPによるEXE更新はビルド済みWindows版のみ対応です。'))
            with zipfile.ZipFile(path) as z:
                validate_archive(z)
            if self.question('バージョンアップ',
                    '録音を終了してアプリを閉じ、更新用ウィンドウで新EXEの起動を検査します。\n'
                    '検査後にEXEを更新して再起動します。\n続けますか？')!=QtWidgets.QMessageBox.Yes:return
            manifest=prepare_update(path,sys.executable)
            launch_update(manifest)
            self.close()
        except Exception as e:self.warning('バージョンアップ',self.tr_text(str(e)))

    def about(self):
        html=f'''<p align="center"><img src="pssaq-icon" width="72" height="72"></p><h2>PSSAQ — SAQ 17.2 kHz Receiver</h2><p>Version {__version__}</p>
<p>{escape(self.tr_text('PSSAQは、H. Tanaka（JH1HST）が個人的に、世界遺産のヴァールベリ無線局（SAQ）の超長波17.2 kHzの電波（モールス）を受信することに挑戦する際に、作成したソフトウェアです。'))}</p>
<h3>{escape(self.tr_text('世界遺産のヴァールベリ無線局（SAQ）について'))}</h3>
<p>{escape(self.tr_text('スウェーデン・グリメトンのヴァールベリ無線局は、1920年代に建設された長波無線通信施設で、アレキサンダーソン式高周波発電機と巨大なアンテナ施設が保存されています。2004年にユネスコ世界遺産へ登録され、記念送信では17.2 kHzのモールス信号を発信します。'))}</p>
<p><a href="https://grimeton.org/">https://grimeton.org/</a><br><a href="https://alexander.n.se/">https://alexander.n.se/</a></p>
<h3>{escape(self.tr_text('SAQのイラストについて'))}</h3>
<p>{escape(self.tr_text('ARRLの掲載の写真をイラストにしたものです。'))}</p>
<h3>{escape(self.tr_text('著作権'))}</h3><p>Copyright © 2026 H. Tanaka (JH1HST)<br>PS Ham-ware / Akihabara-Giken JS1YJY</p>
<h3>{escape(self.tr_text('ライセンス'))}</h3>
<p>{escape(self.tr_text('本ソフトウェアには PS Ham-ware / AKIHABARA-GIKEN 共通ライセンスを適用します。利用条件は「共通ライセンス全文」または同梱の LICENSE.md をご確認ください。第三者ライブラリには、それぞれのライセンスが適用されます。'))}</p>
<p>{escape(self.tr_text('Python (PSF), PySide6/Qt (LGPLなど), NumPy (BSD-3-Clause), SciPy (BSD-3-Clause), sounddevice (MIT), PyInstaller (GPL＋例外) を使用します。実際の配布時はバンドルしたバージョンの正式なライセンス本文・通知を同梱してください。'))}</p>
<p>{escape(self.tr_text('非公式の個人製作ソフトウェアです。SAQ施設・関連団体とは提携していません。'))}</p>'''
        d=QtWidgets.QDialog(self);d.setWindowTitle(self.tr_text('PSSAQについて'));d.resize(580,540)
        lay=QtWidgets.QVBoxLayout(d);browser=QtWidgets.QTextBrowser();browser.setOpenExternalLinks(True)
        browser.document().addResource(QtGui.QTextDocument.ImageResource,QtCore.QUrl('pssaq-icon'),
                                       QtGui.QImage(str(asset_path('pssaq.png'))))
        browser.setHtml(html);lay.addWidget(browser)
        buttons=QtWidgets.QHBoxLayout();lay.addLayout(buttons)
        license_button=QtWidgets.QPushButton(self.tr_text('共通ライセンス全文'))
        license_button.clicked.connect(lambda:self.show_license(d));buttons.addWidget(license_button)
        buttons.addStretch()
        b=QtWidgets.QPushButton(self.tr_text('閉じる'));b.clicked.connect(d.accept);buttons.addWidget(b);d.exec()

    def show_license(self,parent=None):
        dialog=QtWidgets.QDialog(parent or self)
        dialog.setWindowTitle('PS Ham-ware / AKIHABARA-GIKEN License');dialog.resize(700,600)
        layout=QtWidgets.QVBoxLayout(dialog);browser=QtWidgets.QTextBrowser()
        browser.setMarkdown(license_path().read_text(encoding='utf-8-sig'));layout.addWidget(browser)
        close=QtWidgets.QPushButton(self.tr_text('閉じる'));close.clicked.connect(dialog.accept)
        layout.addWidget(close);dialog.exec()

    def closeEvent(self,event):
        if hasattr(self,'taskbar_identity'):self.taskbar_identity.close()
        self.stop_audio()
        if self.recorder:self.recorder.close()
        self.cfg.update(gain=self.gain.value(),volume=self.volume.value(),mute=self.mute.isChecked(),auto=self.auto.isChecked(),wpm=self.speed.value())
        save_settings(self.cfg,self.root)
        event.accept()
