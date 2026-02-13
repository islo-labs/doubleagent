"""
DoubleAgent Service Template - Python/FastAPI

Replace TODO comments with your implementation.
"""

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# =============================================================================
# State - Replace with your service's state
# =============================================================================

state: dict[str, dict] = {
    # TODO: Add your collections here
    # "items": {},
}

counters: dict[str, int] = {
    # TODO: Add ID counters
    # "item_id": 0,
}


def next_id(key: str) -> int:
    counters[key] += 1
    return counters[key]


def reset_state() -> None:
    global state, counters
    state = {
        # TODO: Reset to initial state
    }
    counters = {
        # TODO: Reset counters
    }


# =============================================================================
# Pydantic Models - Define your request/response models
# =============================================================================

class SeedData(BaseModel):
    # TODO: Define your seed data model
    pass


# Example models:
# class ItemCreate(BaseModel):
#     name: str
#     description: str = ""
#
# class ItemUpdate(BaseModel):
#     name: Optional[str] = None
#     description: Optional[str] = None


# =============================================================================
# App Setup
# =============================================================================

app = FastAPI(
    title="My Service Fake",  # TODO: Change this
    description="DoubleAgent fake of My Service API",
    version="1.0.0",
)


# =============================================================================
# REQUIRED: /_doubleagent endpoints
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    """Health check - REQUIRED."""
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    """Reset all state - REQUIRED."""
    reset_state()
    return {"status": "ok"}


@app.post("/_doubleagent/seed")
async def seed(data: SeedData):
    """Seed state from JSON - REQUIRED."""
    seeded: dict[str, int] = {}
    
    # TODO: Implement seeding for your collections
    # if data.items:
    #     for item in data.items:
    #         state["items"][item["id"]] = item
    #     seeded["items"] = len(data.items)
    
    return {"status": "ok", "seeded": seeded}


@app.get("/_doubleagent/info")
async def info():
    """Service info - OPTIONAL."""
    return {
        "name": "my-service",  # TODO: Change this
        "version": "1.0",
    }


# =============================================================================
# API Endpoints - Implement your service's API
# =============================================================================

# TODO: Add your API endpoints here
#
# @app.get("/items")
# async def list_items():
#     return list(state["items"].values())
#
# @app.post("/items", status_code=201)
# async def create_item(item: ItemCreate):
#     item_id = next_id("item_id")
#     item_obj = {"id": item_id, **item.model_dump()}
#     state["items"][item_id] = item_obj
#     return item_obj
#
# @app.get("/items/{item_id}")
# async def get_item(item_id: int):
#     if item_id not in state["items"]:
#         raise HTTPException(status_code=404, detail={"message": "Not Found"})
#     return state["items"][item_id]
#
# @app.patch("/items/{item_id}")
# async def update_item(item_id: int, update: ItemUpdate):
#     if item_id not in state["items"]:
#         raise HTTPException(status_code=404, detail={"message": "Not Found"})
#     item = state["items"][item_id]
#     if update.name is not None:
#         item["name"] = update.name
#     if update.description is not None:
#         item["description"] = update.description
#     return item
#
# @app.delete("/items/{item_id}", status_code=204)
# async def delete_item(item_id: int):
#     if item_id in state["items"]:
#         del state["items"][item_id]
#     return None


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
