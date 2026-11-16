import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageOps, __version__ as PIL_VERSION
except ImportError:
    print("请先安装 Pillow：pip install Pillow")
    sys.exit(1)

# 显示名 -> (扩展名, Pillow 格式名)
FORMATS = {
    "JPEG (.jpg)":  ("jpg",  "JPEG"),
    "PNG (.png)":   ("png",  "PNG"),
    "WebP (.webp)": ("webp", "WEBP"),
    "BMP (.bmp)":   ("bmp",  "BMP"),
    "TIFF (.tiff)": ("tiff", "TIFF"),
    "GIF (.gif)":   ("gif",  "GIF"),
    "ICO (.ico)":   ("ico",  "ICO"),
}

IMG_TYPES = [
    ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.tif *.gif *.ico *.ppm *.pgm *.tga"),
    ("所有文件", "*.*"),
]
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
        ".gif", ".ico", ".ppm", ".pgm", ".tga"}


# ---------------- 核心转换逻辑 ----------------

def flatten_to_rgb(img: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    """把带透明通道的图像压平到白底 RGB（JPEG/BMP 不支持透明）。"""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, bg)
        background.paste(img, mask=img.split()[-1])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def parse_size(w_text: str, h_text: str, orig: tuple) -> tuple | None:
    """计算目标尺寸。0 表示按原比例自动推算；都为 0 则返回 None（保持原尺寸）。"""
    try:
        w = int(w_text.strip() or "0")
        h = int(h_text.strip() or "0")
    except ValueError:
        raise ValueError("尺寸必须为整数")
    if w < 0 or h < 0:
        raise ValueError("尺寸不能为负数")
    ow, oh = orig
    if w == 0 and h == 0:
        return None
    if w == 0:
        w = max(1, int(ow * h / oh))
    elif h == 0:
        h = max(1, int(oh * w / ow))
    return (w, h)


def convert_one(src, dst, target_fmt, quality, w_text, h_text, keep_exif):
    with Image.open(src) as im:
        # 按 EXIF 方向信息自动旋正（手机拍的照片常带旋转标记）
        im = ImageOps.exif_transpose(im)

        # 提取原始 EXIF（仅 JPEG 保存时可用）
        exif_bytes = None
        if keep_exif and target_fmt == "JPEG":
            try:
                exif_bytes = im.info.get("exif")
            except Exception:
                exif_bytes = None

        # 调整尺寸
        new_size = parse_size(w_text, h_text, im.size)
        if new_size:
            im = im.resize(new_size, Image.LANCZOS)

        # 目标格式的模式适配
        if target_fmt in ("JPEG", "BMP"):
            im = flatten_to_rgb(im)
        elif target_fmt == "ICO":
            im = im.convert("RGBA")
        elif im.mode == "P" and target_fmt not in ("GIF", "PNG"):
            im = im.convert("RGBA")

        # 组装保存参数
        kw = {}
        if target_fmt == "JPEG":
            kw.update(quality=quality, optimize=True, progressive=True)
            if exif_bytes:
                kw["exif"] = exif_bytes
        elif target_fmt == "WEBP":
            kw.update(quality=quality, method=6)
        elif target_fmt == "PNG":
            kw.update(optimize=True, compress_level=6)
        elif target_fmt == "TIFF":
            kw.update(compression="tiff_lzw")
        elif target_fmt == "ICO":
            max_dim = min(256, max(im.size))
            sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max_dim]
            kw["sizes"] = sizes or [(max_dim, max_dim)]

        im.save(dst, target_fmt, **kw)


# ---------------- GUI ----------------

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.files: list[str] = []
        self.busy = False
        self.stop_flag = False

        root.title("图片格式转换器 · Pillow GUI")
        root.geometry("860x660")
        root.minsize(760, 600)

        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=2)   # 文件列表
        main.rowconfigure(5, weight=3)   # 日志

        # 1) 文件选择
        f1 = ttk.LabelFrame(main, text="1. 选择图片", padding=8)
        f1.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(f1, text="添加文件…", command=self.add_files).pack(side="left")
        ttk.Button(f1, text="添加文件夹…", command=self.add_folder).pack(side="left", padx=6)
        ttk.Button(f1, text="清空", command=self.clear_files).pack(side="left")
        self.count_label = ttk.Label(f1, text="已选择 0 个文件")
        self.count_label.pack(side="right")

        # 2) 文件列表
        lf = ttk.Frame(main)
        lf.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(lf, height=6)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb1 = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        sb1.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb1.set)

        # 3) 输出设置
        f2 = ttk.LabelFrame(main, text="2. 输出设置", padding=8)
        f2.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        f2.columnconfigure(3, weight=1)

        ttk.Label(f2, text="目标格式：").grid(row=0, column=0, sticky="w")
        self.fmt_var = tk.StringVar(value="PNG (.png)")
        self.fmt_cb = ttk.Combobox(f2, textvariable=self.fmt_var, values=list(FORMATS),
                                   state="readonly", width=16)
        self.fmt_cb.grid(row=0, column=1, sticky="w", padx=(4, 20))
        self.fmt_cb.bind("<<ComboboxSelected>>", lambda e: self._update_quality_state())

        ttk.Label(f2, text="输出目录：").grid(row=0, column=2, sticky="w")
        self.outdir_var = tk.StringVar()
        ttk.Entry(f2, textvariable=self.outdir_var).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Button(f2, text="浏览…", command=self.choose_outdir).grid(row=0, column=4)

        ttk.Label(f2, text="质量（JPEG/WebP）：").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.quality_var = tk.IntVar(value=90)
        self.quality_scale = ttk.Scale(f2, from_=1, to=100, variable=self.quality_var,
                                       orient="horizontal")
        self.quality_scale.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(10, 0))
        self.quality_label = ttk.Label(f2, text="90", width=4)
        self.quality_label.grid(row=1, column=3, sticky="w", pady=(10, 0))
        self.quality_var.trace_add("write", lambda *a: self.quality_label.configure(
            text=str(self.quality_var.get())))

        ttk.Label(f2, text="尺寸（宽×高，0=自动）：").grid(row=2, column=0, sticky="w", pady=(10, 0))
        size_frame = ttk.Frame(f2)
        size_frame.grid(row=2, column=1, columnspan=4, sticky="w", pady=(10, 0))
        self.w_var = tk.StringVar(value="0")
        self.h_var = tk.StringVar(value="0")
        ttk.Entry(size_frame, textvariable=self.w_var, width=8).pack(side="left")
        ttk.Label(size_frame, text=" × ").pack(side="left")
        ttk.Entry(size_frame, textvariable=self.h_var, width=8).pack(side="left")
        ttk.Label(size_frame, text="  例如 1920×0 或 0×1080 保持比例；0×0 保持原尺寸",
                  foreground="#888").pack(side="left", padx=8)

        self.exif_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f2, text="JPEG 输出时保留原始 EXIF 信息",
                        variable=self.exif_var).grid(row=3, column=1, columnspan=3,
                                                     sticky="w", pady=(10, 0))

        # 4) 操作区
        f3 = ttk.Frame(main)
        f3.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        f3.columnconfigure(1, weight=1)
        self.btn_start = ttk.Button(f3, text="开始转换", command=self.start)
        self.btn_start.grid(row=0, column=0, padx=(0, 12))
        self.pbar = ttk.Progressbar(f3, mode="determinate", maximum=100)
        self.pbar.grid(row=0, column=1, sticky="ew")
        self.pct_label = ttk.Label(f3, text="  0%", width=6)
        self.pct_label.grid(row=0, column=2)

        # 5) 日志
        lf2 = ttk.LabelFrame(main, text="日志", padding=4)
        lf2.grid(row=5, column=0, sticky="nsew")
        lf2.rowconfigure(0, weight=1)
        lf2.columnconfigure(0, weight=1)
        self.log_text = tk.Text(lf2, height=8, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(lf2, orient="vertical", command=self.log_text.yview)
        sb2.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb2.set)

        self._update_quality_state()
        self.log(f"Pillow 版本：{PIL_VERSION}")
        self.log("就绪。添加图片后点击“开始转换”。")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- 工具 ----------
    def log(self, msg: str):
        def _do():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg.rstrip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, _do)

    def _update_quality_state(self):
        ext, fmt = FORMATS[self.fmt_var.get()]
        self.quality_scale.configure(state="normal" if fmt in ("JPEG", "WEBP") else "disabled")

    def _update_count(self):
        self.count_label.configure(text=f"已选择 {len(self.files)} 个文件")

    # ---------- 事件 ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(title="选择图片", filetypes=IMG_TYPES)
        if not paths:
            return
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", os.path.basename(p))
        self._update_count()
        if not self.outdir_var.get():
            self.outdir_var.set(os.path.dirname(paths[0]))

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择包含图片的文件夹")
        if not folder:
            return
        added = 0
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and os.path.splitext(name)[1].lower() in EXTS:
                if path not in self.files:
                    self.files.append(path)
                    self.listbox.insert("end", name)
                    added += 1
        self._update_count()
        if added and not self.outdir_var.get():
            self.outdir_var.set(folder)
        self.log(f"从文件夹添加了 {added} 个图片。")

    def clear_files(self):
        self.files.clear()
        self.listbox.delete(0, "end")
        self._update_count()

    def choose_outdir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.outdir_var.set(d)

    # ---------- 转换流程 ----------
    def start(self):
        if self.busy:
            return
        if not self.files:
            messagebox.showwarning("提示", "请先添加图片。")
            return
        outdir = self.outdir_var.get().strip()
        if not outdir:
            messagebox.showwarning("提示", "请选择输出目录。")
            return
        os.makedirs(outdir, exist_ok=True)

        self.busy = True
        self.stop_flag = False
        self.btn_start.configure(state="disabled")
        self.pbar["value"] = 0
        self.pct_label.configure(text="  0%")
        self.log("─" * 50)
        self.log(f"开始转换 {len(self.files)} 张图片 → {FORMATS[self.fmt_var.get()][1]}")

        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        ext, fmt = FORMATS[self.fmt_var.get()]
        outdir = self.outdir_var.get().strip()
        q = self.quality_var.get()
        w_text = self.w_var.get()
        h_text = self.h_var.get()
        keep_exif = self.exif_var.get()

        total = len(self.files)
        success, failed = 0, []

        for i, src in enumerate(self.files, 1):
            if self.stop_flag:
                self.log("✘ 用户中止。")
                break
            name = os.path.splitext(os.path.basename(src))[0]
            dst = os.path.join(outdir, f"{name}.{ext}")
            if os.path.abspath(src) == os.path.abspath(dst):
                dst = os.path.join(outdir, f"{name}_converted.{ext}")
            try:
                convert_one(src, dst, fmt, q, w_text, h_text, keep_exif)
                success += 1
                self.log(f"[{i}/{total}] ✔ {os.path.basename(src)} → {os.path.basename(dst)}")
            except Exception as e:
                failed.append((src, str(e)))
                self.log(f"[{i}/{total}] ✘ {os.path.basename(src)}：{e}")
            self.root.after(0, self._update_progress, int(i / total * 100))

        self.root.after(0, self._finish, success, failed, total)

    def _update_progress(self, pct):
        self.pbar["value"] = pct
        self.pct_label.configure(text=f"{pct:3d}%")

    def _finish(self, success, failed, total):
        self.busy = False
        self.btn_start.configure(state="normal")
        if success == total:
            self.log(f"✔ 全部完成：{success}/{total}")
            messagebox.showinfo("完成", f"成功转换 {success} 张图片。")
        elif success > 0:
            self.log(f"⚠ 部分完成：成功 {success}，失败 {len(failed)}，共 {total}")
            messagebox.showwarning("完成", f"成功 {success}，失败 {len(failed)}。详见日志。")
        else:
            self.log("✘ 全部失败。")
            messagebox.showerror("失败", "全部图片转换失败，详见日志。")

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno("确认", "正在转换中，确定要退出吗？"):
                return
            self.stop_flag = True
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    try:
        s = ttk.Style()
        for name in ("vista", "clam", "default"):
            if name in s.theme_names():
                s.theme_use(name)
                break
    except Exception:
        pass
    App(root)
    root.mainloop()
