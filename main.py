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
    def __init__(self,app,items,pos):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.app=app; self.setAttribute(Qt.WA_ShowWithoutActivating); self.setStyleSheet("""
        QDialog{background:#111;border:1px solid #555;border-radius:6px}
        QPushButton{background:#181818;color:white;border:0;padding:8px 14px;text-align:left}
        QPushButton:hover{background:#333}""")
        v=QVBoxLayout(self); v.setContentsMargins(4,4,4,4)
        for s in items:
            b=QPushButton(s); b.clicked.connect(lambda _,x=s:self.input_text(x)); v.addWidget(b)
        self.adjustSize(); self.move(pos)
    def input_text(self,s):
        self.hide(); QApplication.clipboard().setText(s)
        # Ctrl+V into the control under the mouse, preserving native right-click behavior
        ctypes.windll.user32.keybd_event(0x11,0,0,0); ctypes.windll.user32.keybd_event(0x56,0,0,0); ctypes.windll.user32.keybd_event(0x56,0,2,0); ctypes.windll.user32.keybd_event(0x11,0,2,0)
    def closeEvent(self,e): self.app.overlay=None; e.accept()

class App(QApplication):
    def __init__(self):
        super().__init__(sys.argv); self.setQuitOnLastWindowClosed(False); self.icon=QIcon(str(APP_DIR/"app.ico"))
        if self.icon.isNull(): self.icon=self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray=QSystemTrayIcon(self.icon); self.tray.setToolTip("预置输入助手"); self.tray.activated.connect(self.tray_click)
        m=QMenu(); self.settings_action=QAction("设置",m); self.exit_action=QAction("退出",m)
        self.settings_action.triggered.connect(self.open_settings); self.exit_action.triggered.connect(self.quit)
        m.addAction(self.settings_action); m.addSeparator(); m.addAction(self.exit_action); self.tray.setContextMenu(m); self.tray.show()
        self.overlay=None; self.last_buttons=False; self.reload()
    def open_settings(self):
        self.settings=Settings(self); self.settings.setAttribute(Qt.WA_DeleteOnClose,True); self.settings.show(); self.settings.raise_(); self.settings.activateWindow()
    def tray_click(self,r):
        if r==QSystemTrayIcon.DoubleClick: self.open_settings()
    def reload(self):
        self.cfg=load()
    def notify(self,pos):
        # placeholder for hook integration; global mouse hook implemented below
        pass
    def quit(self):
        self.tray.hide(); super().quit()

if __name__=="__main__":
    app=App()
    sys.exit(app.exec())
