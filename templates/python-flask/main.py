"""
DoubleAgent Service Template - Python/Flask

Replace TODO comments with your implementation.
"""

import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# State - Replace with your service's state
# =============================================================================

state = {
    # TODO: Add your collections here
    # "items": {},
}

counters = {
    # TODO: Add ID counters
    # "item_id": 0,
}


def next_id(key):
    counters[key] += 1
    return counters[key]


def reset_state():
    global state, counters
    state = {
        # TODO: Reset to initial state
    }
    counters = {
        # TODO: Reset counters
    }


# =============================================================================
# REQUIRED: /_doubleagent endpoints
# =============================================================================

@app.route("/_doubleagent/health", methods=["GET"])
def health():
    """Health check - REQUIRED."""
    return jsonify({"status": "healthy"})


@app.route("/_doubleagent/reset", methods=["POST"])
def reset():
    """Reset all state - REQUIRED."""
    reset_state()
    return jsonify({"status": "ok"})


@app.route("/_doubleagent/seed", methods=["POST"])
def seed():
    """Seed state from JSON - REQUIRED."""
    data = request.json or {}
    seeded = {}
    
    # TODO: Implement seeding for your collections
    # if "items" in data:
    #     for item in data["items"]:
    #         state["items"][item["id"]] = item
    #     seeded["items"] = len(data["items"])
    
    return jsonify({"status": "ok", "seeded": seeded})


@app.route("/_doubleagent/info", methods=["GET"])
def info():
    """Service info - OPTIONAL."""
    return jsonify({
        "name": "my-service",  # TODO: Change this
        "version": "1.0",
    })


# =============================================================================
# API Endpoints - Implement your service's API
# =============================================================================

# TODO: Add your API endpoints here
# 
# @app.route("/items", methods=["GET"])
# def list_items():
#     return jsonify(list(state["items"].values()))
# 
# @app.route("/items", methods=["POST"])
# def create_item():
#     data = request.json
#     item_id = next_id("item_id")
#     item = {"id": item_id, **data}
#     state["items"][item_id] = item
#     return jsonify(item), 201


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
