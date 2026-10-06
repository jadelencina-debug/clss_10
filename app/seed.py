import os
from datetime import datetime, timezone
from app.database import SessionLocal
from app import models
from app.core.security import hash_password

DEMO_PRODUCTOS = [
    {
        "nombre": "Hamburguesa (Está hecho de banana y avena)",
        "precio_final": 9500.0,
        "cuotas_cantidad": 3,
        "cuotas_valor": round(9500.0 / 3, 2),
        "garantia_meses": 0,
        "stock": 15,
        "imagen_url": "/demo/hamburguesa.png",
    },
    {
        "nombre": "Esponja (Es un bizcochuelo)",
        "precio_final": 12500.0,
        "cuotas_cantidad": 3,
        "cuotas_valor": round(12500.0 / 3, 2),
        "garantia_meses": 0,
        "stock": 15,
        "imagen_url": "/demo/esponja.png",
    },
    {
        "nombre": "Huevo (De gelatina)",
        "precio_final": 6000.0,
        "cuotas_cantidad": 3,
        "cuotas_valor": round(6000.0 / 3, 2),
        "garantia_meses": 0,
        "stock": 15,
        "imagen_url": "/demo/huevo.png",
    },
    {
        "nombre": "Vela (Chocolate blanco y negro)",
        "precio_final": 9000.0,
        "cuotas_cantidad": 3,
        "cuotas_valor": round(9000.0 / 3, 2),
        "garantia_meses": 0,
        "stock": 15,
        "imagen_url": "/demo/velas.png",
    },
    {
        "nombre": "Tomate (Algo parecido al alfajor de maicena)",
        "precio_final": 11000.0,
        "cuotas_cantidad": 3,
        "cuotas_valor": round(11000.0 / 3, 2),
        "garantia_meses": 0,
        "stock": 15,
        "imagen_url": "/demo/tomates.png",
    },
]

def seed():
    db = SessionLocal()
    try:
        admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@equipo.com")
        admin_password = os.getenv("SEED_ADMIN_PASSWORD", "Admin1234!")

        admin = db.query(models.Usuario).filter(models.Usuario.email == admin_email).first()
        if not admin:
            admin = models.Usuario(
                nombre="Administrador",
                email=admin_email,
                hashed_password=hash_password(admin_password),
                rol="admin",
                acepto_tratamiento=True,
                fecha_consentimiento=datetime.now(timezone.utc),
                activo=True,
            )
            db.add(admin)
            db.commit()

        for prod_data in DEMO_PRODUCTOS:
            prod = db.query(models.Producto).filter(models.Producto.nombre == prod_data["nombre"]).first()
            if not prod:
                prod = models.Producto(**prod_data)
                db.add(prod)
            else:
                prod.imagen_url = prod_data["imagen_url"]
        
        db.commit()
        print("Seed listo.")
    except Exception as e:
        db.rollback()
        print("Error en seed:", e)
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed()
