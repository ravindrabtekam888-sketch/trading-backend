import os
import time
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ------------------------------------------------------------------------------
# Optional imports of your real code. If not found, we use safe fallbacks.
# Put your real modules under folders like: broker/, strategies/, utils/
# ------------------------------------------------------------------------------
BROKER_OK = False
STRATEGY_OK = False

try:
    # Example: from your project
    # from broker.angel_api import AngelAPI
    # from strategies.supertrend import supertrend_signal
    from broker.angel_api import AngelAPI  # type: ignore
    from strategies.supertrend import supertrend_signal  # type: ignore
    BROKER_OK = True
    STRATEGY_OK = True
except Exception:
    # Fallback stubs so the API still works end-to-end on Render
    class AngelAPI:  # type: ignore
        def __init__(self, api_key: str, client_id: str, password: str, totp_secret: Optional[str] = None):
            self.api_key = api_key
            self.client_id = client_id
            self.password = password
            self.totp_secret = totp_secret
            self.session_token = "DEMO_SESSION"

        def place_order(self, symbol: str, side: str, qty: int, order_type: str = "MARKET") -> Dict[str, Any]:
            order_id = f"SIM-{int(time.time())}"
            return {"order_id": order_id, "status": "accepted", "symbol": symbol, "side": side, "qty": qty, "type": order_type}

        def get_positions(self) -> List[Dict[str, Any]]:
            return [{"symbol": "NIFTY", "qty": 1, "avg_price": 25000.0}]

    def supertrend_signal(symbol: str, timeframe: str = "5m", **kwargs) -> Dict[str, Any]:  # type: ignore
        # Simple demo logic: alternate BUY/SELL by timestamp parity
        side = "BUY" if int(time.time()) % 2 == 0 else "SELL"
        return {"symbol": symbol, "timeframe": timeframe, "signal": side, "confidence": 0.55}

# ------------------------------------------------------------------------------
# App & CORS
# ------------------------------------------------------------------------------
app = FastAPI(title="Trading Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production (e.g., your Vercel domain)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------
class StrategyRequest(BaseModel):
    symbol: str = Field(..., examples=["NIFTY", "BANKNIFTY", "RELIANCE"])
    timeframe: str = Field("5m", examples=["1m", "5m", "15m", "1h"])
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)

class OrderRequest(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    qty: int = Field(..., gt=0)
    order_type: str = Field("MARKET", pattern="^(MARKET|LIMIT)$")
    price: Optional[float] = Field(None, gt=0)

class WebhookAlert(BaseModel):
    source: str = Field(..., examples=["tradingview", "internal"])
    event: str = Field(..., examples=["signal", "error", "heartbeat"])
    payload: Dict[str, Any] = Field(default_factory=dict)

# ------------------------------------------------------------------------------
# Simple in-memory "DB" for demo
# In your real app, replace with a persistent store (Postgres, Firestore, etc.)
# ------------------------------------------------------------------------------
TRADES: List[Dict[str, Any]] = []

# ------------------------------------------------------------------------------
# Environment (don’t hardcode secrets)
# ------------------------------------------------------------------------------
API_KEY = os.getenv("ANGEL_API_KEY", "")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
PASSWORD = os.getenv("ANGEL_PASSWORD", "")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

def broker_connected() -> bool:
    return bool(API_KEY and CLIENT_ID and PASSWORD)

def masked(s: str) -> str:
    if not s:
        return ""
    return s[:2] + "****" + s[-2:]

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "Trading Backend Online", "version": app.version}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "time": int(time.time()),
        "broker_env_configured": broker_connected(),
        "modules": {"broker": BROKER_OK, "strategy": STRATEGY_OK},
    }

@app.get("/config")
def config():
    # Shows presence (not values) of secrets and which modules are detected
    return {
        "env": {
            "ANGEL_API_KEY_set": bool(API_KEY),
            "ANGEL_CLIENT_ID_set": bool(CLIENT_ID),
            "ANGEL_PASSWORD_set": bool(PASSWORD),
            "ANGEL_TOTP_SECRET_set": bool(TOTP_SECRET),
        },
        "modules": {"broker": BROKER_OK, "strategy": STRATEGY_OK},
    }

@app.post("/strategy/run")
def run_strategy(req: StrategyRequest):
    try:
        result = supertrend_signal(req.symbol, req.timeframe, **(req.params or {}))
        return {"ok": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Strategy error: {e}")

@app.post("/orders")
def place_order(req: OrderRequest):
    if not broker_connected() and BROKER_OK:
        raise HTTPException(status_code=400, detail="Broker credentials missing in environment.")

    try:
        # Use real broker if available; otherwise stub
        broker = AngelAPI(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)  # type: ignore
        resp = broker.place_order(req.symbol, req.side, req.qty, req.order_type)
        trade_rec = {
            "ts": int(time.time()),
            "symbol": req.symbol,
            "side": req.side,
            "qty": req.qty,
            "order_type": req.order_type,
            "price": req.price,
            "broker_ref": resp.get("order_id"),
            "status": resp.get("status", "unknown"),
        }
        TRADES.append(trade_rec)
        return {"ok": True, "order": trade_rec}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order failed: {e}")

@app.get("/trades")
def trades():
    return {"count": len(TRADES), "items": TRADES}

@app.post("/webhook/alert")
async def webhook_alert(alert: WebhookAlert, request: Request):
    # You can add signature validation here if needed
    record = {
        "ts": int(time.time()),
        "source": alert.source,
        "event": alert.event,
        "payload": alert.payload,
        "ip": request.client.host if request.client else None,
    }
    # In production, forward to queue/DB/notification service
    return {"ok": True, "received": record}
