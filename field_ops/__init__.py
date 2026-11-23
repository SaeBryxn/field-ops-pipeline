"""Field Ops Pipeline: fotos de campo -> carpetas NODO/ITEM -> cartera Excel -> entrega.

Flujo:
    1. ``ui``          ordenar fotos por NODO e ITEM (Tkinter, OCR opcional, Undo).
    2. ``reporte``     resumen Excel de lo ordenado (validación de observaciones).
    3. ``cartera``     completar la cartera Excel con los datos de las fotos y recalcular.
    4. ``empaquetar``  armar la carpeta/ZIP de entrega lista para subir a Drive.
"""

__version__ = "2.0.0"
