"""Interfaz Tkinter del ordenador de fotos (paso 1 del flujo).

Atajos:
    Enter        guardar (mover/copiar) y pasar a la siguiente
    Ctrl+Z       deshacer (ilimitado)
    ← / →        foto anterior / siguiente sin guardar
    F2 / F3      foco en NODO / ITEM
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from PIL import Image, ImageTk

from . import undo as undo_ops
from .config import Preferencias, raiz_proyecto
from .imagen import crop_bottom_right, open_image, resize_to_fit
from .nodos import CatalogoNodos, normalize_node_input
from .ocr import Sugerencia, ocr_disponible, sugerir
from .registro import RegistroAcciones
from .rutas import build_dest_folder, list_images, normalize_item_input

NO_EN_LISTA = "NO EN LISTA"


class FieldPhotoSorterApp:
    """Ventana principal: vista previa, recorte del rótulo y asignación NODO/ITEM."""

    def __init__(self, root: tk.Tk, prefs: Optional[Preferencias] = None):
        self.root = root
        self.root.title("Field Ops — Ordenador de fotos NODO / ITEM")
        self.prefs = prefs or Preferencias.cargar()
        self.catalogo = CatalogoNodos.por_defecto(raiz_proyecto())

        self.src_dir = tk.StringVar(value=self.prefs.src_dir)
        self.out_dir = tk.StringVar(value=self.prefs.out_dir)
        self.mode = tk.StringVar(value=self.prefs.modo)
        self.operador = tk.StringVar(value=self.prefs.operador or os.environ.get("FIELD_OPS_OPERADOR", ""))
        self.usar_ocr = tk.BooleanVar(value=self.prefs.usar_ocr)

        self.node_num = tk.StringVar()
        self.node_code = tk.StringVar()
        self.localidad = tk.StringVar()
        self.item_val = tk.StringVar()
        self.sugerencia_txt = tk.StringVar(value="Sugerencia: -")
        self.status = tk.StringVar()

        self.files: List[Path] = []
        self.idx = 0
        self.undo_stack = undo_ops.UndoStack()
        self.registro: Optional[RegistroAcciones] = None

        self._photo_main = None
        self._photo_crop = None
        self._im_cache: Optional[Image.Image] = None
        self._loc_auto = ""          # última localidad puesta automáticamente
        self._ediciones = 0          # cambia cuando el operador escribe (para no pisarlo con el OCR)
        self._sugerencia_actual = Sugerencia()
        self._cola: "queue.Queue[tuple[Path, Sugerencia, int]]" = queue.Queue()
        self._resize_job: Optional[str] = None

        self._build_ui()
        self._bind_keys()
        self._refresh_ui_state()
        self._revisar_cola()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        # escala por DPI (pantallas al 125-150 %): 1.0 = 96 dpi
        self._esc = max(1.0, float(self.root.tk.call("tk", "scaling")) / (96 / 72))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{min(int(1280 * self._esc), sw - 60)}x{min(int(780 * self._esc), sh - 90)}")
        self.root.minsize(min(int(1000 * self._esc), sw - 60), min(int(640 * self._esc), sh - 90))
        ancho_panel = int(380 * self._esc)
        wrap = ancho_panel - int(40 * self._esc)

        top = ttk.Frame(self.root, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Fuente (carpeta con fotos):").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.src_dir, width=70).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(top, text="Elegir...", command=self.pick_src).grid(row=0, column=2, padx=4)

        ttk.Label(top, text="Salida (carpeta base):").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.out_dir, width=70).grid(row=1, column=1, sticky="we", padx=6)
        ttk.Button(top, text="Elegir...", command=self.pick_out).grid(row=1, column=2, padx=4)

        ttk.Label(top, text="Operador:").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.operador, width=30).grid(row=2, column=1, sticky="w", padx=6)

        opts = ttk.Frame(top)
        opts.grid(row=0, column=3, rowspan=3, padx=(12, 0), sticky="ns")
        ttk.Label(opts, text="Modo:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(opts, text="MOVE (mover)", variable=self.mode, value="move").grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(opts, text="COPY (copiar)", variable=self.mode, value="copy").grid(row=2, column=0, sticky="w")
        ocr_txt = "OCR rótulo (Tesseract)" if ocr_disponible() else "OCR (instala Tesseract)"
        ttk.Checkbutton(opts, text=ocr_txt, variable=self.usar_ocr).grid(row=3, column=0, sticky="w")
        ttk.Button(opts, text="Cargar", command=self.load_files).grid(row=0, column=1, sticky="we", padx=(10, 0))
        ttk.Button(opts, text="Undo (Ctrl+Z)", command=self.undo).grid(row=1, column=1, sticky="we", padx=(10, 0))
        ttk.Button(opts, text="Catálogo nodos...", command=self.pick_catalogo).grid(row=2, column=1, sticky="we", padx=(10, 0))

        top.columnconfigure(1, weight=1)

        main = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pv = self._pv = ttk.Frame(left)
        pv.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.lbl_main = ttk.Label(pv, text="(sin imagen)", anchor="center")
        self.lbl_main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.lbl_crop = ttk.Label(pv, text="(recorte inferior-derecha)", anchor="center")
        self.lbl_crop.pack(side=tk.LEFT, fill=tk.BOTH)
        pv.bind("<Configure>", self._on_resize)

        cropbar = ttk.Frame(left)
        cropbar.pack(side=tk.TOP, fill=tk.X, pady=(8, 0))
        ttk.Label(cropbar, text="Recorte inferior-derecha (%):").pack(side=tk.LEFT)
        self.scale = ttk.Scale(cropbar, from_=15, to=70, orient="horizontal", command=self._on_crop_change)
        self.scale.set(self.prefs.crop_pct)
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.lbl_crop_pct = ttk.Label(cropbar, text=f"{self.prefs.crop_pct}%")
        self.lbl_crop_pct.pack(side=tk.LEFT)

        right = ttk.Frame(main, width=ancho_panel)
        # before=left: el panel reserva su espacio primero y la imagen no lo empuja fuera
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0), before=left)
        right.pack_propagate(False)

        box = ttk.Labelframe(right, text="Asignación", padding=10)
        box.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(box, textvariable=self.sugerencia_txt, foreground="#1F4E78", wraplength=wrap).grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(box, text="Número de nodo (XXXX)  [F2]:").grid(row=1, column=0, sticky="w")
        self.ent_num = ttk.Entry(box, textvariable=self.node_num)
        self.ent_num.grid(row=2, column=0, sticky="we", pady=(0, 8))
        self.ent_num.bind("<KeyRelease>", self._on_node_key)
        self.ent_num.bind("<FocusOut>", lambda e: self._finalize_node_fields())
        ttk.Label(box, text="Código (auto):").grid(row=3, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.node_code, state="readonly").grid(row=4, column=0, sticky="we", pady=(0, 8))
        ttk.Label(box, text="Localidad (auto, editable):").grid(row=5, column=0, sticky="w")
        self.ent_loc = ttk.Entry(box, textvariable=self.localidad)
        self.ent_loc.grid(row=6, column=0, sticky="we", pady=(0, 8))
        self.ent_loc.bind("<KeyRelease>", lambda e: self._marcar_edicion())
        ttk.Label(box, text="ITEM (ej: 7_8 / 01-A)  [F3]:").grid(row=7, column=0, sticky="w")
        self.ent_item = ttk.Entry(box, textvariable=self.item_val)
        self.ent_item.grid(row=8, column=0, sticky="we")
        self.ent_item.bind("<KeyRelease>", lambda e: self._marcar_edicion())
        box.columnconfigure(0, weight=1)

        btns = ttk.Frame(right, padding=(0, 10, 0, 0))
        btns.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(btns, text="Guardar + Siguiente (Enter)", command=self.save_and_next).grid(row=0, column=0, columnspan=2, sticky="we")
        ttk.Button(btns, text="← Anterior", command=self.prev_file).grid(row=1, column=0, sticky="we", pady=(6, 0), padx=(0, 3))
        ttk.Button(btns, text="Siguiente →", command=self.next_file).grid(row=1, column=1, sticky="we", pady=(6, 0), padx=(3, 0))
        ttk.Button(btns, text="Abrir carpeta destino", command=self.open_current_dest).grid(row=2, column=0, columnspan=2, sticky="we", pady=(6, 0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        flujo = ttk.Labelframe(right, text="Siguientes pasos", padding=10)
        flujo.pack(side=tk.TOP, fill=tk.X, pady=(10, 0))
        ttk.Button(flujo, text="2. Reporte Excel de ordenamiento", command=self.generar_reporte).pack(fill=tk.X)
        ttk.Button(flujo, text="3. Completar cartera Excel...", command=self.completar_cartera).pack(fill=tk.X, pady=(6, 0))
        ttk.Button(flujo, text="4. Empaquetar entrega...", command=self.empaquetar).pack(fill=tk.X, pady=(6, 0))

        info = ttk.Labelframe(right, text="Info", padding=10)
        info.pack(side=tk.TOP, fill=tk.X, pady=(10, 0))
        self.lbl_file = ttk.Label(info, text="Archivo: -", wraplength=wrap, justify="left")
        self.lbl_file.pack(anchor="w")
        self.lbl_prog = ttk.Label(info, text="Progreso: 0/0")
        self.lbl_prog.pack(anchor="w", pady=(6, 0))
        self.lbl_cat = ttk.Label(info, text=self._texto_catalogo())
        self.lbl_cat.pack(anchor="w", pady=(6, 0))

        ttk.Label(right, textvariable=self.status, wraplength=wrap, justify="left").pack(side=tk.TOP, fill=tk.X, pady=(10, 0))

    def _bind_keys(self) -> None:
        self.root.bind("<Return>", lambda e: self.save_and_next())
        self.root.bind_all("<Control-z>", lambda e: self.undo())
        self.root.bind_all("<Control-Z>", lambda e: self.undo())
        self.root.bind("<F2>", lambda e: self._focus(self.ent_num))
        self.root.bind("<F3>", lambda e: self._focus(self.ent_item))
        # flechas: solo si el foco NO está en un campo de texto (ahí mueven el cursor)
        self.root.bind("<Left>", lambda e: None if isinstance(e.widget, (tk.Entry, ttk.Entry)) else self.prev_file())
        self.root.bind("<Right>", lambda e: None if isinstance(e.widget, (tk.Entry, ttk.Entry)) else self.next_file())

    @staticmethod
    def _focus(entry: ttk.Entry) -> None:
        entry.focus_set()
        entry.select_range(0, tk.END)

    def _texto_catalogo(self) -> str:
        origen = self.catalogo.origen.name if self.catalogo.origen else "ninguno"
        return f"Catálogo: {len(self.catalogo)} nodos ({origen})"

    # ------------------------------------------------------------ carpetas
    def pick_src(self) -> None:
        d = filedialog.askdirectory(title="Elegir carpeta fuente", initialdir=self.src_dir.get() or None)
        if d:
            self.src_dir.set(d)

    def pick_out(self) -> None:
        d = filedialog.askdirectory(title="Elegir carpeta salida (base)", initialdir=self.out_dir.get() or None)
        if d:
            self.out_dir.set(d)

    def pick_catalogo(self) -> None:
        f = filedialog.askopenfilename(title="Catálogo de nodos (CSV)", filetypes=[("CSV", "*.csv")])
        if not f:
            return
        try:
            self.catalogo = CatalogoNodos.desde_csv(Path(f))
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            messagebox.showerror("Catálogo", f"No pude leer el CSV: {e}")
            return
        self.lbl_cat.config(text=self._texto_catalogo())

    def load_files(self) -> None:
        src = Path(self.src_dir.get().strip())
        out = Path(self.out_dir.get().strip())
        if not src.is_dir():
            messagebox.showerror("Error", "La carpeta fuente no existe.")
            return
        if not out.is_dir():
            messagebox.showerror("Error", "La carpeta de salida no existe.")
            return
        files = list_images(src)
        if not files:
            messagebox.showwarning("Sin archivos", "No encontré imágenes en la carpeta fuente (ni subcarpetas).")
            return
        self.files = files
        self.idx = 0
        self.undo_stack.clear()
        self.registro = RegistroAcciones.en_salida(out)
        self._guardar_prefs()
        self.status.set(f"Cargadas {len(files)} imágenes. Log: {self.registro.path.name}")
        self._refresh_ui_state()
        self.ent_num.focus_set()

    # -------------------------------------------------------------- vista
    def _refresh_ui_state(self) -> None:
        if not self.files:
            self.lbl_file.config(text="Archivo: -")
            self.lbl_prog.config(text="Progreso: 0/0")
            if not self.status.get():
                self.status.set("Listo. Elige carpeta fuente y salida, luego 'Cargar'.")
            self.lbl_main.config(image="", text="(sin imagen)")
            self.lbl_crop.config(image="", text="(recorte inferior-derecha)")
            return
        self.idx = max(0, min(self.idx, len(self.files) - 1))
        p = self.files[self.idx]
        self.lbl_file.config(text=f"Archivo: {p.name}")
        self.lbl_prog.config(text=f"Progreso: {self.idx + 1}/{len(self.files)}   (Undo: {len(self.undo_stack)})")
        self._im_cache = None
        self._show_image(p)
        self._lanzar_sugerencia(p)

    def _crop_pct(self) -> int:
        return int(float(self.scale.get()))

    def _show_image(self, path: Path) -> None:
        try:
            im = open_image(path)
            self._im_cache = im
            self._pintar_preview()
        except Exception as e:  # noqa: BLE001
            self.lbl_main.config(image="", text="(error abriendo imagen)")
            self.lbl_crop.config(image="", text="(sin recorte)")
            self.status.set(f"Error: {e}")

    def _area_preview(self) -> tuple[int, int]:
        """Espacio disponible para las dos vistas (se adapta al tamaño de la ventana)."""
        self._pv.update_idletasks()
        w, h = self._pv.winfo_width(), self._pv.winfo_height()
        if w < 50 or h < 50:  # aún no se dibuja la ventana
            return 1200, 560
        return w, h

    def _pintar_preview(self) -> None:
        if self._im_cache is None:
            return
        w, h = self._area_preview()
        self._photo_main = ImageTk.PhotoImage(resize_to_fit(self._im_cache, int(w * 0.62), h))
        self.lbl_main.config(image=self._photo_main, text="")
        self._pintar_recorte()

    def _on_resize(self, _evt=None) -> None:
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(150, self._pintar_preview)

    def _pintar_recorte(self) -> None:
        if self._im_cache is None:
            return
        pct = self._crop_pct()
        self.lbl_crop_pct.config(text=f"{pct}%")
        w, h = self._area_preview()
        crop = resize_to_fit(crop_bottom_right(self._im_cache, pct), int(w * 0.36), h)
        self._photo_crop = ImageTk.PhotoImage(crop)
        self.lbl_crop.config(image=self._photo_crop, text="")

    def _on_crop_change(self, _val: str) -> None:
        if self.files:
            self._pintar_recorte()

    # --------------------------------------------------------- sugerencias
    def _marcar_edicion(self) -> None:
        self._ediciones += 1

    def _lanzar_sugerencia(self, path: Path) -> None:
        """Calcula la sugerencia (nombre + OCR) en segundo plano para no congelar la UI."""
        self.sugerencia_txt.set("Sugerencia: analizando...")
        ediciones = self._ediciones
        recorte = crop_bottom_right(self._im_cache, self._crop_pct()) if self._im_cache else None
        usar_ocr = bool(self.usar_ocr.get())

        def trabajo() -> None:
            try:
                s = sugerir(path, recorte, usar_ocr=usar_ocr)
            except Exception:  # noqa: BLE001 - una sugerencia fallida no debe romper la UI
                s = Sugerencia()
            self._cola.put((path, s, ediciones))  # Tkinter solo se toca desde el hilo principal

        threading.Thread(target=trabajo, daemon=True).start()

    def _revisar_cola(self) -> None:
        try:
            while True:
                self._aplicar_sugerencia(*self._cola.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._revisar_cola)

    def _aplicar_sugerencia(self, path: Path, s: Sugerencia, ediciones: int) -> None:
        if not self.files or self.files[self.idx] != path:
            return  # el operador ya cambió de foto
        self._sugerencia_actual = s
        if s.vacia:
            self.sugerencia_txt.set("Sugerencia: — (se mantienen los valores anteriores)")
            return
        partes = []
        if s.nodo_num:
            partes.append(f"nodo {s.nodo_num}")
        if s.item:
            partes.append(f"ITEM {s.item}")
        self.sugerencia_txt.set(f"Sugerencia ({s.fuente}): {', '.join(partes)} — Enter para confirmar")
        if ediciones != self._ediciones:
            return  # el operador escribió mientras corría el OCR: no lo pisamos
        if s.nodo_num:
            self.node_num.set(s.nodo_num)
            self._finalize_node_fields()
        if s.item:
            self.item_val.set(s.item)
        self.ent_num.focus_set()
        self.ent_num.select_range(0, tk.END)

    # --------------------------------------------------------------- nodo
    def _on_node_key(self, _evt=None) -> None:
        self._marcar_edicion()
        raw = (self.node_num.get() or "").strip()
        if raw.isdigit() and len(raw) == 4 or any(ch.isalpha() or ch == "-" for ch in raw):
            self._finalize_node_fields()
        elif len(raw) < 4:
            self.node_code.set("")

    def _finalize_node_fields(self) -> None:
        raw = (self.node_num.get() or "").strip()
        if not raw:
            self.node_code.set("")
            return
        num, code, loc = normalize_node_input(raw, self.catalogo)
        if not num or not code:
            self.node_code.set("")
            return
        self.node_num.set(num)
        self.node_code.set(code)
        actual = (self.localidad.get() or "").strip()
        # solo reemplazamos la localidad si fue puesta automáticamente (no si el operador la editó)
        if not actual or actual == self._loc_auto or actual.upper() == NO_EN_LISTA:
            nuevo = loc or NO_EN_LISTA
            self.localidad.set(nuevo)
            self._loc_auto = nuevo

    def _dest_dir(self) -> Optional[Path]:
        out_base = Path(self.out_dir.get().strip())
        if not out_base.is_dir():
            self.status.set("Salida inválida.")
            return None
        num, code, loc_auto = normalize_node_input(self.node_num.get(), self.catalogo)
        if not code:
            self.status.set("Nodo inválido: escribe el número XXXX.")
            return None
        loc = (self.localidad.get() or "").strip() or loc_auto or "SIN_LOCALIDAD"
        item = normalize_item_input(self.item_val.get())
        if not item:
            self.status.set("ITEM inválido: ejemplo 7_8 o 01-A.")
            return None
        self.item_val.set(item)
        return build_dest_folder(out_base, code, loc, item)

    # ------------------------------------------------------------ acciones
    def save_and_next(self) -> None:
        if not self.files:
            return
        self._finalize_node_fields()
        dest_dir = self._dest_dir()
        if dest_dir is None:
            return
        src = self.files[self.idx]
        mode = self.mode.get()
        try:
            rec = undo_ops.aplicar(mode, src, dest_dir, idx=self.idx)
        except Exception as e:  # noqa: BLE001
            self.status.set(f"Error guardando: {e}")
            return
        rec.nodo, rec.localidad, rec.item = self.node_code.get(), self.localidad.get(), self.item_val.get()
        self.undo_stack.push(rec)
        self._anotar("GUARDAR", rec)
        if mode == "copy":
            if self.idx < len(self.files) - 1:
                self.idx += 1
        else:
            del self.files[rec.idx]
        self.status.set(f"OK {mode.upper()} → {rec.dst.parent.parent.name}/{rec.dst.parent.name}/{rec.dst.name}")
        if not self.files:
            self.status.set("¡Terminaste! Todas las fotos fueron ordenadas. Sigue con el paso 2.")
        self._refresh_ui_state()

    def undo(self) -> None:
        rec = self.undo_stack.pop()
        if rec is None:
            self.status.set("Nada para deshacer.")
            return
        try:
            back = undo_ops.revertir(rec)
        except FileNotFoundError:
            self.status.set("UNDO: el destino ya no existe (movido o borrado).")
            self._refresh_ui_state()
            return
        except Exception as e:  # noqa: BLE001
            self.status.set(f"Error UNDO: {e}")
            return
        self._anotar("UNDO", rec)
        if rec.mode == "move" and back is not None:
            pos = max(0, min(rec.idx, len(self.files)))
            self.files.insert(pos, back)
            self.idx = pos
            self.status.set(f"UNDO MOVE: regresó {back.name}. Quedan {len(self.undo_stack)}")
        else:
            self.status.set(f"UNDO COPY: copia borrada. Quedan {len(self.undo_stack)}")
        self._refresh_ui_state()

    def _anotar(self, accion: str, rec: undo_ops.UndoRecord) -> None:
        if not self.registro:
            return
        try:
            self.registro.anotar(
                accion=accion, modo=rec.mode, archivo=rec.src, destino=rec.dst,
                nodo=rec.nodo, localidad=rec.localidad, item=rec.item,
                operador=self.operador.get(),
                sugerencia=(self._sugerencia_actual.fuente or "manual") if accion == "GUARDAR" else "",
            )
        except OSError as e:
            self.status.set(f"Aviso: no pude escribir el log ({e})")

    def prev_file(self) -> None:
        if self.files and self.idx > 0:
            self.idx -= 1
            self._refresh_ui_state()

    def next_file(self) -> None:
        if self.files and self.idx < len(self.files) - 1:
            self.idx += 1
            self._refresh_ui_state()

    def open_current_dest(self) -> None:
        self._finalize_node_fields()
        d = self._dest_dir()
        if d is None:
            return
        d.mkdir(parents=True, exist_ok=True)
        _abrir(d)

    # ------------------------------------------------- pasos 2, 3 y 4
    def _salida(self) -> Optional[Path]:
        out = Path(self.out_dir.get().strip())
        if not out.is_dir():
            messagebox.showerror("Salida", "Elige primero la carpeta de salida.")
            return None
        return out

    def generar_reporte(self) -> None:
        from .reporte import generar_reporte

        out = self._salida()
        if out is None:
            return
        try:
            path = generar_reporte(out, catalogo=self.catalogo)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Reporte", str(e))
            return
        self.status.set(f"Reporte creado: {path.name}")
        _abrir(path)

    def completar_cartera(self) -> None:
        from .cartera.completar import completar_cartera

        out = self._salida()
        if out is None:
            return
        plantilla = filedialog.askopenfilename(
            title="Plantilla o cartera Excel existente (Cancelar = crear una nueva)",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=self.prefs.plantilla_cartera or None,
        )
        self.prefs.plantilla_cartera = plantilla or ""
        try:
            res = completar_cartera(out, Path(plantilla) if plantilla else None, catalogo=self.catalogo)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Cartera", str(e))
            return
        self.status.set(res.resumen())
        messagebox.showinfo("Cartera completada", res.resumen())
        _abrir(res.salida)

    def empaquetar(self) -> None:
        from .empaquetar import RevisionPendiente, empaquetar_entrega

        out = self._salida()
        if out is None:
            return
        try:
            res = empaquetar_entrega(out)
        except RevisionPendiente as e:
            if not messagebox.askyesno("Revisión pendiente", f"{e}\n\n¿Empaquetar de todas formas?"):
                return
            res = empaquetar_entrega(out, permitir_pendientes=True)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Empaquetar", str(e))
            return
        self.status.set(res.resumen())
        messagebox.showinfo("Entrega lista", res.resumen())
        _abrir(res.carpeta)

    # -------------------------------------------------------------- cierre
    def _guardar_prefs(self) -> None:
        self.prefs.src_dir = self.src_dir.get()
        self.prefs.out_dir = self.out_dir.get()
        self.prefs.modo = self.mode.get()
        self.prefs.crop_pct = self._crop_pct()
        self.prefs.operador = self.operador.get()
        self.prefs.usar_ocr = bool(self.usar_ocr.get())
        try:
            self.prefs.guardar()
        except OSError:
            pass

    def _on_close(self) -> None:
        self._guardar_prefs()
        self.root.destroy()


def _abrir(path: Path) -> None:
    """Abre un archivo/carpeta con la app del sistema."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(path)])
    except Exception:  # noqa: BLE001
        pass


def run() -> None:
    if os.name == "nt":  # nitidez en pantallas con escala 125-150 %
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    FieldPhotoSorterApp(root)
    root.mainloop()
