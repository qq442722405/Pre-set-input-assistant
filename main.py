import sys, os, json, subprocess, ctypes
from pathlib import Path
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QApplication,QSystemTrayIcon,QMenu,QDialog,QVBoxLayout,QHBoxLayout,
 QLabel,QPushButton,QCheckBox,QListWidget,QListWidgetItem,QLineEdit,QInputDialog,QMessageBox,
 QComboBox,QGroupBox,QFormLayout,QStyle,QAbstractItemView)

APP_DIR=Path(__file__).resolve().parent
CFG=APP_DIR/"config.json"
DEFAULT={"autostart":False,"programs":{}}
def load():
    try: return {**DEFAULT, **json.loads(CFG.read_text("utf-8"))}
    except: return DEFAULT.copy()
def save(c): CFG.write_text(json.dumps(c,ensure_ascii=False,indent=2),"utf-8")

def set_autostart(on):
    try:
        import winreg
        k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run",0,winreg.KEY_SET_VALUE)
        exe=sys.executable if not getattr(sys,"frozen",False) else str(Path(sys.executable))
        cmd=f'"{exe}"'
        if on: winreg.SetValueEx(k,"PresetInputAssistant",0,winreg.REG_SZ,cmd)
        else:
            try: winreg.DeleteValue(k,"PresetInputAssistant")
            except FileNotFoundError: pass
        winreg.CloseKey(k)
    except Exception as e: raise RuntimeError(str(e))


# --- Windows global mouse hook helpers ---
WH_MOUSE_LL=14
WM_RBUTTONDOWN=0x0204
WM_LBUTTONDOWN=0x0201
PROCESS_QUERY_LIMITED_INFORMATION=0x1000
class POINT(ctypes.Structure): _fields_=[('x',ctypes.c_long),('y',ctypes.c_long)]
class MSLLHOOKSTRUCT(ctypes.Structure): _fields_=[('pt',POINT),('mouseData',ctypes.c_ulong),('flags',ctypes.c_ulong),('time',ctypes.c_ulong),('dwExtraInfo',ctypes.c_void_p)]
LowLevelMouseProc=ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_int,ctypes.c_ulong,ctypes.POINTER(MSLLHOOKSTRUCT))
user32=ctypes.windll.user32
kernel32=ctypes.windll.kernel32

def foreground_exe(hwnd):
    if not hwnd: return ''
    pid=ctypes.c_ulong(); user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    h=kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,False,pid.value)
    if not h: return ''
    try:
        buf=ctypes.create_unicode_buffer(32768); n=ctypes.c_ulong(len(buf))
        if kernel32.QueryFullProcessImageNameW(h,0,buf,ctypes.byref(n)): return os.path.abspath(buf.value)
    finally: kernel32.CloseHandle(h)
    return ''

def menu_rect_near(x,y):
    out=[]
    Proc=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    def cb(hwnd,lparam):
        if not user32.IsWindowVisible(hwnd): return True
        name=ctypes.create_unicode_buffer(128); user32.GetClassNameW(hwnd,name,128)
        if name.value!='#32768': return True
        r=ctypes.wintypes.RECT(); user32.GetWindowRect(hwnd,ctypes.byref(r))
        out.append((r.left,r.top,r.right,r.bottom))
        return True
    import ctypes.wintypes
    fn=Proc(cb); user32.EnumWindows(fn,0)
    for r in out:
        if r[0]<=x<=r[2] and r[1]<=y<=r[3]: return r
    return min(out,key=lambda r:(max(r[0]-x,0,x-r[2])**2+max(r[1]-y,0,y-r[3])**2),default=None)

class Settings(QDialog):
    def __init__(self,app):
        super().__init__(app); self.app=app; self.cfg=load(); self.current=None
        self.setWindowTitle("预置输入助手 - 设置"); self.resize(720,560)
        self.setWindowIcon(app.icon)
        root=QVBoxLayout(self)
        g=QGroupBox("1. 开机启动"); f=QHBoxLayout(g)
        self.auto=QCheckBox("Windows 开机自动启动"); self.auto.setChecked(self.cfg.get("autostart",False)); f.addWidget(self.auto); f.addStretch(); root.addWidget(g)
        g2=QGroupBox("2. 选择程序"); v=QVBoxLayout(g2)
        row=QHBoxLayout(); self.prog=QComboBox(); self.prog.setEditable(False); self.prog.currentIndexChanged.connect(self.load_program)
        add=QPushButton("选择程序"); add.clicked.connect(self.add_program); rem=QPushButton("删除程序"); rem.clicked.connect(self.remove_program)
        row.addWidget(self.prog,1); row.addWidget(add); row.addWidget(rem); v.addLayout(row); root.addWidget(g2)
        g3=QGroupBox("3. 右键预设输入选项"); v=QVBoxLayout(g3)
        self.enabled=QCheckBox("启用此程序的右键预设输入（默认关闭）"); self.enabled.stateChanged.connect(self.mark_dirty); v.addWidget(self.enabled); root.addWidget(g3)
        g4=QGroupBox("4. 右键预设输入内容"); v=QVBoxLayout(g4)
        self.list=QListWidget(); self.list.setDragDropMode(QAbstractItemView.NoDragDrop); v.addWidget(self.list)
        row=QHBoxLayout(); addc=QPushButton("添加内容"); addc.clicked.connect(self.add_content)
        up=QPushButton("↑"); up.clicked.connect(lambda:self.move(-1)); down=QPushButton("↓"); down.clicked.connect(lambda:self.move(1)); dele=QPushButton("删除"); dele.clicked.connect(self.delete_content)
        for x in (addc,up,down,dele): row.addWidget(x)
        v.addLayout(row); root.addWidget(g4,1)
        buttons=QHBoxLayout(); buttons.addStretch(); saveb=QPushButton("保存退出"); saveb.clicked.connect(self.save_close); cancel=QPushButton("取消"); cancel.clicked.connect(self.close)
        buttons.addWidget(saveb); buttons.addWidget(cancel); root.addLayout(buttons)
        if self.prog.count(): self.prog.setCurrentIndex(0)

    def add_program(self):
        p,_=QInputDialog.getText(self,"添加程序","输入程序 EXE 完整路径：")
        if not p: return
        p=os.path.abspath(p.strip().strip('"'))
        if not p.lower().endswith(".exe"): QMessageBox.warning(self,"提示","请输入 EXE 程序路径"); return
        if p not in self.cfg["programs"]: self.cfg["programs"][p]={"enabled":False,"items":[]}
        self.refresh_programs(p)
    def refresh_programs(self,select=None):
        self.prog.blockSignals(True); self.prog.clear()
        for p in self.cfg["programs"]: self.prog.addItem(p)
        self.prog.blockSignals(False)
        if select and self.prog.findText(select)>=0: self.prog.setCurrentText(select)
        elif self.prog.count(): self.prog.setCurrentIndex(0)
        self.load_program()
    def remove_program(self):
        p=self.prog.currentText()
        if p and p in self.cfg["programs"] and QMessageBox.question(self,"确认","删除此程序的预设？")==QMessageBox.Yes:
            del self.cfg["programs"][p]; self.refresh_programs()
    def load_program(self):
        self.current=self.prog.currentText()
        d=self.cfg["programs"].get(self.current,{"enabled":False,"items":[]})
        self.enabled.blockSignals(True); self.enabled.setChecked(d.get("enabled",False)); self.enabled.blockSignals(False)
        self.list.clear()
        for x in d.get("items",[]): self.list.addItem(x)
    def mark_dirty(self,*a): pass
    def add_content(self):
        if not self.current: QMessageBox.information(self,"提示","请先选择程序"); return
        s,ok=QInputDialog.getText(self,"添加预设输入","输入内容：")
        if ok and s: self.list.addItem(s)
    def delete_content(self):
        r=self.list.currentRow()
        if r>=0: self.list.takeItem(r)
    def move(self,d):
        r=self.list.currentRow(); n=r+d
        if 0<=r<self.list.count() and 0<=n<self.list.count():
            item=self.list.takeItem(r); self.list.insertItem(n,item); self.list.setCurrentRow(n)
    def save_close(self):
        self.cfg["autostart"]=self.auto.isChecked()
        try: set_autostart(self.cfg["autostart"])
        except Exception as e: QMessageBox.warning(self,"开机启动设置失败",str(e))
        if self.current:
            self.cfg["programs"][self.current]={"enabled":self.enabled.isChecked(),
                "items":[self.list.item(i).text() for i in range(self.list.count())]}
        save(self.cfg); self.app.reload(); self.accept()

class Overlay(QDialog):
    def __init__(self,app,items,pos,target_hwnd=None):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.app=app; self.target_hwnd=target_hwnd; self.setAttribute(Qt.WA_ShowWithoutActivating); self.setStyleSheet("""
        QDialog{background:#111;border:1px solid #555;border-radius:6px}
        QPushButton{background:#181818;color:white;border:0;padding:8px 14px;text-align:left}
        QPushButton:hover{background:#333}""")
        v=QVBoxLayout(self); v.setContentsMargins(4,4,4,4)
        for s in items:
            b=QPushButton(s); b.clicked.connect(lambda _,x=s:self.input_text(x)); v.addWidget(b)
        self.adjustSize(); self.move(pos)
    def input_text(self,s):
        self.hide(); self.app.overlay=None
        # 关闭原生右键菜单，再把焦点恢复到原目标窗口。
        user32.keybd_event(0x1B,0,0,0); user32.keybd_event(0x1B,0,2,0)
        time.sleep(0.05)
        if self.target_hwnd and user32.IsWindow(self.target_hwnd): user32.SetForegroundWindow(self.target_hwnd)
        QApplication.clipboard().setText(s); time.sleep(0.05)
        user32.keybd_event(0x11,0,0,0); user32.keybd_event(0x56,0,0,0); user32.keybd_event(0x56,0,2,0); user32.keybd_event(0x11,0,2,0)
    def closeEvent(self,e): self.app.overlay=None; e.accept()

class App(QApplication):
    def __init__(self):
        super().__init__(sys.argv); self.setQuitOnLastWindowClosed(False)
        self.icon=QIcon(str(APP_DIR/'app.ico'))
        if self.icon.isNull(): self.icon=self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray=QSystemTrayIcon(self.icon); self.tray.setToolTip('预置输入助手'); self.tray.activated.connect(self.tray_click)
        m=QMenu(); a=QAction('设置',m); e=QAction('退出',m); a.triggered.connect(self.open_settings); e.triggered.connect(self.exit_app); m.addAction(a); m.addSeparator(); m.addAction(e); self.tray.setContextMenu(m); self.tray.show()
        self.settings=None; self.overlay=None; self.pending=None; self.reload()
        self._proc=LowLevelMouseProc(self.mouse_hook)
        self._hook=user32.SetWindowsHookExW(WH_MOUSE_LL,self._proc,kernel32.GetModuleHandleW(None),0)
        if not self._hook: self.tray.showMessage('预置输入助手','全局鼠标监听启动失败，请尝试管理员运行。',QSystemTrayIcon.Warning,4000)
    def reload(self): self.cfg=load()
    def open_settings(self):
        if self.settings:
            try: self.settings.raise_(); self.settings.activateWindow(); return
            except RuntimeError: self.settings=None
        self.settings=Settings(self); self.settings.setAttribute(Qt.WA_DeleteOnClose); self.settings.finished.connect(lambda: setattr(self,'settings',None)); self.settings.show(); self.settings.raise_(); self.settings.activateWindow()
    def tray_click(self,r):
        if r==QSystemTrayIcon.DoubleClick: self.open_settings()
    def mouse_hook(self,nCode,wParam,lParam):
        if nCode>=0 and lParam:
            try:
                d=lParam.contents; x,y=int(d.pt.x),int(d.pt.y)
                if wParam==WM_RBUTTONDOWN:
                    hwnd=user32.GetForegroundWindow(); exe=foreground_exe(hwnd)
                    self.pending=(hwnd,exe,x,y); QTimer.singleShot(140,self.show_pending)
                elif wParam==WM_LBUTTONDOWN and self.overlay:
                    self.overlay.close(); self.overlay=None
            except Exception: pass
        return user32.CallNextHookEx(self._hook,nCode,wParam,lParam)
    def show_pending(self):
        if not self.pending: return
        hwnd,exe,x,y=self.pending; d=None
        for k,v in self.cfg.get('programs',{}).items():
            path=str(v.get('path',k))
            if os.path.abspath(path).lower()==os.path.abspath(exe).lower(): d=v; break
        if not d or not d.get('enabled') or not d.get('items'): return
        if self.overlay: self.overlay.close()
        items=[str(v) for v in d.get('items',[]) if str(v)]
        if not items: return
        self.overlay=Overlay(self,items, QPoint(x+220,y+5), hwnd)
        r=menu_rect_near(x,y)
        if r:
            pos=QPoint(r[2]+6,r[1]); screen=QApplication.screenAt(QPoint(x,y)) or QApplication.primaryScreen(); a=screen.availableGeometry()
            if pos.x()+self.overlay.width()>a.right(): pos.setX(max(a.left(),r[0]-self.overlay.width()-6))
            if pos.y()+self.overlay.height()>a.bottom(): pos.setY(max(a.top(),a.bottom()-self.overlay.height()))
            self.overlay.move(pos)
        self.overlay.show(); self.overlay.raise_()
    def exit_app(self):
        if self.overlay: self.overlay.close()
        if self._hook: user32.UnhookWindowsHookEx(self._hook); self._hook=None
        self.tray.hide(); self.quit()

if __name__=="__main__":
    app=App()
    sys.exit(app.exec())
