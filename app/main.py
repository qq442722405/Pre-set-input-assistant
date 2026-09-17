import sys, os, json, time, ctypes
from ctypes import wintypes
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QSystemTrayIcon, QMenu, QCheckBox, QDialog, QListWidget,
    QListWidgetItem, QMessageBox, QFileDialog, QGroupBox
)

APP_NAME = '预置输入助手'
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG = os.path.join(BASE_DIR, 'config.json')
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'PresetInputAssistant'

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]
class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG), ('right', wintypes.LONG), ('bottom', wintypes.LONG)]

def get_cursor():
    p = POINT(); user32.GetCursorPos(ctypes.byref(p)); return p.x, p.y

def get_foreground():
    return user32.GetForegroundWindow()

def set_foreground(hwnd):
    if hwnd:
        try:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

def get_process_info(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name, path = '未知程序', ''
    h = kernel32.OpenProcess(0x1000 | 0x0400, False, pid.value)
    if h:
        try:
            buf = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                path = buf.value
                name = os.path.basename(path) or name
        finally:
            kernel32.CloseHandle(h)
    return pid.value, name, path

def enum_windows():
    arr = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            arr.append((hwnd, cls.value))
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    return arr

def find_context_menu():
    for hwnd, cls in enum_windows():
        if cls == '#32768':
            r = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                if r.right-r.left > 20 and r.bottom-r.top > 10:
                    return hwnd, (r.left, r.top, r.right, r.bottom)
    return None, None

def paste_text(text, target_hwnd):
    if not text:
        return
    try:
        import pyperclip
        old = None
        try: old = pyperclip.paste()
        except Exception: pass
        pyperclip.copy(text)
        set_foreground(target_hwnd)
        time.sleep(0.10)
        user32.keybd_event(0x11, 0, 0, 0)
        user32.keybd_event(0x56, 0, 0, 0)
        user32.keybd_event(0x56, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)
        if old is not None:
            time.sleep(0.08)
            pyperclip.copy(old)
    except Exception as e:
        print('paste error:', e)


def get_startup_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return bool(value)
    except Exception:
        return False

def set_startup(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            exe = os.path.abspath(sys.executable)
            # 打包后 sys.executable 是 exe；开发运行时则用 pythonw + main.py
            if os.path.basename(exe).lower() in ('python.exe', 'pythonw.exe'):
                script = os.path.abspath(__file__)
                pythonw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
                value = f'"{pythonw}" "{script}"'
            else:
                value = f'"{exe}"'
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, value)
        else:
            try: winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError: pass

class Bridge(QObject):
    right_clicked = Signal(int, int, int, str, str)

class InputPanel(QWidget):
    chosen = Signal(str)
    def __init__(self):
        super().__init__()
        self.items = []
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet('''
            QWidget { background:#0f0f0f; color:#ffffff; border:1px solid #666666; border-radius:7px; }
            QLabel { border:none; color:#ffffff; font-weight:bold; padding:3px 7px; }
            QPushButton { background:#202020; color:#ffffff; border:1px solid #555555; border-radius:5px; padding:8px 13px; text-align:left; }
            QPushButton:hover { background:#353535; border:1px solid #aaaaaa; }
        ''')
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(7,7,7,7); self.layout.setSpacing(5)
        self.rebuild()
    def rebuild(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.layout.addWidget(QLabel('预置输入'))
        for text in self.items:
            b = QPushButton(text); b.setToolTip(text)
            b.clicked.connect(lambda checked=False, s=text: self.chosen.emit(s))
            self.layout.addWidget(b)
        self.adjustSize()

class SettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.current_key = None
        self.setWindowTitle(APP_NAME + ' - 设置')
        self.resize(760, 600)
        self.setStyleSheet('''
            QDialog, QWidget { background:#202020; color:#ffffff; }
            QLabel { color:#ffffff; }
            QLineEdit, QListWidget { background:#111111; color:#ffffff; border:1px solid #555555; padding:6px; }
            QPushButton { background:#303030; color:#ffffff; border:1px solid #555555; border-radius:4px; padding:7px 12px; }
            QPushButton:hover { background:#414141; }
            QCheckBox { color:#ffffff; spacing:7px; }
            QGroupBox { color:#ffffff; border:1px solid #555555; margin-top:10px; padding-top:10px; }
            QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
        ''')
        root = QVBoxLayout(self)

        startup_box = QGroupBox('开机启动')
        sb = QHBoxLayout(startup_box)
        self.startup = QCheckBox('Windows 开机自动启动预置输入助手')
        self.startup.setChecked(get_startup_enabled())
        sb.addWidget(self.startup); sb.addStretch()
        root.addWidget(startup_box)

        root.addWidget(QLabel('选择程序：为不同程序分别设置独立的右键预输入。新程序默认关闭。'))
        select_row = QHBoxLayout()
        self.program_list = QListWidget(); self.program_list.setMinimumHeight(115)
        select_row.addWidget(self.program_list, 1)
        btn_col = QVBoxLayout()
        choose = QPushButton('选择程序')
        choose.clicked.connect(self.choose_program)
        delete_program = QPushButton('删除程序')
        delete_program.clicked.connect(self.remove_program)
        btn_col.addWidget(choose); btn_col.addWidget(delete_program); btn_col.addStretch()
        select_row.addLayout(btn_col)
        root.addLayout(select_row)

        self.detail = QGroupBox('右键预设输入选项')
        detail = QVBoxLayout(self.detail)
        self.enable = QCheckBox('启用此程序的右键预设输入（默认关闭）')
        self.enable.stateChanged.connect(self.changed_enable)
        detail.addWidget(self.enable)
        self.path_label = QLabel('请选择一个程序')
        detail.addWidget(self.path_label)

        detail.addWidget(QLabel('右键预设输入内容（每行一条）：'))
        self.editor = QListWidget()
        self.editor.setSpacing(2)
        detail.addWidget(self.editor, 1)

        add_row = QHBoxLayout()
        self.newtext = QLineEdit(); self.newtext.setPlaceholderText('输入新的预设内容，例如：12345+ -')
        add = QPushButton('添加')
        add.clicked.connect(self.add_item)
        add_row.addWidget(self.newtext, 1); add_row.addWidget(add)
        detail.addLayout(add_row)

        root.addWidget(self.detail, 1)

        foot = QHBoxLayout(); foot.addStretch()
        save = QPushButton('保存退出'); save.clicked.connect(self.save_and_close)
        foot.addWidget(save)
        root.addLayout(foot)

        self.program_list.currentRowChanged.connect(self.select_program)
        self.refresh()

    def refresh(self):
        self.program_list.blockSignals(True)
        self.program_list.clear()
        for key, data in self.owner.programs.items():
            name = data.get('name') or os.path.basename(key) or key
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, key)
            self.program_list.addItem(item)
        self.program_list.blockSignals(False)
        if self.program_list.count():
            self.program_list.setCurrentRow(0)
        else:
            self.clear_detail()

    def clear_detail(self):
        self.current_key = None
        self.path_label.setText('请选择一个程序')
        self.enable.blockSignals(True); self.enable.setChecked(False); self.enable.blockSignals(False)
        self.editor.clear()

    def select_program(self, row):
        if row < 0:
            self.clear_detail(); return
        key = self.program_list.item(row).data(Qt.UserRole)
        data = self.owner.programs.get(key, {})
        self.current_key = key
        self.path_label.setText(key)
        self.enable.blockSignals(True)
        self.enable.setChecked(bool(data.get('enabled', False)))
        self.enable.blockSignals(False)
        self.editor.clear()
        self.editor.addItems(data.get('items', []))

    def choose_program(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择程序 EXE', '', 'Windows 程序 (*.exe)')
        if not path: return
        path = os.path.normcase(os.path.abspath(path))
        name = os.path.basename(path)
        if path not in self.owner.programs:
            self.owner.programs[path] = {'name': name, 'enabled': False, 'items': []}
        self.owner.save()
        self.refresh()
        for i in range(self.program_list.count()):
            if self.program_list.item(i).data(Qt.UserRole) == path:
                self.program_list.setCurrentRow(i); break

    def remove_program(self):
        if not self.current_key: return
        name = self.owner.programs.get(self.current_key, {}).get('name', self.current_key)
        if QMessageBox.question(self, '确认删除', f'确定删除“{name}”的独立预输入设置吗？') == QMessageBox.Yes:
            self.owner.programs.pop(self.current_key, None)
            self.owner.save(); self.refresh()

    def changed_enable(self):
        if self.current_key in self.owner.programs:
            self.owner.programs[self.current_key]['enabled'] = self.enable.isChecked()

    def add_item(self):
        if not self.current_key: return
        text = self.newtext.text()
        if not text.strip(): return
        items = self.owner.programs[self.current_key].setdefault('items', [])
        items.append(text)
        self.newtext.clear(); self.refresh_editor()

    def refresh_editor(self):
        if not self.current_key: return
        self.install_row_controls()

    def delete_selected(self):
        row = self.editor.currentRow()
        if row < 0 or not self.current_key: return
        self.owner.programs[self.current_key]['items'].pop(row)
        self.refresh_editor()
        if self.editor.count(): self.editor.setCurrentRow(min(row, self.editor.count()-1))

    def move_item(self, direction):
        row = self.editor.currentRow()
        if row < 0 or not self.current_key: return
        items = self.owner.programs[self.current_key]['items']
        new_row = row + direction
        if new_row < 0 or new_row >= len(items): return
        items[row], items[new_row] = items[new_row], items[row]
        self.refresh_editor(); self.editor.setCurrentRow(new_row)

    def save_and_close(self):
        try:
            set_startup(self.startup.isChecked())
        except Exception as e:
            QMessageBox.warning(self, '开机启动设置失败', str(e))
        if self.current_key in self.owner.programs:
            self.owner.programs[self.current_key]['enabled'] = self.enable.isChecked()
        self.owner.save()
        self.accept()

    # 让每一行都拥有“删除、上移、下移”按钮：用事件过滤式的自定义行布局实现
    def showEvent(self, event):
        super().showEvent(event)
        self.install_row_controls()

    def install_row_controls(self):
        # QListWidget 本身只显示文字；这里把每行替换为 QWidget，右侧提供三个按钮。
        if not self.current_key: return
        items = self.owner.programs.get(self.current_key, {}).get('items', [])
        self.editor.clear()
        for index, text in enumerate(items):
            roww = QWidget(); lay = QHBoxLayout(roww); lay.setContentsMargins(5,3,5,3); lay.setSpacing(4)
            label = QLabel(text); label.setWordWrap(True); lay.addWidget(label, 1)
            up = QPushButton('↑'); up.setFixedWidth(34); up.clicked.connect(lambda checked=False, i=index: self.move_item(i - self.editor.row(self.editor.itemAt(0))))
            # 使用按钮所在行动态定位，避免刷新后索引失效
            up.clicked.disconnect(); up.clicked.connect(lambda checked=False, w=roww: self.row_move_widget(w, -1))
            down = QPushButton('↓'); down.setFixedWidth(34); down.clicked.connect(lambda checked=False, w=roww: self.row_move_widget(w, 1))
            dele = QPushButton('删除'); dele.setFixedWidth(50); dele.clicked.connect(lambda checked=False, w=roww: self.row_delete_widget(w))
            lay.addWidget(up); lay.addWidget(down); lay.addWidget(dele)
            item = QListWidgetItem(); item.setSizeHint(roww.sizeHint()); self.editor.addItem(item); self.editor.setItemWidget(item, roww)

    def row_index(self, roww):
        for i in range(self.editor.count()):
            if self.editor.itemWidget(self.editor.item(i)) is roww: return i
        return -1

    def row_move_widget(self, roww, direction):
        i = self.row_index(roww)
        if i < 0 or not self.current_key: return
        items = self.owner.programs[self.current_key]['items']
        j = i + direction
        if j < 0 or j >= len(items): return
        items[i], items[j] = items[j], items[i]
        self.install_row_controls()
        if 0 <= j < self.editor.count(): self.editor.setCurrentRow(j)

    def row_delete_widget(self, roww):
        i = self.row_index(roww)
        if i < 0 or not self.current_key: return
        self.owner.programs[self.current_key]['items'].pop(i)
        self.install_row_controls()

    def select_program(self, row):
        if row < 0:
            self.clear_detail(); return
        key = self.program_list.item(row).data(Qt.UserRole)
        data = self.owner.programs.get(key, {})
        self.current_key = key
        self.path_label.setText(key)
        self.enable.blockSignals(True); self.enable.setChecked(bool(data.get('enabled', False))); self.enable.blockSignals(False)
        self.install_row_controls()

class App(QObject):
    def __init__(self):
        super().__init__()
        self.programs = {}
        self.enabled = True
        self.load()
        self.target_hwnd = 0
        self.panel = InputPanel(); self.panel.chosen.connect(self.select)
        self.bridge = Bridge(); self.bridge.right_clicked.connect(self.on_right)
        self.listener = None; self.settings = None
        self.start_listener(); self.setup_tray()

    def load(self):
        try:
            with open(CONFIG, 'r', encoding='utf-8') as f: d = json.load(f)
            self.programs = d.get('programs', {})
            self.enabled = bool(d.get('enabled', True))
        except Exception:
            self.programs = {}; self.enabled = True

    def save(self):
        try:
            with open(CONFIG, 'w', encoding='utf-8') as f:
                json.dump({'enabled': self.enabled, 'programs': self.programs}, f, ensure_ascii=False, indent=2)
        except Exception as e: print('save error:', e)

    def setup_tray(self):
        icon_path = os.path.join(BASE_DIR, 'app.ico')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QApplication.style().standardIcon(QApplication.style().SP_ComputerIcon)
        QApplication.instance().setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, QApplication.instance())
        self.tray.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.act_settings = QAction('设置', self.menu)
        self.act_exit = QAction('退出', self.menu)
        self.act_settings.triggered.connect(self.open_settings)
        self.act_exit.triggered.connect(self.quit)
        self.menu.addAction(self.act_settings)
        self.menu.addSeparator()
        self.menu.addAction(self.act_exit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()

    def tray_activated(self, reason):
        # 左键/双击托盘图标直接打开设置，避免“点击没反应”的感觉
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_settings()

    def start_listener(self):
        from pynput import mouse
        def on_click(x, y, button, pressed):
            if pressed and button == mouse.Button.right:
                hwnd = get_foreground()
                pid, name, path = get_process_info(hwnd)
                self.target_hwnd = hwnd
                self.bridge.right_clicked.emit(x, y, pid, name, path)
        self.listener = mouse.Listener(on_click=on_click)
        self.listener.daemon = True; self.listener.start()

    def on_right(self, x, y, pid, name, path):
        if not self.enabled: return
        key = os.path.normcase(os.path.abspath(path)) if path else ''
        d = self.programs.get(key)
        if not d or not d.get('enabled', False) or not d.get('items'): return
        self.panel.items = list(d['items']); self.panel.rebuild()
        QTimer.singleShot(100, lambda: self.show_panel(x, y))

    def show_panel(self, x, y):
        _, rect = find_context_menu()
        screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
        geo = screen.availableGeometry(); self.panel.adjustSize()
        w, h, gap = self.panel.width(), self.panel.height(), 8
        if rect:
            l, t, r, b = rect
            # 首选右上方；不遮挡原生右键菜单
            if r+w+gap <= geo.right() and t-h-gap >= geo.top(): px, py = r+gap, t-h-gap
            elif r+w+gap <= geo.right(): px, py = r+gap, max(geo.top(), min(t, geo.bottom()-h))
            elif l-w-gap >= geo.left(): px, py = l-w-gap, max(geo.top(), min(t, geo.bottom()-h))
            else: px, py = max(geo.left(), min(x, geo.right()-w)), max(geo.top(), min(t-h-gap, geo.bottom()-h))
        else:
            px = min(x+180, geo.right()-w); py = max(geo.top(), y-h-12)
        self.panel.move(px, py); self.panel.show()

    def select(self, text):
        self.panel.hide(); QApplication.processEvents(); paste_text(text, self.target_hwnd)

    def open_settings(self):
        if self.settings is None: self.settings = SettingsDialog(self)
        self.settings.refresh(); self.settings.show(); self.settings.raise_(); self.settings.activateWindow()

    def quit(self):
        try: self.listener.stop()
        except Exception: pass
        self.panel.close(); self.tray.hide(); QApplication.quit()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    a = App()
    sys.exit(app.exec())
