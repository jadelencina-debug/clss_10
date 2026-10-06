from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from pathlib import Path
from sqlalchemy import text
import uuid
import os

from app import models, schemas
from app.core.config import settings
from app.database import engine, get_db
from app.routers import auth as auth_router
from app.routers import pedidos as pedidos_router
from app.routers import usuarios as usuarios_router
from app.dependencies import require_admin
from app.services import productos as productos_service

# ── Directorio de imágenes ────────────────────────────────────────────────────
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
Path("uploads/productos").mkdir(parents=True, exist_ok=True)
Path("app/static/demo").mkdir(parents=True, exist_ok=True)

# Magic bytes de formatos permitidos
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",   # WebP: primeros 4 bytes RIFF, bytes 8-11 WEBP
}

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

BYTES_TO_READ = 12  # suficiente para todos los magic bytes listados


models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    swagger_ui_oauth2_redirect_url="/oauth2-redirect",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(pedidos_router.router)
app.include_router(usuarios_router.router)


# ── Productos — GET abierto, POST/PUT/DELETE protegidos ──────────────────────
@app.get("/productos", response_model=List[schemas.ProductoOut])
def obtener_productos(
    skip: int = 0,
    limit: int = 100,
    nombre: Optional[str] = None,
    precio_max: Optional[float] = None,
    db: Session = Depends(get_db),
):
    return productos_service.listar_productos(
        db=db, skip=skip, limit=limit, nombre=nombre, precio_max=precio_max
    )


@app.post(
    "/productos",
    response_model=schemas.ProductoOut,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def crear_producto(producto: schemas.ProductoCreate, db: Session = Depends(get_db)):
    return productos_service.crear_producto(db=db, producto=producto)


@app.put(
    "/productos/{producto_id}",
    response_model=schemas.ProductoOut,
    dependencies=[Depends(require_admin)],
)
def actualizar_producto(
    producto_id: int,
    producto: schemas.ProductoCreate,
    db: Session = Depends(get_db),
):
    db_prod = db.query(models.Producto).filter(models.Producto.id == producto_id).first()
    if not db_prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    for field, value in producto.model_dump().items():
        setattr(db_prod, field, value)
    db.commit()
    db.refresh(db_prod)
    return db_prod


@app.delete(
    "/productos/{producto_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def eliminar_producto(producto_id: int, db: Session = Depends(get_db)):
    db_prod = db.query(models.Producto).filter(models.Producto.id == producto_id).first()
    if not db_prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    db.delete(db_prod)
    db.commit()


# ── POST /productos/{id}/imagen ───────────────────────────────────────────────
# Prueba 6: Subida de imagen con validación de Magic Bytes + renombre UUID
# Solo admins pueden subir imágenes.
@app.post(
    "/productos/{producto_id}/imagen",
    status_code=200,
    summary="Subir imagen de producto (admin) — valida Magic Bytes + UUID",
    dependencies=[Depends(require_admin)],
)
async def subir_imagen_producto(
    producto_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Valida:
    1. Extensión permitida (.jpg, .jpeg, .png, .gif, .webp).
    2. Magic Bytes reales del archivo (no se fía de la extensión).
    3. Guarda la imagen renombrada con UUID para evitar colisiones.
    """
    # 1. Verificar que el producto existe
    db_prod = db.query(models.Producto).filter(models.Producto.id == producto_id).first()
    if not db_prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")

    # 2. Verificar extensión declarada
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Extensión '{ext}' no permitida. Usá: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # 3. Leer los primeros bytes y verificar Magic Bytes (firma real del archivo)
    header = await file.read(BYTES_TO_READ)
    tipo_detectado = None
    for firma, mime in MAGIC_BYTES.items():
        if header[:len(firma)] == firma:
            tipo_detectado = mime
            break

    if tipo_detectado is None:
        raise HTTPException(
            status_code=415,
            detail=(
                "El archivo no es una imagen válida: la firma de bytes (magic bytes) "
                "no corresponde a ningún formato permitido (JPEG, PNG, GIF, WebP). "
                "Intentaste subir un archivo disfrazado de imagen."
            ),
        )

    # Caso especial WebP: después de RIFF, los bytes 8-11 deben ser "WEBP"
    if tipo_detectado == "image/webp" and header[8:12] != b"WEBP":
        raise HTTPException(
            status_code=415,
            detail="El archivo RIFF no es un WebP válido.",
        )

    # 4. Guardar el resto del archivo con nombre UUID para evitar colisiones
    nombre_uuid = f"{uuid.uuid4()}{ext}"
    ruta_destino = os.path.join(UPLOAD_DIR, nombre_uuid)

    # Reposicionar el stream al principio para guardar el archivo completo
    await file.seek(0)
    contenido = await file.read()
    with open(ruta_destino, "wb") as f:
        f.write(contenido)

    # 5. Guardar la URL en la base de datos
    url_imagen = f"/uploads/{nombre_uuid}"
    db_prod.imagen_url = url_imagen
    db.commit()
    db.refresh(db_prod)

    return {
        "mensaje": "Imagen subida correctamente.",
        "nombre_archivo": nombre_uuid,
        "tipo_detectado": tipo_detectado,
        "url": url_imagen,
    }


# ── POST /arrepentimiento ─────────────────────────────────────────────────────
# Prueba 5: Endpoint TOTALMENTE PÚBLICO (sin token) — Res. 271/2020 y 424/2020.
# Recibe email + código de compra, cancela el pedido y repone stock.

class ArrepentimientoIn(BaseModel):
    email: str
    codigo_pedido: int   # ID del pedido


@app.post(
    "/arrepentimiento",
    status_code=200,
    summary="Arrepentimiento de compra — PÚBLICO (sin login) — Res. 271/2020",
    tags=["arrepentimiento"],
)
def arrepentimiento_publico(
    datos: ArrepentimientoIn,
    db: Session = Depends(get_db),
):
    """
    Endpoint PÚBLICO (no requiere token). Permite al consumidor cancelar una
    compra enviando su email y el número de pedido (Res. 271/2020 y 424/2020).

    - Busca el pedido por ID y verifica que el email corresponda al usuario propietario.
    - Si el pedido está en estado 'pendiente', lo cancela y repone stock.
    - Devuelve un código de revocación único como comprobante.
    """
    from datetime import timezone
    from datetime import datetime
    import secrets

    # 1. Buscar el pedido
    pedido = db.query(models.Pedido).filter(models.Pedido.id == datos.codigo_pedido).first()
    if not pedido:
        raise HTTPException(
            status_code=404,
            detail="No se encontró un pedido con ese código.",
        )

    # 2. Verificar que el email corresponde al usuario del pedido
    usuario = db.query(models.Usuario).filter(models.Usuario.id == pedido.usuario_id).first()
    if not usuario or usuario.email.lower() != datos.email.lower():
        raise HTTPException(
            status_code=404,
            detail="El email no coincide con el pedido indicado.",
        )

    # 3. Verificar que no está ya cancelado
    if pedido.estado == "cancelado":
        raise HTTPException(
            status_code=409,
            detail="El pedido ya fue cancelado previamente.",
        )

    # 4. Verificar plazo de 10 días
    creado_en = pedido.creado_en
    if creado_en.tzinfo is None:
        creado_en = creado_en.replace(tzinfo=timezone.utc)
    diferencia = datetime.now(timezone.utc) - creado_en
    if diferencia.days > 10:
        raise HTTPException(
            status_code=409,
            detail=f"El plazo de 10 días para arrepentirse ya venció ({diferencia.days} días desde la compra).",
        )

    # 5. Transacción: cancelar pedido + reponer stock + emitir código
    try:
        for item in pedido.items:
            producto = (
                db.query(models.Producto)
                .filter(models.Producto.id == item.producto_id)
                .with_for_update()
                .first()
            )
            if producto:
                producto.stock += item.cantidad

        pedido.estado = "cancelado"

        fecha = datetime.now(timezone.utc).strftime("%Y%m%d")
        codigo = f"ARR-{fecha}-{secrets.token_hex(3).upper()}"

        solicitud = models.SolicitudRevocacion(
            codigo=codigo,
            pedido_id=pedido.id,
            usuario_id=usuario.id,
        )
        db.add(solicitud)
        db.commit()
        db.refresh(solicitud)

        return {
            "mensaje": "Pedido cancelado exitosamente. El stock fue repuesto.",
            "codigo_revocacion": codigo,
            "pedido_id": pedido.id,
            "estado_nuevo": "cancelado",
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error interno al procesar el arrepentimiento.",
        ) from exc


# ── Servir archivos de imágenes subidas y demo ────────────────────────────────
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")
app.mount("/demo", StaticFiles(directory="app/static/demo"), name="demo")


@app.get("/salud", tags=["Salud"])
def salud(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"estado": "ok", "base": "ok"}