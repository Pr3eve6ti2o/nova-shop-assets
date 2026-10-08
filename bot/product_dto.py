"""Public product DTO/projection (re-audit P3.24).

The internal `products` table contains fields that must never leak to
clients (cost price, supplier info, internal notes, etc.). This module
defines the public projection used by the Mini App, the API, and any
external consumer.

Rules:
- Only whitelisted fields are exposed
- Prices are in minor units (cents) with explicit currency
- Stock is projected as availability status, not raw counts
  (prevents inventory probing)
- Internal IDs are stable; never expose rowids or internal keys
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProductDTO:
    """Public product representation."""
    id: int
    name: str
    description: str
    price_cents: int
    currency: str
    category_id: int
    category_name: str
    image_url: Optional[str]
    is_digital: bool
    availability: str  # "in_stock" | "low_stock" | "out_of_stock" | "unlimited"
    # Never: cost_price, supplier_id, internal_notes, etc.

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price_cents": self.price_cents,
            "currency": self.currency,
            "category_id": self.category_id,
            "category_name": self.category_name,
            "image_url": self.image_url,
            "is_digital": self.is_digital,
            "availability": self.availability,
        }


def _availability_status(stock: int, is_digital: bool) -> str:
    if is_digital or stock == -1:
        return "unlimited"
    if stock <= 0:
        return "out_of_stock"
    if stock <= 5:
        return "low_stock"
    return "in_stock"


def product_to_dto(row: dict, currency: str = "USD") -> ProductDTO:
    """Project a database row to the public DTO.

    Only whitelisted fields are copied. Internal fields (cost_price,
    supplier info, etc.) are never exposed even if present in the row.
    """
    stock = row.get("stock", 0)
    is_digital = bool(row.get("is_digital", 0))
    return ProductDTO(
        id=row["id"],
        name=row["name"],
        description=row.get("description", ""),
        price_cents=row["price_cents"],
        currency=currency,
        category_id=row.get("category_id", 0),
        category_name=row.get("category_name", ""),
        image_url=row.get("image_url"),
        is_digital=is_digital,
        availability=_availability_status(stock, is_digital),
    )


def products_to_dtos(rows: list, currency: str = "USD") -> list:
    """Project multiple rows. Returns list of dicts (JSON-ready)."""
    return [product_to_dto(dict(r), currency).to_dict() for r in rows]
