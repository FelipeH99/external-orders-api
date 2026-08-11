# External Orders API

Aplicacion Python que simula la recepcion de pedidos externos y su procesamiento dentro de un sistema interno.

El objetivo principal es cubrir una integracion simple con:

- API REST con FastAPI.
- Persistencia relacional con SQLAlchemy.
- SQLite como base de datos local.
- Validacion de payloads con Pydantic.
- Pruebas automatizadas con pytest.

## Instalacion

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Inicializar la base de datos

Por defecto se usa SQLite y se crea el archivo `external_orders.db`.

```bash
python -m app.init_db
```

El script crea las tablas y carga productos de ejemplo si la tabla esta vacia:

- `SKU-001` Keyboard
- `SKU-002` Mouse
- `SKU-003` Monitor

Tambien se puede usar otra base configurando `DATABASE_URL`:

```bash
DATABASE_URL=sqlite:///./external_orders.db python -m app.init_db
```

## Ejecutar la API

La aplicacion tambien inicializa la base al arrancar, para facilitar el uso local.

```bash
uvicorn app.main:app --reload
```

Luego abrir:

- Swagger/OpenAPI: http://127.0.0.1:8000/docs
- Productos disponibles: http://127.0.0.1:8000/products

## Ejecutar pruebas

```bash
pytest
```

Las pruebas usan una base SQLite en memoria, aislada de la base local de desarrollo.

## Endpoints principales

- `POST /orders/external`: recibe y procesa un pedido externo.
- `GET /orders`: lista pedidos internos creados.
- `GET /orders/{order_id}`: consulta un pedido puntual.
- `GET /sync-attempts`: lista intentos de sincronizacion.
- `GET /products`: lista productos disponibles.

## Ejemplo de pedido

```json
{
  "external_id": "EXT-001",
  "cliente": "Acme SA",
  "fecha": "2026-08-11T10:30:00",
  "lineas": [
    {
      "sku": "SKU-001",
      "quantity": 2,
      "price": "10.50"
    }
  ]
}
```

## Estructura

```text
app/
  database.py   Configuracion de SQLAlchemy y sesiones.
  main.py       Definicion de FastAPI y endpoints.
  models.py     Modelos ORM.
  schemas.py    Esquemas Pydantic de entrada y salida.
  services.py   Logica de negocio para procesar pedidos.
tests/
  conftest.py   Fixtures de pytest y base en memoria.
  test_orders.py
```

## Decisiones tecnicas

- Se separo la logica de negocio en `services.py` para que los endpoints queden delgados y sea mas facil probar el comportamiento.
- `external_id` es unico en la tabla de pedidos para reforzar la idempotencia tambien a nivel de base de datos.
- Antes de crear un pedido se validan todos los SKU recibidos. Si falta alguno, no se crea el pedido y se registra un intento fallido.
- Cada procesamiento registra un intento con resultado `success`, `failed` o `duplicate`.
- Si se recibe nuevamente un `external_id` ya procesado, la API devuelve el pedido existente con HTTP 200 y registra el intento como duplicado.
- Para datos invalidos del endpoint de recepcion de pedidos, se registra un intento fallido mediante un handler de validacion de FastAPI.
- La configuracion de base de datos se lee desde `DATABASE_URL`, manteniendo SQLite como valor por defecto para simplificar la ejecucion local.

## Aprendizaje

Para resolver el ejercicio, los conceptos clave a revisar son:

- Ciclo de vida de una aplicacion FastAPI y declaracion de endpoints.
- Modelado declarativo en SQLAlchemy 2.0.
- Validacion y aliases de campos con Pydantic.
- Uso de dependencias de FastAPI para inyectar sesiones de base de datos.
- Tests de API con `TestClient` y SQLite en memoria.

El abordaje recomendado es empezar por el contrato de la API y los casos de prueba esperados, luego implementar los modelos y finalmente la logica de procesamiento.

## Mejoras para produccion

- Usar PostgreSQL y migraciones con Alembic en lugar de `create_all`.
- Manejar concurrencia sobre `external_id` con transacciones mas estrictas y captura explicita de errores de unicidad.
- Agregar autenticacion, autorizacion y rate limiting.
- Incorporar logging estructurado y trazabilidad por request.
- Persistir el payload original del intento para auditoria.
- Agregar paginacion y filtros en listados.
- Separar configuracion por ambiente mediante variables de entorno.
- Sumar validaciones de negocio mas completas, por ejemplo moneda, precision de precios y normalizacion de SKU.
