import ctypes
import subprocess
import sys
import winreg
from ctypes.wintypes import DWORD, LONG, POINT, RECT, UINT
from pathlib import Path

from PyQt6.QtCore import QLockFile, QPointF, QRectF, QSettings, QStandardPaths, QTime, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QSpinBox, QStyle, QStyleOptionSpinBox, QSystemTrayIcon, QTimeEdit, QVBoxLayout, QWidget,
)


RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'MouseActivityHelper'
user32 = ctypes.windll.user32
MIN_DISTANCE = 10
MAX_DISTANCE = 50
DEFAULT_DISTANCE = 20
INPUT_MOUSE = 0
MOUSE_MOVE = 0x0001
MOUSE_NO_COALESCE = 0x2000
MOUSE_VIRTUAL_DESKTOP = 0x4000
MOUSE_ABSOLUTE = 0x8000
VIRTUAL_LEFT, VIRTUAL_TOP, VIRTUAL_WIDTH, VIRTUAL_HEIGHT = 76, 77, 78, 79


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', LONG), ('dy', LONG), ('mouseData', DWORD), ('dwFlags', DWORD),
                ('time', DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class Input(ctypes.Structure):
    # MouseInput is the largest arm of the Win32 INPUT union.
    _fields_ = [('type', DWORD), ('mouse', MouseInput)]


user32.MonitorFromPoint.argtypes = [POINT, DWORD]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.SendInput.argtypes = [UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = UINT


def move_cursor(distance):
    origin = POINT()
    clip = RECT()
    if not user32.GetCursorPos(ctypes.byref(origin)) or not user32.GetClipCursor(ctypes.byref(clip)):
        return

    monitor = user32.MonitorFromPoint(origin, 0)
    if not monitor:
        return
    for x in (origin.x + distance, origin.x - distance):
        if clip.left <= x < clip.right and user32.MonitorFromPoint(POINT(x, origin.y), 0) == monitor:
            break
    else:
        return

    left = user32.GetSystemMetrics(VIRTUAL_LEFT)
    top = user32.GetSystemMetrics(VIRTUAL_TOP)
    width = user32.GetSystemMetrics(VIRTUAL_WIDTH)
    height = user32.GetSystemMetrics(VIRTUAL_HEIGHT)
    if width <= 0 or height <= 0:
        return

    flags = MOUSE_MOVE | MOUSE_NO_COALESCE | MOUSE_VIRTUAL_DESKTOP | MOUSE_ABSOLUTE
    y = ((origin.y - top) * 65536 + 32768) // height
    events = (Input * 2)()
    for index, target_x in enumerate((x, origin.x)):
        normalized_x = ((target_x - left) * 65536 + 32768) // width
        events[index] = Input(INPUT_MOUSE, MouseInput(normalized_x, y, 0, flags, 0, 0))
    if user32.SendInput(len(events), events, ctypes.sizeof(Input)) == 1:
        user32.SetCursorPos(origin.x, origin.y)


STYLESHEET = '''
QWidget#mainWindow { background: #101622; }
QLabel { color: #EEF3FA; }
QLabel#heading { font-size: 24pt; font-weight: 700; }
QLabel#sectionTitle { font-size: 12pt; font-weight: 650; }
QLabel#fieldLabel { font-weight: 550; }
QLabel#hint, QLabel#statusOff { color: #AEBBD0; }
QLabel#statusOn { color: #76EDCC; }
QFrame#panel { background: #1A2333; border: 1px solid #2C3A50; border-radius: 16px; }
QFrame#startupPanel { background: #142C31; border: 1px solid #356760; border-radius: 16px; }
QFrame#rule { background: #2C3A50; border: 0; }
QSpinBox, QTimeEdit {
    background: #101824;
    color: #EEF3FA;
    border: 1px solid #475872;
    border-radius: 8px;
    padding: 1px 9px;
    selection-background-color: #76EDCC;
    selection-color: #102421;
}
QSpinBox:focus, QTimeEdit:focus { border-color: #76EDCC; }
QTimeEdit:disabled { background: #17202F; color: #AEBBD0; border-color: #35445A; }
QSpinBox::up-button, QTimeEdit::up-button, QSpinBox::down-button, QTimeEdit::down-button {
    width: 24px;
    border-left: 1px solid #475872;
    background: #253347;
}
QSpinBox::up-button, QTimeEdit::up-button { border-top-right-radius: 7px; }
QSpinBox::down-button, QTimeEdit::down-button { border-bottom-right-radius: 7px; }
QSpinBox::up-button:hover, QTimeEdit::up-button:hover,
QSpinBox::down-button:hover, QTimeEdit::down-button:hover { background: #344B63; }
QTimeEdit::up-button:disabled, QTimeEdit::down-button:disabled { background: #222F41; }
QSpinBox::up-arrow, QTimeEdit::up-arrow, QSpinBox::down-arrow, QTimeEdit::down-arrow { image: none; }
QMenu { background: #1A2333; color: #EEF3FA; border: 1px solid #475872; padding: 4px; }
QMenu::item { padding: 6px 18px; }
QMenu::item:selected { background: #2B4953; }
'''


class Toggle(QCheckBox):
    def __init__(self, name):
        super().__init__()
        self.setAccessibleName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(50, 34)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked()
        if self.hasFocus():
            painter.setPen(QPen(QColor('#9BF5DE'), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(1.5, 2, 47, 30), 15, 15)

        painter.setPen(QPen(QColor('#76EDCC' if checked else '#75869F'), 1))
        track = '#76EDCC' if checked else '#33465D'
        if self.underMouse():
            track = '#9BF5DE' if checked else '#435971'
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(QRectF(4, 5, 42, 24), 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#123732' if checked else '#E6EDF7'))
        painter.drawEllipse(QRectF(25 if checked else 8, 8.5, 17, 17))
        painter.end()


class SpinArrows:
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#D4E5F5' if self.isEnabled() else '#8393AC'))
        for control, direction in ((QStyle.SubControl.SC_SpinBoxUp, -1), (QStyle.SubControl.SC_SpinBoxDown, 1)):
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, control, self)
            x, y = QRectF(rect).center().x(), QRectF(rect).center().y()
            painter.drawPolygon(QPolygonF([QPointF(x - 4, y - direction * 2),
                                           QPointF(x + 4, y - direction * 2),
                                           QPointF(x, y + direction * 3)]))
        painter.end()


class IntervalEdit(SpinArrows, QSpinBox):
    pass


class StartTimeEdit(SpinArrows, QTimeEdit):
    pass


def app_icon():
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#76EDCC'))
    painter.drawRoundedRect(QRectF(0, 0, 128, 128), 31, 31)
    pen = QPen(QColor('#16353A'), 7, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(43, 30, 42, 68), 21, 21)
    painter.drawLine(64, 42, 64, 53)
    painter.drawLine(24, 66, 31, 66)
    painter.drawLine(97, 66, 104, 66)
    painter.end()
    return QIcon(pixmap)


def label(text, style=''):
    widget = QLabel(text)
    widget.setObjectName(style)
    return widget


def panel(style='panel'):
    widget = QFrame()
    widget.setObjectName(style)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(17, 14, 17, 14)
    layout.setSpacing(9)
    return widget, layout


def panel_row(title, control, description=None):
    row = QHBoxLayout()
    row.setSpacing(14)
    title_label = label(title, 'sectionTitle' if description else 'fieldLabel')
    title_label.setBuddy(control)
    if description:
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(title_label)
        detail = label(description, 'hint')
        detail.setWordWrap(True)
        text.addWidget(detail)
        row.addLayout(text, 1)
    else:
        row.addWidget(title_label, 1)
    row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('MouseActivityHelper', 'MouseActivityHelper')
        self.setWindowTitle('Активность мыши')
        self.setObjectName('mainWindow')
        self.setMinimumWidth(455)
        self.setFont(QFont('Segoe UI', 10))
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor('#101622'))
        palette.setColor(QPalette.ColorRole.Base, QColor('#101824'))
        palette.setColor(QPalette.ColorRole.Button, QColor('#26364A'))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            palette.setColor(role, QColor('#EEF3FA'))
        self.setPalette(palette)
        self.setStyleSheet(STYLESHEET)
        icon = app_icon()
        self.setWindowIcon(icon)

        self.interval = IntervalEdit()
        self.interval.setRange(1, 1440)
        self.interval.setSuffix(' мин')
        self.interval.setValue(self.settings.value('interval', 15, type=int))
        self.interval.setFixedSize(112, 34)
        self.interval.setAccessibleName('Интервал движения мыши')
        self.distance = IntervalEdit()
        self.distance.setRange(MIN_DISTANCE, MAX_DISTANCE)
        self.distance.setSuffix(' пикс.')
        self.distance.setValue(self.settings.value('distance', DEFAULT_DISTANCE, type=int))
        self.distance.setFixedSize(112, 34)
        self.distance.setAccessibleName('Сдвиг курсора в пикселях')
        self.scheduled = Toggle('Ждать заданного времени при запуске')
        self.scheduled.setChecked(self.settings.value('scheduled', False, type=bool))
        self.start_time = StartTimeEdit(QTime.fromString(self.settings.value('start', '09:00'), 'HH:mm'))
        self.start_time.setDisplayFormat('HH:mm')
        self.start_time.setFixedSize(112, 34)
        self.start_time.setAccessibleName('Время начала')
        self.active = Toggle('Двигать мышь по таймеру')
        self.active.setChecked(self.settings.value('active', False, type=bool))
        self.autostart = Toggle('Автозапуск Windows')
        self.status = label('', 'statusOff')
        self.build_layout(icon)
        self.setTabOrder(self.active, self.distance)
        self.setTabOrder(self.distance, self.interval)
        self.setTabOrder(self.interval, self.scheduled)
        self.setTabOrder(self.scheduled, self.start_time)
        self.setTabOrder(self.start_time, self.autostart)
        self.resize(475, self.sizeHint().height())

        dark_title = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        try:
            set_attribute = dwm.DwmSetWindowAttribute
            set_attribute.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
            set_attribute(int(self.winId()), 20, ctypes.byref(dark_title), ctypes.sizeof(dark_title))
        except AttributeError:
            pass

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('Активность мыши')
        self.menu = QMenu(self)
        self.menu.addAction('Открыть', self.open_window)
        self.menu.addAction('Приостановить / возобновить', self.active.toggle)
        self.menu.addAction('Выход', QApplication.instance().quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.move_mouse)
        self.interval.valueChanged.connect(self.reschedule)
        self.distance.valueChanged.connect(lambda value: self.settings.setValue('distance', value))
        self.scheduled.toggled.connect(self.reschedule)
        self.start_time.timeChanged.connect(self.reschedule)
        self.active.toggled.connect(self.reschedule)
        self.autostart.setChecked(self.autostart_enabled())
        self.autostart.toggled.connect(self.set_autostart)
        self.reschedule()

    def build_layout(self, icon):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 23, 24, 19)
        layout.setSpacing(13)

        header = QHBoxLayout()
        header.setSpacing(15)
        mark = QLabel()
        mark.setPixmap(icon.pixmap(52, 52))
        header.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        heading.addWidget(label('Активность мыши', 'heading'))
        heading.addWidget(self.status)
        header.addLayout(heading, 1)
        layout.addLayout(header)
        layout.addSpacing(3)

        movement, controls = panel()
        controls.addLayout(panel_row('Движение по таймеру', self.active, 'Сдвигает курсор и возвращает его на место'))
        controls.addLayout(panel_row('Сдвиг курсора', self.distance, f'От {MIN_DISTANCE} до {MAX_DISTANCE} пикселей'))
        layout.addWidget(movement)

        schedule, controls = panel()
        controls.addWidget(label('Расписание', 'sectionTitle'))
        controls.addLayout(panel_row('Интервал', self.interval))
        rule = QFrame()
        rule.setObjectName('rule')
        rule.setFixedHeight(1)
        controls.addWidget(rule)
        controls.addLayout(panel_row('Ждать заданного времени', self.scheduled))
        controls.addLayout(panel_row('Время начала', self.start_time))
        layout.addWidget(schedule)

        startup, controls = panel('startupPanel')
        controls.addLayout(panel_row('Автозапуск Windows', self.autostart, 'Запускает приложение в трее при входе в систему'))
        layout.addWidget(startup)

        footer = label('Закрытие окна сворачивает приложение в трей.', 'hint')
        footer.setWordWrap(True)
        layout.addSpacing(2)
        layout.addWidget(footer)
        layout.addStretch()

    def startup_command(self):
        args = [str(Path(sys.executable).resolve())]
        if not getattr(sys, 'frozen', False):
            args.append(str(Path(__file__).resolve()))
        args.append('--tray')
        return subprocess.list2cmdline(args)

    def autostart_enabled(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return bool(winreg.QueryValueEx(key, RUN_NAME)[0])
        except OSError:
            return False

    def set_autostart(self, enabled):
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, self.startup_command())
                elif self.autostart_enabled():
                    winreg.DeleteValue(key, RUN_NAME)
        except OSError as error:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(self.autostart_enabled())
            self.autostart.blockSignals(False)
            QMessageBox.warning(self, 'Автозапуск', f'Не удалось изменить автозапуск.\n{error}')

    def reschedule(self):
        self.timer.stop()
        self.start_time.setEnabled(self.scheduled.isChecked())
        self.settings.setValue('interval', self.interval.value())
        self.settings.setValue('scheduled', self.scheduled.isChecked())
        self.settings.setValue('start', self.start_time.time().toString('HH:mm'))
        self.settings.setValue('active', self.active.isChecked())
        if not self.active.isChecked():
            self.update_status('Таймер выключен', active=False)
            return
        delay = self.interval.value() * 60_000
        if self.scheduled.isChecked():
            now = QTime.currentTime()
            if now < self.start_time.time():
                delay = now.msecsTo(self.start_time.time())
        self.arm_timer(delay)

    def arm_timer(self, delay):
        self.timer.start(delay)
        next_time = QTime.currentTime().addMSecs(delay).toString('HH:mm:ss')
        self.update_status(f'Следующее движение в {next_time}', active=True)

    def update_status(self, text, *, active):
        self.status.setObjectName('statusOn' if active else 'statusOff')
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)

    def move_mouse(self):
        move_cursor(self.distance.value())
        self.arm_timer(self.interval.value() * 60_000)

    def open_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_window()

    def closeEvent(self, event):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            QApplication.instance().quit()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    temp_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation))
    lock = QLockFile(str(temp_dir / 'MouseActivityHelper.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        if '--tray' not in sys.argv:
            QMessageBox.information(None, 'Активность мыши', 'Программа уже запущена. Откройте её из трея.')
        return 0
    try:
        window = Window()
        if '--tray' not in sys.argv or not QSystemTrayIcon.isSystemTrayAvailable():
            window.show()
        return app.exec()
    finally:
        lock.unlock()


if __name__ == '__main__':
    sys.exit(main())
