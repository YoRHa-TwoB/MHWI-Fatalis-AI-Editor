import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os, sys, re, json, shutil, traceback, threading, importlib, ctypes
import tkinter.font as tkfont
from pathlib import Path

# Windows 高 DPI 适配（须在任何 tk 窗口创建之前调用）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def _set_icon(win):
    """金色三角图标 — 用 iconbitmap + default 参数确保覆盖"""
    import struct, tempfile
    S = 32
    gold = (0xc8, 0xa0, 0x40, 0xff)
    trans = (0, 0, 0, 0)
    pixels = []
    for y in range(S):
        for x in range(S):
            cx, t, btm = S / 2, 6, 26
            if y < t or y > btm:
                pixels.append(trans)
            else:
                p = (y - t) / (btm - t)
                hw = int(p * (S / 2 - 8) + 8)
                pixels.append(gold if abs(x - cx) <= hw else trans)
    data = b''
    for row in range(S - 1, -1, -1):
        for col in range(S):
            r, g, b, a = pixels[row * S + col]
            data += struct.pack('BBBB', b, g, r, a)
    bsz = len(data)
    ico = struct.pack('<HHH', 0, 1, 1)
    ico += struct.pack('<BBBBHHII', S, S, 0, 0, 1, 32, bsz + 40, 22)
    ico += struct.pack('<IIIHHIIiiII', 40, S, 2 * S, 1, 32, 0, bsz, 0, 0, 0, 0)
    ico += data
    tmp = os.path.join(tempfile.gettempdir(), '_mhw_tri.ico')
    with open(tmp, 'wb') as f:
        f.write(ico)
    # tk iconbitmap + SendMessage 双重保险
    win.iconbitmap(tmp)
    try:
        hicon = ctypes.windll.user32.LoadImageW(None, tmp, 1, 32, 32, 0x00000010)
        if hicon:
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ctypes.windll.user32.SendMessageW(int(win.frame(), 16), WM_SETICON, ICON_SMALL, hicon)
    except Exception:
        pass

def _dark_titlebar(win):
    """Windows 暗色标题栏"""
    try:
        win.update_idletasks()
        hwnd = int(win.frame(), 16)
        ctypes.windll.uxtheme.SetWindowTheme(hwnd, 'DarkMode_Explorer', None)
        val = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):
            try:
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
                break
            except Exception:
                continue
        try:
            color = ctypes.c_int(0x001a1a1a)
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
        except Exception:
            pass
    except Exception as e:
        print(f'[WARN] dark titlebar failed: {e}', file=sys.stderr)

# ================== 微动画工具 ==================
_COLOR_NAME_MAP = {
    'white': '#ffffff', 'black': '#000000', 'gray': '#808080',
    'red': '#ff0000', 'green': '#00ff00', 'blue': '#0000ff',
}

def _hex_to_rgb(h):
    h = _COLOR_NAME_MAP.get(h, h)  # 颜色名 → hex
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

def _rgb_to_hex(r, g, b):
    return f'#{int(r):02x}{int(g):02x}{int(b):02x}'

def _lerp(a, b, t):
    return a + (b - a) * t

def _animate_bg_only(widget, bg_from, bg_to, steps=6, ms=16):
    """平滑过渡背景色（仅 bg，用于 Frame 等无 fg 属性的控件）"""
    br, bg, bb = _hex_to_rgb(bg_from)
    tr, tg, tb = _hex_to_rgb(bg_to)
    def _step(i):
        if i > steps: return
        t = i / steps; e = 1 - (1 - t) ** 3
        widget.configure(bg=_rgb_to_hex(_lerp(br, tr, e), _lerp(bg, tg, e), _lerp(bb, tb, e)))
        widget.after(ms, lambda: _step(i + 1))
    _step(0)

def _animate_bg_fg(widget, bg_from, bg_to, fg_from, fg_to, steps=6, ms=16):
    """平滑过渡背景色和前景色"""
    br, bg, bb = _hex_to_rgb(bg_from)
    tr, tg, tb = _hex_to_rgb(bg_to)
    fr, fg, fb = _hex_to_rgb(fg_from)
    tr2, tg2, tb2 = _hex_to_rgb(fg_to)
    def _step(i):
        if i > steps:
            return
        t = i / steps
        # ease-out: cubic
        e = 1 - (1 - t) ** 3
        widget.configure(
            bg=_rgb_to_hex(_lerp(br, tr, e), _lerp(bg, tg, e), _lerp(bb, tb, e)),
            fg=_rgb_to_hex(_lerp(fr, tr2, e), _lerp(fg, tg2, e), _lerp(fb, tb2, e)),
        )
        widget.after(ms, lambda: _step(i + 1))
    _step(0)

# ================== 圆角按钮 ==================
class RoundedButton(tk.Canvas):
    """Canvas 绘制的圆角按钮，支持 hover 动画和禁用态"""
    def __init__(self, parent, text='', command=None, font=None, radius=8,
                 bg='#2d2d2d', fg='#d4c5a9', hover_bg='#c8a040', hover_fg='#1a1a1a',
                 disabled_bg='#222222', disabled_fg='#555555',
                 padx=24, pady=8, width=None, **kw):
        self._text = text
        self._cmd = command
        self._font = font or ('Microsoft YaHei UI', 9)
        self._r = radius
        self._bg = bg
        self._fg = fg
        self._hbg = hover_bg
        self._hfg = hover_fg
        self._dbg = disabled_bg
        self._dfg = disabled_fg
        self._px = padx
        self._py = pady
        self._enabled = True
        self._hovered = False
        self._current_bg = bg
        self._current_fg = fg

        # 计算尺寸
        f = tkfont.Font(font=self._font)
        tw = f.measure(text)
        th = f.metrics('linespace')
        cw = tw + 2 * padx
        ch = th + 2 * pady
        if width and width > cw:
            cw = width
        self._cw = cw
        self._ch = ch

        super().__init__(parent, width=cw, height=ch,
                         highlightthickness=0, bg=parent.cget('bg') if hasattr(parent, 'cget') else '#1a1a1a',
                         **kw)
        self._draw()
        self.bind('<Button-1>', self._on_click)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)

    def _draw(self):
        self.delete('all')
        bg = self._current_bg
        fg = self._current_fg
        r = self._r
        w, h = self._cw, self._ch
        d = 2 * r  # diameter of corner arcs
        # 中间矩形（填充四边平面区域）
        self.create_rectangle(r, 0, w-r, h, fill=bg, outline='', width=0)
        self.create_rectangle(0, r, w, h-r, fill=bg, outline='', width=0)
        # 四个圆角
        self.create_arc(0, 0, d, d, start=90, extent=90, fill=bg, outline='', style='pieslice')
        self.create_arc(w-d, 0, w, d, start=0, extent=90, fill=bg, outline='', style='pieslice')
        self.create_arc(0, h-d, d, h, start=180, extent=90, fill=bg, outline='', style='pieslice')
        self.create_arc(w-d, h-d, w, h, start=270, extent=90, fill=bg, outline='', style='pieslice')
        # 文字
        self.create_text(w//2, h//2, text=self._text, fill=fg,
                         font=self._font, anchor='center')

    def _on_enter(self, e):
        if not self._enabled:
            return
        self._hovered = True
        self._animate_to(self._hbg, self._hfg)

    def _on_leave(self, e):
        if not self._enabled:
            return
        self._hovered = False
        self._animate_to(self._bg, self._fg)

    def _on_click(self, e):
        if self._enabled and self._cmd:
            self._cmd()

    def _animate_to(self, target_bg, target_fg):
        _animate_bg_fg_canvas(self, self._current_bg, target_bg,
                              self._current_fg, target_fg)

    def config(self, **kw):
        if 'text' in kw:
            self._text = kw.pop('text')
        if 'command' in kw:
            self._cmd = kw.pop('command')
        if 'state' in kw:
            s = kw.pop('state')
            self._enabled = (s != 'disabled')
            if not self._enabled:
                self._current_bg = self._dbg
                self._current_fg = self._dfg
            else:
                self._current_bg = self._bg
                self._current_fg = self._fg
        super().config(**kw)
        self._draw()

    def cget(self, key):
        if key == 'state':
            return 'normal' if self._enabled else 'disabled'
        return super().cget(key)


def _animate_bg_fg_canvas(canvas, bg_from, bg_to, fg_from, fg_to, steps=6, ms=16):
    """平滑过渡 Canvas 圆角按钮的颜色"""
    br, bg, bb = _hex_to_rgb(bg_from)
    tr, tg, tb = _hex_to_rgb(bg_to)
    fr, fg, fb = _hex_to_rgb(fg_from)
    tr2, tg2, tb2 = _hex_to_rgb(fg_to)
    def _step(i):
        if i > steps:
            return
        t = i / steps
        e = 1 - (1 - t) ** 3
        canvas._current_bg = _rgb_to_hex(_lerp(br, tr, e), _lerp(bg, tg, e), _lerp(bb, tb, e))
        canvas._current_fg = _rgb_to_hex(_lerp(fr, tr2, e), _lerp(fg, tg2, e), _lerp(fb, tb2, e))
        canvas._draw()
        canvas.after(ms, lambda: _step(i + 1))
    _step(0)


# ================== 主题 ==================
def apply_theme():
    """应用怪物猎人暗色主题"""
    style = ttk.Style()
    style.theme_use('clam')

    # --- 调色板 ---
    BG_DARK       = '#1a1a1a'
    BG_SURFACE    = '#252525'
    BG_ELEVATED   = '#2d2d2d'
    BORDER        = '#3a3a3a'
    TEXT          = '#d4c5a9'
    TEXT_SEC      = '#8a806e'
    GOLD          = '#c8a040'
    GOLD_LIGHT    = '#d4b050'
    GOLD_DARK     = '#9a7a30'
    SELECT        = '#3d3620'

    FONT_BASE   = ('Microsoft YaHei UI', 10)
    FONT_SMALL  = ('Microsoft YaHei UI', 9)
    FONT_BOLD   = ('Microsoft YaHei UI', 10, 'bold')
    FONT_TITLE  = ('Microsoft YaHei UI', 20, 'bold')
    FONT_SUB    = ('Microsoft YaHei UI', 13, 'bold')
    FONT_HEAD   = ('Microsoft YaHei UI', 11, 'bold')

    # === 全局默认 ===
    style.configure('.', background=BG_DARK, foreground=TEXT, font=FONT_BASE,
                    troughcolor=BG_DARK, borderwidth=0, relief='flat',
                    selectbackground=SELECT, selectforeground=GOLD)

    # === Frame ===
    style.configure('TFrame', background=BG_DARK)
    style.configure('Surface.TFrame', background=BG_SURFACE)
    style.configure('Card.TFrame', background=BG_SURFACE, relief='solid', borderwidth=1, bordercolor=BORDER)

    # === Label ===
    style.configure('TLabel', background=BG_DARK, foreground=TEXT, font=FONT_BASE)
    style.configure('Title.TLabel', font=FONT_TITLE, foreground=GOLD)
    style.configure('Subtitle.TLabel', font=FONT_SUB, foreground=GOLD)
    style.configure('Heading.TLabel', font=FONT_HEAD, foreground=GOLD)
    style.configure('Hint.TLabel', font=FONT_SMALL, foreground=TEXT_SEC)
    style.configure('Surface.TLabel', background=BG_SURFACE, foreground=TEXT)
    style.configure('Card.TLabel', background=BG_SURFACE, foreground=TEXT)

    # === Button ===
    style.configure('TButton', font=FONT_BASE,
                    background=BG_ELEVATED, foreground=TEXT,
                    borderwidth=1, relief='solid', bordercolor=BORDER,
                    focusthickness=0, padding=(14, 5), anchor='center')
    style.map('TButton',
              background=[('active', GOLD), ('pressed', GOLD_DARK)],
              foreground=[('active', BG_DARK)],
              bordercolor=[('active', GOLD_LIGHT), ('pressed', GOLD_DARK)])
    # 强调按钮：实心金
    style.configure('Accent.TButton', font=FONT_BOLD,
                    background=GOLD, foreground=BG_DARK,
                    relief='flat', borderwidth=0,
                    focusthickness=0, padding=(20, 10))
    style.map('Accent.TButton',
              background=[('active', GOLD_LIGHT), ('pressed', GOLD_DARK)])

    # === Entry ===
    style.configure('TEntry', font=FONT_BASE,
                    fieldbackground=BG_ELEVATED, foreground=TEXT,
                    insertcolor=TEXT, insertwidth=1,
                    relief='solid', borderwidth=1, bordercolor=BORDER)
    style.map('TEntry',
              bordercolor=[('focus', GOLD)],
              fieldbackground=[('readonly', BG_SURFACE)])

    # === Treeview ===
    style.configure('Treeview', font=FONT_BASE,
                    background=BG_SURFACE, foreground=TEXT,
                    fieldbackground=BG_SURFACE, borderwidth=0,
                    rowheight=28)
    style.configure('Treeview.Heading', font=FONT_BOLD,
                    background=BG_ELEVATED, foreground=GOLD,
                    relief='flat', borderwidth=0, padding=(6, 4))
    style.map('Treeview',
              background=[('selected', SELECT)],
              foreground=[('selected', GOLD)])
    style.map('Treeview.Heading',
              background=[('active', BG_ELEVATED)],
              foreground=[('active', GOLD_LIGHT)])

    # === PanedWindow ===
    style.configure('TPanedwindow', background=BG_DARK)

    # === Separator ===
    style.configure('TSeparator', background=BORDER)

    # === LabelFrame ===
    style.configure('TLabelframe', background=BG_DARK, foreground=TEXT,
                    borderwidth=1, relief='solid', bordercolor=BORDER)
    style.configure('TLabelframe.Label', background=BG_DARK, foreground=GOLD, font=FONT_BOLD)

    # === Scrollbar ===
    style.configure('Vertical.TScrollbar',
                    background=BG_DARK, troughcolor=BG_DARK,
                    arrowcolor=TEXT_SEC, arrowsize=14,
                    borderwidth=0, relief='flat', width=10)
    style.map('Vertical.TScrollbar',
              background=[('active', GOLD), ('pressed', GOLD_DARK)],
              arrowcolor=[('active', GOLD_LIGHT), ('pressed', GOLD)])

    # === tk.Menu（尽力而为，Windows 原生菜单限制较多）===
    # === 树节点深度颜色 ===
    TREE_COLORS = {
        0: GOLD,           # 根：金
        1: '#e8ddcc',      # 一级分类：亮暖白
        2: '#d9cebb',      # 二级：暖白
        3: '#c4b9a5',      # 三级条件：标准暖
        4: '#a89d8a',      # 四级：稍暗
        5: '#8c8272',      # 五级+：暗灰
    }
    TREE_BG_EVEN = '#222222'
    TREE_BG_ODD  = '#252525'

    return {
        'bg_dark': BG_DARK, 'bg_surface': BG_SURFACE, 'bg_elevated': BG_ELEVATED,
        'border': BORDER,
        'text': TEXT, 'text_sec': TEXT_SEC,
        'gold': GOLD, 'gold_light': GOLD_LIGHT, 'gold_dark': GOLD_DARK,
        'select': SELECT,
        'font_base': FONT_BASE, 'font_small': FONT_SMALL,
        'font_bold': FONT_BOLD, 'font_title': FONT_TITLE,
        'font_sub': FONT_SUB, 'font_head': FONT_HEAD,
        'tree_colors': TREE_COLORS,
        'tree_bg_even': TREE_BG_EVEN, 'tree_bg_odd': TREE_BG_ODD,
    }

# ================== 资源路径 ==================
def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_user_data_dir():
    home = Path.home()
    data_dir = home / '.mhw_ai_editor'
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)

# ================== 设置 ==================
SETTINGS_FILE = 'settings.json'
def load_settings():
    path = os.path.join(get_user_data_dir(), SETTINGS_FILE)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_settings(settings):
    path = os.path.join(get_user_data_dir(), SETTINGS_FILE)
    with open(path, 'w') as f:
        json.dump(settings, f, indent=2)

def ask_game_directory(parent=None):
    settings = load_settings()
    current = settings.get('game_dir', '')
    if not current or not os.path.isdir(current):
        current = os.path.expanduser("~")
    dir_path = filedialog.askdirectory(
        title="请选择 Monster Hunter World 游戏根目录（包含 MonsterHunterWorld.exe）",
        initialdir=current,
        parent=parent
    )
    if dir_path:
        settings['game_dir'] = dir_path
        save_settings(settings)
        return dir_path
    return None

# ================== 条件翻译 ==================
def describe_single_condition(cond, condition_map=None):
    cond = cond.strip()
    # ★ 处理携带了前一个条件的 else（格式：else|原始条件）
    if cond.startswith('else|'):
        real_prev = cond[5:]
        return describe_else_from_prev(real_prev)
    
    # === 已有 ===
    if 'function#101()' in cond and 'function#101(1)' not in cond:
        return '二足'
    if 'function#101(1)' in cond:
        return '四足'
    if 'self.flying()' in cond:
        return '飞行状态'
    if 'self.enraged()' in cond:
        return '愤怒'
    if 'function#103()' in cond and 'function#103(1)' not in cond:
        return '一阶段'
    if 'function#103(1)' in cond:
        return '二阶段'
    if 'function#106(1)' in cond:
        return '三阶段'
    if 'function#106()' in cond:          # ★ 新增
        return '非三阶段'
    if 'function#104()' in cond and 'function#104(1)' not in cond:
        return '一阶段高台'
    if 'function#104(1)' in cond:
        return '二三阶段高台'

    # === 新增：其他常见条件 ===
    if 'function#2D(1)' in cond:
        return '不明条件2D(1)（不懂别动）'
    if 'function#10A()' in cond:
        return '不明条件10A()（不懂别动）'
    if 'function#10D()' in cond:
        return '黑龙与玩家之间视野有遮挡'
    if 'function#10E()' in cond:
        return '黑龙刚开局一段时间（不会出扇火）'
    if 'function#108()' in cond:
        return '不明条件108(1)与特黑有关（不懂别动）'
    if 'function#110(2)' in cond:
        return '不明条件110(2)（不懂别动）'
    if 'function#111()' in cond:
        return '操虫棍'
    if 'function#112(0,1)' in cond:
        return '不明条件112(0,1)（不懂别动）'
    if 'function#113(3,40)' in cond:
        return '不明条件113(3,40)（不懂别动）'
    if 'function#7F()' in cond and 'function#7F(6)' not in cond:
        return '又一个神秘条件'
    if 'function#7F(6)' in cond:
        return '神秘条件'
    if 'self.target(3)' in cond:
        return '与索敌有关的神秘条件target(3)'
    if 'self.target(4)' in cond:
        return '与索敌有关的神秘条件target(4)'
    if 'self.above_target()' in cond:
        return '神秘条件据说是：在水潭里不会判定，疑似是低处不判定'
    if 'self.target.helpless_0()' in cond:
        return '我方有受击反应时（坐倒，击飞，被下压爬起时）'

    # 距离
    m = re.search(r'\.leq\((\d+)\)', cond)
    if m: return f'距离≤{m.group(1)}'
    m = re.search(r'\.gt\((\d+)\)', cond)
    if m: return f'距离>{m.group(1)}'

    # 角度
    m = re.search(r'between\((\d+),\s*(\d+)\)', cond)
    if m:
        a1, a2 = m.group(1), m.group(2)
        if a1 == '330' and a2 == '30':   return '正面'
        if a1 == '30'  and a2 == '100':  return '右侧前'
        if a1 == '260' and a2 == '330':  return '左侧前'
        if a1 == '150' and a2 == '210':  return '背后'
        return f'{a1}°-{a2}°'

    # 寄存器变量
    m = re.match(r'\[RegisterVar(\d+)\s*([><=!]+)\s*(\d+)\]', cond)
    if m:
        var_num = m.group(1)
        op = m.group(2)
        val = m.group(3)
        op_text = op.replace('>=', '≥').replace('<=', '≤').replace('==', '＝')
        return f'计数器{var_num} {op_text} {val}'

    # 破头/破胸
    if '.is_broken(1)' in cond:
        if 'part(0)' in cond:
            return '头已破'
        if 'part(1)' or 'part(2)' in cond:
            return '翅膀已破'
        if 'part(3)' in cond:
            return '胸已破'
    # 血量
    if '.hp_percent()' in cond:
        m = re.search(r'\.leq\((\d+)\)', cond)
        if m: return f'黑龙血量≤{m.group(1)}%'

    # 垂直距离
    if '.vertical_distance_to_target()' in cond:
        m = re.search(r'\.gt\((\d+)\)', cond)
        if m: return f'高度>{m.group(1)}'

    # quest_id
    if '.quest_id(51612)' in cond:
        return '任务ID=51612(即特黑)'

    # distance_3d
    m = re.search(r'\.distance_3d_to_target\(\)\.gt\((\d+)\)', cond)
    if m: return f'3D距离>{m.group(1)}'

    if cond == 'else':
        return 'else'    # 兜底，理论上不应该走到这里（已在inline_expand中处理）
    # 从 condition_map.json 查翻译
    if condition_map and cond in condition_map:
        return condition_map[cond]
    return cond


def describe_else_from_prev(prev_cond):
    if prev_cond is None:
        return '否则'

    # 1. 角度条件
    if 'angle_2d_cw_between' in prev_cond:
        return '其他角度'

    # 2. 飞行/地面
    if 'self.flying()' in prev_cond:
        return '地面'

    # 3. 二足/四足
    if 'function#101()' in prev_cond and 'function#101(1)' not in prev_cond:
        return '四足'
    if 'function#101(1)' in prev_cond:
        return '二足'

    # 4. 阶段
    if 'function#103()' in prev_cond and 'function#103(1)' not in prev_cond:
        return '非一阶段'
    if 'function#103(1)' in prev_cond:
        return '三阶段'          # 修复：二阶段之后 else 为三阶段

    # 5. 高台
    if 'function#104()' in prev_cond and 'function#104(1)' not in prev_cond:
        return '非一阶段高台'
    if 'function#104(1)' in prev_cond:
        return '非二三阶段高台'

    # 6. 愤怒
    if 'self.enraged()' in prev_cond:
        return '非愤怒'

    # 7. 距离取反
    m = re.search(r'\.leq\((\d+)\)', prev_cond)
    if m:
        return f'距离>{m.group(1)}'
    m = re.search(r'\.gt\((\d+)\)', prev_cond)
    if m:
        return f'距离≤{m.group(1)}'

    # 8. 其他
    return '否则'

def describe_conditions(cond_list):
    parts = [describe_single_condition(c) for c in cond_list]
    return ' · '.join(parts) if parts else '(无条件)'

# ================== .nack 解析 ==================
class RandomAction:
    def __init__(self, line_no, weight, target, raw_line):
        self.line_no = line_no
        self.weight = weight
        self.target = target
        self.raw_line = raw_line

class RandomBlock:
    def __init__(self, func_name, condition_path, condition_desc, actions):
        self.func_name = func_name
        self.condition_path = condition_path
        self.condition_desc = condition_desc
        self.actions = actions

def parse_nack(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    blocks = []
    calls = {}
    current_func = None
    if_depth = 0
    condition_stack = []
    if_stack = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        func_match = re.match(r'def (\w+)', stripped)
        if func_match:
            current_func = func_match.group(1)
            calls[current_func] = []
            condition_stack.clear()
            if_stack.clear()
            if_depth = 0
        elif re.match(r'if\b', stripped):
            if_depth += 1
            cond = stripped[2:].strip()
            if_stack.append({'type': 'if', 'cond': cond, 'depth': if_depth})
            condition_stack.append(cond)
        elif re.match(r'elif\b', stripped):
            if if_stack:
                if_stack.pop(); condition_stack.pop()
                cond = stripped[4:].strip()
                if_stack.append({'type': 'elif', 'cond': cond, 'depth': if_depth})
                condition_stack.append(cond)
        elif re.match(r'else\b', stripped):
            if if_stack:
                if_stack.pop()
                old_cond = condition_stack.pop()       # ★ 保存被丢弃的条件
                if_stack.append({'type': 'else', 'cond': 'else', 'depth': if_depth})
                condition_stack.append('else|' + old_cond)  # ★ 用特殊格式保留
        elif re.match(r'endif\b', stripped):
            while if_stack and if_stack[-1]['depth'] == if_depth:
                if_stack.pop(); condition_stack.pop()
            if_depth -= 1
        elif re.match(r'(?:>>|->)\s+', stripped):
            target = stripped[2:].strip()
            if current_func is not None:
                calls[current_func].append( (list(condition_stack), target) )
        elif re.match(r'random\b', stripped):
            actions = []
            pending_weight = None
            weight_line_no = None
            j = i
            while j < len(lines):
                l = lines[j].strip()
                if l.startswith('endr'):
                    break
                m = re.match(r'(?:random|elser)\s*\((\d+)\)', l)
                if m:
                    pending_weight = int(m.group(1))
                    weight_line_no = j
                    arrow = re.search(r'(?:>>|->)\s*(\S+)', l)
                    if arrow:
                        target = arrow.group(1)
                        actions.append(RandomAction(weight_line_no, pending_weight, target, lines[weight_line_no]))
                        pending_weight = None
                elif pending_weight is not None:
                    arrow = re.match(r'\s*(?:>>|->)\s*(\S+)', l)
                    if arrow:
                        target = arrow.group(1)
                        actions.append(RandomAction(weight_line_no, pending_weight, target, lines[weight_line_no]))
                        pending_weight = None
                j += 1
            cond_desc = describe_conditions(list(condition_stack))
            if current_func is not None:
                blocks.append(RandomBlock(current_func, list(condition_stack), cond_desc, actions))
            i = j
        i += 1
    return blocks, calls, lines

# ================== 模式选择 ==================
class ModeSelectionWindow:
    def __init__(self):
        self.window = tk.Tk()
        self.c = apply_theme()
        self.window.configure(bg=self.c['bg_dark'])
        self.window.title("怪物猎人世界 · 怪物 AI 编辑器")
        self.window.geometry("520x440")
        self.window.resizable(False, False)
        self.window.eval('tk::PlaceWindow . center')
        _dark_titlebar(self.window)
        _set_icon(self.window)
        self.window.after(200, lambda: _set_icon(self.window))
        self.setup_ui()
        self.window.mainloop()

    def setup_ui(self):
        c = self.c

        tk.Frame(self.window, bg=c['gold'], height=2).pack(fill=tk.X)

        # 标题区域
        title_frame = ttk.Frame(self.window, style='Surface.TFrame')
        title_frame.pack(fill=tk.X, padx=40, pady=(30, 10))
        ttk.Label(title_frame, text="MONSTER HUNTER WORLD",
                  style='Hint.TLabel', background=c['bg_surface']).pack(pady=(14, 0))
        ttk.Label(title_frame, text="怪物 AI 编辑器",
                  style='Title.TLabel', background=c['bg_surface']).pack()
        ttk.Label(title_frame, text="黑龙特化版 · 内置编译引擎",
                  style='Hint.TLabel', background=c['bg_surface']).pack(pady=(0, 14))

        ttk.Label(self.window, text="仅供研究学习使用 · 严禁用于竞速作弊",
                  style='Hint.TLabel').pack(pady=(0, 8))

        ttk.Separator(self.window).pack(fill=tk.X, padx=60, pady=10)

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(pady=(10, 6))
        ttk.Button(btn_frame, text="黑龙 AI 编辑器",
                   command=self.launch_editor, style='Accent.TButton',
                   width=28).pack(pady=6)
        ttk.Button(btn_frame, text="更多怪物支持开发中...",
                   command=lambda: messagebox.showinfo("开发中", "更多怪物支持开发中！"),
                   width=28).pack(pady=6)

        ttk.Button(self.window, text="游戏目录设置",
                   command=self.open_settings, width=20).pack(pady=(6, 0))

        self.update_status_label()

    def update_status_label(self):
        c = self.c
        settings = load_settings()
        game_dir = settings.get('game_dir', '')
        if game_dir:
            status = f"游戏目录: {game_dir}"
        else:
            status = "尚未设置游戏目录"
        if hasattr(self, 'status_label'):
            self.status_label.config(text=status)
        else:
            self.status_label = tk.Label(self.window, text=status,
                                         font=c['font_small'], fg=c['text_sec'],
                                         bg=c['bg_dark'])
            self.status_label.pack(side=tk.BOTTOM, pady=12)

    def launch_editor(self):
        settings = load_settings()
        if not settings.get('game_dir'):
            if messagebox.askyesno("提示", "需要先设置游戏目录，是否现在设置？"):
                ask_game_directory()
        self.window.destroy()
        FatalisAIEditor().run()

    def open_settings(self):
        ask_game_directory(self.window)
        self.update_status_label()

# ================== 主编辑器 ==================
class FatalisAIEditor:
    def __init__(self):
        self.root = tk.Tk()
        self.c = apply_theme()
        self.root.configure(bg=self.c['bg_dark'])
        self.root.title("黑龙 AI 编辑器")
        self.root.geometry("1300x820")
        self.root.minsize(1000, 600)
        self.root.eval('tk::PlaceWindow . center')
        _dark_titlebar(self.root)
        _set_icon(self.root)
        self.root.after(200, lambda: _set_icon(self.root))
        self.files_data = {}
        self.current_selection = None
        self.move_map = {}
        self.condition_map = {}         # ★ 新增
        self.node_label_map = {}        # ★ 新增
        self._visited_expand = set()
        self.user_dir = get_user_data_dir()
        self.workspace_dir = os.path.join(self.user_dir, 'workspace')
        self._saving = False
        self._compiling = False
        self.init_workspace()
        self.load_move_map()
        self.load_condition_map()      # ★ 新增
        self.load_node_label_map()     # ★ 新增
        self.setup_ui()
        self.load_files()
        self._update_pending_status()

    # ---------- 工作区（每次启动自动重置） ----------
    def init_workspace(self):
        shutil.rmtree(self.workspace_dir, ignore_errors=True)
        src = resource_path(os.path.join('data', 'source'))
        if os.path.exists(src):
            shutil.copytree(src, self.workspace_dir)
        else:
            messagebox.showerror("错误", "内置源文件缺失，请检查程序完整性。")

    def reset_workspace(self):
        if messagebox.askyesno("确认", "重置将恢复所有默认文件，继续？"):
            self.init_workspace()
            self.files_data.clear()
            self.load_files()
            self.status_var.set("已重置")
            self._disable_weight_edit()

    def load_move_map(self):
        map_path = os.path.join(self.workspace_dir, 'move_map.json')
        if os.path.exists(map_path):
            with open(map_path, 'r', encoding='utf-8') as f:
                self.move_map = json.load(f)
    def load_condition_map(self):                               # ★ 新增
        path = os.path.join(self.workspace_dir, 'condition_map.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                self.condition_map = json.load(f)
    def load_node_label_map(self):                              # ★ 新增
        path = os.path.join(self.workspace_dir, 'node_label_map.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                self.node_label_map = json.load(f)
    def get_move_display(self, target):
        """获取招式的中文显示名：优先 move_map.json，否则原始名"""
        clean = re.sub(r'\s*@.*', '', target).strip()   # 去 @ 参数
        clean = re.sub(r'\([^)]*\)', '', clean).strip()  # ← 新增：去括号及参数
        return self.move_map.get(clean, target)
    # ---------- UI ----------
    def setup_ui(self):
        c = self.c

        # === 自定义菜单栏（暗色，替代原生白底菜单） ===
        self.root.config(menu='')  # 移除原生菜单
        menu_bar = tk.Frame(self.root, bg=c['bg_dark'], height=34)
        menu_bar.pack(fill=tk.X)
        menu_bar.pack_propagate(False)

        def _mk_menu(label, items):
            mb = tk.Menubutton(menu_bar, text=label + ' ▾', font=c['font_base'],
                               fg=c['text_sec'], bg=c['bg_dark'],
                               activeforeground=c['gold'], activebackground=c['bg_dark'],
                               relief='flat', borderwidth=0, padx=14, pady=5,
                               cursor='hand2', direction='below')
            menu = tk.Menu(mb, tearoff=0, bg=c['bg_surface'], fg=c['text'],
                           activebackground=c['gold'], activeforeground=c['bg_dark'],
                           font=c['font_base'], borderwidth=0, relief='flat')
            for it_label, it_cmd in items:
                if it_label == '---':
                    menu.add_separator()
                else:
                    menu.add_command(label='  ' + it_label + '  ', command=it_cmd)
            mb.configure(menu=menu)
            mb.bind('<Enter>', lambda e, m=mb:
                _animate_bg_fg(m, m.cget('bg'), m.cget('bg'), c['text_sec'], c['gold']))
            mb.bind('<Leave>', lambda e, m=mb:
                _animate_bg_fg(m, m.cget('bg'), m.cget('bg'), c['gold'], c['text_sec']))
            return mb

        menus = [
            ('文件', [('重置工作区', self.reset_workspace), ('---', None),
                      ('返回主菜单', self.back_to_mode), ('退出', self.on_close)]),
            ('设置', [('游戏目录', lambda: ask_game_directory(self.root))]),
            ('帮助', [('使用说明', self.show_help), ('关于', self.show_about)]),
        ]
        for i, (lbl, items) in enumerate(menus):
            if i > 0:
                tk.Frame(menu_bar, bg=c['border'], width=1).pack(
                    side=tk.LEFT, fill=tk.Y, padx=2, pady=8)
            _mk_menu(lbl, items).pack(side=tk.LEFT)

        # 菜单栏下方金色分隔线
        tk.Frame(self.root, bg=c['gold'], height=1).pack(fill=tk.X)

        # === 工具栏（带分组） ===
        toolbar = tk.Frame(self.root, bg=c['bg_surface'], height=36)
        toolbar.pack(fill=tk.X)
        toolbar.pack_propagate(False)

        def _make_tool_btn(parent, text, cmd):
            bar = tk.Frame(parent, bg=c['bg_surface'], height=4)
            btn = RoundedButton(parent, text=text, command=cmd,
                                font=c['font_base'],
                                bg=c['bg_surface'], fg=c['text'],
                                hover_bg=c['select'], hover_fg=c['gold'],
                                radius=5, padx=14, pady=4)
            def on_enter(e):
                _animate_bg_only(bar, c['bg_surface'], c['gold'], steps=4)
            def on_leave(e):
                _animate_bg_only(bar, c['gold'], c['bg_surface'], steps=4)
            btn.bind('<Enter>', on_enter, add='+')
            btn.bind('<Leave>', on_leave, add='+')
            bar.bind('<Enter>', on_enter)
            bar.bind('<Leave>', on_leave)
            btn.pack(side=tk.LEFT)
            bar.pack(side=tk.LEFT, fill=tk.X, padx=(0, 0))
            return btn, bar

        def _tool_sep(parent):
            sep = tk.Frame(parent, bg=c['border'], width=1)
            sep.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=7)

        btn_refs = {}
        btns_spec = [
            ('保存修改', self.save_changes),
            ('导出 .thk', self.export_thk),
            ('部署到游戏', self.auto_deploy),
        ]
        for i, (label, cmd) in enumerate(btns_spec):
            if i > 0:
                _tool_sep(toolbar)
            btn_refs[label] = _make_tool_btn(toolbar, label, cmd)

        # 分隔操作组与工具组（更明显的分隔）
        tk.Frame(toolbar, bg=c['gold'], width=1).pack(side=tk.LEFT, fill=tk.Y, padx=12, pady=5)
        reset_btn, reset_bar = _make_tool_btn(toolbar, '重置', self.reset_workspace)

        # 存储按钮引用供 disable/enable 使用
        self.save_btn   = btn_refs['保存修改'][0]
        self.export_btn = btn_refs['导出 .thk'][0]
        self.deploy_btn = btn_refs['部署到游戏'][0]
        self.reset_btn  = reset_btn

        # 工具条底部分隔线
        tk.Frame(self.root, bg=c['bg_elevated'], height=1).pack(fill=tk.X)

        # === 主区域 ===
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # --- 左侧：行为树 ---
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        tree_header = tk.Frame(tree_frame, bg=c['bg_dark'], height=32)
        tree_header.pack(fill=tk.X, padx=4, pady=(4, 0))
        tree_header.pack_propagate(False)
        tk.Label(tree_header, text='AI 行为树', font=c['font_head'],
                 fg=c['gold'], bg=c['bg_dark']).pack(side=tk.LEFT, padx=6, pady=4)
        # 展开/折叠按钮
        for lbl, action in [('╔', 'expand'), ('╝', 'collapse')]:
            tk.Label(tree_header, text=lbl, font=c['font_small'],
                     fg=c['text_sec'], bg=c['bg_dark'], padx=4, cursor='hand2').pack(
                         side=tk.RIGHT, padx=2, pady=4)
        tree_expand_btn = tree_header.winfo_children()[1]
        tree_collapse_btn = tree_header.winfo_children()[2]
        tree_expand_btn.bind('<Button-1>', lambda e: self._expand_all())
        tree_expand_btn.bind('<Enter>', lambda e: tree_expand_btn.configure(fg=c['gold']))
        tree_expand_btn.bind('<Leave>', lambda e: tree_expand_btn.configure(fg=c['text_sec']))
        tree_collapse_btn.bind('<Button-1>', lambda e: self._collapse_all())
        tree_collapse_btn.bind('<Enter>', lambda e: tree_collapse_btn.configure(fg=c['gold']))
        tree_collapse_btn.bind('<Leave>', lambda e: tree_collapse_btn.configure(fg=c['text_sec']))

        self.tree = ttk.Treeview(tree_frame, show='tree', selectmode='browse')
        self.tree.heading('#0', text='点击招式修改权重')
        # 配置树标签颜色
        for depth, color in c['tree_colors'].items():
            self.tree.tag_configure(f'd{depth}', foreground=color)
        self.tree.tag_configure('d0_bold', foreground=c['tree_colors'][0], font=c['font_bold'])
        self.tree.tag_configure('bg_even', background=c['tree_bg_even'])
        self.tree.tag_configure('bg_odd', background=c['tree_bg_odd'])

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                               command=self.tree.yview, style='Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=(0, 4))
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=(0, 4))

        # --- 右侧：编辑面板 ---
        edit_outer = ttk.Frame(paned)
        paned.add(edit_outer, weight=2)

        edit_header = tk.Frame(edit_outer, bg=c['bg_dark'], height=32)
        edit_header.pack(fill=tk.X, padx=4, pady=(4, 0))
        edit_header.pack_propagate(False)
        tk.Label(edit_header, text='招式编辑', font=c['font_head'],
                 fg=c['gold'], bg=c['bg_dark']).pack(side=tk.LEFT, padx=6, pady=4)

        card = tk.Frame(edit_outer, bg=c['bg_surface'], padx=20, pady=16)
        card.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.info_text = tk.StringVar(value='请在左侧树中点击一个招式')
        tk.Label(card, textvariable=self.info_text, font=c['font_base'],
                 fg=c['text'], bg=c['bg_surface'], wraplength=400,
                 justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 18))

        ttk.Separator(card).pack(fill=tk.X, pady=(0, 16))

        # 权重编辑区域 — 纵向布局
        tk.Label(card, text='修改权重', font=c['font_sub'],
                 fg=c['gold'], bg=c['bg_surface']).pack(anchor=tk.W, pady=(0, 10))

        # 大号输入框
        self.weight_var = tk.StringVar()
        self.weight_entry = ttk.Entry(card, textvariable=self.weight_var,
                                      width=16, state='disabled',
                                      font=('Microsoft YaHei UI', 18))
        self.weight_entry.pack(anchor=tk.W, pady=(0, 12))
        self.weight_entry.bind('<Return>', lambda e: self.apply_weight())

        # 宽大的圆角应用按钮
        self.apply_btn = RoundedButton(card, text='应用', command=self.apply_weight,
                                       font=('Microsoft YaHei UI', 12, 'bold'),
                                       bg=c['gold'], fg=c['bg_dark'],
                                       hover_bg=c['gold_light'], hover_fg=c['bg_dark'],
                                       disabled_bg=c['bg_elevated'], disabled_fg=c['text_sec'],
                                       radius=8, padx=44, pady=11, width=180)
        self.apply_btn.pack(anchor=tk.W, pady=(0, 0))
        self.apply_btn._enabled = False
        self.apply_btn._current_bg = c['bg_elevated']
        self.apply_btn._current_fg = c['text_sec']
        self.apply_btn._draw()

        ttk.Separator(card).pack(fill=tk.X, pady=18)

        tk.Label(card, text='操作说明', font=c['font_bold'],
                 fg=c['gold'], bg=c['bg_surface']).pack(anchor=tk.W, pady=(0, 4))
        for h in [
            '点击左侧招式节点 → 输入新权重数字 → 点击「应用」',
            '修改完成后点击「保存修改」写入文件',
            '导出或部署前请确保已保存所有修改',
        ]:
            tk.Label(card, text='  ·  ' + h, font=c['font_small'],
                     fg=c['text_sec'], bg=c['bg_surface'],
                     anchor=tk.W, justify=tk.LEFT).pack(anchor=tk.W)

        # === 状态栏 ===
        status_frame = tk.Frame(self.root, bg=c['bg_surface'], height=26)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        status_frame.pack_propagate(False)
        tk.Frame(self.root, bg=c['gold'], height=1).pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value='就绪')
        tk.Label(status_frame, textvariable=self.status_var, font=c['font_small'],
                 fg=c['text_sec'], bg=c['bg_surface'], anchor=tk.W).pack(
                     side=tk.LEFT, fill=tk.X, padx=10, pady=2)

        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    def _expand_all(self):
        """递归展开所有树节点"""
        def _expand(item):
            self.tree.item(item, open=True)
            for child in self.tree.get_children(item):
                _expand(child)
        for item in self.tree.get_children():
            _expand(item)

    def _collapse_all(self):
        """递归折叠所有树节点（保留根节点展开）"""
        def _collapse(item):
            for child in self.tree.get_children(item):
                _collapse(child)
            self.tree.item(item, open=False)
        for item in self.tree.get_children():
            _collapse(item)


    # ---------- 待保存状态更新 ----------
    def _update_pending_status(self):
        total = sum(len(data.get('changes', {})) for data in self.files_data.values())
        total += sum(len(data.get('data_changes', {})) for data in self.files_data.values())
        if total:
            self.status_var.set(f'已修改 {total} 处，请点击保存')
        else:
            self.status_var.set('就绪')

    # ---------- 树加载（与之前相同，保持手动结构） ----------
    def load_files(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.files_data.clear()
        self._visited_expand.clear()

        if not os.path.isdir(self.workspace_dir):
            return

        parse_errors = []
        for fname in ('em013_00.nack', 'em013_55.nack'):
            fpath = os.path.join(self.workspace_dir, fname)
            if not os.path.exists(fpath):
                continue
            try:
                blocks, calls, lines = parse_nack(fpath)
                self.files_data[fname] = {
                    'path': fpath,
                    'lines': lines,
                    'blocks': blocks,
                    'calls': calls,
                    'changes': {},
                    'data_changes': {}     # ← 新增：存储数据值修改
                }
            except Exception as e:
                parse_errors.append(f"{fname} 解析失败: {e}")

        if parse_errors:
            messagebox.showerror("文件错误",
                "以下文件无法解析，可能已损坏：\n" + "\n".join(parse_errors) +
                "\n\n请点击「重置」恢复原始文件即可修复。")
            self.status_var.set("文件解析错误，请重置工作区！")
            return

        def resolve_call(current_fname, target_str):
            target_str = target_str.strip()
            if target_str.startswith('Global.'):
                return ('em013_55.nack', target_str[7:])
            elif target_str.startswith('fatalis.'):
                return (current_fname, target_str[8:])
            else:
                return (current_fname, target_str)

        def inline_expand(parent, fname, func_name, prefix_conds=None, depth=0):
            if depth > 20:
                return
            if prefix_conds is None:
                prefix_conds = []

            parent_id = str(parent)
            visit_key = (parent_id, fname, func_name, tuple(prefix_conds))
            if visit_key in self._visited_expand:
                return
            self._visited_expand.add(visit_key)

            data = self.files_data.get(fname)
            if not data:
                return

            # 处理 random 块（即有权重的动作）
            for block in data['blocks']:
                if block.func_name != func_name:
                    continue
                merged = prefix_conds + block.condition_path

                cur = parent
                cond_depth = 0
                for cond in merged:
                    cond_depth += 1
                    desc = describe_single_condition(cond, self.condition_map)
                    # 查找或创建节点（用 values[0] 存储原始描述用于匹配）
                    found = None
                    for child in self.tree.get_children(cur):
                        cv = self.tree.item(child, 'values')
                        if cv and cv[0] == desc:
                            found = child
                            break
                    if found:
                        cur = found
                    else:
                        # 深度标签：0-5+ 对应不同颜色
                        d_tag = f'd{min(cond_depth, 5)}'
                        bg_tag = 'bg_even' if cond_depth % 2 == 0 else 'bg_odd'
                        cur = self.tree.insert(cur, 'end',
                                               text='◇ ' + desc,
                                               values=(desc,),
                                               tags=(d_tag, bg_tag),
                                               open=False)
                for act in block.actions:
                    disp = self.get_move_display(act.target)
                    d_tag = f'd{min(cond_depth + 1, 5)}'
                    bg_tag = 'bg_even' if (cond_depth + 1) % 2 == 0 else 'bg_odd'
                    self.tree.insert(cur, 'end',
                                     text='○ {0} → {1}'.format(act.weight, disp),
                                     values=(fname, act.line_no, act.weight, act.target),
                                     tags=(d_tag, bg_tag),
                                     open=False)

            # 处理无条件跳转（>> node_xxx），保留展开，因为这些是你手动指定的结构
            for call_conds, target_str in data['calls'].get(func_name, []):
                resolved = resolve_call(fname, target_str)
                if not resolved: continue
                next_fname, next_func = resolved
                cur = parent
                for cond in call_conds:
                    desc = describe_single_condition(cond, self.condition_map)
                    found = None
                    for child in self.tree.get_children(cur):
                        cv = self.tree.item(child, 'values')
                        if cv and cv[0] == desc:
                            found = child; break
                    if found: cur = found
                    else: cur = self.tree.insert(cur, 'end', text='◇ ' + desc,
                                                 values=(desc,), open=False)
                inline_expand(cur, next_fname, next_func, [], depth + 1)

        # ========================
        # 辅助：创建带深度标签的静态节点
        def _stag(parent, text, d, bold=False, **kw):
            tags = [f'd{d}', 'bg_even' if d % 2 == 0 else 'bg_odd']
            if bold:
                tags.append(f'd{d}_bold')
            return self.tree.insert(parent, 'end', text=text, tags=tags, **kw)

        root = _stag('', '黑龙 AI', 0, bold=True, open=True)

        # ===== 一、黑龙反钩爪 =====
        b1 = _stag(root, '一、黑龙反钩爪', 1, open=False)

        fly_node = _stag(b1, '飞天', 2, open=False)
        inline_expand(fly_node, 'em013_55.nack', 'node_004', prefix_conds=['self.flying()'])

        two_node = _stag(b1, '二足', 2, open=False)
        for sub in ['node_005', 'node_006', 'node_007']:
            label = self.node_label_map.get(sub, sub)
            sub_node = _stag(two_node, label, 2, open=False)
            inline_expand(sub_node, 'em013_55.nack', sub)

        four_node = _stag(b1, '四足', 2, open=False)
        for sub in ['node_008', 'node_009', 'node_010']:
            label = self.node_label_map.get(sub, sub)
            sub_node = _stag(four_node, label, 2, open=False)
            inline_expand(sub_node, 'em013_55.nack', sub)

        # ===== 二、黑龙飞行 =====
        b2 = _stag(root, '二、黑龙飞行', 1, open=False)

        plat = _stag(b2, '玩家在高台', 2, open=False)
        inline_expand(plat, 'em013_00.nack', 'node_051')

        d1 = _stag(b2, '玩家在地面且水平距离≤1000', 2, open=False)
        c1a = _stag(d1, '非三阶段', 2, open=False)
        inline_expand(c1a, 'em013_00.nack', 'node_056')
        c1b = _stag(d1, '三阶段', 2, open=False)
        inline_expand(c1b, 'em013_00.nack', 'node_059')

        d2 = _stag(b2, '玩家在地面且水平距离≤5000', 2, open=False)
        c2a = _stag(d2, '非三阶段', 2, open=False)
        inline_expand(c2a, 'em013_00.nack', 'node_057')
        c2b = _stag(d2, '三阶段', 2, open=False)
        inline_expand(c2b, 'em013_00.nack', 'node_060')

        d3 = _stag(b2, '玩家在地面且水平距离>5000', 2, open=False)
        c3a = _stag(d3, '非三阶段', 2, open=False)
        inline_expand(c3a, 'em013_00.nack', 'node_058')
        c3b = _stag(d3, '三阶段', 2, open=False)
        inline_expand(c3b, 'em013_00.nack', 'node_061')

        # ===== 三、黑龙在地面 =====
        b3 = _stag(root, '三、黑龙在地面', 1, open=False)

        n1 = _stag(b3, '一阶段玩家在高台', 2, open=False)
        inline_expand(n1, 'em013_00.nack', 'node_041')

        n2 = _stag(b3, '二三阶段玩家在高台', 2, open=False)
        inline_expand(n2, 'em013_00.nack', 'node_051')

        n4 = _stag(b3, '特殊：一阶段二足七招以后车的概率', 2, open=False)
        inline_expand(n4, 'em013_00.nack', 'node_015')

        n5 = _stag(b3, '特殊：防空AI（距离代表离地面高度）', 2, open=False)
        inline_expand(n5, 'em013_00.nack', 'node_019')

        # 二足
        data00 = self.files_data.get('em013_00.nack')
        data00calls = data00.get('calls', {}) if data00 else {}
        two_g = _stag(b3, '二足', 2, open=False)
        for call_conds, target_str in data00calls.get('node_009', []):
            if any('function#101()' in c and 'function#101(1)' not in c for c in call_conds):
                res = resolve_call('em013_00.nack', target_str)
                if res:
                    pref = [c for c in call_conds if 'function#101()' not in c]
                    inline_expand(two_g, res[0], res[1], pref)

        # 四足
        four_g = self.tree.insert(b3, 'end', text='四足', open=False)
        for call_conds, target_str in data00calls.get('node_009', []):
            if any('function#101(1)' in c for c in call_conds):
                res = resolve_call('em013_00.nack', target_str)
                if res:
                    pref = [c for c in call_conds if 'function#101(1)' not in c]
                    inline_expand(four_g, res[0], res[1], pref)

        n8 = _stag(b3, '受击追击AI', 2, open=False)
        inline_expand(n8, 'em013_00.nack', 'node_109')
        n8_node110 = _stag(n8, 'node_110 内部调整', 2, open=False)
        inline_expand(n8_node110, 'em013_00.nack', 'node_110')

        n9 = _stag(b3, '视野遮挡', 2, open=False)
        inline_expand(n9, 'em013_00.nack', 'node_038')

        # ===== 四、后续更新的功能 =====
        b4 = _stag(root, '四、后续更新的功能', 1, open=False)
        n_future = _stag(b4, '一阶段瓦砾AI', 2, open=False)
        inline_expand(n_future, 'em013_00.nack', 'node_035')

        # ===== 五、部分计数器和数据设置 =====
        b5 = _stag(root, '五、部分计数器和数据设置', 1, open=False)

        # 数据节点：用 d3 标签 + 暗色背景
        _d3 = 'bg_even'
        def _data(parent, text, lines, val, pattern):
            return self.tree.insert(parent, 'end', text=text,
                values=('data', 'em013_00.nack', json.dumps(lines), val, pattern),
                tags=('d2', _d3), open=False)

        # 数据节点
        _data(b5, '计数器0(二足招式计数器，控制转四足) = 15', [407, 471], 15,
              r"(\[RegisterVar0\s*>=\s*)\d+")
        _data(b5, '计数器1(四足招式计数器，控制转二足) = 15', [434, 498], 15,
              r"(\[RegisterVar1\s*>=\s*)\d+")

        c3 = _stag(b5, '计数器3(二三阶段地面招式计数器，控制起飞)', 2, open=False)
        _data(c3, '最少招式数 = 35', [101, 113], 35, r"(\[RegisterVar3\s*>=\s*)\d+")
        _data(c3, '最多招式数 = 50', [98, 110], 50, r"(\[RegisterVar3\s*>=\s*)\d+")

        c4 = _stag(b5, '计数器4(飞行招式计数器，控制降落)', 2, open=False)
        _data(c4, '最少额外概率招式数 = 3', [73, 85], 3, r"(\[RegisterVar4\s*>=\s*)\d+")
        _data(c4, '最多招式数 = 7', [70, 82], 7, r"(\[RegisterVar4\s*>=\s*)\d+")

        _data(b5, '黑龙一转二血量百分比 = 77', [572], 77, r"(\.leq\()\d+")
        _data(b5, '黑龙二转三血量百分比 = 49', [588], 49, r"(\.leq\()\d+")
        _data(b5, '黑龙劫火1血量百分比 = 5', [668], 5, r"(\.leq\()\d+")
        _data(b5, '黑龙劫火2血量百分比 = 25', [683], 25, r"(\.leq\()\d+")
        _data(b5, '黑龙劫火3血量百分比 = 40', [697], 40, r"(\.leq\()\d+")

        self.status_var.set('AI行为树加载完成')

    # ---------- 树选择与右侧面板控制 ----------
    def on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            self._disable_weight_edit()
            return
        vals = self.tree.item(sel[0]).get('values')
        if vals and len(vals) >= 4:
            # 旧格式兼容：如果第一个值不是 'weight' 或 'data'，且第四个值不是以 '@' 开头，视为招式节点
            if vals[0] not in ('weight', 'data') and not str(vals[3]).startswith('@'):
                # 旧招式节点: (fname, line_no, weight, target)
                fname, line_no, weight, target = vals
                self.current_selection = ('weight', fname, int(line_no), int(weight), target)
                self.weight_var.set(str(weight))
                self.info_text.set(f"文件: {fname}\n目标: {target}\n当前权重: {weight}")
                self.weight_entry.config(state='normal')
                self.apply_btn.config(state='normal')
                return
            # 新格式
            sel_type = vals[0]
            if sel_type == 'weight':
                fname, line_no, weight, target = vals[1:]
                self.current_selection = ('weight', fname, int(line_no), int(weight), target)
                self.weight_var.set(str(weight))
                self.info_text.set(f"文件: {fname}\n目标: {target}\n当前权重: {weight}")
                self.weight_entry.config(state='normal')
                self.apply_btn.config(state='normal')
            elif sel_type == 'data':
                fname = vals[1]
                lines = json.loads(vals[2])
                cur_val = int(vals[3])
                pattern = vals[4]
                self.current_selection = ('data', fname, lines, cur_val, pattern)
                self.weight_var.set(str(cur_val))
                line_info = f"将同步修改 {len(lines)} 行" if len(lines) > 1 else "单行修改"
                self.info_text.set(f"文件: {fname}\n{line_info}\n当前值: {cur_val}")
                self.weight_entry.config(state='normal')
                self.apply_btn.config(state='normal')
            else:
                self.current_selection = None
                self._disable_weight_edit()
        else:
            self.current_selection = None
            self._disable_weight_edit()

    def _disable_weight_edit(self):
        self.weight_var.set('')
        self.info_text.set("（非招式节点，无法修改）")
        self.weight_entry.config(state='disabled')
        self.apply_btn.config(state='disabled')

    # ---------- 修改与保存 ----------
    def apply_weight(self):
        if not self.current_selection:
            messagebox.showwarning("提示", "请先选择一个招式或数据项")
            return
        try:
            new_value = int(self.weight_var.get())
        except ValueError:
            messagebox.showerror("错误", "必须输入整数")
            return
        if new_value < 0:
            messagebox.showerror("错误", "数值不能为负")
            return

        sel_type = self.current_selection[0]

        if sel_type == 'weight':
            _, fname, line_no, old_weight, target = self.current_selection
            data = self.files_data.get(fname)
            if not data:
                messagebox.showerror("错误", f"找不到文件 {fname} 的数据")
                return
            if line_no < 0 or line_no >= len(data['lines']):
                messagebox.showerror("错误", f"行号 {line_no} 超出文件范围")
                return
            data['changes'][line_no] = new_value
            sel = self.tree.selection()[0]
            old_text = self.tree.item(sel, 'text')
            new_text = re.sub(r'^\d+', str(new_value), old_text)
            self.tree.item(sel, text=new_text)
            self.current_selection = ('weight', fname, line_no, new_value, target)
            self._update_pending_status()

        elif sel_type == 'data':
            _, fname, lines, old_val, pattern = self.current_selection
            data = self.files_data.get(fname)
            if not data:
                messagebox.showerror("错误", f"找不到文件 {fname} 的数据")
                return
            # 存储时用 tuple(lines) 作为 key，便于保存时识别
            key = tuple(lines)
            if 'data_changes' not in data:
                data['data_changes'] = {}
            data['data_changes'][key] = (new_value, pattern)
            
            



            # 更新树节点显示文本
            sel = self.tree.selection()[0]
            old_text = self.tree.item(sel, 'text')
            new_text = re.sub(r'= \d+', f'= {new_value}', old_text)
            self.tree.item(sel, text=new_text)
            self.current_selection = ('data', fname, lines, new_value, pattern)
            self._update_pending_status()

    def save_changes(self):
        if self._saving:
            return
        if self._compiling:
            messagebox.showwarning("提示", "正在编译中，请等待完成后再保存。")
            return

        # 统计待保存数量（包括权重和数据）
        total = sum(len(data.get('changes', {})) for data in self.files_data.values())
        total += sum(len(data.get('data_changes', {})) for data in self.files_data.values())
        if total == 0:
            messagebox.showinfo("提示", "当前没有需要保存的修改。")
            return

        self._saving = True
        errors = []
        try:
            for fname, data in self.files_data.items():
                if not data.get('changes') and not data.get('data_changes'):
                    continue

                # 复制原始行用于修改
                lines_copy = data['lines'].copy()

                # 1. 处理招式权重修改
                for line_no, new_weight in data.get('changes', {}).items():
                    try:
                        lines_copy[line_no] = re.sub(
                            r'(\(\s*)\d+(\s*\))',
                            rf'\g<1>{new_weight}\g<2>',
                            lines_copy[line_no]
                        )
                    except Exception as e:
                        errors.append(f"[{fname}] 权重行 {line_no} 出错: {e}")
                        break  # 中断当前文件的处理，但不影响其他文件

                # 2. 处理数据修改（计数器、血量等）
                dc = data.get('data_changes')
                if dc:
                    data_ok = True
                    for lines_key, (new_val, pattern) in dc.items():
                        if not data_ok:
                            break
                        for line_no in lines_key:
                            try:
                                new_line = re.sub(pattern, rf'\g<1>{new_val}', lines_copy[line_no])
                                if new_line == lines_copy[line_no]:
                                    raise ValueError(f"正则未匹配：{pattern}")
                                lines_copy[line_no] = new_line
                            except Exception as e:
                                errors.append(f"[{fname}] 数据行 {line_no} 出错: {e}")
                                data_ok = False
                                break
                    if data_ok:
                        data['data_changes'] = {}
                    else:
                        # 如果数据修改失败，则跳过文件写入
                        continue

                # 3. 写入文件
                path = data['path']
                tmp_path = path + '.tmp'
                if os.path.exists(tmp_path):
                    try: os.remove(tmp_path)
                    except: pass

                try:
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        f.writelines(lines_copy)
                    os.replace(tmp_path, path)
                    data['lines'] = lines_copy
                    data['changes'] = {}
                except Exception as e:
                    errors.append(f"[{fname}] 文件写入失败: {e}")

            # 4. 显示结果
            if errors:
                self.status_var.set(f"保存时发生 {len(errors)} 个错误")
                messagebox.showerror("保存错误", "以下文件保存失败：\n" + "\n".join(errors))
            else:
                self.status_var.set('已保存修改')
                messagebox.showinfo("保存成功", "修改已成功保存。")

        except Exception as e:
            self.status_var.set("保存失败")
            messagebox.showerror("严重错误", f"保存过程中发生未预期的错误：\n{e}")
        finally:
            self._saving = False
            self._update_pending_status()

    # ---------- 编译（强化版，自动诊断） ----------
    def compile_thk(self, output_dir):
        compiler_src = resource_path(os.path.join('data', 'compiler_src'))
        if not os.path.isdir(compiler_src):
            raise FileNotFoundError(f"编译器源码目录缺失: {compiler_src}")

        # 检查必需文件
        main_py = os.path.join(compiler_src, 'compilerMain.py')
        if not os.path.isfile(main_py):
            raise FileNotFoundError(f"缺少 compilerMain.py: {main_py}")

        # 添加路径
        if compiler_src not in sys.path:
            sys.path.insert(0, compiler_src)

        # 尝试导入并捕获所有错误
        try:
            import compilerMain
        except Exception as e:
            # 收集详细信息
            details = f"导入编译器失败: {e}\n\n"
            details += f"sys.path 包含: {sys.path[:3]}...\n"
            details += f"编译器目录: {compiler_src}\n"
            details += f"目录内容: {os.listdir(compiler_src)[:10]}\n"
            # 检查是否缺少依赖库
            try:
                import construct
            except ImportError:
                details += "\n【缺失库】construct 未安装，请执行: pip install construct"
            try:
                import lark
            except ImportError:
                details += "\n【缺失库】lark-parser 未安装，请执行: pip install lark-parser"
            raise RuntimeError(details)

        # 准备临时工作目录
        temp_base = os.path.join(self.user_dir, '_build')
        shutil.rmtree(temp_base, ignore_errors=True)
        os.makedirs(temp_base)
        temp_work = os.path.join(temp_base, 'work')
        shutil.copytree(self.workspace_dir, temp_work)

        fand_files = [f for f in os.listdir(temp_work) if f.endswith('.fand')]
        if not fand_files:
            raise FileNotFoundError("工作区中无 .fand 文件")
        fand_path = os.path.join(temp_work, fand_files[0])

        compiled_dir = os.path.join(temp_base, 'compiled')
        os.makedirs(compiled_dir, exist_ok=True)

        log_dir = os.path.join(self.user_dir, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'compile.log')

        # 调用编译器主函数
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        try:
            with open(log_file, 'w', encoding='utf-8') as log:
                sys.stdout = log
                sys.stderr = log
                args = [
                    fand_path,
                    '-outputRoot', compiled_dir,
                    '-projectNames', 'index'
                ]
                compilerMain.main(args)
        except Exception as e:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            with open(log_file, 'a', encoding='utf-8') as log:
                log.write(f"\n[ERROR] {traceback.format_exc()}\n")
            raise RuntimeError(f"编译失败，请查看日志 {log_file}")
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

        if not os.path.isdir(compiled_dir) or not any(f.endswith('.thk') for f in os.listdir(compiled_dir)):
            raise FileNotFoundError("编译未生成 .thk 文件，请查看日志 " + log_file)

        os.makedirs(output_dir, exist_ok=True)
        for f in os.listdir(compiled_dir):
            full = os.path.join(compiled_dir, f)
            if f.endswith('.thklst'):
                os.remove(full)
            elif f.endswith('.thk') and f.startswith('em000_'):
                new_name = f.replace('em000_', 'em013_', 1)
                shutil.copy2(full, os.path.join(output_dir, new_name))
            elif f.endswith('.thk'):
                shutil.copy2(full, os.path.join(output_dir, f))

        shutil.rmtree(temp_base, ignore_errors=True)

    def _compile_thread(self, output_dir, success_callback, error_callback):
        try:
            self.compile_thk(output_dir)
            self.root.after(0, success_callback, output_dir)
        except Exception as e:
            self.root.after(0, error_callback, str(e))

    def _on_compile_success(self, output_dir):
        self._enable_buttons()
        self._compiling = False
        self.status_var.set("编译成功")
        messagebox.showinfo("编译完成", f"文件已生成到:\n{output_dir}")

    def _on_compile_error(self, error_msg):
        self._enable_buttons()
        self._compiling = False
        self.status_var.set(f"编译失败")
        messagebox.showerror("编译失败", error_msg)

    def _start_compile(self, output_dir, purpose="导出"):
        if self._compiling:
            messagebox.showwarning("提示", "当前正在编译中，请等待完成。")
            return
        if any(data['changes'] for data in self.files_data.values()):
            if messagebox.askyesno("提示", "有未保存的修改，是否先保存？"):
                self.save_changes()
                if any(data['changes'] for data in self.files_data.values()):
                    if not messagebox.askyesno("警告", "仍有修改未保存，是否继续编译？\n（编译将基于上次保存的文件）"):
                        return

        self._compiling = True
        self._disable_buttons()
        self.status_var.set(f"编译中（{purpose}），请稍候...")
        threading.Thread(target=self._compile_thread, args=(output_dir, self._on_compile_success, self._on_compile_error), daemon=True).start()

    def _disable_buttons(self):
        self.save_btn.config(state='disabled')
        self.export_btn.config(state='disabled')
        self.deploy_btn.config(state='disabled')
        self.reset_btn.config(state='disabled')

    def _enable_buttons(self):
        self.save_btn.config(state='normal')
        self.export_btn.config(state='normal')
        self.deploy_btn.config(state='normal')
        self.reset_btn.config(state='normal')

    def export_thk(self):
        export_dir = filedialog.askdirectory(title="选择导出文件夹")
        if not export_dir: return
        self._start_compile(export_dir, "导出")

    def auto_deploy(self):
        settings = load_settings()
        game_dir = settings.get('game_dir', '')
        if not game_dir or not os.path.isdir(game_dir):
            messagebox.showerror("错误", "请先设置正确的游戏根目录（包含 MonsterHunterWorld.exe 的文件夹）")
            return
        deploy_dir = os.path.join(game_dir, 'nativePC', 'em', 'em013', '00', 'data')
        self._start_compile(deploy_dir, "部署")

    # ---------- 其他方法 ----------
    def back_to_mode(self):
        self.root.destroy()
        ModeSelectionWindow()

    def on_close(self):
        if any(data['changes'] for data in self.files_data.values()):
            resp = messagebox.askyesnocancel("提示", "有未保存修改。\n「是」保存后退出，「否」不保存退出，「取消」返回")
            if resp is None: return
            if resp: self.save_changes()
        self.root.destroy()

    def show_help(self):
        msg = (
            "1. 设置游戏目录（选择 MonsterHunterWorld.exe 所在文件夹）\n"
            "2. 在左侧树点击招式 -> 输入新权重 -> 点击应用\n"
            "3. 点击保存修改写入文件\n"
            "4. 点击部署到游戏自动编译并复制文件\n"
            "（编译日志位于：%s\\logs\\compile.log）" % self.user_dir
        )
        messagebox.showinfo("帮助", msg)

    def show_about(self):
        messagebox.showinfo("关于", "怪物猎人世界 黑龙AI编辑器 v1.0\n内置编译引擎，开箱即用\n研究学习使用，严禁用于竞速作弊")

    def run(self):
        self.root.mainloop()

if __name__ == '__main__':
    ModeSelectionWindow()